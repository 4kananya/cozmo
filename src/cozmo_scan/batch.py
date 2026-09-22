"""Sequential multi-capture execution and reviewer-facing batch summaries."""

from __future__ import annotations

import re
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from cozmo_scan.dataset import CaptureError, discover_capture_root, open_capture
from cozmo_scan.models import BatchItemResult, BatchSummary, PipelineConfig
from cozmo_scan.outputs import FINAL_RUN_FILENAMES, OutputError, write_run_outputs
from cozmo_scan.pipeline import PipelineError, run_pipeline

BATCH_JSON_FILENAME = "batch.json"
BATCH_REPORT_FILENAME = "batch-report.md"
BATCH_FILENAMES = (BATCH_JSON_FILENAME, BATCH_REPORT_FILENAME)


class BatchError(ValueError):
    """Raised when a batch cannot be discovered or executed safely."""


def discover_captures(path: str | Path) -> tuple[Path, ...]:
    """Discover one capture or top-level capture children in stable order."""
    source = Path(path)
    if source.is_file():
        if source.suffix.casefold() != ".zip":
            raise BatchError(f"Batch input file must be a ZIP capture: {source}")
        return (source,)
    if not source.exists():
        raise BatchError(f"Batch input does not exist: {source}")
    if not source.is_dir():
        raise BatchError(f"Batch input is not a file or directory: {source}")

    captures = [
        candidate
        for candidate in source.iterdir()
        if (
            candidate.is_file()
            and candidate.suffix.casefold() == ".zip"
        )
        or (candidate.is_dir() and _looks_like_capture_directory(candidate))
    ]
    captures.sort(key=lambda candidate: (candidate.name.casefold(), candidate.name))
    if not captures:
        if _looks_like_capture_directory(source):
            return (source,)
        raise BatchError(f"No capture ZIPs or capture directories found in: {source}")

    output_names: dict[str, Path] = {}
    for capture in captures:
        output_name = _capture_output_name(capture)
        normalized = output_name.casefold()
        previous = output_names.get(normalized)
        if previous is not None:
            raise BatchError(
                "Capture output names collide: "
                f"{previous.name} and {capture.name} both map to {output_name}"
            )
        output_names[normalized] = capture
    return tuple(captures)


def run_batch(
    input_path: str | Path,
    output_directory: str | Path,
    config: PipelineConfig,
    *,
    overwrite: bool = False,
) -> BatchSummary:
    """Run the unchanged single-capture pipeline sequentially for every input."""
    captures = discover_captures(input_path)
    directory = Path(output_directory)
    output_names = tuple(_capture_output_name(capture) for capture in captures)
    _preflight_outputs(directory, output_names, overwrite=overwrite)

    started = time.perf_counter()
    items: list[BatchItemResult] = []
    for capture, output_name in zip(captures, output_names, strict=True):
        item_started = time.perf_counter()
        destination = directory / output_name
        try:
            execution = run_pipeline(capture, config)
            write_run_outputs(execution, destination, overwrite=overwrite)
        except (PipelineError, OutputError) as exc:
            items.append(
                BatchItemResult(
                    input_name=capture.name,
                    status="failed",
                    output_directory=output_name,
                    elapsed_seconds=time.perf_counter() - item_started,
                    error=str(exc),
                )
            )
            continue

        result = execution.result
        plan = result.room.floor_plan
        items.append(
            BatchItemResult(
                input_name=capture.name,
                status="succeeded",
                output_directory=output_name,
                input_sha256=result.input.sha256,
                selected_frame_count=result.reconstruction.selected_frame_count,
                output_point_count=result.reconstruction.output_point_count,
                floor_area_m2=plan.area_m2,
                area_is_provisional=(
                    plan.convex_fill_ratio
                    < result.config.structure.minimum_boundary_fill_ratio
                ),
                length_m=plan.length_m,
                width_m=plan.width_m,
                perimeter_m=plan.perimeter_m,
                floor_inlier_ratio=result.quality.floor_inlier_ratio,
                floor_rmse_m=result.quality.floor_rmse_m,
                boundary_fill_ratio=result.quality.boundary_fill_ratio,
                detected_wall_count=result.quality.detected_wall_count,
                ceiling_height_m=result.room.ceiling_height_m,
                measurement_confidence=result.quality.measurement_confidence,
                elapsed_seconds=time.perf_counter() - item_started,
                warnings=result.warnings,
            )
        )

    return summarize_runs(
        input_name=Path(input_path).name or str(input_path),
        config=config,
        elapsed_seconds=time.perf_counter() - started,
        items=tuple(items),
    )


