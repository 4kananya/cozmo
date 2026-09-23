"""Tests for ground-truth evaluation and capability reporting."""

from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from cozmo_scan.batch import summarize_runs
from cozmo_scan.benchmark import (
    COMPLIANCE_MATRIX_FILENAME,
    EVALUATION_JSON_FILENAME,
    EVALUATION_REPORT_FILENAME,
    BenchmarkEvaluation,
    EvaluationError,
    EvaluationStatus,
    GroundTruthCapture,
    GroundTruthManifest,
    GroundTruthOpening,
    GroundTruthRoom,
    GroundTruthWall,
    InputTier,
    MeasurementEvaluation,
    calculate_absolute_error,
    calculate_percentage_error,
    evaluate_benchmark,
    evaluate_interval_coverage,
    evaluate_measurement,
    load_ground_truth,
    load_run_results,
    render_compliance_matrix,
    render_evaluation_report,
    run_evaluation,
    write_evaluation_outputs,
    _summarize_openings,
)
from cozmo_scan.cli import build_parser, main
from cozmo_scan.models import BatchItemResult, BatchSummary, RunResult
from tests.pipeline_factory import make_pipeline_execution


def make_manifest(
    *,
    capture_names: tuple[str, ...] = ("synthetic-room.zip",),
    tier: InputTier = InputTier.LIDAR,
    repeatability_group: str | None = None,
    include_opening: bool = True,
) -> GroundTruthManifest:
    base_result = make_pipeline_execution().result
    plan = base_result.room.floor_plan
    room = GroundTruthRoom(
        room_id="room-1",
        floor_area_m2=plan.area_m2 + 1.0,
        principal_length_m=plan.length_m,
        principal_width_m=plan.width_m,
        ceiling_height_m=base_result.room.ceiling_height_m,
        walls=(GroundTruthWall(wall_id="wall-a", length_m=4.0),),
        openings=(
            (GroundTruthOpening(opening_id="door-a", wall_id="wall-a", width_m=0.9),)
            if include_opening
            else ()
        ),
    )
    return GroundTruthManifest(
        property_id="property-a",
        measurement_method="laser distance meter and tape",
        rooms=(room,),
        captures=tuple(
            GroundTruthCapture(
                capture_name=name,
                room_id="room-1",
                tier=tier,
                repeatability_group=repeatability_group,
            )
            for name in capture_names
        ),
    )


def make_result(name: str = "synthetic-room.zip", hash_character: str = "a") -> RunResult:
    result = make_pipeline_execution().result
    return result.model_copy(
        update={
            "input": result.input.model_copy(
                update={"name": name, "sha256": hash_character * 64}
            )
        }
    )


def make_item(result: RunResult, output_directory: str) -> BatchItemResult:
    plan = result.room.floor_plan
    return BatchItemResult(
        input_name=result.input.name,
        status="succeeded",
        output_directory=output_directory,
        input_sha256=result.input.sha256,
        selected_frame_count=result.reconstruction.selected_frame_count,
        output_point_count=result.reconstruction.output_point_count,
        floor_area_m2=plan.area_m2,
        area_is_provisional=False,
        length_m=plan.length_m,
        width_m=plan.width_m,
        perimeter_m=plan.perimeter_m,
        floor_inlier_ratio=result.quality.floor_inlier_ratio,
        floor_rmse_m=result.quality.floor_rmse_m,
        boundary_fill_ratio=result.quality.boundary_fill_ratio,
        detected_wall_count=result.quality.detected_wall_count,
        ceiling_height_m=result.room.ceiling_height_m,
        measurement_confidence=result.quality.measurement_confidence,
        elapsed_seconds=0.5,
        warnings=result.warnings,
    )


def make_summary(*results: RunResult) -> BatchSummary:
    items = tuple(make_item(result, Path(result.input.name).stem) for result in results)
    return summarize_runs(
        input_name="sample",
        config=results[0].config,
        elapsed_seconds=1.0,
        items=items,
    )


