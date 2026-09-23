"""Small, deterministic output writers for reconstruction and measurements."""

from __future__ import annotations

from html import escape
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageDraw, ImageFont

from cozmo_scan.floorplan import StructureResult
from cozmo_scan.models import (
    ReconstructionStatistics,
    ReconstructionSummary,
    RunResult,
    StructureSummary,
)
from cozmo_scan.pipeline import FINAL_ARTIFACT_RECORDS, PipelineExecution
from cozmo_scan.reconstruction import ReconstructionResult

POINT_CLOUD_FILENAME = "reconstruction.ply"
TOPDOWN_FILENAME = "topdown.png"
SUMMARY_FILENAME = "reconstruction.json"
RECONSTRUCTION_FILENAMES = (
    POINT_CLOUD_FILENAME,
    TOPDOWN_FILENAME,
    SUMMARY_FILENAME,
)
STRUCTURE_FILENAME = "structure.json"
FLOORPLAN_SVG_FILENAME = "floorplan.svg"
FLOORPLAN_PNG_FILENAME = "floorplan.png"
MEASUREMENT_FILENAMES = RECONSTRUCTION_FILENAMES + (
    STRUCTURE_FILENAME,
    FLOORPLAN_SVG_FILENAME,
    FLOORPLAN_PNG_FILENAME,
)
FINAL_RUN_FILENAMES = tuple(record.filename for record in FINAL_ARTIFACT_RECORDS)


class OutputError(ValueError):
    """Raised when reconstruction artifacts cannot be written safely."""


def write_reconstruction_outputs(
    result: ReconstructionResult,
    output_directory: str | Path,
    *,
    overwrite: bool = False,
) -> dict[str, Path]:
    """Write the complete CP03 diagnostic artifact set."""
    directory = Path(output_directory)
    if directory.exists() and not directory.is_dir():
        raise OutputError(f"Output path is not a directory: {directory}")

    existing = [directory / name for name in RECONSTRUCTION_FILENAMES]
    conflicts = [path for path in existing if path.exists()]
    if conflicts and not overwrite:
        names = ", ".join(path.name for path in conflicts)
        raise OutputError(
            f"Output artifacts already exist ({names}); pass --overwrite to replace them"
        )

    directory.mkdir(parents=True, exist_ok=True)
    paths = {
        "point_cloud": directory / POINT_CLOUD_FILENAME,
        "topdown_preview": directory / TOPDOWN_FILENAME,
        "summary": directory / SUMMARY_FILENAME,
    }
    write_ply(paths["point_cloud"], result.points_xyz_m)
    render_topdown(
        paths["topdown_preview"],
        result.points_xyz_m,
        result.trajectory_xyz_m,
    )
    write_reconstruction_summary(paths["summary"], result.summary)
    return paths


def write_measurement_outputs(
    reconstruction: ReconstructionResult,
    structure: StructureResult,
    output_directory: str | Path,
    *,
    overwrite: bool = False,
) -> dict[str, Path]:
    """Write the combined CP03/CP04 diagnostic and floor-plan artifacts."""
    directory = Path(output_directory)
    if directory.exists() and not directory.is_dir():
        raise OutputError(f"Output path is not a directory: {directory}")
    conflicts = [
        directory / filename
        for filename in MEASUREMENT_FILENAMES
        if (directory / filename).exists()
    ]
    if conflicts and not overwrite:
        names = ", ".join(path.name for path in conflicts)
        raise OutputError(
            f"Output artifacts already exist ({names}); pass --overwrite to replace them"
        )

    directory.mkdir(parents=True, exist_ok=True)
    paths = write_reconstruction_outputs(
        reconstruction,
        directory,
        overwrite=True,
    )
    structure_paths = {
        "structure_summary": directory / STRUCTURE_FILENAME,
        "floorplan_vector": directory / FLOORPLAN_SVG_FILENAME,
        "floorplan_preview": directory / FLOORPLAN_PNG_FILENAME,
    }
    write_structure_summary(structure_paths["structure_summary"], structure.summary)
    render_floorplan_svg(structure_paths["floorplan_vector"], structure.summary)
    render_floorplan_png(structure_paths["floorplan_preview"], structure.summary)
    paths.update(structure_paths)
    return paths