def summarize_runs(
    *,
    input_name: str,
    config: PipelineConfig,
    elapsed_seconds: float,
    items: tuple[BatchItemResult, ...],
) -> BatchSummary:
    """Build the validated aggregate status and counts for completed items."""
    if not items:
        raise BatchError("Cannot summarize an empty batch")
    succeeded_count = sum(item.status == "succeeded" for item in items)
    failed_count = len(items) - succeeded_count
    status = "failed" if succeeded_count == 0 else "partial" if failed_count else "ok"
    return BatchSummary(
        status=status,
        input_name=input_name,
        config=config,
        total_capture_count=len(items),
        succeeded_count=succeeded_count,
        failed_count=failed_count,
        elapsed_seconds=elapsed_seconds,
        items=items,
        artifacts={
            "batch_summary": BATCH_JSON_FILENAME,
            "batch_report": BATCH_REPORT_FILENAME,
        },
    )


def write_batch_outputs(
    summary: BatchSummary,
    output_directory: str | Path,
    *,
    overwrite: bool = False,
) -> dict[str, Path]:
    """Stage and publish the JSON and Markdown batch-level evidence."""
    directory = Path(output_directory)
    if directory.exists() and not directory.is_dir():
        raise OutputError(f"Output path is not a directory: {directory}")
    conflicts = [
        directory / filename
        for filename in BATCH_FILENAMES
        if (directory / filename).exists()
    ]
    if conflicts and not overwrite:
        names = ", ".join(path.name for path in conflicts)
        raise OutputError(
            f"Batch artifacts already exist ({names}); pass --overwrite to replace them"
        )

    parent = directory.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OutputError(f"Cannot create output parent directory: {parent}") from exc

    with TemporaryDirectory(prefix=".cozmo-batch-stage-", dir=parent) as temporary:
        staging = Path(temporary)
        staged_json = staging / BATCH_JSON_FILENAME
        staged_report = staging / BATCH_REPORT_FILENAME
        write_batch_json(staged_json, summary)
        write_batch_report(staged_report, summary)
        try:
            directory.mkdir(parents=True, exist_ok=True)
            staged_json.replace(directory / BATCH_JSON_FILENAME)
            staged_report.replace(directory / BATCH_REPORT_FILENAME)
        except OSError as exc:
            raise OutputError(f"Cannot publish batch artifacts to: {directory}") from exc

    return {
        "batch_summary": directory / BATCH_JSON_FILENAME,
        "batch_report": directory / BATCH_REPORT_FILENAME,
    }


