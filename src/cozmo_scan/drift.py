"""Bounded plane-anchored drift correction with an on/off ablation.

Recorded ARKit poses accumulate error over a walk. In an indoor capture that
error is visible without any external reference: the floor is one physical
plane, so if a late keyframe's floor points sit systematically above or below an
early keyframe's, the difference is pose drift rather than architecture.

This module measures that per-keyframe residual against the globally fitted floor
plane, smooths it, bounds it, and applies it as a rigid per-frame translation
along the floor normal. It then rebuilds the structure and compares the two arms.

Two rules are deliberately hard-coded into the design:

- The recorded-pose reconstruction is the control and stays reproducible. Passing
  no offsets reproduces the pre-correction result exactly.
- A correction is kept only when broader structural evidence improves. A smaller
  start-to-end closure distance is not accepted as proof, and is not even used
  here: this correction does not move the recorded camera path, so a closure
  proxy would be unchanged and uninformative.
"""

from __future__ import annotations

import time
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from numpy.typing import NDArray

from cozmo_scan.floorplan import StructureError, StructureResult, analyze_structure
from cozmo_scan.models import (
    DriftAblation,
    DriftConfig,
    DriftCorrectionEvidence,
    DriftVariant,
    PipelineConfig,
)
from cozmo_scan.reconstruction import (
    ReconstructionError,
    ReconstructionResult,
    iterate_frame_points,
    reconstruct_capture,
)

DRIFT_ABLATION_JSON_FILENAME = "drift-ablation.json"
DRIFT_ABLATION_REPORT_FILENAME = "drift-ablation.md"

PoseOffsets = dict[str, tuple[float, float, float]]


class DriftError(ValueError):
    """Raised when a drift ablation cannot be produced at all."""


def measure_frame_floor_residuals(
    path: str | Path,
    config: PipelineConfig,
    drift_config: DriftConfig,
    *,
    floor_normal_xyz: NDArray[np.float64],
    floor_offset_m: float,
) -> tuple[tuple[str, ...], NDArray[np.float64]]:
    """Return each keyframe's mean signed distance from the global floor plane.

    Frames whose own floor support is too thin to measure are skipped rather than
    corrected from noise.
    """
    frame_ids: list[str] = []
    residuals: list[float] = []
    band = drift_config.floor_band_m
    for frame, points in iterate_frame_points(path, config.reconstruction):
        signed = np.asarray(points, dtype=np.float64) @ floor_normal_xyz + floor_offset_m
        near_floor = signed[np.abs(signed) <= band]
        if len(near_floor) < drift_config.minimum_frame_floor_points:
            continue
        frame_ids.append(frame.frame_id)
        residuals.append(float(np.mean(near_floor)))
    return tuple(frame_ids), np.asarray(residuals, dtype=np.float64)


