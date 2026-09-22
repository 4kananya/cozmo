"""Command-line entry point for Cozmo Scan."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from cozmo_scan import __version__
from cozmo_scan.dataset import validate_capture
from cozmo_scan.models import FrameSelection, ReconstructionProfile, ValidationResult


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

    reconstruct_parser = subparsers.add_parser(
        "reconstruct",
        help="build a bounded metric point cloud and diagnostic preview",
        description=(
            "Fuse selected LiDAR depth frames using recorded camera poses and "
            "write CP03 diagnostic artifacts."
        ),
    )
    reconstruct_parser.add_argument(
        "capture", type=Path, help="validated capture ZIP or directory"
    )
    reconstruct_parser.add_argument(
        "--output", type=Path, required=True, help="artifact output directory"
    )
    reconstruct_parser.add_argument(
        "--profile",
        choices=[profile.value for profile in ReconstructionProfile],
        default=ReconstructionProfile.FAST.value,
        help="bounded processing profile (default: fast)",
    )
    reconstruct_parser.add_argument(
        "--max-frames",
        type=_positive_int,
        help="override the profile frame limit for an audited diagnostic run",
    )
    reconstruct_parser.add_argument(
        "--frame-selection",
        choices=[selection.value for selection in FrameSelection],
        default=FrameSelection.DISTRIBUTED.value,
        help="select frames across the capture or from its beginning",
    )
    reconstruct_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace known reconstruction artifacts in the output directory",
    )
    reconstruct_parser.set_defaults(handler=handle_reconstruct)

    measure_parser = subparsers.add_parser(
        "measure",
        help="reconstruct a capture and generate a measured floor plan",
        description=(
            "Reconstruct a LiDAR capture, detect structural planes, derive a "
            "convex floor outline, and write CP03/CP04 diagnostic artifacts."
        ),
    )
    measure_parser.add_argument(
        "capture", type=Path, help="validated capture ZIP or directory"
    )
    measure_parser.add_argument(
        "--output", type=Path, required=True, help="artifact output directory"
    )
    measure_parser.add_argument(
        "--profile",
        choices=[profile.value for profile in ReconstructionProfile],
        default=ReconstructionProfile.FAST.value,
        help="bounded reconstruction profile (default: fast)",
    )
    measure_parser.add_argument(
        "--max-frames",
        type=_positive_int,
        help="override the profile frame limit for an audited diagnostic run",
    )
    measure_parser.add_argument(
        "--frame-selection",
        choices=[selection.value for selection in FrameSelection],
        default=FrameSelection.DISTRIBUTED.value,
        help="select frames across the capture or from its beginning",
    )
    measure_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace known measurement artifacts in the output directory",
    )
    measure_parser.set_defaults(handler=handle_measure)

    run_parser = subparsers.add_parser(
        "run",
        help="generate the complete reviewer-facing artifact bundle",
        description=(
            "Validate, reconstruct, measure, evaluate, and write the final "
            "seven-file result bundle for one capture."
        ),
    )
    run_parser.add_argument(
        "capture", type=Path, help="validated capture ZIP or directory"
    )
    run_parser.add_argument(
        "--output", type=Path, required=True, help="artifact output directory"
    )
    run_parser.add_argument(
        "--profile",
        choices=[profile.value for profile in ReconstructionProfile],
        default=ReconstructionProfile.FAST.value,
        help="bounded reconstruction profile (default: fast)",
    )
    run_parser.add_argument(
        "--max-frames",
        type=_positive_int,
        help="override the profile frame limit for an audited run",
    )
    run_parser.add_argument(
        "--frame-selection",
        choices=[selection.value for selection in FrameSelection],
        default=FrameSelection.DISTRIBUTED.value,
        help="select frames across the capture or from its beginning",
    )
    run_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace known final artifacts in the output directory",
    )
    run_parser.set_defaults(handler=handle_run)

    batch_parser = subparsers.add_parser(
        "batch",
        help="run the final pipeline across every discovered capture",
        description=(
            "Discover supplied capture ZIPs or directories, process each one "
            "with one shared configuration, and write combined evidence."
        ),
    )
    batch_parser.add_argument(
        "input", type=Path, help="capture file, capture directory, or sample directory"
    )
    batch_parser.add_argument(
        "--output", type=Path, required=True, help="batch artifact output directory"
    )
    batch_parser.add_argument(
        "--profile",
        choices=[profile.value for profile in ReconstructionProfile],
        default=ReconstructionProfile.FAST.value,
        help="shared bounded reconstruction profile (default: fast)",
    )
    batch_parser.add_argument(
        "--max-frames",
        type=_positive_int,
        help="override the shared profile frame limit for every capture",
    )
    batch_parser.add_argument(
        "--frame-selection",
        choices=[selection.value for selection in FrameSelection],
        default=FrameSelection.DISTRIBUTED.value,
        help="shared frame-selection strategy for every capture",
    )
    batch_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace known batch and per-capture artifacts",
    )
    batch_parser.set_defaults(handler=handle_batch)
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


def handle_reconstruct(arguments: argparse.Namespace) -> int:
    """Run metric reconstruction and write its CP03 diagnostic artifacts."""
    from cozmo_scan.outputs import OutputError, write_reconstruction_outputs
    from cozmo_scan.reconstruction import (
        ReconstructionError,
        get_profile_config,
        reconstruct_capture,
    )

    try:
        config = get_profile_config(
            arguments.profile,
            max_frames=arguments.max_frames,
            frame_selection=arguments.frame_selection,
        )
        result = reconstruct_capture(arguments.capture, config)
        paths = write_reconstruction_outputs(
            result,
            arguments.output,
            overwrite=arguments.overwrite,
        )
    except (OutputError, ReconstructionError, ValueError) as exc:
        print(f"Reconstruction failed: {exc}", file=sys.stderr)
        return 2

    statistics = result.summary.statistics
    print(f"Status: {result.summary.status.upper()}")
    print(f"Selected frames: {statistics.selected_frame_count}")
    print(f"Processed frames: {statistics.processed_frame_count}")
    print(f"Valid points before voxel: {statistics.valid_point_count_before_voxel}")
    print(f"Output points: {statistics.output_point_count}")
    print(f"Elapsed: {result.summary.elapsed_seconds:.2f} seconds")
    for name, path in paths.items():
        print(f"{name}: {path}")
    for warning in result.summary.warnings:
        print(f"WARNING: {warning}")
    return 0


def handle_measure(arguments: argparse.Namespace) -> int:
    """Reconstruct a capture, measure its structure, and write CP04 artifacts."""
    from cozmo_scan.floorplan import StructureError, analyze_structure
    from cozmo_scan.outputs import OutputError, write_measurement_outputs
    from cozmo_scan.reconstruction import (
        ReconstructionError,
        get_profile_config,
        reconstruct_capture,
    )

    try:
        config = get_profile_config(
            arguments.profile,
            max_frames=arguments.max_frames,
            frame_selection=arguments.frame_selection,
        )
        reconstruction = reconstruct_capture(arguments.capture, config)
        structure = analyze_structure(reconstruction)
        paths = write_measurement_outputs(
            reconstruction,
            structure,
            arguments.output,
            overwrite=arguments.overwrite,
        )
    except (OutputError, ReconstructionError, StructureError, ValueError) as exc:
        print(f"Measurement failed: {exc}", file=sys.stderr)
        return 2

    plan = structure.summary.floor_plan
    print(f"Status: {structure.summary.status.upper()}")
    area_label = (
        "Floor area (convex/provisional)"
        if plan.convex_fill_ratio < structure.summary.config.minimum_boundary_fill_ratio
        else "Floor area"
    )
    print(f"{area_label}: {plan.area_m2:.2f} square metres")
    print(f"Principal dimensions: {plan.length_m:.2f} x {plan.width_m:.2f} metres")
    print(f"Perimeter: {plan.perimeter_m:.2f} metres")
    print(f"Detected walls: {len(structure.summary.walls)}")
    if structure.summary.ceiling_height_m is None:
        print("Ceiling height: not available")
    else:
        print(f"Ceiling height: {structure.summary.ceiling_height_m:.2f} metres")
    for name, path in paths.items():
        print(f"{name}: {path}")
    for warning in structure.summary.warnings:
        print(f"WARNING: {warning}")
    return 0


def handle_run(arguments: argparse.Namespace) -> int:
    """Run the final single-capture product pipeline and artifact writer."""
    from cozmo_scan.outputs import OutputError, write_run_outputs
    from cozmo_scan.pipeline import PipelineError, get_pipeline_config, run_pipeline

    try:
        config = get_pipeline_config(
            arguments.profile,
            max_frames=arguments.max_frames,
            frame_selection=arguments.frame_selection,
        )
        execution = run_pipeline(arguments.capture, config)
        paths = write_run_outputs(
            execution,
            arguments.output,
            overwrite=arguments.overwrite,
        )
    except (OutputError, PipelineError, ValueError) as exc:
        print(f"Pipeline failed: {exc}", file=sys.stderr)
        return 2

    result = execution.result
    plan = result.room.floor_plan
    provisional = (
        plan.convex_fill_ratio < result.config.structure.minimum_boundary_fill_ratio
    )
    print(f"Status: {result.status.upper()}")
    print(f"Input SHA-256: {result.input.sha256}")
    print(
        f"Floor area{' (convex/provisional)' if provisional else ''}: "
        f"{plan.area_m2:.2f} square metres"
    )
    print(f"Principal dimensions: {plan.length_m:.2f} x {plan.width_m:.2f} metres")
    print(f"Measurement confidence: {result.quality.measurement_confidence.upper()}")
    print(f"Total elapsed: {result.timings.total_seconds:.2f} seconds")
    for name, path in paths.items():
        print(f"{name}: {path}")
    for warning in result.warnings:
        print(f"WARNING: {warning}")
    return 0


def handle_batch(arguments: argparse.Namespace) -> int:
    """Run all discovered captures with one frozen pipeline configuration."""
    from cozmo_scan.batch import (
        BatchError,
        run_batch,
        write_batch_outputs,
    )
    from cozmo_scan.outputs import OutputError
    from cozmo_scan.pipeline import get_pipeline_config

    try:
        config = get_pipeline_config(
            arguments.profile,
            max_frames=arguments.max_frames,
            frame_selection=arguments.frame_selection,
        )
        summary = run_batch(
            arguments.input,
            arguments.output,
            config,
            overwrite=arguments.overwrite,
        )
        paths = write_batch_outputs(
            summary,
            arguments.output,
            overwrite=arguments.overwrite,
        )
    except (BatchError, OutputError, ValueError) as exc:
        print(f"Batch failed: {exc}", file=sys.stderr)
        return 2

    print(f"Status: {summary.status.upper()}")
    print(f"Captures: {summary.total_capture_count}")
    print(f"Succeeded: {summary.succeeded_count}")
    print(f"Failed: {summary.failed_count}")
    print(f"Total elapsed: {summary.elapsed_seconds:.2f} seconds")
    for item in summary.items:
        detail = item.error if item.status == "failed" else item.output_directory
        print(f"{item.status.upper()}: {item.input_name}: {detail}")
    for name, path in paths.items():
        print(f"{name}: {path}")
    return 0 if summary.failed_count == 0 else 2


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


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return parsed
