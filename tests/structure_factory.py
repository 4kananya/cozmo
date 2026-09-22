"""Deterministic synthetic structural geometry shared by CP04 tests."""

from __future__ import annotations

import math

import numpy as np

from cozmo_scan.models import (
    FrameSelection,
    ReconstructionConfig,
    ReconstructionProfile,
    ReconstructionStatistics,
    ReconstructionSummary,
)
from cozmo_scan.reconstruction import ReconstructionResult


def make_synthetic_room(*, include_ceiling: bool = True) -> ReconstructionResult:
    """Create a four-by-three-metre noisy room with a camera at 1.5 m."""
    generator = np.random.default_rng(8)
    floor_x, floor_z = np.meshgrid(np.linspace(-2, 2, 41), np.linspace(-1.5, 1.5, 31))
    floor = np.column_stack(
        (
            floor_x.ravel(),
            generator.normal(0.0, 0.004, floor_x.size),
            floor_z.ravel(),
        )
    )
    surfaces = [floor]
    if include_ceiling:
        ceiling = floor.copy()
        ceiling[:, 1] = 2.5 + generator.normal(0.0, 0.004, len(ceiling))
        surfaces.append(ceiling)

    wall_count = 900
    y = generator.uniform(0.08, 2.42, wall_count)
    first_wall = np.column_stack(
        (np.full(wall_count, -2.0), y, generator.uniform(-1.5, 1.5, wall_count))
    )
    y = generator.uniform(0.08, 2.42, wall_count)
    second_wall = np.column_stack(
        (np.full(wall_count, 2.0), y, generator.uniform(-1.5, 1.5, wall_count))
    )
    y = generator.uniform(0.08, 2.42, wall_count)
    third_wall = np.column_stack(
        (generator.uniform(-2.0, 2.0, wall_count), y, np.full(wall_count, -1.5))
    )
    y = generator.uniform(0.08, 2.42, wall_count)
    fourth_wall = np.column_stack(
        (generator.uniform(-2.0, 2.0, wall_count), y, np.full(wall_count, 1.5))
    )
    walls = np.vstack((first_wall, second_wall, third_wall, fourth_wall))
    walls += generator.normal(0.0, 0.004, walls.shape)
    noise = generator.uniform((-2.2, 0.1, -1.7), (2.2, 2.4, 1.7), (150, 3))
    points = np.vstack((*surfaces, walls, noise)).astype(np.float32)
    trajectory = np.asarray(
        [[-1.0, 1.5, -1.0], [0.0, 1.5, 0.0], [1.0, 1.5, 1.0]],
        dtype=np.float64,
    )
    reconstruction_config = ReconstructionConfig(
        profile=ReconstructionProfile.TEST,
        frame_selection=FrameSelection.DISTRIBUTED,
        max_frames=10,
        pixel_stride=8,
        voxel_size_m=0.08,
        minimum_confidence=1,
        minimum_depth_m=0.2,
        maximum_depth_m=5.0,
        calibration_width=1920,
        calibration_height=1440,
        fusion_batch_frames=5,
    )
    statistics = ReconstructionStatistics(
        total_matched_frames=3,
        selected_frame_count=3,
        processed_frame_count=3,
        skipped_frame_count=0,
        sampled_pixel_count=len(points),
        valid_point_count_before_voxel=len(points),
        output_point_count=len(points),
        bounds_min_xyz_m=tuple(float(value) for value in points.min(axis=0)),
        bounds_max_xyz_m=tuple(float(value) for value in points.max(axis=0)),
        trajectory_start_xyz_m=(-1.0, 1.5, -1.0),
        trajectory_end_xyz_m=(1.0, 1.5, 1.0),
        trajectory_path_length_m=2 * math.sqrt(2),
        closure_proxy_m=2 * math.sqrt(2),
    )
    summary = ReconstructionSummary(
        status="ok",
        source="synthetic-room",
        config=reconstruction_config,
        statistics=statistics,
        elapsed_seconds=0.0,
    )
    return ReconstructionResult(points, trajectory, summary)
