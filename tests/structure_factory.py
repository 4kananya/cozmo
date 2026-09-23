"""Deterministic synthetic structural geometry shared by measurement tests."""

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


def _wall_points(
    generator: np.random.Generator,
    *,
    axis: str,
    fixed: float,
    span: tuple[float, float],
    height: tuple[float, float],
    count: int,
    exclude_span: tuple[float, float] | None = None,
    exclude_height: tuple[float, float] | None = None,
) -> np.ndarray:
    """Sample one planar wall, optionally cutting a rectangular void from it."""
    kept: list[np.ndarray] = []
    remaining = count
    # Rejection sampling keeps the surface density uniform outside the void.
    while remaining > 0:
        batch = max(remaining * 2, 256)
        along = generator.uniform(span[0], span[1], batch)
        vertical = generator.uniform(height[0], height[1], batch)
        if exclude_span is not None:
            inside_span = (along >= exclude_span[0]) & (along <= exclude_span[1])
            if exclude_height is None:
                void = inside_span
            else:
                void = (
                    inside_span
                    & (vertical >= exclude_height[0])
                    & (vertical <= exclude_height[1])
                )
            along = along[~void]
            vertical = vertical[~void]
        if axis == "x":
            points = np.column_stack(
                (np.full(len(along), fixed), vertical, along)
            )
        else:
            points = np.column_stack(
                (along, vertical, np.full(len(along), fixed))
            )
        kept.append(points)
        remaining -= len(points)
    stacked = np.vstack(kept)[:count]
    return stacked + generator.normal(0.0, 0.003, stacked.shape)


def make_room_with_openings(
    *,
    door: bool = True,
    window: bool = True,
    wall_points: int = 4000,
    space_beyond: bool = True,
) -> ReconstructionResult:
    """Build a 6 x 4 m room with an optional full-height door and a window.

    The door is a 0.90 m full-height void centred at x = 0 in the z = -2 wall.
    The window is a 1.20 m void from 0.90 m to 2.00 m in the x = +3 wall.

    `space_beyond` adds the geometry a real aperture always has behind it: a
    short corridor past the doorway and an exterior surface past the window.
    Without it, a void in an otherwise closed box carries no evidence that it is
    an opening at all rather than a patch of wall that returned nothing, and the
    detector is expected to refuse it.
    """
    generator = np.random.default_rng(21)
    floor_x, floor_z = np.meshgrid(np.linspace(-3, 3, 121), np.linspace(-2, 2, 81))
    floor = np.column_stack(
        (
            floor_x.ravel(),
            generator.normal(0.0, 0.003, floor_x.size),
            floor_z.ravel(),
        )
    )
    ceiling = floor.copy()
    ceiling[:, 1] = 2.5 + generator.normal(0.0, 0.003, len(ceiling))

    walls = [
        _wall_points(
            generator,
            axis="z",
            fixed=-2.0,
            span=(-3.0, 3.0),
            height=(0.06, 2.44),
            count=wall_points,
            exclude_span=(-0.45, 0.45) if door else None,
        ),
        _wall_points(
            generator,
            axis="z",
            fixed=2.0,
            span=(-3.0, 3.0),
            height=(0.06, 2.44),
            count=wall_points,
        ),
        _wall_points(
            generator,
            axis="x",
            fixed=3.0,
            span=(-2.0, 2.0),
            height=(0.06, 2.44),
            count=wall_points,
            exclude_span=(-0.60, 0.60) if window else None,
            exclude_height=(0.90, 2.00) if window else None,
        ),
        _wall_points(
            generator,
            axis="x",
            fixed=-3.0,
            span=(-2.0, 2.0),
            height=(0.06, 2.44),
            count=wall_points,
        ),
    ]
    surfaces = [floor, ceiling, *walls]
    if space_beyond:
        if door:
            # A corridor seen through the doorway: floor plus a far wall.
            corridor_x, corridor_z = np.meshgrid(
                np.linspace(-0.7, 0.7, 29), np.linspace(-3.2, -2.06, 23)
            )
            surfaces.append(
                np.column_stack(
                    (
                        corridor_x.ravel(),
                        generator.normal(0.0, 0.003, corridor_x.size),
                        corridor_z.ravel(),
                    )
                )
            )
            surfaces.append(
                _wall_points(
                    generator, axis="z", fixed=-3.2, span=(-0.7, 0.7),
                    height=(0.06, 2.44), count=900,
                )
            )
        if window:
            # An exterior surface seen through the window aperture.
            beyond_z, beyond_y = np.meshgrid(
                np.linspace(-0.6, 0.6, 25), np.linspace(0.95, 1.95, 21)
            )
            surfaces.append(
                np.column_stack(
                    (
                        np.full(beyond_z.size, 3.9)
                        + generator.normal(0.0, 0.003, beyond_z.size),
                        beyond_y.ravel(),
                        beyond_z.ravel(),
                    )
                )
            )
    points = np.vstack(surfaces).astype(np.float32)
    trajectory = np.asarray(
        [[-1.5, 1.5, -1.0], [0.0, 1.5, 0.0], [1.5, 1.5, 1.0]],
        dtype=np.float64,
    )
    reconstruction_config = ReconstructionConfig(
        profile=ReconstructionProfile.TEST,
        frame_selection=FrameSelection.DISTRIBUTED,
        max_frames=10,
        pixel_stride=8,
        voxel_size_m=0.04,
        minimum_confidence=1,
        minimum_depth_m=0.2,
        maximum_depth_m=8.0,
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
        trajectory_start_xyz_m=(-1.5, 1.5, -1.0),
        trajectory_end_xyz_m=(1.5, 1.5, 1.0),
        trajectory_path_length_m=2 * math.sqrt(2.5**2 + 1.0),
        closure_proxy_m=math.sqrt(3.0**2 + 2.0**2),
    )
    summary = ReconstructionSummary(
        status="ok",
        source="synthetic-openings",
        config=reconstruction_config,
        statistics=statistics,
        elapsed_seconds=0.0,
    )
    return ReconstructionResult(points, trajectory, summary)


