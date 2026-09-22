"""Tests for the checkpoint-one command-line foundation."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout

from cozmo_scan import __version__
from cozmo_scan.cli import build_parser, main


class CommandLineTests(unittest.TestCase):
    def test_parser_uses_public_command_name(self) -> None:
        self.assertEqual(build_parser().prog, "cozmo-scan")

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


if __name__ == "__main__":
    unittest.main()