def estimate_pose_offsets(
    frame_ids: tuple[str, ...],
    residuals_m: NDArray[np.float64],
    floor_normal_xyz: NDArray[np.float64],
    config: DriftConfig,
) -> tuple[PoseOffsets, DriftCorrectionEvidence]:
    """Turn per-frame floor residuals into bounded per-frame pose translations.

    The residual is smoothed along keyframe order first. Drift is a slow
    accumulation, so a single noisy frame must not move a pose; only the trend
    that persists across neighbouring frames is corrected. The correction is then
    centred, so it removes the drift trend without shifting the whole room, and
    clamped to a configured maximum.
    """
    if len(frame_ids) == 0:
        return {}, DriftCorrectionEvidence(
            measured_frame_count=0,
            corrected_frame_count=0,
            clamped_frame_count=0,
            maximum_absolute_offset_m=0.0,
            mean_absolute_offset_m=0.0,
            residual_trend_m=0.0,
            raw_residual_span_m=0.0,
        )
    smoothed = _smooth(residuals_m, config.smoothing_window_frames)
    # Centre on the median so the correction removes the trend rather than
    # translating the whole reconstruction, which would change nothing about
    # internal consistency while making the result harder to compare.
    centred = smoothed - float(np.median(smoothed))
    clamped = np.clip(centred, -config.maximum_offset_m, config.maximum_offset_m)
    clamped_count = int(np.count_nonzero(np.abs(centred) > config.maximum_offset_m))

    normal = np.asarray(floor_normal_xyz, dtype=np.float64)
    offsets: PoseOffsets = {}
    for frame_id, value in zip(frame_ids, clamped, strict=True):
        if abs(float(value)) < 1e-6:
            continue
        # Move the camera opposite the residual so the frame's floor points land
        # on the fitted plane.
        shift = -float(value) * normal
        offsets[frame_id] = (float(shift[0]), float(shift[1]), float(shift[2]))
    evidence = DriftCorrectionEvidence(
        measured_frame_count=len(frame_ids),
        corrected_frame_count=len(offsets),
        clamped_frame_count=clamped_count,
        maximum_absolute_offset_m=float(np.abs(clamped).max()),
        mean_absolute_offset_m=float(np.abs(clamped).mean()),
        residual_trend_m=float(smoothed[-1] - smoothed[0]),
        raw_residual_span_m=float(residuals_m.max() - residuals_m.min()),
    )
    return offsets, evidence


def trimmed_floor_residual_m(
    reconstruction: ReconstructionResult,
    structure: StructureResult,
    quantile: float,
) -> float:
    """RMS plane distance over the closest `quantile` fraction of every point.

    Uses a fraction of the arm's own cloud rather than a fixed distance band, so
    the value does not move when points cross a band edge. That makes the two
    ablation arms comparable even though voxel fusion repartitions the cloud
    differently once poses shift.
    """
    points = np.asarray(reconstruction.points_xyz_m, dtype=np.float64)
    points = points[np.isfinite(points).all(axis=1)]
    if len(points) == 0:
        return 0.0
    floor = structure.summary.floor
    distances = np.abs(
        points @ np.asarray(floor.normal_xyz, dtype=np.float64) + floor.offset_m
    )
    keep = max(1, int(round(len(distances) * quantile)))
    closest = np.partition(distances, keep - 1)[:keep]
    return float(np.sqrt(np.mean(np.square(closest))))


def build_variant(
    label: str,
    reconstruction: ReconstructionResult,
    structure: StructureResult,
    *,
    residual_quantile: float = 0.30,
) -> DriftVariant:
    """Summarize one ablation arm into comparable structural evidence."""
    summary = structure.summary
    walls = summary.walls
    plan = summary.floor_plan
    openings = summary.openings
    return DriftVariant(
        label=label,
        output_point_count=reconstruction.summary.statistics.output_point_count,
        floor_rmse_m=summary.floor.rmse_m,
        floor_trimmed_rmse_m=trimmed_floor_residual_m(
            reconstruction, structure, residual_quantile
        ),
        floor_inlier_ratio=summary.floor.inlier_ratio,
        mean_wall_rmse_m=(
            float(np.mean([wall.rmse_m for wall in walls])) if walls else None
        ),
        wall_count=len(walls),
        floor_area_m2=plan.area_m2,
        perimeter_m=plan.perimeter_m,
        length_m=plan.length_m,
        width_m=plan.width_m,
        boundary_support_ratio=plan.boundary_support_ratio,
        outline_method=plan.outline_method,
        ceiling_height_m=summary.ceiling_height_m,
        opening_count=(
            len(openings.openings)
            if openings is not None and openings.status == "available"
            else 0
        ),
    )