def write_batch(directory: Path, *results: RunResult) -> BatchSummary:
    summary = make_summary(*results)
    directory.mkdir(parents=True)
    (directory / "batch.json").write_text(
        summary.model_dump_json(indent=2), encoding="utf-8"
    )
    for result in results:
        result_directory = directory / Path(result.input.name).stem
        result_directory.mkdir()
        (result_directory / "result.json").write_text(
            result.model_dump_json(indent=2), encoding="utf-8"
        )
    return summary


class GroundTruthContractTests(unittest.TestCase):
    def test_manifest_round_trips_and_rejects_unknown_fields(self) -> None:
        manifest = make_manifest()
        self.assertEqual(
            GroundTruthManifest.model_validate_json(manifest.model_dump_json()), manifest
        )
        with self.assertRaises(ValidationError):
            GroundTruthManifest.model_validate(
                {**manifest.model_dump(), "unexpected": "misspelled field"}
            )

    def test_manifest_rejects_duplicate_ids_and_unknown_wall_reference(self) -> None:
        with self.assertRaisesRegex(ValidationError, "duplicate wall_id"):
            GroundTruthRoom(
                room_id="r",
                walls=(
                    GroundTruthWall(wall_id="w", length_m=2),
                    GroundTruthWall(wall_id="w", length_m=3),
                ),
            )
        with self.assertRaisesRegex(ValidationError, "unknown walls"):
            GroundTruthRoom(
                room_id="r",
                openings=(
                    GroundTruthOpening(
                        opening_id="door", wall_id="missing", width_m=0.9
                    ),
                ),
            )

    def test_load_ground_truth_reports_missing_and_invalid_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(EvaluationError, "does not exist"):
                load_ground_truth(root / "missing.json")
            invalid = root / "invalid.json"
            invalid.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(EvaluationError, "Invalid ground-truth"):
                load_ground_truth(invalid)