def write_run_outputs(
    execution: PipelineExecution,
    output_directory: str | Path,
    *,
    overwrite: bool = False,
) -> dict[str, Path]:
    """Stage and publish the complete seven-file reviewer artifact bundle."""
    directory = Path(output_directory)
    if directory.exists() and not directory.is_dir():
        raise OutputError(f"Output path is not a directory: {directory}")
    conflicts = [
        directory / filename
        for filename in FINAL_RUN_FILENAMES
        if (directory / filename).exists()
    ]
    if conflicts and not overwrite:
        names = ", ".join(path.name for path in conflicts)
        raise OutputError(
            f"Output artifacts already exist ({names}); pass --overwrite to replace them"
        )

    parent = directory.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OutputError(f"Cannot create output parent directory: {parent}") from exc

    with TemporaryDirectory(prefix=".cozmo-scan-stage-", dir=parent) as temporary:
        staging = Path(temporary)
        staged_paths = {
            record.key: staging / record.filename for record in FINAL_ARTIFACT_RECORDS
        }
        write_ply(
            staged_paths["point_cloud"],
            execution.reconstruction.points_xyz_m,
        )
        render_topdown(
            staged_paths["topdown_preview"],
            execution.reconstruction.points_xyz_m,
            execution.reconstruction.trajectory_xyz_m,
        )
        render_trajectory(
            staged_paths["trajectory_preview"],
            execution.reconstruction.trajectory_xyz_m,
            execution.reconstruction.summary.statistics,
        )
        render_floorplan_svg(
            staged_paths["floorplan_vector"],
            execution.structure.summary,
        )
        render_floorplan_png(
            staged_paths["floorplan_preview"],
            execution.structure.summary,
        )
        write_report(staged_paths["report"], execution.result)
        write_result_json(staged_paths["result"], execution.result)

        missing = [path.name for path in staged_paths.values() if not path.is_file()]
        if missing:
            raise OutputError(
                f"Staged artifact set is incomplete: {', '.join(missing)}"
            )
        try:
            directory.mkdir(parents=True, exist_ok=True)
            for record in FINAL_ARTIFACT_RECORDS:
                staged_paths[record.key].replace(directory / record.filename)
        except OSError as exc:
            raise OutputError(f"Cannot publish run artifacts to: {directory}") from exc

    return {
        record.key: directory / record.filename for record in FINAL_ARTIFACT_RECORDS
    }


def write_ply(path: str | Path, points_xyz_m: NDArray[np.floating]) -> None:
    """Write XYZ points as a compact binary little-endian PLY file."""
    points = np.asarray(points_xyz_m)
    if points.ndim != 2 or points.shape[1] != 3:
        raise OutputError("PLY points must have shape (N, 3)")
    if not np.isfinite(points).all():
        raise OutputError("PLY points contain non-finite values")

    destination = Path(path)
    temporary = destination.with_name(f"{destination.name}.tmp")
    header = (
        "ply\n"
        "format binary_little_endian 1.0\n"
        "comment generated by cozmo-scan\n"
        f"element vertex {len(points)}\n"
        "property float x\n"
        "property float y\n"
        "property float z\n"
        "end_header\n"
    ).encode("ascii")
    try:
        with temporary.open("wb") as stream:
            stream.write(header)
            np.asarray(points, dtype="<f4").tofile(stream)
        temporary.replace(destination)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise OutputError(f"Cannot write PLY output: {destination}") from exc


def render_topdown(
    path: str | Path,
    points_xyz_m: NDArray[np.floating],
    trajectory_xyz_m: NDArray[np.floating] | None = None,
    *,
    image_size: int = 1000,
) -> None:
    """Render a robust X-Z density view with an optional camera trajectory."""
    points = np.asarray(points_xyz_m)
    if points.ndim != 2 or points.shape[1] != 3 or len(points) == 0:
        raise OutputError("Top-down points must be a non-empty array with shape (N, 3)")
    if image_size < 64:
        raise OutputError("Top-down image_size must be at least 64 pixels")

    finite = points[np.isfinite(points).all(axis=1)]
    if len(finite) == 0:
        raise OutputError("Top-down points contain no finite values")
    x = finite[:, 0]
    z = finite[:, 2]
    x_min, x_max = _robust_axis_range(x)
    z_min, z_max = _robust_axis_range(z)

    trajectory = None
    if trajectory_xyz_m is not None:
        candidate = np.asarray(trajectory_xyz_m)
        if candidate.ndim == 2 and candidate.shape[1] == 3:
            trajectory = candidate[np.isfinite(candidate).all(axis=1)]
            if len(trajectory):
                x_min = min(x_min, float(trajectory[:, 0].min()))
                x_max = max(x_max, float(trajectory[:, 0].max()))
                z_min = min(z_min, float(trajectory[:, 2].min()))
                z_max = max(z_max, float(trajectory[:, 2].max()))
                x_min, x_max = _pad_axis_range(x_min, x_max)
                z_min, z_max = _pad_axis_range(z_min, z_max)

    histogram, _, _ = np.histogram2d(
        z,
        x,
        bins=(image_size, image_size),
        range=((z_min, z_max), (x_min, x_max)),
    )
    density = np.log1p(histogram)
    if density.max() > 0:
        density /= density.max()
    grayscale = 255 - np.asarray(density * 235, dtype=np.uint8)
    image = Image.fromarray(np.flipud(grayscale), mode="L").convert("RGB")

    if trajectory is not None and len(trajectory):
        _draw_trajectory(
            image,
            trajectory,
            x_range=(x_min, x_max),
            z_range=(z_min, z_max),
        )

    destination = Path(path)
    temporary = destination.with_name(f"{destination.name}.tmp")
    try:
        image.save(temporary, format="PNG")
        temporary.replace(destination)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise OutputError(f"Cannot write top-down output: {destination}") from exc


