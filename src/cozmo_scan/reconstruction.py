"""Metric point-cloud reconstruction from Stray Scanner depth and odometry."""

from __future__ import annotations

import io
import math
import time
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image, UnidentifiedImageError

from cozmo_scan.dataset import (
    CaptureError,
    CaptureSource,
    build_capture_index,
    open_capture,
    select_keyframes,
    validate_capture,
)
from cozmo_scan.models import (
    FrameSelection,
    FrameRecord,
    IssueSeverity,
    OdometryRecord,
    ReconstructionConfig,
    ReconstructionProfile,
    ReconstructionStatistics,
    ReconstructionSummary,
)

FloatArray = NDArray[np.floating]
BoolArray = NDArray[np.bool_]


class ReconstructionError(ValueError):
    """Raised when a capture cannot produce a valid reconstruction."""


@dataclass(frozen=True, slots=True)
class FramePointResult:
    """Points and accounting data produced from one frame."""

    points_xyz_m: NDArray[np.float32]
    sampled_pixel_count: int
    valid_point_count: int


@dataclass(frozen=True, slots=True)
class ReconstructionResult:
    """In-memory reconstruction and its serializable summary."""

    points_xyz_m: NDArray[np.float32]
    trajectory_xyz_m: NDArray[np.float64]
    summary: ReconstructionSummary


def get_profile_config(
    profile: ReconstructionProfile | str,
    *,
    max_frames: int | None = None,
    frame_selection: FrameSelection | str = FrameSelection.DISTRIBUTED,
) -> ReconstructionConfig:
    """Return one centrally defined reconstruction profile."""
    selected = ReconstructionProfile(profile)
    profile_values = {
        ReconstructionProfile.TEST: (10, 8, 0.08, 5),
        ReconstructionProfile.FAST: (200, 4, 0.04, 20),
        ReconstructionProfile.QUALITY: (500, 2, 0.02, 20),
    }
    default_frames, pixel_stride, voxel_size_m, fusion_batch_frames = (
        profile_values[selected]
    )
    return ReconstructionConfig(
        profile=selected,
        frame_selection=FrameSelection(frame_selection),
        max_frames=default_frames if max_frames is None else max_frames,
        pixel_stride=pixel_stride,
        voxel_size_m=voxel_size_m,
        minimum_confidence=1,
        minimum_depth_m=0.20,
        maximum_depth_m=5.00,
        calibration_width=1920,
        calibration_height=1440,
        fusion_batch_frames=fusion_batch_frames,
    )


def load_depth_and_confidence(
    source: CaptureSource, frame: FrameRecord
) -> tuple[NDArray[np.uint16], NDArray[np.uint8]]:
    """Decode one matched 16-bit depth and 8-bit confidence pair."""
    try:
        with Image.open(io.BytesIO(source.read_bytes(frame.depth_path))) as image:
            image.load()
            depth = np.asarray(image, dtype=np.uint16).copy()
        with Image.open(io.BytesIO(source.read_bytes(frame.confidence_path))) as image:
            image.load()
            confidence = np.asarray(image, dtype=np.uint8).copy()
    except (OSError, UnidentifiedImageError) as exc:
        raise ReconstructionError(
            f"Cannot decode frame {frame.frame_id}: {exc}"
        ) from exc

    if depth.ndim != 2 or confidence.ndim != 2:
        raise ReconstructionError(
            f"Frame {frame.frame_id} depth/confidence images must be two-dimensional"
        )
    if depth.shape != confidence.shape:
        raise ReconstructionError(
            f"Frame {frame.frame_id} depth and confidence sizes do not match"
        )
    return depth, confidence


def depth_to_metres(depth_mm: NDArray[np.integer]) -> NDArray[np.float32]:
    """Convert unsigned millimetre depth values to floating-point metres."""
    return depth_mm.astype(np.float32) * np.float32(0.001)


def scale_intrinsics(
    intrinsics_fx_fy_cx_cy: tuple[float, float, float, float],
    *,
    source_size: tuple[int, int],
    target_size: tuple[int, int],
) -> tuple[float, float, float, float]:
    """Scale pinhole intrinsics between image resolutions."""
    source_width, source_height = source_size
    target_width, target_height = target_size
    if min(source_width, source_height, target_width, target_height) <= 0:
        raise ValueError("source and target image dimensions must be positive")
    fx, fy, cx, cy = intrinsics_fx_fy_cx_cy
    scale_x = target_width / source_width
    scale_y = target_height / source_height
    return fx * scale_x, fy * scale_y, cx * scale_x, cy * scale_y