class MetricEvaluationTests(unittest.TestCase):
    def test_error_functions_use_absolute_and_percent_units(self) -> None:
        self.assertAlmostEqual(calculate_absolute_error(1.98, 2.0), 0.02)
        self.assertAlmostEqual(calculate_percentage_error(1.9, 2.0), 5.0)
        with self.assertRaisesRegex(ValueError, "positive"):
            calculate_percentage_error(1.0, 0.0)

    def test_lidar_scalars_are_diagnostic_but_ceiling_gate_is_exact(self) -> None:
        result = make_result()
        manifest = make_manifest(include_opening=False)
        summary = make_summary(result)

        evaluation = evaluate_benchmark(manifest, summary, {result.input.name: result})

        measurements = {item.metric: item for item in evaluation.captures[0].measurements}
        self.assertEqual(measurements["floor_area"].status, EvaluationStatus.NOT_EVALUATED)
        self.assertAlmostEqual(measurements["floor_area"].absolute_error, 1.0)
        self.assertEqual(measurements["ceiling_height"].status, EvaluationStatus.PASSED)
        self.assertEqual(measurements["ceiling_height"].threshold_value, 0.015)
        self.assertEqual(measurements["wall_length"].status, EvaluationStatus.MISSING_PREDICTION)
        self.assertFalse(measurements["wall_length"].gate_applicable)
        self.assertEqual(evaluation.status, "incomplete")

    def test_evaluation_gate_boundaries_for_ceiling_photo_and_video_walls(self) -> None:
        ceiling_capture = GroundTruthCapture(
            capture_name="lidar.zip", room_id="r", tier=InputTier.LIDAR
        )
        at_ceiling_limit = evaluate_measurement(
            capture=ceiling_capture,
            metric="ceiling_height",
            target_id=None,
            unit="metre",
            truth=2.0,
            predicted=2.015,
        )
        above_ceiling_limit = evaluate_measurement(
            capture=ceiling_capture,
            metric="ceiling_height",
            target_id=None,
            unit="metre",
            truth=2.0,
            predicted=2.0151,
        )
        self.assertEqual(at_ceiling_limit.status, EvaluationStatus.PASSED)
        self.assertEqual(above_ceiling_limit.status, EvaluationStatus.FAILED)

        for tier, allowed_percent in ((InputTier.PHOTO, 8.0), (InputTier.VIDEO, 3.0)):
            capture = GroundTruthCapture(
                capture_name=f"{tier.value}.zip", room_id="r", tier=tier
            )
            at_limit = evaluate_measurement(
                capture=capture,
                metric="wall_length",
                target_id="wall-a",
                unit="metre",
                truth=10.0,
                predicted=10.0 * (1.0 + allowed_percent / 100.0),
            )
            over_limit = evaluate_measurement(
                capture=capture,
                metric="wall_length",
                target_id="wall-a",
                unit="metre",
                truth=10.0,
                predicted=10.0 * (1.0 + (allowed_percent + 0.01) / 100.0),
            )
            self.assertEqual(at_limit.status, EvaluationStatus.PASSED)
            self.assertEqual(over_limit.status, EvaluationStatus.FAILED)

    def test_missing_opening_counts_as_failed_gate(self) -> None:
        result = make_result()
        evaluation = evaluate_benchmark(
            make_manifest(), make_summary(result), {result.input.name: result}
        )

        self.assertEqual(evaluation.status, "failed_gates")
        self.assertEqual(evaluation.openings.expected_count, 1)
        self.assertEqual(evaluation.openings.missed_count, 1)
        self.assertEqual(evaluation.openings.pass_rate, 0.0)
        self.assertEqual(evaluation.openings.status, EvaluationStatus.FAILED)

    def test_opening_summary_counts_phantom_in_denominator(self) -> None:
        common = {
            "capture_name": "c",
            "room_id": "r",
            "metric": "opening_width",
            "unit": "metre",
            "threshold_value": 0.02,
            "threshold_unit": "metre",
            "gate_applicable": True,
        }
        passed = MeasurementEvaluation(
            **common,
            target_id="door",
            truth_value=0.9,
            predicted_value=0.91,
            absolute_error=0.01,
            percentage_error=1.111,
            status=EvaluationStatus.PASSED,
            reason="within",
        )
        phantom = MeasurementEvaluation(
            **common,
            target_id="ghost",
            predicted_value=1.0,
            status=EvaluationStatus.FAILED,
            reason="phantom",
        )

        summary = _summarize_openings((passed, phantom))

        self.assertEqual(summary.denominator_count, 2)
        self.assertEqual(summary.phantom_count, 1)
        self.assertEqual(summary.pass_rate, 0.5)
        self.assertEqual(summary.status, EvaluationStatus.FAILED)

    def test_interval_coverage_is_descriptive_without_invented_gate(self) -> None:
        unavailable = evaluate_interval_coverage(())
        measured = evaluate_interval_coverage(((0.9, 1.1, 1.0), (2.1, 2.2, 2.0)))

        self.assertEqual(unavailable.status, EvaluationStatus.NOT_EVALUATED)
        self.assertIn("ground-truth value", unavailable.reason)
        self.assertEqual(measured.covered_count, 1)
        self.assertEqual(measured.coverage_rate, 0.5)
        self.assertEqual(measured.status, EvaluationStatus.NOT_EVALUATED)
        with self.assertRaisesRegex(ValueError, "lower bound"):
            evaluate_interval_coverage(((2.0, 1.0, 1.5),))