def judge_correction(
    control: DriftVariant, corrected: DriftVariant, config: DriftConfig
) -> tuple[bool, str]:
    """Accept a correction only on improved residual with no material regression.

    Point count and inlier support are checked *first* and unconditionally. A
    residual measured over a band-limited inlier subset drops when inliers leave
    the subset, so without these checks a correction can buy its improvement by
    discarding the very points that were hardest to fit. That was observed on
    real data: a published 10.3% improvement became 20.7% worse once both arms
    were scored over the same number of points.
    """
    lost = control.output_point_count - corrected.output_point_count
    if (
        control.output_point_count > 0
        and lost > control.output_point_count * config.maximum_point_loss_ratio
    ):
        return False, (
            f"The corrected arm lost {lost:,} of {control.output_point_count:,} points "
            f"({lost / control.output_point_count:.1%}); a residual improvement bought "
            "by discarding points is not evidence of better alignment."
        )
    inlier_drop = control.floor_inlier_ratio - corrected.floor_inlier_ratio
    if inlier_drop > config.maximum_inlier_ratio_regression:
        return False, (
            f"Floor inlier support fell by {inlier_drop:.3f} "
            f"({control.floor_inlier_ratio:.4f} to {corrected.floor_inlier_ratio:.4f}); "
            "fewer points fitting the plane is attrition, not improvement."
        )

    # Prefer the quantile residual, which is computed over every point and so is
    # not sensitive to inliers entering or leaving a fixed band.
    if control.floor_trimmed_rmse_m is not None and corrected.floor_trimmed_rmse_m is not None:
        baseline, candidate, metric = (
            control.floor_trimmed_rmse_m,
            corrected.floor_trimmed_rmse_m,
            "trimmed floor-plane residual",
        )
    else:
        baseline, candidate, metric = (
            control.floor_rmse_m,
            corrected.floor_rmse_m,
            "floor residual",
        )
    if baseline <= 0:
        return False, f"The control {metric} is zero, so no improvement is measurable."
    improvement = (baseline - candidate) / baseline
    if improvement < config.minimum_rmse_improvement:
        return False, (
            f"The {metric} changed by {improvement:+.1%}, short of the required "
            f"{config.minimum_rmse_improvement:.0%} improvement."
        )
    if (
        control.mean_wall_rmse_m is not None
        and corrected.mean_wall_rmse_m is not None
        and control.mean_wall_rmse_m > 0
    ):
        regression = (
            corrected.mean_wall_rmse_m - control.mean_wall_rmse_m
        ) / control.mean_wall_rmse_m
        if regression > config.maximum_wall_rmse_regression:
            return False, (
                f"The {metric} improved by {improvement:.1%} but wall residual "
                f"worsened by {regression:.1%}; the correction trades one surface "
                "against another."
            )
    if corrected.wall_count < control.wall_count:
        return False, (
            f"The {metric} improved by {improvement:.1%} but supported wall planes "
            f"fell from {control.wall_count} to {corrected.wall_count}."
        )
    support_drop = control.boundary_support_ratio - corrected.boundary_support_ratio
    if support_drop > config.maximum_support_regression:
        return False, (
            f"The {metric} improved by {improvement:.1%} but occupied boundary "
            f"support fell by {support_drop:.1%}."
        )
    return True, (
        f"The {metric} improved by {improvement:.1%} with no material regression in "
        "wall residual, wall count, or boundary support."
    )


