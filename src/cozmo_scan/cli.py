"""Command-line entry point for Cozmo Scan."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from cozmo_scan import __version__
from cozmo_scan.dataset import validate_capture
from cozmo_scan.models import ValidationResult


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
    subparsers = parser.add_subparsers(dest="command")

    validate_parser = subparsers.add_parser(
        "validate",
        help="inspect a Stray Scanner capture without reconstructing it",
        description=(
            "Validate capture structure, calibration, odometry, frame matching, "
            "and representative depth/confidence images."
        ),
    )
    validate_parser.add_argument("capture", type=Path, help="capture ZIP or directory")
    validate_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="emit the complete structured validation result as JSON",
    )
    validate_parser.set_defaults(handler=handle_validate)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""
    parser = build_parser()
    arguments = parser.parse_args(argv)
    handler = getattr(arguments, "handler", None)
    if handler is None:
        parser.print_help()
        return 0

    try:
        return int(handler(arguments))
    except Exception as exc:  # pragma: no cover - last-resort CLI boundary
        print(f"Internal error: {exc}", file=sys.stderr)
        return 1


def handle_validate(arguments: argparse.Namespace) -> int:
    """Run capture validation and map its status to a CLI exit code."""
    result = validate_capture(arguments.capture)
    if arguments.json_output:
        print(result.model_dump_json(indent=2))
    else:
        print(format_validation_report(result))
    return 0 if result.valid else 2


def format_validation_report(result: ValidationResult) -> str:
    """Render a compact human-readable capture validation report."""
    lines = [
        f"Capture: {result.source}",
        f"Format: {result.capture_format}",
        f"Status: {'VALID' if result.valid else 'INVALID'}",
    ]
    inventory = result.inventory
    if inventory is not None:
        lines.extend(
            [
                f"Source kind: {inventory.source_kind}",
                f"Capture root: {inventory.capture_root or '<root>'}",
                "",
                f"Depth frames: {inventory.depth_frame_count}",
                f"Confidence frames: {inventory.confidence_frame_count}",
                f"Odometry records: {inventory.odometry_record_count}",
                f"Matched frames: {inventory.matched_frame_count}",
                f"IMU records: {_optional_number(inventory.imu_record_count)}",
                f"RGB video: {'present' if inventory.rgb_video_present else 'missing'}",
                f"Duration: {_format_duration(inventory.duration_seconds)}",
                f"Depth image: {_format_image(inventory.depth_image_size, inventory.depth_modes)}",
                "Confidence image: "
                f"{_format_image(inventory.confidence_image_size, inventory.confidence_modes)}",
                f"Image pairs inspected: {inventory.image_pairs_inspected}",
            ]
        )

    lines.extend(
        [
            "",
            f"Errors: {result.error_count}",
            f"Warnings: {result.warning_count}",
        ]
    )
    for issue in result.issues:
        lines.append(
            f"- {issue.severity.value.upper()} [{issue.code}] {issue.message}"
        )
    return "\n".join(lines)


def _optional_number(value: int | None) -> str:
    return "not available" if value is None else str(value)


def _format_duration(value: float | None) -> str:
    return "not available" if value is None else f"{value:.2f} seconds"


def _format_image(
    size: tuple[int, int] | None, modes: tuple[str, ...]
) -> str:
    if size is None:
        return "not available"
    mode_text = ", ".join(modes) if modes else "unknown mode"
    return f"{size[0]} x {size[1]} ({mode_text})"