def write_batch_json(path: str | Path, summary: BatchSummary) -> None:
    """Write the versioned batch summary as UTF-8 JSON."""
    destination = Path(path)
    try:
        destination.write_text(
            summary.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise OutputError(f"Cannot write batch JSON: {destination}") from exc


def write_batch_report(path: str | Path, summary: BatchSummary) -> None:
    """Write a compact cross-capture comparison and explicit failures."""
    destination = Path(path)
    lines = [
        "# Cozmo Scan batch report",
        "",
        f"- Status: **{summary.status.upper()}**",
        f"- Input: `{_markdown_cell(summary.input_name)}`",
        f"- Captures: {summary.total_capture_count}",
        f"- Succeeded: {summary.succeeded_count}",
        f"- Failed: {summary.failed_count}",
        f"- Total elapsed: {summary.elapsed_seconds:.2f} seconds",
        f"- Profile: `{summary.config.reconstruction.profile.value}`",
        f"- Frame selection: `{summary.config.reconstruction.frame_selection.value}`",
        f"- Maximum frames per capture: {summary.config.reconstruction.max_frames}",
        "",
        "## Cross-capture results",
        "",
        (
            "| Capture | Status | Points | Area | Dimensions | Perimeter | Walls | "
            "Ceiling | Floor support | Floor RMSE | Fill | Confidence | Warnings | Runtime |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in summary.items:
        area = _optional_measurement(item.floor_area_m2, "m²")
        if item.area_is_provisional:
            area += " provisional"
        dimensions = (
            "not available"
            if item.length_m is None or item.width_m is None
            else f"{item.length_m:.2f} × {item.width_m:.2f} m"
        )
        ceiling = _optional_measurement(item.ceiling_height_m, "m")
        fill = (
            "not available"
            if item.boundary_fill_ratio is None
            else f"{item.boundary_fill_ratio:.1%}"
        )
        floor_support = (
            "not available"
            if item.floor_inlier_ratio is None
            else f"{item.floor_inlier_ratio:.1%}"
        )
        floor_rmse = _optional_measurement(item.floor_rmse_m, "m", decimals=3)
        runtime = (
            "not available"
            if item.elapsed_seconds is None
            else f"{item.elapsed_seconds:.2f} s"
        )
        lines.append(
            "| "
            + " | ".join(
                (
                    _markdown_cell(item.input_name),
                    item.status,
                    _optional_integer(item.output_point_count),
                    area,
                    dimensions,
                    _optional_measurement(item.perimeter_m, "m"),
                    _optional_integer(item.detected_wall_count),
                    ceiling,
                    floor_support,
                    floor_rmse,
                    fill,
                    item.measurement_confidence or "not available",
                    str(len(item.warnings)),
                    runtime,
                )
            )
            + " |"
        )

    failed_items = [item for item in summary.items if item.status == "failed"]
    if failed_items:
        lines.extend(["", "## Failures", ""])
        for item in failed_items:
            lines.append(
                f"- `{_markdown_cell(item.input_name)}`: "
                f"{_markdown_cell(item.error or 'unknown error')}"
            )

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            (
                "Each successful capture was processed independently with the same "
                "frozen configuration."
            ),
            (
                "Area marked provisional is the convex measured boundary and may "
                "overfill unscanned or concave regions."
            ),
            (
                "A missing ceiling means no ceiling plane passed the evidence "
                "thresholds; it is not estimated."
            ),
            (
                "No ground-truth survey dimensions were supplied, so these results "
                "do not certify absolute accuracy."
            ),
            "",
        ]
    )
    try:
        destination.write_text("\n".join(lines), encoding="utf-8")
    except OSError as exc:
        raise OutputError(f"Cannot write batch report: {destination}") from exc


def _looks_like_capture_directory(path: Path) -> bool:
    try:
        with open_capture(path) as source:
            discover_capture_root(source.members)
    except (CaptureError, OSError):
        return False
    return True


def _capture_output_name(path: Path) -> str:
    raw_name = path.stem if path.is_file() else path.name
    output_name = re.sub(r"[^A-Za-z0-9._-]+", "-", raw_name).strip(".-")
    if not output_name:
        raise BatchError(f"Capture has no safe output name: {path.name}")
    return output_name


def _preflight_outputs(
    directory: Path,
    output_names: tuple[str, ...],
    *,
    overwrite: bool,
) -> None:
    if directory.exists() and not directory.is_dir():
        raise BatchError(f"Output path is not a directory: {directory}")
    invalid_capture_paths = [
        directory / output_name
        for output_name in output_names
        if (directory / output_name).exists()
        and not (directory / output_name).is_dir()
    ]
    if invalid_capture_paths:
        shown = ", ".join(str(path) for path in invalid_capture_paths)
        raise BatchError(f"Capture output path is not a directory: {shown}")
    if overwrite:
        return
    conflicts = [
        directory / filename
        for filename in BATCH_FILENAMES
        if (directory / filename).exists()
    ]
    for output_name in output_names:
        capture_directory = directory / output_name
        conflicts.extend(
            capture_directory / filename
            for filename in FINAL_RUN_FILENAMES
            if (capture_directory / filename).exists()
        )
    if conflicts:
        shown = ", ".join(str(path) for path in conflicts[:5])
        suffix = " ..." if len(conflicts) > 5 else ""
        raise BatchError(
            f"Output artifacts already exist ({shown}{suffix}); "
            "pass --overwrite to replace them"
        )


def _optional_integer(value: int | None) -> str:
    return "not available" if value is None else str(value)


def _optional_measurement(
    value: float | None,
    unit: str,
    *,
    decimals: int = 2,
) -> str:
    return "not available" if value is None else f"{value:.{decimals}f} {unit}"


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