def run_drift_ablation(
    path: str | Path,
    config: PipelineConfig,
    drift_config: DriftConfig,
    *,
    input_sha256: str,
) -> tuple[DriftAblation, ReconstructionResult, StructureResult]:
    """Run both arms and return the ablation plus the arm that was selected."""
    started = time.perf_counter()
    warnings: list[str] = []
    try:
        control_reconstruction = reconstruct_capture(path, config.reconstruction)
        control_structure = analyze_structure(control_reconstruction, config.structure)
    except (ReconstructionError, StructureError) as exc:
        raise DriftError(f"The recorded-pose control could not be built: {exc}") from exc
    control = build_variant(
        "recorded_poses",
        control_reconstruction,
        control_structure,
        residual_quantile=drift_config.residual_quantile,
    )

    floor = control_structure.summary.floor
    normal = np.asarray(floor.normal_xyz, dtype=np.float64)
    frame_ids, residuals = measure_frame_floor_residuals(
        path,
        config,
        drift_config,
        floor_normal_xyz=normal,
        floor_offset_m=floor.offset_m,
    )
    offsets, evidence = estimate_pose_offsets(
        frame_ids, residuals, normal, drift_config
    )

    unavailable_reason: str | None = None
    if len(offsets) and len(offsets) < drift_config.minimum_corrected_frames:
        unavailable_reason = (
            f"Only {len(offsets)} keyframe(s) received a correction; "
            f"{drift_config.minimum_corrected_frames} are required."
        )
    elif len(frame_ids) < drift_config.minimum_corrected_frames:
        unavailable_reason = (
            f"Only {len(frame_ids)} keyframe(s) had enough floor support to measure a "
            f"residual; {drift_config.minimum_corrected_frames} are required."
        )
    elif not offsets:
        unavailable_reason = (
            "The measured floor residual showed no drift trend to correct."
        )

    if unavailable_reason is not None:
        ablation = DriftAblation(
            source_name=Path(str(path)).name or str(path),
            input_sha256=input_sha256,
            decision="correction_unavailable",
            decision_reason=unavailable_reason,
            selected_variant="recorded_poses",
            drift=drift_config,
            variants=(control,),
            evidence=None,
            elapsed_seconds=time.perf_counter() - started,
            warnings=tuple(warnings),
            artifacts=_artifacts(),
        )
        return ablation, control_reconstruction, control_structure

    try:
        corrected_reconstruction = reconstruct_capture(
            path, config.reconstruction, pose_offsets_xyz_m=offsets
        )
        corrected_structure = analyze_structure(
            corrected_reconstruction, config.structure
        )
    except (ReconstructionError, StructureError) as exc:
        ablation = DriftAblation(
            source_name=Path(str(path)).name or str(path),
            input_sha256=input_sha256,
            decision="correction_rejected",
            decision_reason=(
                f"The corrected arm failed to produce a structural result: {exc}"
            ),
            selected_variant="recorded_poses",
            drift=drift_config,
            variants=(control,),
            evidence=evidence,
            elapsed_seconds=time.perf_counter() - started,
            warnings=tuple(warnings),
            artifacts=_artifacts(),
        )
        return ablation, control_reconstruction, control_structure

    corrected = build_variant(
        "plane_anchored_correction",
        corrected_reconstruction,
        corrected_structure,
        residual_quantile=drift_config.residual_quantile,
    )
    accepted, reason = judge_correction(control, corrected, drift_config)
    if not accepted:
        warnings.append(
            "Drift correction was estimated and then rolled back; the published "
            "geometry uses the recorded poses."
        )
    ablation = DriftAblation(
        source_name=Path(str(path)).name or str(path),
        input_sha256=input_sha256,
        decision="correction_accepted" if accepted else "correction_rejected",
        decision_reason=reason,
        selected_variant=(
            "plane_anchored_correction" if accepted else "recorded_poses"
        ),
        drift=drift_config,
        variants=(control, corrected),
        evidence=evidence,
        elapsed_seconds=time.perf_counter() - started,
        warnings=tuple(warnings),
        artifacts=_artifacts(),
    )
    if accepted:
        return ablation, corrected_reconstruction, corrected_structure
    return ablation, control_reconstruction, control_structure