class RepeatabilityTests(unittest.TestCase):
    def test_ceiling_spread_at_one_centimetre_boundary_passes(self) -> None:
        first = make_result("first.zip", "a")
        first_height = float(first.room.ceiling_height_m)
        second_base = make_result("second.zip", "b")
        second = second_base.model_copy(
            update={
                "room": second_base.room.model_copy(
                    update={"ceiling_height_m": first_height + 0.01}
                )
            }
        )
        manifest = make_manifest(
            capture_names=("first.zip", "second.zip"),
            repeatability_group="room-1-repeat",
            include_opening=False,
        )
        room = manifest.rooms[0].model_copy(
            update={"ceiling_height_m": first_height + 0.005}
        )
        manifest = manifest.model_copy(update={"rooms": (room,)})

        evaluation = evaluate_benchmark(
            manifest,
            make_summary(first, second),
            {first.input.name: first, second.input.name: second},
        )

        ceiling = next(check for check in evaluation.repeatability if check.metric == "ceiling_height")
        self.assertAlmostEqual(ceiling.spread_m, 0.01)
        self.assertEqual(ceiling.accuracy_status, EvaluationStatus.PASSED)
        self.assertEqual(ceiling.status, EvaluationStatus.PASSED)
        self.assertEqual(ceiling.classification, "accurate_and_repeatable")

    def test_repeatable_but_biased_ceiling_is_distinguished(self) -> None:
        first = make_result("first.zip", "a")
        second = make_result("second.zip", "b")
        truth_height = float(first.room.ceiling_height_m) + 0.02
        manifest = make_manifest(
            capture_names=("first.zip", "second.zip"),
            repeatability_group="room-1-repeat",
            include_opening=False,
        )
        room = manifest.rooms[0].model_copy(update={"ceiling_height_m": truth_height})
        manifest = manifest.model_copy(update={"rooms": (room,)})

        evaluation = evaluate_benchmark(
            manifest,
            make_summary(first, second),
            {first.input.name: first, second.input.name: second},
        )

        ceiling = next(check for check in evaluation.repeatability if check.metric == "ceiling_height")
        self.assertEqual(ceiling.status, EvaluationStatus.PASSED)
        self.assertEqual(ceiling.accuracy_status, EvaluationStatus.FAILED)
        self.assertEqual(ceiling.classification, "biased_but_repeatable")
        wall = next(check for check in evaluation.repeatability if check.metric == "wall_length")
        self.assertEqual(wall.status, EvaluationStatus.MISSING_PREDICTION)
        self.assertEqual(wall.classification, "incomplete")