def make_two_rooms_with_doorway(*, doorway: bool = True) -> ReconstructionResult:
    """Build two 4 x 4 m rooms sharing a wall at z = 0 with a 0.90 m doorway.

    The shared wall runs the full 4 m width. When `doorway` is False the wall is
    solid, so no adjacency may be claimed.
    """
    generator = np.random.default_rng(37)
    surfaces: list[np.ndarray] = []
    for z_low, z_high in ((-4.0, -0.06), (0.06, 4.0)):
        floor_x, floor_z = np.meshgrid(
            np.linspace(-2, 2, 81),
            np.linspace(z_low, z_high, max(2, int((z_high - z_low) / 0.05))),
        )
        floor = np.column_stack(
            (
                floor_x.ravel(),
                generator.normal(0.0, 0.003, floor_x.size),
                floor_z.ravel(),
            )
        )
        surfaces.append(floor)
        ceiling = floor.copy()
        ceiling[:, 1] = 2.5 + generator.normal(0.0, 0.003, len(ceiling))
        surfaces.append(ceiling)

    walls = [
        # Shared interior wall carrying the doorway.
        _wall_points(
            generator,
            axis="z",
            fixed=0.0,
            span=(-2.0, 2.0),
            height=(0.06, 2.44),
            count=3500,
            exclude_span=(-0.45, 0.45) if doorway else None,
        ),
        _wall_points(
            generator, axis="z", fixed=-4.0, span=(-2.0, 2.0),
            height=(0.06, 2.44), count=3500,
        ),
        _wall_points(
            generator, axis="z", fixed=4.0, span=(-2.0, 2.0),
            height=(0.06, 2.44), count=3500,
        ),
        _wall_points(
            generator, axis="x", fixed=-2.0, span=(-4.0, 4.0),
            height=(0.06, 2.44), count=6000,
        ),
        _wall_points(
            generator, axis="x", fixed=2.0, span=(-4.0, 4.0),
            height=(0.06, 2.44), count=6000,
        ),
    ]
    points = np.vstack((*surfaces, *walls)).astype(np.float32)
    trajectory = np.asarray(
        [[0.0, 1.5, -2.5], [0.0, 1.5, 0.0], [0.0, 1.5, 2.5]],
        dtype=np.float64,
    )
    reconstruction_config = ReconstructionConfig(
        profile=ReconstructionProfile.TEST,
        frame_selection=FrameSelection.DISTRIBUTED,
        max_frames=10,
        pixel_stride=8,
        voxel_size_m=0.04,
        minimum_confidence=1,
        minimum_depth_m=0.2,
        maximum_depth_m=12.0,
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
        trajectory_start_xyz_m=(0.0, 1.5, -2.5),
        trajectory_end_xyz_m=(0.0, 1.5, 2.5),
        trajectory_path_length_m=5.0,
        closure_proxy_m=5.0,
    )
    summary = ReconstructionSummary(
        status="ok",
        source="synthetic-two-rooms",
        config=reconstruction_config,
        statistics=statistics,
        elapsed_seconds=0.0,
    )
    return ReconstructionResult(points, trajectory, summary)
