"""Cross-platform, reviewer-oriented demonstration for the supplied samples."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

EXPECTED_SAMPLE_NAMES = (
    "single_room.zip",
    "single_scan_floor_only.zip",
    "single_scan_with_ceiling.zip",
)


class DemoError(ValueError):
    """Raised when the demonstration cannot be run or verified."""


def build_parser() -> argparse.ArgumentParser:
    """Create the small demonstration command-line interface."""
    parser = argparse.ArgumentParser(
        description=(
            "Run tests, validate one supplied capture, execute the complete batch, "
            "and print the evidence summary."
        )
    )
    parser.add_argument(
        "--sample-dir",
        type=Path,
        default=Path("sample"),
        help="directory containing the three supplied ZIPs (default: sample)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("runs/demo"),
        help="batch output directory (default: runs/demo)",
    )
    parser.add_argument(
        "--profile",
        choices=("test", "fast", "quality"),
        default="fast",
        help="shared reconstruction profile (default: fast)",
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="skip the unit suite when it was already run separately",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace known artifacts from an earlier demonstration",
    )
    return parser


def find_required_samples(sample_directory: str | Path) -> tuple[Path, ...]:
    """Return the three assignment samples in a stable, explicit order."""
    directory = Path(sample_directory)
    if not directory.is_dir():
        raise DemoError(f"Sample directory does not exist: {directory}")
    samples = tuple(directory / name for name in EXPECTED_SAMPLE_NAMES)
    missing = [sample.name for sample in samples if not sample.is_file()]
    if missing:
        raise DemoError("Missing supplied sample ZIPs: " + ", ".join(missing))
    return samples


def run_command(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: dict[str, str],
) -> int:
    """Run one visible demonstration command without invoking a shell."""
    completed = subprocess.run(
        tuple(command),
        cwd=cwd,
        env=environment,
        check=False,
    )
    return int(completed.returncode)


def load_batch_summary(path: str | Path) -> dict[str, object]:
    """Load and minimally verify the evidence needed by the demo summary."""
    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DemoError(f"Cannot read batch evidence: {source}") from exc
    if not isinstance(value, dict):
        raise DemoError("Batch evidence must be a JSON object")
    required = {
        "status",
        "total_capture_count",
        "succeeded_count",
        "failed_count",
        "items",
    }
    missing = sorted(required.difference(value))
    if missing:
        raise DemoError("Batch evidence is missing: " + ", ".join(missing))
    if not isinstance(value["items"], list):
        raise DemoError("Batch evidence items must be a list")
    return value


def print_batch_summary(summary: dict[str, object], output_directory: Path) -> None:
    """Print the compact evidence an assessor normally wants first."""
    print("\nDEMONSTRATION SUMMARY")
    print(f"Status: {str(summary['status']).upper()}")
    print(f"Captures: {summary['total_capture_count']}")
    print(f"Succeeded: {summary['succeeded_count']}")
    print(f"Failed: {summary['failed_count']}")
    print("")
    print(
        "Capture | Status | Outline | Area | Dimensions | Ceiling | Openings | "
        "Confidence"
    )
    print("-" * 110)
    items = summary["items"]
    assert isinstance(items, list)
    for raw_item in items:
        if not isinstance(raw_item, dict):
            raise DemoError("Batch evidence contains a non-object item")
        name = str(raw_item.get("input_name", "unknown"))
        status = str(raw_item.get("status", "unknown"))
        outline = str(raw_item.get("outline_method") or "n/a")
        area = _measurement(raw_item.get("floor_area_m2"), "m2")
        if raw_item.get("area_is_provisional") is True:
            area += " provisional"
        dimensions = _dimensions(
            raw_item.get("length_m"),
            raw_item.get("width_m"),
        )
        ceiling = _measurement(raw_item.get("ceiling_height_m"), "m")
        confidence = str(raw_item.get("measurement_confidence") or "n/a")
        openings = _openings(
            raw_item.get("opening_count"), raw_item.get("opening_status")
        )
        print(
            f"{name} | {status} | {outline} | {area} | {dimensions} | "
            f"{ceiling} | {openings} | {confidence}"
        )
    print("")
    print(f"Batch JSON: {output_directory / 'batch.json'}")
    print(f"Batch report: {output_directory / 'batch-report.md'}")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the reproducible repository demonstration."""
    arguments = build_parser().parse_args(argv)
    repository_root = Path(__file__).resolve().parents[1]
    sample_directory = arguments.sample_dir.resolve()
    output_directory = arguments.output.resolve()
    try:
        samples = find_required_samples(sample_directory)
    except DemoError as exc:
        print(f"Demo failed: {exc}", file=sys.stderr)
        return 2

    environment = os.environ.copy()
    source_directory = str(repository_root / "src")
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        source_directory
        if not existing_pythonpath
        else source_directory + os.pathsep + existing_pythonpath
    )

    if not arguments.skip_tests:
        print("\n[1/3] Running the complete unit suite", flush=True)
        test_code = run_command(
            (
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                str(repository_root / "tests"),
                "-v",
            ),
            cwd=repository_root,
            environment=environment,
        )
        if test_code:
            return test_code
    else:
        print("\n[1/3] Unit suite skipped by request", flush=True)

    print("\n[2/3] Validating single_room.zip", flush=True)
    validation_code = run_command(
        (
            sys.executable,
            "-m",
            "cozmo_scan",
            "validate",
            str(samples[0]),
        ),
        cwd=repository_root,
        environment=environment,
    )
    if validation_code:
        return validation_code

    print("\n[3/3] Running the frozen all-sample pipeline", flush=True)
    summary_path = output_directory / "batch.json"
    previous_summary_signature = _file_signature(summary_path)
    batch_command = [
        sys.executable,
        "-m",
        "cozmo_scan",
        "batch",
        str(sample_directory),
        "--output",
        str(output_directory),
        "--profile",
        arguments.profile,
    ]
    if arguments.overwrite:
        batch_command.append("--overwrite")
    batch_code = run_command(
        batch_command,
        cwd=repository_root,
        environment=environment,
    )

    current_summary_signature = _file_signature(summary_path)
    summary_was_published = (
        current_summary_signature is not None
        and current_summary_signature != previous_summary_signature
    )
    if summary_was_published:
        try:
            summary = load_batch_summary(summary_path)
            print_batch_summary(summary, output_directory)
        except DemoError as exc:
            print(f"Demo failed: {exc}", file=sys.stderr)
            return 2
    elif batch_code == 0:
        print(f"Demo failed: batch output is missing: {summary_path}", file=sys.stderr)
        return 2
    elif current_summary_signature is not None:
        print(
            "Demo note: the batch did not publish new evidence; "
            "the existing summary was not displayed.",
            file=sys.stderr,
        )
    return batch_code


def _openings(count: object, status: object) -> str:
    """Report the opening count without implying a verified absence."""
    if status != "available":
        return "unavailable"
    if not isinstance(count, int):
        return "n/a"
    if count == 0:
        return "0 (none passed gates)"
    return str(count)


def _measurement(value: object, unit: str) -> str:
    if not isinstance(value, int | float):
        return "n/a"
    return f"{float(value):.2f} {unit}"


def _dimensions(length: object, width: object) -> str:
    if not isinstance(length, int | float) or not isinstance(width, int | float):
        return "n/a"
    return f"{float(length):.2f} x {float(width):.2f} m"


def _file_signature(path: Path) -> tuple[int, int] | None:
    try:
        statistics = path.stat()
    except OSError:
        return None
    if not path.is_file():
        return None
    return statistics.st_mtime_ns, statistics.st_size


if __name__ == "__main__":
    raise SystemExit(main())
