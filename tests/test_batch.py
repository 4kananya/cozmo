"""Tests for CP06 sequential all-capture processing and summaries."""

from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from cozmo_scan.batch import (
    BATCH_JSON_FILENAME,
    BATCH_REPORT_FILENAME,
    BatchError,
    discover_captures,
    run_batch,
    summarize_runs,
    write_batch_outputs,
)
from cozmo_scan.cli import build_parser, main
from cozmo_scan.models import BatchItemResult, BatchSummary
from cozmo_scan.outputs import OutputError
from cozmo_scan.pipeline import PipelineError
from tests.capture_factory import create_test_capture
from tests.pipeline_factory import make_pipeline_execution


def make_success(name: str = "room.zip") -> BatchItemResult:
    return BatchItemResult(
        input_name=name,
        status="succeeded",
        output_directory=Path(name).stem,
        input_sha256="a" * 64,
        selected_frame_count=12,
        output_point_count=3456,
        floor_area_m2=18.25,
        area_is_provisional=False,
        outline_method="occupancy_concave",
        length_m=5.0,
        width_m=3.8,
        perimeter_m=17.6,
        floor_inlier_ratio=0.42,
        floor_rmse_m=0.012,
        boundary_fill_ratio=0.73,
        detected_wall_count=4,
        ceiling_height_m=None,
        measurement_confidence="good",
        elapsed_seconds=1.25,
        warnings=(),
    )


def make_summary(*items: BatchItemResult) -> BatchSummary:
    return summarize_runs(
        input_name="sample",
        config=make_pipeline_execution().result.config,
        elapsed_seconds=2.5,
        items=tuple(items) or (make_success(),),
    )


class CaptureDiscoveryTests(unittest.TestCase):
    def test_single_zip_is_accepted_and_other_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "room.ZIP"
            archive.write_bytes(b"placeholder")
            text = root / "notes.txt"
            text.write_text("ignore", encoding="utf-8")

            self.assertEqual(discover_captures(archive), (archive,))
            with self.assertRaisesRegex(BatchError, "must be a ZIP"):
                discover_captures(text)

    def test_capture_directory_itself_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            capture = create_test_capture(Path(temporary), root_name="room")

            self.assertEqual(discover_captures(capture), (capture,))

    def test_collection_is_stable_and_ignores_unrelated_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "b.zip").write_bytes(b"b")
            (root / "A.zip").write_bytes(b"a")
            capture = create_test_capture(root, root_name="c-room")
            (root / "notes.txt").write_text("not a capture", encoding="utf-8")
            (root / "misc").mkdir()
            (root / "misc" / "file.txt").write_text("x", encoding="utf-8")

            discovered = discover_captures(root)

            self.assertEqual(
                tuple(path.name for path in discovered),
                ("A.zip", "b.zip", capture.name),
            )

    def test_empty_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(BatchError, "No capture"):
                discover_captures(temporary)

    def test_duplicate_output_names_are_rejected_case_insensitively(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            create_test_capture(root, root_name="room")
            (root / "ROOM.zip").write_bytes(b"placeholder")

            with self.assertRaisesRegex(BatchError, "collide"):
                discover_captures(root)


class BatchExecutionTests(unittest.TestCase):
    def test_batch_continues_after_capture_failure_with_shared_config(self) -> None:
        execution = make_pipeline_execution(include_ceiling=False)
        config = execution.result.config
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "a.zip"
            second = root / "b.zip"
            first.write_bytes(b"a")
            second.write_bytes(b"b")
            output = root / "results"

            with (
                patch(
                    "cozmo_scan.batch.run_pipeline",
                    side_effect=(execution, PipelineError("bad capture")),
                ) as pipeline,
                patch("cozmo_scan.batch.write_run_outputs") as writer,
            ):
                summary = run_batch(root, output, config)

        self.assertEqual(summary.status, "partial")
        self.assertEqual(summary.succeeded_count, 1)
        self.assertEqual(summary.failed_count, 1)
        self.assertEqual(tuple(item.input_name for item in summary.items), ("a.zip", "b.zip"))
        self.assertEqual(summary.items[1].error, "bad capture")
        self.assertEqual(pipeline.call_count, 2)
        self.assertIs(pipeline.call_args_list[0].args[1], config)
        self.assertIs(pipeline.call_args_list[1].args[1], config)
        writer.assert_called_once()

    def test_output_conflict_is_detected_before_processing(self) -> None:
        config = make_pipeline_execution().result.config
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "a.zip").write_bytes(b"a")
            output = root / "results"
            (output / "a").mkdir(parents=True)
            (output / "a" / "result.json").write_text("old", encoding="utf-8")

            with patch("cozmo_scan.batch.run_pipeline") as pipeline:
                with self.assertRaisesRegex(BatchError, "--overwrite"):
                    run_batch(root, output, config)

            pipeline.assert_not_called()

    def test_overwrite_still_rejects_capture_output_that_is_a_file(self) -> None:
        config = make_pipeline_execution().result.config
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "a.zip").write_bytes(b"a")
            output = root / "results"
            output.mkdir()
            (output / "a").write_text("not a directory", encoding="utf-8")

            with patch("cozmo_scan.batch.run_pipeline") as pipeline:
                with self.assertRaisesRegex(BatchError, "not a directory"):
                    run_batch(root, output, config, overwrite=True)

            pipeline.assert_not_called()

    def test_unexpected_programming_error_is_not_hidden_as_capture_failure(self) -> None:
        config = make_pipeline_execution().result.config
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "a.zip").write_bytes(b"a")

            with patch(
                "cozmo_scan.batch.run_pipeline",
                side_effect=RuntimeError("injected bug"),
            ):
                with self.assertRaisesRegex(RuntimeError, "injected bug"):
                    run_batch(root, root / "results", config)

    def test_summary_round_trips_and_rejects_false_counts(self) -> None:
        failed = BatchItemResult(
            input_name="bad.zip",
            status="failed",
            output_directory="bad",
            elapsed_seconds=0.1,
            error="invalid data",
        )
        summary = make_summary(make_success(), failed)

        decoded = BatchSummary.model_validate_json(summary.model_dump_json())

        self.assertEqual(decoded, summary)
        self.assertEqual(decoded.status, "partial")
        with self.assertRaisesRegex(ValidationError, "item statuses"):
            BatchSummary.model_validate(
                {
                    **summary.model_dump(),
                    "succeeded_count": 2,
                    "failed_count": 0,
                    "status": "ok",
                }
            )


