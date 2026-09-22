"""Command-line entry point for Cozmo Scan."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from cozmo_scan import __version__


def build_parser() -> argparse.ArgumentParser:
    """Create the top-level command-line parser."""
    parser = argparse.ArgumentParser(
        prog="cozmo-scan",
        description=(
            "Reconstruct and measure supplied Stray Scanner LiDAR captures. "
            "Processing commands are added through approved checkpoints."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0