def filter_depth(
    depth_m: FloatArray,
    confidence: NDArray[np.integer],
    *,
    minimum_confidence: int,
    minimum_depth_m: float,
    maximum_depth_m: float,
) -> BoolArray:
    """Return the pixels that have finite, in-range, sufficiently confident depth."""
    if depth_m.shape != confidence.shape:
        raise ValueError("depth and confidence arrays must have the same shape")
    return (
        np.isfinite(depth_m)
        & (depth_m >= minimum_depth_m)
        & (depth_m <= maximum_depth_m)
        & (confidence >= minimum_confidence)
    )


def backproject_depth(
    depth_m: FloatArray,
    valid_mask: BoolArray,
    intrinsics_fx_fy_cx_cy: tuple[float, float, float, float],
    *,
    pixel_stride: int,
) -> NDArray[np.float32]:
    """Back-project selected depth pixels into OpenCV-style camera coordinates."""
    if depth_m.ndim != 2 or valid_mask.shape != depth_m.shape:
        raise ValueError("depth and mask must be equally sized two-dimensional arrays")
    if pixel_stride < 1:
        raise ValueError("pixel_stride must be at least 1")

    fx, fy, cx, cy = intrinsics_fx_fy_cx_cy
    if fx <= 0 or fy <= 0:
        raise ValueError("fx and fy must be positive")

    height, width = depth_m.shape
    rows = np.arange(0, height, pixel_stride)
    columns = np.arange(0, width, pixel_stride)
    sampled_depth = depth_m[np.ix_(rows, columns)]
    sampled_mask = valid_mask[np.ix_(rows, columns)]
    pixel_x, pixel_y = np.meshgrid(columns, rows)

    z = sampled_depth[sampled_mask].astype(np.float32, copy=False)
    x = ((pixel_x[sampled_mask] - cx) * z / fx).astype(np.float32)
    y = ((pixel_y[sampled_mask] - cy) * z / fy).astype(np.float32)
    if z.size == 0:
        return np.empty((0, 3), dtype=np.float32)
    return np.column_stack((x, y, z)).astype(np.float32, copy=False)


