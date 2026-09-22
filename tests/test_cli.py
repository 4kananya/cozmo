"""Tests for the checkpoint-one command-line foundation."""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from cozmo_scan import __version__
from cozmo_scan.cli import build_parser, main
from cozmo_scan.models import ValidationResult


class CommandLineTests(unittest.TestCase):
    def test_parser_uses_public_command_name(self) -> None:
        self.assertEqual(build_parser().prog, "cozmo-scan")

    def test_parser_exposes_validate_command(self) -> None:
        arguments = build_parser().parse_args(["validate", "capture.zip"])

        self.assertEqual(arguments.command, "validate")
        self.assertEqual(arguments.capture, Path("capture.zip"))

    def test_parser_exposes_reconstruct_command(self) -> None:
        arguments = build_parser().parse_args(
            [
                "reconstruct",
                "capture.zip",
                "--output",
                "run",
                "--profile",
                "test",
                "--max-frames",
                "3",
                "--frame-selection",
                "contiguous-start",
            ]
        )

        self.assertEqual(arguments.command, "reconstruct")
        self.assertEqual(arguments.output, Path("run"))
        self.assertEqual(arguments.profile, "test")
        self.assertEqual(arguments.max_frames, 3)
        self.assertEqual(arguments.frame_selection, "contiguous-start")

    def test_parser_exposes_measure_command(self) -> None:
        arguments = build_parser().parse_args(
            ["measure", "capture.zip", "--output", "run", "--profile", "fast"]
        )

        self.assertEqual(arguments.command, "measure")
        self.assertEqual(arguments.capture, Path("capture.zip"))
        self.assertEqual(arguments.output, Path("run"))
        self.assertEqual(arguments.profile, "fast")

    def test_no_arguments_prints_help_and_succeeds(self) -> None:
        output = io.StringIO()

        with redirect_stdout(output):
            exit_code = main([])

        self.assertEqual(exit_code, 0)
        self.assertIn("usage: cozmo-scan", output.getvalue())

    def test_version_flag_prints_package_version(self) -> None:
        output = io.StringIO()

        with self.assertRaises(SystemExit) as raised, redirect_stdout(output):
            main(["--version"])

        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(output.getvalue().strip(), f"cozmo-scan {__version__}")

    def test_validate_returns_success_and_prints_json(self) -> None:
        result = ValidationResult(source="capture.zip", valid=True)
        output = io.StringIO()

        with patch("cozmo_scan.cli.validate_capture", return_value=result):
            with redirect_stdout(output):
                exit_code = main(["validate", "capture.zip", "--json"])

        self.assertEqual(exit_code, 0)
        self.assertTrue(json.loads(output.getvalue())["valid"])

    def test_validate_returns_two_for_invalid_input(self) -> None:
        output = io.StringIO()

        with redirect_stdout(output):
            exit_code = main(["validate", "missing-capture.zip"])

        self.assertEqual(exit_code, 2)
        self.assertIn("Status: INVALID", output.getvalue())

    def test_reconstruct_returns_two_for_missing_input(self) -> None:
        errors = io.StringIO()

        with redirect_stderr(errors):
            exit_code = main(
                [
                    "reconstruct",
                    "missing-capture.zip",
                    "--output",
                    "unused-output",
                    "--profile",
                    "test",
                ]
            )

        self.assertEqual(exit_code, 2)
        self.assertIn("Reconstruction failed", errors.getvalue())

    def test_measure_returns_two_for_missing_input(self) -> None:
        errors = io.StringIO()

        with redirect_stderr(errors):
            exit_code = main(
                [
                    "measure",
                    "missing-capture.zip",
                    "--output",
                    "unused-output",
                    "--profile",
                    "test",
                ]
            )

        self.assertEqual(exit_code, 2)
        self.assertIn("Measurement failed", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