def write_reconstruction_summary(
    path: str | Path, summary: ReconstructionSummary
) -> None:
    """Write the diagnostic summary as formatted UTF-8 JSON."""
    destination = Path(path)
    temporary = destination.with_name(f"{destination.name}.tmp")
    try:
        temporary.write_text(summary.model_dump_json(indent=2) + "\n", encoding="utf-8")
        temporary.replace(destination)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise OutputError(f"Cannot write reconstruction summary: {destination}") from exc


def write_structure_summary(path: str | Path, summary: StructureSummary) -> None:
    """Write structural measurements as formatted UTF-8 JSON."""
    destination = Path(path)
    temporary = destination.with_name(f"{destination.name}.tmp")
    try:
        temporary.write_text(summary.model_dump_json(indent=2) + "\n", encoding="utf-8")
        temporary.replace(destination)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise OutputError(f"Cannot write structure summary: {destination}") from exc


def write_result_json(path: str | Path, result: RunResult) -> None:
    """Write the versioned final result atomically as UTF-8 JSON."""
    destination = Path(path)
    temporary = destination.with_name(f"{destination.name}.tmp")
    try:
        temporary.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
        temporary.replace(destination)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise OutputError(f"Cannot write final result JSON: {destination}") from exc


def write_report(path: str | Path, result: RunResult) -> None:
    """Write a self-contained Markdown report for a human reviewer."""
    plan = result.room.floor_plan
    area_label = (
        "Floor area (provisional)"
        if plan.boundary_support_ratio
        < result.config.structure.minimum_boundary_fill_ratio
        else "Floor area"
    )
    outline_label = _outline_method_label(plan.outline_method)
    ceiling = (
        "Not available — no ceiling plane passed the evidence checks."
        if result.room.ceiling_height_m is None
        else f"{result.room.ceiling_height_m:.2f} m"
    )
    warnings = (
        "\n".join(f"- {warning}" for warning in result.warnings)
        if result.warnings
        else "- None"
    )
    capabilities = "\n".join(
        f"| `{item.capability}` | `{item.status.value}` | {_markdown_cell(item.explanation)} |"
        for item in result.capabilities
    )
    artifacts = "\n".join(
        f"| `{item.filename}` | {item.description} |"
        for item in result.artifacts.artifacts
    )
    inventory = result.input.inventory
    report = f"""# Cozmo Scan Result

## Executive summary

- Status: `{result.status}`
- Input: `{result.input.name}`
- Profile: `{result.config.reconstruction.profile.value}`
- Measurement confidence: `{result.quality.measurement_confidence}`
- {area_label}: **{plan.area_m2:.2f} m²**
- Principal dimensions: **{plan.length_m:.2f} × {plan.width_m:.2f} m**
- Perimeter: **{plan.perimeter_m:.2f} m**
- Ceiling height: **{ceiling}**

This is an offline geometric estimate from the supplied LiDAR depth, confidence, intrinsics, and recorded poses. It is not a certified survey and no ground-truth dimensions were supplied.

## Input and provenance

| Field | Value |
|---|---|
| Capture format | `{result.input.capture_format}` |
| Source kind | `{result.input.source_kind}` |
| SHA-256 | `{result.input.sha256}` |
| Hash method | `{result.input.hash_kind}` |
| Input bytes | {result.input.byte_count:,} |
| Matched frames | {inventory.matched_frame_count:,} |
| Capture duration | {_optional_seconds(inventory.duration_seconds)} |
| Package version | `{result.software.package_version}` |
| Python version | `{result.software.python_version}` |

## Measurements

| Measurement | Value |
|---|---:|
| {area_label} | {plan.area_m2:.2f} m² |
| Principal length | {plan.length_m:.2f} m |
| Principal width | {plan.width_m:.2f} m |
| Perimeter | {plan.perimeter_m:.2f} m |
| Ceiling height | {ceiling} |
| Detected wall planes | {len(result.room.walls)} |
| Polygon vertices | {len(plan.vertices_xy_m)} |
| Outline method | {outline_label} |

## Quality evidence

| Evidence | Value |
|---|---:|
| Valid sampled depth | {result.quality.valid_sampled_depth_ratio:.1%} |
| Points retained after voxel fusion | {result.quality.voxel_retention_ratio:.1%} |
| Floor support | {result.quality.floor_inlier_ratio:.1%} |
| Floor-plane RMSE | {result.quality.floor_rmse_m:.3f} m |
| Floor/world-up alignment | {result.quality.floor_world_up_alignment:.5f} |
| Occupied support inside selected outline | {result.quality.boundary_fill_ratio:.1%} |
| Connected occupancy components | {plan.connected_component_count} |
| Retained component support | {plan.retained_component_ratio:.1%} |
| Discarded occupied cells | {plan.discarded_cell_count} |
| Camera path length | {_optional_metres(result.reconstruction.trajectory_path_length_m)} |
| Start-to-end distance | {_optional_metres(result.quality.closure_proxy_m)} |

The start-to-end value is only a closure proxy. It is **not certified drift** and is not an accuracy score.

## Warnings

{warnings}

## Artifacts

| File | Purpose |
|---|---|
{artifacts}

## Method

The pipeline validates the capture, selects deterministic keyframes, filters depth by confidence and range, scales camera intrinsics to the depth resolution, back-projects metric points, transforms them with recorded camera-to-world poses, and voxel-downsamples the fused cloud. It then detects a camera-relative floor, an optional evidence-supported ceiling, and gravity-aligned wall planes. Floor inliers are projected to a local occupancy grid. A cleaned, simple concave contour is used only when component retention and support improve over the occupancy convex hull; otherwise the prior convex boundary remains the safety fallback.

## Assignment capability coverage

| Capability | Status | Explanation |
|---|---|---|
{capabilities}

## Limitations

- Occupancy contours can follow unscanned gaps; weak, fragmented, invalid, or overly complex contours fall back to a convex boundary that can overfill concavity.
- Measurements are internal geometric estimates; absolute accuracy was not evaluated because no reference dimensions were supplied.
- Furniture, reflective surfaces, pose error, incomplete coverage, and LiDAR noise can affect the result.
- Missing evidence remains unavailable rather than being replaced with zero or an invented value.
- Damage, concealed conditions, and repair scope require validated labelled evidence that is not present in the supplied data.

## Reproduce this run

```text
python -m cozmo_scan run "<capture-path>/{result.input.name}" --output <output-directory> --profile {result.config.reconstruction.profile.value}
```
"""
    destination = Path(path)
    temporary = destination.with_name(f"{destination.name}.tmp")
    try:
        temporary.write_text(report, encoding="utf-8")
        temporary.replace(destination)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise OutputError(f"Cannot write Markdown report: {destination}") from exc