def render_drift_report(ablation: DriftAblation) -> str:
    """Render the on/off comparison a reviewer can read without the JSON."""
    lines = [
        "# Drift correction ablation",
        "",
        f"- Capture: `{ablation.source_name}`",
        f"- Input SHA-256: `{ablation.input_sha256}`",
        f"- Decision: **{ablation.decision.replace('_', ' ').upper()}**",
        f"- Published geometry uses: `{ablation.selected_variant}`",
        f"- Reason: {ablation.decision_reason}",
        "",
        "## Method",
        "",
        "Drift is corrected by anchoring to the floor plane. Every keyframe's own "
        "near-floor points are compared with the globally fitted floor, giving a "
        "per-frame signed residual. That residual is smoothed along keyframe order, "
        "centred on its median, clamped to a configured maximum, and applied as a "
        "rigid translation of the frame's pose along the floor normal.",
        "",
        "Poses are **not** used as-is: the correction is always estimated and both "
        "arms are always rebuilt. It is kept only when the structural evidence "
        "improves, and rolled back automatically otherwise. A smaller start-to-end "
        "camera distance is not used as evidence, because this correction does not "
        "move the recorded camera path.",
        "",
        "## Ablation",
        "",
        "| Evidence | " + " | ".join(v.label for v in ablation.variants) + " |",
        "|---" * (len(ablation.variants) + 1) + "|",
    ]

    def row(name: str, values: list[str]) -> str:
        return f"| {name} | " + " | ".join(values) + " |"

    variants = ablation.variants
    lines.extend(
        [
            row("Output points", [f"{v.output_point_count:,}" for v in variants]),
            row("Floor-plane RMSE (band inliers)", [f"{v.floor_rmse_m:.4f} m" for v in variants]),
            row(
                "Trimmed floor-plane residual (closest points, all surfaces)",
                [
                    "not available"
                    if v.floor_trimmed_rmse_m is None
                    else f"{v.floor_trimmed_rmse_m:.4f} m"
                    for v in variants
                ],
            ),
            row("Floor support", [f"{v.floor_inlier_ratio:.1%}" for v in variants]),
            row(
                "Mean wall RMSE",
                [
                    "not available"
                    if v.mean_wall_rmse_m is None
                    else f"{v.mean_wall_rmse_m:.4f} m"
                    for v in variants
                ],
            ),
            row("Wall planes", [str(v.wall_count) for v in variants]),
            row("Footprint area", [f"{v.floor_area_m2:.2f} m²" for v in variants]),
            row(
                "Footprint dimensions",
                [f"{v.length_m:.2f} × {v.width_m:.2f} m" for v in variants],
            ),
            row("Footprint perimeter", [f"{v.perimeter_m:.2f} m" for v in variants]),
            row("Boundary support", [f"{v.boundary_support_ratio:.1%}" for v in variants]),
            row("Outline method", [v.outline_method for v in variants]),
            row(
                "Ceiling height",
                [
                    "not available"
                    if v.ceiling_height_m is None
                    else f"{v.ceiling_height_m:.2f} m"
                    for v in variants
                ],
            ),
            row("Openings published", [str(v.opening_count) for v in variants]),
        ]
    )
    if len(variants) == 1:
        lines.extend(
            [
                "",
                "Only the recorded-pose control is present because a correction could "
                "not be estimated for this capture. The reason is recorded above.",
            ]
        )

    if ablation.evidence is not None:
        evidence = ablation.evidence
        lines.extend(
            [
                "",
                "## Correction magnitude",
                "",
                "| Evidence | Value |",
                "|---|---:|",
                f"| Keyframes measured | {evidence.measured_frame_count} |",
                f"| Keyframes corrected | {evidence.corrected_frame_count} |",
                f"| Keyframes clamped at the bound | {evidence.clamped_frame_count} |",
                f"| Maximum applied offset | {evidence.maximum_absolute_offset_m:.4f} m |",
                f"| Mean absolute offset | {evidence.mean_absolute_offset_m:.4f} m |",
                f"| Smoothed residual trend | {evidence.residual_trend_m:+.4f} m |",
                f"| Raw residual span | {evidence.raw_residual_span_m:.4f} m |",
                f"| Configured bound | {ablation.drift.maximum_offset_m:.4f} m |",
            ]
        )

    lines.extend(
        [
            "",
            "## How to read the two residuals",
            "",
            "The band RMSE is measured over floor inliers inside a fixed distance "
            "band, so it falls when inliers simply leave the band. It is reported "
            "for continuity but it is **not** the acceptance metric. The trimmed "
            "residual is measured over a fixed fraction of every point, so a "
            "correction cannot improve it by discarding the points that were "
            "hardest to fit. Point count and inlier support are additionally "
            "checked as hard conditions before either residual is considered.",
            "",
            "## Honest reading",
            "",
            "- These are internal consistency metrics. No survey ground truth was "
            "supplied, so neither arm is an accuracy claim.",
            "- A footprint that changes between arms shows sensitivity to pose error; "
            "it does not by itself show which arm is closer to the real room.",
            "- The correction is bounded and centred, so it cannot reshape the room; "
            "it can only remove a slow vertical trend across keyframes.",
        ]
    )
    if ablation.warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in ablation.warnings)
    lines.append("")
    return "\n".join(lines)