class InputOutputTests(unittest.TestCase):
    def test_loads_batch_results_and_refuses_hash_or_path_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            batch = root / "batch"
            result = make_result()
            summary = write_batch(batch, result)

            loaded_summary, loaded, warnings = load_run_results(batch)
            self.assertEqual(loaded_summary, summary)
            self.assertEqual(loaded[result.input.name], result)
            self.assertEqual(warnings, ())

            bad_summary = summary.model_copy(
                update={
                    "items": (
                        summary.items[0].model_copy(update={"input_sha256": "b" * 64}),
                    )
                }
            )
            (batch / "batch.json").write_text(
                bad_summary.model_dump_json(), encoding="utf-8"
            )
            with self.assertRaisesRegex(EvaluationError, "hash"):
                load_run_results(batch)

    def test_expected_truth_hash_prevents_scoring_wrong_capture(self) -> None:
        result = make_result()
        manifest = make_manifest()
        capture = manifest.captures[0].model_copy(
            update={"expected_input_sha256": "f" * 64}
        )
        manifest = manifest.model_copy(update={"captures": (capture,)})

        with self.assertRaisesRegex(EvaluationError, "refusing to score"):
            evaluate_benchmark(
                manifest, make_summary(result), {result.input.name: result}
            )

    def test_run_and_write_outputs_stage_three_files_and_protect_existing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            batch = root / "batch"
            output = root / "evaluation"
            truth_path = root / "truth.json"
            result = make_result()
            write_batch(batch, result)
            truth_path.write_text(make_manifest().model_dump_json(indent=2), encoding="utf-8")

            evaluation = run_evaluation(batch, truth_path)
            paths = write_evaluation_outputs(evaluation, output)

            self.assertEqual(
                {path.name for path in paths.values()},
                {
                    EVALUATION_JSON_FILENAME,
                    EVALUATION_REPORT_FILENAME,
                    COMPLIANCE_MATRIX_FILENAME,
                },
            )
            decoded = BenchmarkEvaluation.model_validate_json(
                (output / EVALUATION_JSON_FILENAME).read_text(encoding="utf-8")
            )
            self.assertEqual(decoded, evaluation)
            report = render_evaluation_report(evaluation)
            matrix = render_compliance_matrix(evaluation)
            self.assertIn("successful command", report)
            self.assertIn("Opening gate", report)
            self.assertIn("Published precision intervals were checked", report)
            self.assertNotIn("do not publish numerical confidence intervals", report)
            self.assertIn("Drift accountability", matrix)
            self.assertIn("schema 1.4.0", matrix)
            # Requirement -> file path -> artifact -> status is the published
            # table contract.
            self.assertIn(
                "| Requirement | File path | Artifact | Status | Evidence / limitation |",
                matrix,
            )
            # Unbuilt requirements must not point at a file that does not
            # implement them.
            self.assertIn("| Damage regions with class and metric extent | not present |", matrix)
            self.assertIn("`src/cozmo_scan/drift.py`", matrix)
            unrelated = output / "unrelated-note.txt"
            unrelated.write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(EvaluationError, "--overwrite"):
                write_evaluation_outputs(evaluation, output)
            write_evaluation_outputs(evaluation, output, overwrite=True)
            self.assertEqual(unrelated.read_text(encoding="utf-8"), "keep")

    def test_staging_failure_publishes_no_partial_evaluation(self) -> None:
        result = make_result()
        evaluation = evaluate_benchmark(
            make_manifest(), make_summary(result), {result.input.name: result}
        )
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evaluation"
            with patch(
                "cozmo_scan.benchmark.render_compliance_matrix",
                side_effect=RuntimeError("injected render failure"),
            ):
                with self.assertRaisesRegex(RuntimeError, "injected"):
                    write_evaluation_outputs(evaluation, output)

            self.assertFalse(output.exists())


class CommandLineTests(unittest.TestCase):
    def test_parser_exposes_evaluate_command(self) -> None:
        arguments = build_parser().parse_args(
            [
                "evaluate",
                "runs/demo",
                "--ground-truth",
                "benchmark/truth.json",
                "--output",
                "runs/evaluation",
            ]
        )
        self.assertEqual(arguments.command, "evaluate")
        self.assertEqual(arguments.batch_directory, Path("runs/demo"))

    def test_failed_product_gate_still_returns_zero_after_report_is_written(self) -> None:
        result = make_result()
        evaluation = evaluate_benchmark(
            make_manifest(), make_summary(result), {result.input.name: result}
        )
        output = io.StringIO()
        with (
            patch("cozmo_scan.benchmark.run_evaluation", return_value=evaluation),
            patch(
                "cozmo_scan.benchmark.write_evaluation_outputs",
                return_value={"evaluation": Path("evaluation.json")},
            ),
            redirect_stdout(output),
        ):
            exit_code = main(
                [
                    "evaluate",
                    "runs/demo",
                    "--ground-truth",
                    "truth.json",
                    "--output",
                    "runs/evaluation",
                ]
            )
        self.assertEqual(exit_code, 0)
        self.assertIn("FAILED_GATES", output.getvalue())

    def test_invalid_evaluation_input_returns_two(self) -> None:
        errors = io.StringIO()
        with redirect_stderr(errors):
            exit_code = main(
                [
                    "evaluate",
                    "missing",
                    "--ground-truth",
                    "missing.json",
                    "--output",
                    "unused",
                ]
            )
        self.assertEqual(exit_code, 2)
        self.assertIn("Evaluation failed", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
