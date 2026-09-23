"""Tests for the reproducible demonstration wrapper."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts import demo


def create_sample_placeholders(directory: Path) -> None:
    directory.mkdir()
    for name in demo.EXPECTED_SAMPLE_NAMES:
        (directory / name).write_bytes(b"placeholder")


def write_batch_summary(directory: Path, *, status: str = "ok") -> None:
    directory.mkdir(parents=True)
    failed = 0 if status == "ok" else 1
    payload = {
        "status": status,
        "total_capture_count": 1,
        "succeeded_count": 1 - failed,
        "failed_count": failed,
        "items": [
            {
                "input_name": "single_room.zip",
                "status": "succeeded" if not failed else "failed",
                "floor_area_m2": 34.73 if not failed else None,
                "area_is_provisional": True if not failed else None,
                "outline_method": "convex_hull" if not failed else None,
                "length_m": 7.44 if not failed else None,
                "width_m": 6.59 if not failed else None,
                "ceiling_height_m": None,
                "measurement_confidence": "caution" if not failed else None,
            }
        ],
    }
    (directory / "batch.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


class DemoTests(unittest.TestCase):
    def test_parser_defaults_to_fast_complete_demo(self) -> None:
        arguments = demo.build_parser().parse_args([])

        self.assertEqual(arguments.sample_dir, Path("sample"))
        self.assertEqual(arguments.output, Path("runs/demo"))
        self.assertEqual(arguments.profile, "fast")
        self.assertFalse(arguments.skip_tests)

    def test_missing_samples_fail_before_commands_run(self) -> None:
        errors = io.StringIO()
        with tempfile.TemporaryDirectory() as temporary:
            with (
                patch("scripts.demo.run_command") as runner,
                redirect_stderr(errors),
            ):
                exit_code = demo.main(
                    [
                        "--sample-dir",
                        str(Path(temporary) / "missing"),
                        "--output",
                        str(Path(temporary) / "output"),
                    ]
                )

        self.assertEqual(exit_code, 2)
        self.assertIn("Sample directory does not exist", errors.getvalue())
        runner.assert_not_called()

    def test_successful_demo_runs_tests_validation_batch_and_summary(self) -> None:
        commands: list[tuple[str, ...]] = []
        output_text = io.StringIO()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            samples = root / "sample"
            output = root / "run"
            create_sample_placeholders(samples)

            def fake_run(
                command: tuple[str, ...] | list[str],
                **_: object,
            ) -> int:
                commands.append(tuple(command))
                if "batch" in command:
                    write_batch_summary(output)
                return 0

            with (
                patch("scripts.demo.run_command", side_effect=fake_run),
                redirect_stdout(output_text),
            ):
                exit_code = demo.main(
                    [
                        "--sample-dir",
                        str(samples),
                        "--output",
                        str(output),
                        "--overwrite",
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(commands), 3)
        self.assertIn("unittest", commands[0])
        self.assertIn("validate", commands[1])
        self.assertIn("batch", commands[2])
        self.assertIn("--overwrite", commands[2])
        self.assertIn("DEMONSTRATION SUMMARY", output_text.getvalue())
        self.assertIn("34.73 m2 provisional", output_text.getvalue())
        self.assertIn("convex_hull", output_text.getvalue())

    def test_partial_batch_prints_available_summary_and_returns_two(self) -> None:
        output_text = io.StringIO()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            samples = root / "sample"
            output = root / "run"
            create_sample_placeholders(samples)

            def fake_run(
                command: tuple[str, ...] | list[str],
                **_: object,
            ) -> int:
                if "batch" in command:
                    write_batch_summary(output, status="partial")
                    return 2
                return 0

            with (
                patch("scripts.demo.run_command", side_effect=fake_run),
                redirect_stdout(output_text),
            ):
                exit_code = demo.main(
                    [
                        "--sample-dir",
                        str(samples),
                        "--output",
                        str(output),
                        "--skip-tests",
                    ]
                )

        self.assertEqual(exit_code, 2)
        self.assertIn("Status: PARTIAL", output_text.getvalue())
        self.assertIn("Failed: 1", output_text.getvalue())

    def test_success_without_batch_json_is_rejected(self) -> None:
        errors = io.StringIO()
        output_text = io.StringIO()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            samples = root / "sample"
            create_sample_placeholders(samples)

            with (
                patch("scripts.demo.run_command", return_value=0),
                redirect_stderr(errors),
                redirect_stdout(output_text),
            ):
                exit_code = demo.main(
                    [
                        "--sample-dir",
                        str(samples),
                        "--output",
                        str(root / "missing-output"),
                        "--skip-tests",
                    ]
                )

        self.assertEqual(exit_code, 2)
        self.assertIn("batch output is missing", errors.getvalue())

    def test_failed_rerun_does_not_display_stale_summary(self) -> None:
        errors = io.StringIO()
        output_text = io.StringIO()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            samples = root / "sample"
            output = root / "existing-run"
            create_sample_placeholders(samples)
            write_batch_summary(output)

            def fake_run(
                command: tuple[str, ...] | list[str],
                **_: object,
            ) -> int:
                return 2 if "batch" in command else 0

            with (
                patch("scripts.demo.run_command", side_effect=fake_run),
                redirect_stderr(errors),
                redirect_stdout(output_text),
            ):
                exit_code = demo.main(
                    [
                        "--sample-dir",
                        str(samples),
                        "--output",
                        str(output),
                        "--skip-tests",
                    ]
                )

        self.assertEqual(exit_code, 2)
        self.assertNotIn("DEMONSTRATION SUMMARY", output_text.getvalue())
        self.assertIn("did not publish new evidence", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