def render_trajectory(
    path: str | Path,
    trajectory_xyz_m: NDArray[np.floating],
    statistics: ReconstructionStatistics,
    *,
    width: int = 1000,
    height: int = 700,
) -> None:
    """Render the X-Z camera path and explicitly labelled closure proxy."""
    trajectory = np.asarray(trajectory_xyz_m, dtype=np.float64)
    if trajectory.ndim != 2 or trajectory.shape[1] != 3 or len(trajectory) == 0:
        raise OutputError("Trajectory must be a non-empty array with shape (N, 3)")
    trajectory = trajectory[np.isfinite(trajectory).all(axis=1)]
    if len(trajectory) == 0:
        raise OutputError("Trajectory contains no finite positions")

    panel_width = 300
    x_values = trajectory[:, 0]
    z_values = trajectory[:, 2]
    x_min, x_max = _pad_axis_range(float(x_values.min()), float(x_values.max()))
    z_min, z_max = _pad_axis_range(float(z_values.min()), float(z_values.max()))
    available_width = width - panel_width - 100
    available_height = height - 100
    scale = min(
        available_width / max(x_max - x_min, 1e-9),
        available_height / max(z_max - z_min, 1e-9),
    )
    centre_x = (x_min + x_max) / 2
    centre_z = (z_min + z_max) / 2
    pixels = [
        (
            round((float(point[0]) - centre_x) * scale + (width - panel_width) / 2),
            round(-(float(point[2]) - centre_z) * scale + height / 2),
        )
        for point in trajectory
    ]

    image = Image.new("RGB", (width, height), (248, 250, 252))
    drawing = ImageDraw.Draw(image)
    drawing.rounded_rectangle(
        (25, 25, width - panel_width - 25, height - 25),
        radius=14,
        fill=(255, 255, 255),
        outline=(203, 213, 225),
        width=2,
    )
    if len(pixels) > 1:
        drawing.line(pixels, fill=(37, 99, 235), width=4)
    _draw_marker(drawing, pixels[0], 7, (22, 163, 74))
    _draw_marker(drawing, pixels[-1], 7, (220, 38, 38))
    scale_start = (60, height - 60)
    scale_end = (round(scale_start[0] + scale), height - 60)
    drawing.line((*scale_start, *scale_end), fill=(21, 34, 56), width=4)
    drawing.line((scale_start[0], height - 68, scale_start[0], height - 52), fill=(21, 34, 56), width=3)
    drawing.line((scale_end[0], height - 68, scale_end[0], height - 52), fill=(21, 34, 56), width=3)

    panel_x = width - panel_width + 25
    drawing.line((width - panel_width, 25, width - panel_width, height - 25), fill=(203, 213, 225), width=2)
    title_font = _load_font(24, bold=True)
    value_font = _load_font(17, bold=True)
    label_font = _load_font(14)
    drawing.text((panel_x, 55), "CAMERA TRAJECTORY", fill=(21, 34, 56), font=title_font)
    drawing.text((panel_x, 125), "Path length", fill=(37, 56, 88), font=label_font)
    drawing.text(
        (panel_x, 150),
        _optional_metres(statistics.trajectory_path_length_m),
        fill=(11, 110, 79),
        font=value_font,
    )
    drawing.text((panel_x, 210), "Start-to-end distance", fill=(37, 56, 88), font=label_font)
    drawing.text(
        (panel_x, 235),
        _optional_metres(statistics.closure_proxy_m),
        fill=(11, 110, 79),
        font=value_font,
    )
    drawing.text((panel_x, 295), "Not certified drift", fill=(185, 28, 28), font=label_font)
    drawing.text((panel_x, 350), "Green: start", fill=(22, 101, 52), font=label_font)
    drawing.text((panel_x, 378), "Red: end", fill=(153, 27, 27), font=label_font)
    drawing.text(
        ((scale_start[0] + scale_end[0]) // 2, height - 80),
        "1 metre",
        fill=(21, 34, 56),
        anchor="mm",
        font=label_font,
    )

    destination = Path(path)
    temporary = destination.with_name(f"{destination.name}.tmp")
    try:
        image.save(temporary, format="PNG")
        temporary.replace(destination)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise OutputError(f"Cannot write trajectory PNG: {destination}") from exc


def render_floorplan_svg(path: str | Path, summary: StructureSummary) -> None:
    """Render a scalable measured floor plan without an external plotting stack."""
    vertices = np.asarray(summary.floor_plan.vertices_xy_m, dtype=np.float64)
    pixels = _floorplan_pixels(vertices, width=1200, height=800, panel_width=330)
    wall_segments = _wall_segment_pixels(
        summary, vertices, width=1200, height=800, panel_width=330
    )
    polygon = " ".join(f"{x:.1f},{y:.1f}" for x, y in pixels)
    pixels_per_metre = float(
        np.linalg.norm(pixels[1] - pixels[0])
        / summary.floor_plan.edge_lengths_m[0]
    )
    centroid = pixels.mean(axis=0)
    edge_labels: list[str] = []
    label_indices = _dimension_label_indices(summary.floor_plan.edge_lengths_m)
    for index, length in enumerate(summary.floor_plan.edge_lengths_m):
        if index not in label_indices:
            continue
        start = pixels[index]
        end = pixels[(index + 1) % len(pixels)]
        midpoint = (start + end) / 2
        outward = midpoint - centroid
        norm = float(np.linalg.norm(outward))
        if norm > 1e-9:
            midpoint += outward / norm * 16
        edge_labels.append(
            f'<text x="{midpoint[0]:.1f}" y="{midpoint[1]:.1f}" '
            'class="dimension" text-anchor="middle">'
            f"{length:.2f} m</text>"
        )
    ceiling_text = (
        "not available"
        if summary.ceiling_height_m is None
        else f"{summary.ceiling_height_m:.2f} m"
    )
    warning = escape(summary.warnings[0]) if summary.warnings else "None"
    area_label = (
        "Floor area (provisional)"
        if summary.floor_plan.boundary_support_ratio < summary.config.minimum_boundary_fill_ratio
        else "Floor area"
    )
    wall_lines = "".join(
        f'<line x1="{start[0]:.1f}" y1="{start[1]:.1f}" '
        f'x2="{end[0]:.1f}" y2="{end[1]:.1f}" class="wall"/>'
        for start, end in wall_segments
    )
    svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="800" viewBox="0 0 1200 800">
  <defs><clipPath id="plan-clip"><rect x="30" y="30" width="810" height="740" rx="14"/></clipPath></defs>
  <style>
    .title {{ font: 700 28px sans-serif; fill: #152238; }}
    .label {{ font: 18px sans-serif; fill: #253858; }}
    .value {{ font: 700 20px sans-serif; fill: #0b6e4f; }}
    .dimension {{ font: 14px sans-serif; fill: #334155; paint-order: stroke; stroke: white; stroke-width: 4px; }}
    .note {{ font: 13px sans-serif; fill: #64748b; }}
    .wall {{ stroke: #0f766e; stroke-width: 3; stroke-dasharray: 10 7; opacity: 0.75; }}
  </style>
  <rect width="1200" height="800" fill="#f8fafc"/>
  <rect x="30" y="30" width="810" height="740" rx="14" fill="white" stroke="#cbd5e1"/>
  <polygon points="{polygon}" fill="#dbeafe" stroke="#1d4ed8" stroke-width="4" stroke-linejoin="round"/>
  <g clip-path="url(#plan-clip)">{wall_lines}</g>
  {''.join(edge_labels)}
  <line x1="75" y1="735" x2="{75 + pixels_per_metre:.1f}" y2="735" stroke="#152238" stroke-width="4"/>
  <line x1="75" y1="727" x2="75" y2="743" stroke="#152238" stroke-width="3"/>
  <line x1="{75 + pixels_per_metre:.1f}" y1="727" x2="{75 + pixels_per_metre:.1f}" y2="743" stroke="#152238" stroke-width="3"/>
  <text x="{75 + pixels_per_metre / 2:.1f}" y="722" class="dimension" text-anchor="middle">1 metre</text>
  <line x1="870" y1="30" x2="870" y2="770" stroke="#cbd5e1"/>
  <text x="900" y="75" class="title">Measured floor plan</text>
  <text x="900" y="125" class="label">Principal dimensions</text>
  <text x="900" y="153" class="value">{summary.floor_plan.length_m:.2f} x {summary.floor_plan.width_m:.2f} m</text>
  <text x="900" y="205" class="label">{area_label}</text>
  <text x="900" y="233" class="value">{summary.floor_plan.area_m2:.2f} m²</text>
  <text x="900" y="285" class="label">Perimeter</text>
  <text x="900" y="313" class="value">{summary.floor_plan.perimeter_m:.2f} m</text>
  <text x="900" y="365" class="label">Ceiling height</text>
  <text x="900" y="393" class="value">{ceiling_text}</text>
  <text x="900" y="445" class="label">Detected walls</text>
  <text x="900" y="473" class="value">{len(summary.walls)}</text>
  <text x="900" y="535" class="note">{_outline_method_label(summary.floor_plan.outline_method)}</text>
  <text x="900" y="560" class="note">Units: metres</text>
  <text x="900" y="585" class="note">Occupied support: {summary.floor_plan.boundary_support_ratio:.1%}</text>
  <text x="900" y="605" class="note">Teal markers: detected wall direction</text>
  <text x="900" y="625" class="note">{warning[:42]}</text>
  <text x="900" y="645" class="note">{warning[42:84]}</text>
</svg>
"""
    destination = Path(path)
    temporary = destination.with_name(f"{destination.name}.tmp")
    try:
        temporary.write_text(svg, encoding="utf-8")
        temporary.replace(destination)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise OutputError(f"Cannot write floor-plan SVG: {destination}") from exc


def render_floorplan_png(path: str | Path, summary: StructureSummary) -> None:
    """Render an easy-to-open raster preview of the measured floor plan."""
    width, height, panel_width = 1200, 800, 330
    vertices = np.asarray(summary.floor_plan.vertices_xy_m, dtype=np.float64)
    pixels_array = _floorplan_pixels(
        vertices, width=width, height=height, panel_width=panel_width
    )
    wall_segments = _wall_segment_pixels(
        summary, vertices, width=width, height=height, panel_width=panel_width
    )
    pixels = [(round(point[0]), round(point[1])) for point in pixels_array]
    pixels_per_metre = float(
        np.linalg.norm(pixels_array[1] - pixels_array[0])
        / summary.floor_plan.edge_lengths_m[0]
    )
    image = Image.new("RGB", (width, height), (248, 250, 252))
    drawing = ImageDraw.Draw(image)
    title_font = _load_font(24, bold=True)
    value_font = _load_font(17, bold=True)
    label_font = _load_font(15)
    note_font = _load_font(14)
    dimension_font = _load_font(13)
    drawing.rounded_rectangle(
        (30, 30, width - panel_width - 30, height - 30),
        radius=14,
        fill=(255, 255, 255),
        outline=(203, 213, 225),
        width=2,
    )
    drawing.polygon(pixels, fill=(219, 234, 254), outline=(29, 78, 216), width=4)
    for start, end in wall_segments:
        drawing.line(
            (round(start[0]), round(start[1]), round(end[0]), round(end[1])),
            fill=(15, 118, 110),
            width=3,
        )
    scale_start_x = 75
    scale_end_x = round(scale_start_x + pixels_per_metre)
    drawing.line((scale_start_x, 735, scale_end_x, 735), fill=(21, 34, 56), width=4)
    drawing.line((scale_start_x, 727, scale_start_x, 743), fill=(21, 34, 56), width=3)
    drawing.line((scale_end_x, 727, scale_end_x, 743), fill=(21, 34, 56), width=3)
    drawing.text(
        ((scale_start_x + scale_end_x) // 2, 718),
        "1 metre",
        fill=(21, 34, 56),
        anchor="mm",
        font=dimension_font,
    )
    centroid = pixels_array.mean(axis=0)
    label_indices = _dimension_label_indices(summary.floor_plan.edge_lengths_m)
    for index, length in enumerate(summary.floor_plan.edge_lengths_m):
        if index not in label_indices:
            continue
        start = pixels_array[index]
        end = pixels_array[(index + 1) % len(pixels_array)]
        midpoint = (start + end) / 2
        outward = midpoint - centroid
        norm = float(np.linalg.norm(outward))
        if norm > 1e-9:
            midpoint += outward / norm * 14
        drawing.text(
            (round(midpoint[0]), round(midpoint[1])),
            f"{length:.2f} m",
            fill=(51, 65, 85),
            anchor="mm",
            stroke_width=3,
            stroke_fill=(255, 255, 255),
            font=dimension_font,
        )
    panel_x = width - panel_width + 30
    drawing.line((width - panel_width, 30, width - panel_width, height - 30), fill=(203, 213, 225), width=2)
    drawing.text(
        (panel_x, 55),
        "MEASURED FLOOR PLAN",
        fill=(21, 34, 56),
        font=title_font,
    )
    drawing.text(
        (panel_x, 115),
        f"Size: {summary.floor_plan.length_m:.2f} x {summary.floor_plan.width_m:.2f} m",
        fill=(11, 110, 79),
        font=value_font,
    )
    drawing.text(
        (panel_x, 155),
        (
            f"Area (provisional): {summary.floor_plan.area_m2:.2f} m2"
            if summary.floor_plan.boundary_support_ratio
            < summary.config.minimum_boundary_fill_ratio
            else f"Area: {summary.floor_plan.area_m2:.2f} m2"
        ),
        fill=(11, 110, 79),
        font=value_font,
    )
    drawing.text(
        (panel_x, 195),
        f"Perimeter: {summary.floor_plan.perimeter_m:.2f} m",
        fill=(11, 110, 79),
        font=value_font,
    )
    ceiling_text = (
        "not available"
        if summary.ceiling_height_m is None
        else f"{summary.ceiling_height_m:.2f} m"
    )
    drawing.text(
        (panel_x, 235),
        f"Ceiling: {ceiling_text}",
        fill=(37, 56, 88),
        font=label_font,
    )
    drawing.text(
        (panel_x, 275),
        f"Walls: {len(summary.walls)}",
        fill=(37, 56, 88),
        font=label_font,
    )
    drawing.text(
        (panel_x, 335),
        _outline_method_label(summary.floor_plan.outline_method),
        fill=(100, 116, 139),
        font=note_font,
    )
    drawing.text(
        (panel_x, 360), "Units: metres", fill=(100, 116, 139), font=note_font
    )
    drawing.text(
        (panel_x, 385),
        f"Occupied support: {summary.floor_plan.boundary_support_ratio:.1%}",
        fill=(100, 116, 139),
        font=note_font,
    )
    drawing.text(
        (panel_x, 410),
        "Teal markers: wall direction",
        fill=(100, 116, 139),
        font=note_font,
    )

    destination = Path(path)
    temporary = destination.with_name(f"{destination.name}.tmp")
    try:
        image.save(temporary, format="PNG")
        temporary.replace(destination)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise OutputError(f"Cannot write floor-plan PNG: {destination}") from exc


def _floorplan_pixels(
    vertices_xy_m: NDArray[np.float64],
    *,
    width: int,
    height: int,
    panel_width: int,
) -> NDArray[np.float64]:
    if vertices_xy_m.ndim != 2 or vertices_xy_m.shape[1] != 2 or len(vertices_xy_m) < 3:
        raise OutputError("Floor-plan vertices must have shape (N, 2), N >= 3")
    return _transform_floorplan_points(
        vertices_xy_m,
        vertices_xy_m,
        width=width,
        height=height,
        panel_width=panel_width,
    )


def _dimension_label_indices(edge_lengths_m: tuple[float, ...]) -> set[int]:
    """Keep drawings readable while all edge lengths remain available in JSON."""
    if len(edge_lengths_m) <= 12:
        return set(range(len(edge_lengths_m)))
    significant = [
        index for index, length in enumerate(edge_lengths_m) if length >= 0.50
    ]
    significant.sort(key=lambda index: (-edge_lengths_m[index], index))
    return set(significant[:14])


def _outline_method_label(
    method: Literal["convex_hull", "occupancy_concave"],
) -> str:
    if method == "occupancy_concave":
        return "Occupancy-supported concave outline"
    return "Convex safety fallback"


def _transform_floorplan_points(
    reference_vertices_xy_m: NDArray[np.float64],
    points_xy_m: NDArray[np.float64],
    *,
    width: int,
    height: int,
    panel_width: int,
) -> NDArray[np.float64]:
    minimum = reference_vertices_xy_m.min(axis=0)
    maximum = reference_vertices_xy_m.max(axis=0)
    span = np.maximum(maximum - minimum, 1e-9)
    available_width = width - panel_width - 140
    available_height = height - 140
    scale = min(available_width / span[0], available_height / span[1])
    centred = points_xy_m - (minimum + maximum) / 2
    pixels = np.empty_like(centred)
    pixels[:, 0] = centred[:, 0] * scale + (width - panel_width) / 2
    pixels[:, 1] = -centred[:, 1] * scale + height / 2
    return pixels


def _wall_segment_pixels(
    summary: StructureSummary,
    reference_vertices_xy_m: NDArray[np.float64],
    *,
    width: int,
    height: int,
    panel_width: int,
) -> list[tuple[NDArray[np.float64], NDArray[np.float64]]]:
    origin = np.asarray(summary.floor_coordinates.origin_xyz_m, dtype=np.float64)
    x_axis = np.asarray(summary.floor_coordinates.x_axis_xyz, dtype=np.float64)
    y_axis = np.asarray(summary.floor_coordinates.y_axis_xyz, dtype=np.float64)
    up_axis = np.asarray(summary.floor_coordinates.up_axis_xyz, dtype=np.float64)
    floor_axes = np.column_stack((x_axis, y_axis))
    local_segments: list[NDArray[np.float64]] = []
    for wall in summary.walls:
        normal = np.asarray(wall.normal_xyz, dtype=np.float64)
        direction = np.cross(up_axis, normal)
        norm = float(np.linalg.norm(direction))
        if norm < 1e-9:
            continue
        direction /= norm
        centre = np.asarray(wall.centroid_xyz_m, dtype=np.float64)
        # The JSON retains the measured wall span. The drawing uses a short
        # marker so overlapping/infinite plane traces do not obscure the room.
        half_span = min(wall.span_primary_m, 1.0) / 2
        endpoints_world = np.vstack(
            (centre - direction * half_span, centre + direction * half_span)
        )
        local_segments.append((endpoints_world - origin) @ floor_axes)
    if not local_segments:
        return []
    transformed = _transform_floorplan_points(
        reference_vertices_xy_m,
        np.vstack(local_segments),
        width=width,
        height=height,
        panel_width=panel_width,
    )
    return [
        (transformed[index], transformed[index + 1])
        for index in range(0, len(transformed), 2)
    ]


def _load_font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    filename = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(filename, size=size)
    except OSError:
        return ImageFont.load_default()


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _optional_seconds(value: float | None) -> str:
    return "Not available" if value is None else f"{value:.2f} s"


def _optional_metres(value: float | None) -> str:
    return "Not available" if value is None else f"{value:.2f} m"


def _robust_axis_range(values: NDArray[np.floating]) -> tuple[float, float]:
    lower, upper = np.percentile(values, (0.5, 99.5))
    if not np.isfinite([lower, upper]).all():
        raise OutputError("Cannot determine a finite top-down range")
    if upper - lower < 1e-6:
        centre = float((upper + lower) / 2)
        return centre - 0.5, centre + 0.5
    padding = float(upper - lower) * 0.05
    return float(lower - padding), float(upper + padding)


def _pad_axis_range(lower: float, upper: float) -> tuple[float, float]:
    if upper - lower < 1e-6:
        centre = (upper + lower) / 2
        return centre - 0.5, centre + 0.5
    padding = (upper - lower) * 0.05
    return lower - padding, upper + padding


def _draw_trajectory(
    image: Image.Image,
    trajectory: NDArray[np.floating],
    *,
    x_range: tuple[float, float],
    z_range: tuple[float, float],
) -> None:
    width, height = image.size
    x_min, x_max = x_range
    z_min, z_max = z_range
    finite = trajectory[np.isfinite(trajectory).all(axis=1)]
    if len(finite) == 0:
        return

    pixels: list[tuple[int, int]] = []
    for point in finite:
        x_fraction = (float(point[0]) - x_min) / (x_max - x_min)
        z_fraction = (float(point[2]) - z_min) / (z_max - z_min)
        pixel_x = round(np.clip(x_fraction, 0.0, 1.0) * (width - 1))
        pixel_y = round((1.0 - np.clip(z_fraction, 0.0, 1.0)) * (height - 1))
        pixels.append((pixel_x, pixel_y))

    drawing = ImageDraw.Draw(image)
    if len(pixels) > 1:
        drawing.line(pixels, fill=(220, 30, 30), width=3)
    radius = 6
    _draw_marker(drawing, pixels[0], radius, (20, 170, 20))
    _draw_marker(drawing, pixels[-1], radius, (30, 90, 220))


def _draw_marker(
    drawing: ImageDraw.ImageDraw,
    position: tuple[int, int],
    radius: int,
    color: tuple[int, int, int],
) -> None:
    x, y = position
    drawing.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)