def write_drift_outputs(
    ablation: DriftAblation,
    output_directory: str | Path,
    *,
    overwrite: bool = False,
) -> dict[str, Path]:
    """Stage and publish the two drift-ablation artifacts together."""
    directory = Path(output_directory)
    if directory.exists() and not directory.is_dir():
        raise DriftError(f"Output path is not a directory: {directory}")
    names = (DRIFT_ABLATION_JSON_FILENAME, DRIFT_ABLATION_REPORT_FILENAME)
    conflicts = [name for name in names if (directory / name).exists()]
    if conflicts and not overwrite:
        raise DriftError(
            f"Drift artifacts already exist ({', '.join(conflicts)}); "
            "pass --overwrite to replace them"
        )
    try:
        directory.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DriftError(
            f"Cannot create output parent directory: {directory.parent}"
        ) from exc
    with TemporaryDirectory(
        prefix=".cozmo-drift-stage-", dir=directory.parent
    ) as temporary:
        staging = Path(temporary)
        try:
            (staging / DRIFT_ABLATION_JSON_FILENAME).write_text(
                ablation.model_dump_json(indent=2) + "\n", encoding="utf-8"
            )
            (staging / DRIFT_ABLATION_REPORT_FILENAME).write_text(
                render_drift_report(ablation), encoding="utf-8"
            )
            directory.mkdir(parents=True, exist_ok=True)
            for name in names:
                (staging / name).replace(directory / name)
        except OSError as exc:
            raise DriftError(
                f"Cannot publish drift artifacts to: {directory}"
            ) from exc
    return {
        "drift_ablation": directory / DRIFT_ABLATION_JSON_FILENAME,
        "drift_report": directory / DRIFT_ABLATION_REPORT_FILENAME,
    }


def _artifacts() -> dict[str, str]:
    return {
        "drift_ablation": DRIFT_ABLATION_JSON_FILENAME,
        "drift_report": DRIFT_ABLATION_REPORT_FILENAME,
    }


def _smooth(values: NDArray[np.float64], window: int) -> NDArray[np.float64]:
    """Centred moving average that preserves a linear trend at both ends.

    The edges are padded by reflecting *through* the endpoint rather than
    mirroring its neighbours. Plain mirroring would flatten the ramp at the start
    and end of the walk, which is precisely where accumulated drift is largest,
    so it would quietly shrink the correction where it is needed most.
    """
    if window <= 1 or len(values) <= 2:
        return values.astype(np.float64, copy=True)
    half = min(window // 2, (len(values) - 1) // 2)
    if half < 1:
        return values.astype(np.float64, copy=True)
    left = 2.0 * values[0] - values[1 : half + 1][::-1]
    right = 2.0 * values[-1] - values[-half - 1 : -1][::-1]
    padded = np.concatenate((left, values, right))
    kernel = np.ones(2 * half + 1, dtype=np.float64) / (2 * half + 1)
    return np.convolve(padded, kernel, mode="valid")