class BatchOutputTests(unittest.TestCase):
    def test_staging_failure_publishes_no_batch_files(self) -> None:
        summary = make_summary(make_success())
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "batch"

            with patch(
                "cozmo_scan.batch.write_batch_report",
                side_effect=OutputError("injected report failure"),
            ):
                with self.assertRaisesRegex(OutputError, "injected"):
                    write_batch_outputs(summary, destination)

            self.assertFalse(destination.exists())

    def test_json_report_and_overwrite_protection(self) -> None:
        failed = BatchItemResult(
            input_name="bad|capture.zip",
            status="failed",
            output_directory="bad-capture",
            elapsed_seconds=0.2,
            error="could not | validate",
        )
        summary = make_summary(make_success("good.zip"), failed)
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "batch"

            paths = write_batch_outputs(summary, destination)

            self.assertEqual(
                {path.name for path in paths.values()},
                {BATCH_JSON_FILENAME, BATCH_REPORT_FILENAME},
            )
            self.assertEqual(
                BatchSummary.model_validate_json(
                    paths["batch_summary"].read_text(encoding="utf-8")
                ),
                summary,
            )
            report = paths["batch_report"].read_text(encoding="utf-8")
            self.assertIn("Cross-capture results", report)
            self.assertIn("occupancy_concave", report)
            self.assertIn("## Failures", report)
            self.assertIn("bad\\|capture.zip", report)
            unrelated = destination / "reviewer-note.txt"
            unrelated.write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(OutputError, "--overwrite"):
                write_batch_outputs(summary, destination)
            write_batch_outputs(summary, destination, overwrite=True)
            self.assertEqual(unrelated.read_text(encoding="utf-8"), "keep")


class BatchCommandLineTests(unittest.TestCase):
    def test_parser_exposes_batch_command(self) -> None:
        arguments = build_parser().parse_args(
            ["batch", "sample", "--output", "runs/all", "--profile", "fast"]
        )

        self.assertEqual(arguments.command, "batch")
        self.assertEqual(arguments.input, Path("sample"))
        self.assertEqual(arguments.output, Path("runs/all"))
        self.assertEqual(arguments.profile, "fast")

    def test_missing_batch_input_returns_two(self) -> None:
        errors = io.StringIO()

        with redirect_stderr(errors):
            exit_code = main(
                ["batch", "missing", "--output", "unused", "--profile", "test"]
            )

        self.assertEqual(exit_code, 2)
        self.assertIn("Batch failed", errors.getvalue())

    def test_partial_batch_is_reported_and_returns_two(self) -> None:
        failed = BatchItemResult(
            input_name="bad.zip",
            status="failed",
            output_directory="bad",
            elapsed_seconds=0.1,
            error="invalid capture",
        )
        summary = make_summary(make_success(), failed)
        output = io.StringIO()

        with (
            patch("cozmo_scan.batch.run_batch", return_value=summary),
            patch(
                "cozmo_scan.batch.write_batch_outputs",
                return_value={
                    "batch_summary": Path("batch.json"),
                    "batch_report": Path("batch-report.md"),
                },
            ),
            redirect_stdout(output),
        ):
            exit_code = main(["batch", "sample", "--output", "runs/all"])

        self.assertEqual(exit_code, 2)
        self.assertIn("Status: PARTIAL", output.getvalue())
        self.assertIn("FAILED: bad.zip", output.getvalue())


if __name__ == "__main__":
    unittest.main()