def quaternion_to_rotation(
    quaternion_xyzw: tuple[float, float, float, float],
) -> NDArray[np.float64]:
    """Convert and normalize an XYZW quaternion to a 3 x 3 rotation matrix."""
    quaternion = np.asarray(quaternion_xyzw, dtype=np.float64)
    norm = float(np.linalg.norm(quaternion))
    if not math.isfinite(norm) or norm < 1e-12:
        raise ValueError("quaternion must have a finite non-zero norm")
    x, y, z, w = quaternion / norm
    return np.asarray(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


def camera_to_world_matrix(odometry: OdometryRecord) -> NDArray[np.float64]:
    """Create the recorded camera-to-world homogeneous transform."""
    transform = np.eye(4, dtype=np.float64)
    transform[:3, :3] = quaternion_to_rotation(odometry.quaternion_xyzw)
    transform[:3, 3] = np.asarray(odometry.position_xyz_m, dtype=np.float64)
    return transform


def transform_points(
    points_xyz: FloatArray, transform: FloatArray
) -> NDArray[np.float32]:
    """Apply a 4 x 4 homogeneous transform to an N x 3 point array."""
    if points_xyz.ndim != 2 or points_xyz.shape[1] != 3:
        raise ValueError("points must have shape (N, 3)")
    if transform.shape != (4, 4):
        raise ValueError("transform must have shape (4, 4)")
    rotated = points_xyz.astype(np.float64) @ transform[:3, :3].T
    translated = rotated + transform[:3, 3]
    return translated.astype(np.float32)


def voxel_downsample(
    points_xyz_m: FloatArray, voxel_size_m: float
) -> NDArray[np.float32]:
    """Replace points in each metric voxel with their deterministic centroid."""
    if voxel_size_m <= 0:
        raise ValueError("voxel_size_m must be positive")
    if points_xyz_m.ndim != 2 or points_xyz_m.shape[1] != 3:
        raise ValueError("points must have shape (N, 3)")
    if len(points_xyz_m) == 0:
        return np.empty((0, 3), dtype=np.float32)

    finite_points = np.asarray(points_xyz_m[np.isfinite(points_xyz_m).all(axis=1)])
    if len(finite_points) == 0:
        return np.empty((0, 3), dtype=np.float32)
    voxel_keys = np.floor(finite_points / voxel_size_m).astype(np.int64)
    _, inverse = np.unique(voxel_keys, axis=0, return_inverse=True)
    voxel_count = int(inverse.max()) + 1
    sums = np.zeros((voxel_count, 3), dtype=np.float64)
    np.add.at(sums, inverse, finite_points)
    counts = np.bincount(inverse, minlength=voxel_count)
    return (sums / counts[:, None]).astype(np.float32)


def reconstruct_keyframe(
    source: CaptureSource,
    frame: FrameRecord,
    config: ReconstructionConfig,
) -> FramePointResult:
    """Reconstruct one matched frame in world coordinates."""
    depth_mm, confidence = load_depth_and_confidence(source, frame)
    depth_m = depth_to_metres(depth_mm)
    valid_mask = filter_depth(
        depth_m,
        confidence,
        minimum_confidence=config.minimum_confidence,
        minimum_depth_m=config.minimum_depth_m,
        maximum_depth_m=config.maximum_depth_m,
    )
    height, width = depth_m.shape
    scaled_intrinsics = scale_intrinsics(
        frame.odometry.intrinsics_fx_fy_cx_cy,
        source_size=(config.calibration_width, config.calibration_height),
        target_size=(width, height),
    )
    camera_points = backproject_depth(
        depth_m,
        valid_mask,
        scaled_intrinsics,
        pixel_stride=config.pixel_stride,
    )
    world_points = transform_points(
        camera_points, camera_to_world_matrix(frame.odometry)
    )
    sampled_rows = len(range(0, height, config.pixel_stride))
    sampled_columns = len(range(0, width, config.pixel_stride))
    return FramePointResult(
        points_xyz_m=world_points,
        sampled_pixel_count=sampled_rows * sampled_columns,
        valid_point_count=len(world_points),
    )


def trajectory_statistics(
    frames: tuple[FrameRecord, ...],
) -> tuple[NDArray[np.float64], float | None, float | None]:
    """Return camera positions, full path length, and start/end closure proxy."""
    trajectory = np.asarray(
        [frame.odometry.position_xyz_m for frame in frames], dtype=np.float64
    )
    if len(trajectory) == 0:
        return np.empty((0, 3), dtype=np.float64), None, None
    if len(trajectory) == 1:
        return trajectory, 0.0, 0.0
    step_lengths = np.linalg.norm(np.diff(trajectory, axis=0), axis=1)
    path_length = float(step_lengths.sum())
    closure_proxy = float(np.linalg.norm(trajectory[-1] - trajectory[0]))
    return trajectory, path_length, closure_proxy


def offset_frame_pose(
    frame: FrameRecord, offset_xyz_m: tuple[float, float, float] | None
) -> FrameRecord:
    """Return the frame with its recorded camera position translated.

    Used by bounded drift correction. Only the translation changes, so the
    correction stays a rigid per-frame shift of that frame's points and can
    always be reproduced from the recorded pose plus the published offset.
    """
    if offset_xyz_m is None:
        return frame
    position = frame.odometry.position_xyz_m
    moved = (
        position[0] + offset_xyz_m[0],
        position[1] + offset_xyz_m[1],
        position[2] + offset_xyz_m[2],
    )
    return frame.model_copy(
        update={"odometry": frame.odometry.model_copy(update={"position_xyz_m": moved})}
    )


def iterate_frame_points(
    path: str | Path,
    config: ReconstructionConfig,
) -> Iterator[tuple[FrameRecord, NDArray[np.float32]]]:
    """Yield each selected keyframe with its own unfused world points.

    Voxel fusion deliberately discards which frame a point came from, so any
    per-frame measurement (such as a drift residual) needs this separate pass.
    """
    with open_capture(path) as source:
        capture_index = build_capture_index(source)
        if config.frame_selection is FrameSelection.CONTIGUOUS_START:
            selected = capture_index.frames[: config.max_frames]
        else:
            selected = select_keyframes(
                capture_index.frames, max_frames=config.max_frames
            )
        for frame in selected:
            result = reconstruct_keyframe(source, frame, config)
            if result.valid_point_count:
                yield frame, result.points_xyz_m


def reconstruct_capture(
    path: str | Path,
    config: ReconstructionConfig,
    *,
    pose_offsets_xyz_m: Mapping[str, tuple[float, float, float]] | None = None,
) -> ReconstructionResult:
    """Reconstruct a bounded metric point cloud from one validated capture.

    `pose_offsets_xyz_m` optionally translates individual keyframe poses by
    frame identifier. The recorded-pose reconstruction remains the control: pass
    nothing and the result is bit-for-bit what it was before drift correction
    existed.
    """
    started = time.perf_counter()
    validation = validate_capture(path)
    if not validation.valid:
        errors = [
            issue.message
            for issue in validation.issues
            if issue.severity is IssueSeverity.ERROR
        ]
        raise ReconstructionError("; ".join(errors) or "Capture validation failed")

    warnings = [
        issue.message
        for issue in validation.issues
        if issue.severity is IssueSeverity.WARNING
    ]
    try:
        with open_capture(path) as source:
            capture_index = build_capture_index(source)
            if config.frame_selection is FrameSelection.CONTIGUOUS_START:
                selected_frames = capture_index.frames[: config.max_frames]
            else:
                selected_frames = select_keyframes(
                    capture_index.frames, max_frames=config.max_frames
                )
            if not selected_frames:
                raise ReconstructionError("No frames were selected for reconstruction")
            if pose_offsets_xyz_m:
                selected_frames = tuple(
                    offset_frame_pose(frame, pose_offsets_xyz_m.get(frame.frame_id))
                    for frame in selected_frames
                )

            cloud = np.empty((0, 3), dtype=np.float32)
            buffered: list[NDArray[np.float32]] = []
            sampled_pixel_count = 0
            valid_point_count = 0
            processed_frames = 0
            skipped_frames = 0

            for frame in selected_frames:
                frame_result = reconstruct_keyframe(source, frame, config)
                sampled_pixel_count += frame_result.sampled_pixel_count
                valid_point_count += frame_result.valid_point_count
                if frame_result.valid_point_count == 0:
                    skipped_frames += 1
                    warnings.append(
                        f"Frame {frame.frame_id} had no valid sampled depth points"
                    )
                    continue
                processed_frames += 1
                buffered.append(frame_result.points_xyz_m)
                if len(buffered) >= config.fusion_batch_frames:
                    cloud = _merge_voxel_batch(cloud, buffered, config.voxel_size_m)
                    buffered.clear()

            if buffered:
                cloud = _merge_voxel_batch(cloud, buffered, config.voxel_size_m)
            if len(cloud) == 0:
                raise ReconstructionError("Reconstruction produced no valid 3D points")
    except CaptureError as exc:
        raise ReconstructionError(str(exc)) from exc

    trajectory, path_length, closure_proxy = trajectory_statistics(
        capture_index.frames
    )
    bounds_min = tuple(float(value) for value in cloud.min(axis=0))
    bounds_max = tuple(float(value) for value in cloud.max(axis=0))
    spans = np.asarray(bounds_max) - np.asarray(bounds_min)
    if float(spans.max()) > 100.0:
        warnings.append(
            "Reconstruction span exceeds 100 m; verify pose and depth conventions"
        )

    elapsed = time.perf_counter() - started
    statistics = ReconstructionStatistics(
        total_matched_frames=len(capture_index.frames),
        selected_frame_count=len(selected_frames),
        processed_frame_count=processed_frames,
        skipped_frame_count=skipped_frames,
        sampled_pixel_count=sampled_pixel_count,
        valid_point_count_before_voxel=valid_point_count,
        output_point_count=len(cloud),
        bounds_min_xyz_m=bounds_min,
        bounds_max_xyz_m=bounds_max,
        trajectory_start_xyz_m=tuple(float(value) for value in trajectory[0]),
        trajectory_end_xyz_m=tuple(float(value) for value in trajectory[-1]),
        trajectory_path_length_m=path_length,
        closure_proxy_m=closure_proxy,
    )
    summary = ReconstructionSummary(
        status="ok_with_warnings" if warnings else "ok",
        source=str(path),
        config=config,
        statistics=statistics,
        elapsed_seconds=elapsed,
        warnings=tuple(warnings),
        artifacts={
            "point_cloud": "reconstruction.ply",
            "topdown_preview": "topdown.png",
            "summary": "reconstruction.json",
        },
    )
    return ReconstructionResult(
        points_xyz_m=cloud,
        trajectory_xyz_m=trajectory,
        summary=summary,
    )


def _merge_voxel_batch(
    cloud: NDArray[np.float32],
    buffered: list[NDArray[np.float32]],
    voxel_size_m: float,
) -> NDArray[np.float32]:
    combined = np.concatenate([cloud, *buffered], axis=0)
    return voxel_downsample(combined, voxel_size_m)
