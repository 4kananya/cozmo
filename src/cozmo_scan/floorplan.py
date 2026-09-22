"""Deterministic structural planes and measured 2D floor-plan extraction."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from cozmo_scan.models import (
    FloorCoordinateSystem,
    FloorPlanMeasurement,
    PlaneMeasurement,
    StructureConfig,
    StructureSummary,
)
from cozmo_scan.reconstruction import ReconstructionResult

FloatArray = NDArray[np.floating]
BoolArray = NDArray[np.bool_]
WORLD_UP = np.asarray([0.0, 1.0, 0.0], dtype=np.float64)
MAX_RANSAC_SAMPLE_POINTS = 20_000


class StructureError(ValueError):
    """Raised when a trustworthy measured floor plan cannot be produced."""


@dataclass(frozen=True, slots=True)
class PlaneFit:
    """Internal numerical representation of a fitted plane."""

    normal_xyz: NDArray[np.float64]
    offset_m: float
    centroid_xyz_m: NDArray[np.float64]
    inlier_mask: BoolArray
    rmse_m: float


@dataclass(frozen=True, slots=True)
class StructureResult:
    """In-memory structural result with its public serializable summary."""

    summary: StructureSummary


def classify_plane(
    normal_xyz: FloatArray,
    *,
    horizontal_angle_tolerance_deg: float = 15.0,
) -> Literal["horizontal", "vertical", "other"]:
    """Classify a plane by the angle between its normal and world-up."""
    normal = _normalized(normal_xyz)
    alignment = abs(float(normal @ WORLD_UP))
    cosine_tolerance = math.cos(math.radians(horizontal_angle_tolerance_deg))
    sine_tolerance = math.sin(math.radians(horizontal_angle_tolerance_deg))
    if alignment >= cosine_tolerance:
        return "horizontal"
    if alignment <= sine_tolerance:
        return "vertical"
    return "other"


def fit_plane_ransac(
    points_xyz_m: FloatArray,
    *,
    distance_threshold_m: float,
    iterations: int = 300,
    random_seed: int = 17,
    expected_orientation: Literal["horizontal", "vertical"] | None = None,
    angle_tolerance_deg: float = 15.0,
) -> PlaneFit:
    """Fit a plane robustly and deterministically using a fixed-seed RANSAC."""
    points = _finite_points(points_xyz_m)
    if len(points) < 3:
        raise StructureError("At least three finite points are required to fit a plane")
    if distance_threshold_m <= 0 or iterations < 1:
        raise ValueError("Plane threshold and iteration count must be positive")

    search = points
    if len(search) > MAX_RANSAC_SAMPLE_POINTS:
        indices = np.linspace(
            0, len(search) - 1, MAX_RANSAC_SAMPLE_POINTS, dtype=np.int64
        )
        search = search[indices]

    generator = np.random.default_rng(random_seed)
    best_normal: NDArray[np.float64] | None = None
    best_offset = 0.0
    best_count = 0
    for _ in range(iterations):
        sample_indices = generator.choice(len(search), size=3, replace=False)
        first, second, third = search[sample_indices]
        normal = np.cross(second - first, third - first)
        norm = float(np.linalg.norm(normal))
        if norm < 1e-10:
            continue
        normal = normal / norm
        if expected_orientation is not None and classify_plane(
            normal, horizontal_angle_tolerance_deg=angle_tolerance_deg
        ) != expected_orientation:
            continue
        offset = -float(normal @ first)
        count = int(np.count_nonzero(np.abs(search @ normal + offset) <= distance_threshold_m))
        if count > best_count:
            best_count = count
            best_normal = normal
            best_offset = offset

    if best_normal is None:
        raise StructureError("RANSAC could not find a plane with the required orientation")

    inliers = np.abs(points @ best_normal + best_offset) <= distance_threshold_m
    if int(inliers.sum()) < 3:
        raise StructureError("RANSAC plane has fewer than three inliers")
    normal, offset, centroid = _fit_plane_svd(points[inliers])
    for _ in range(2):
        inliers = np.abs(points @ normal + offset) <= distance_threshold_m
        if int(inliers.sum()) < 3:
            break
        normal, offset, centroid = _fit_plane_svd(points[inliers])

    if expected_orientation is not None and classify_plane(
        normal, horizontal_angle_tolerance_deg=angle_tolerance_deg
    ) != expected_orientation:
        raise StructureError("Refined plane does not have the required orientation")
    if float(normal @ WORLD_UP) < 0:
        normal = -normal
        offset = -offset
    distances = np.abs(points[inliers] @ normal + offset)
    rmse = float(np.sqrt(np.mean(np.square(distances))))
    return PlaneFit(normal, offset, centroid, inliers, rmse)


def create_floor_coordinate_system(floor: PlaneFit) -> FloorCoordinateSystem:
    """Create a right-handed, world-X-aligned coordinate system on the floor."""
    up = floor.normal_xyz.copy()
    if float(up @ WORLD_UP) < 0:
        up = -up
    x_axis = np.asarray([1.0, 0.0, 0.0], dtype=np.float64)
    x_axis = x_axis - float(x_axis @ up) * up
    if float(np.linalg.norm(x_axis)) < 1e-8:
        x_axis = np.asarray([0.0, 0.0, 1.0], dtype=np.float64)
        x_axis = x_axis - float(x_axis @ up) * up
    x_axis = _normalized(x_axis)
    y_axis = _normalized(np.cross(x_axis, up))
    origin = floor.centroid_xyz_m
    return FloorCoordinateSystem(
        origin_xyz_m=_float_tuple3(origin),
        x_axis_xyz=_float_tuple3(x_axis),
        y_axis_xyz=_float_tuple3(y_axis),
        up_axis_xyz=_float_tuple3(up),
    )


def project_points_to_floor(
    points_xyz_m: FloatArray, coordinates: FloorCoordinateSystem
) -> NDArray[np.float64]:
    """Project world points into floor-local X/Y coordinates in metres."""
    points = np.asarray(points_xyz_m, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError("points must have shape (N, 3)")
    origin = np.asarray(coordinates.origin_xyz_m, dtype=np.float64)
    axes = np.column_stack(
        (
            np.asarray(coordinates.x_axis_xyz, dtype=np.float64),
            np.asarray(coordinates.y_axis_xyz, dtype=np.float64),
        )
    )
    return (points - origin) @ axes


def build_convex_outline(points_xy_m: FloatArray) -> NDArray[np.float64]:
    """Return the counter-clockwise convex hull of 2D points."""
    points = np.asarray(points_xy_m, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 2:
        raise ValueError("outline points must have shape (N, 2)")
    points = np.unique(points[np.isfinite(points).all(axis=1)], axis=0)
    if len(points) < 3:
        raise StructureError("At least three unique points are required for an outline")
    ordered = sorted((float(point[0]), float(point[1])) for point in points)

    def cross(
        origin: tuple[float, float],
        first: tuple[float, float],
        second: tuple[float, float],
    ) -> float:
        return (first[0] - origin[0]) * (second[1] - origin[1]) - (
            first[1] - origin[1]
        ) * (second[0] - origin[0])

    lower: list[tuple[float, float]] = []
    for point in ordered:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper: list[tuple[float, float]] = []
    for point in reversed(ordered):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    hull = lower[:-1] + upper[:-1]
    if len(hull) < 3:
        raise StructureError("Projected floor points are collinear")
    return np.asarray(hull, dtype=np.float64)


def simplify_polygon(
    vertices_xy_m: FloatArray, tolerance_m: float
) -> NDArray[np.float64]:
    """Remove short or nearly collinear convex-hull vertices."""
    vertices = np.asarray(vertices_xy_m, dtype=np.float64).copy()
    if len(vertices) < 3 or tolerance_m < 0:
        raise ValueError("polygon requires three vertices and a non-negative tolerance")
    while len(vertices) > 3:
        removable_index: int | None = None
        removable_score = math.inf
        for index in range(len(vertices)):
            previous = vertices[index - 1]
            current = vertices[index]
            following = vertices[(index + 1) % len(vertices)]
            chord = following - previous
            chord_length = float(np.linalg.norm(chord))
            if chord_length < 1e-12:
                score = 0.0
            else:
                delta = current - previous
                score = abs(float(chord[0] * delta[1] - chord[1] * delta[0])) / chord_length
            adjacent = min(
                float(np.linalg.norm(current - previous)),
                float(np.linalg.norm(following - current)),
            )
            metric = min(score, adjacent)
            if metric <= tolerance_m and metric < removable_score:
                removable_index = index
                removable_score = metric
        if removable_index is None:
            break
        vertices = np.delete(vertices, removable_index, axis=0)
    return vertices


def measure_polygon(
    vertices_xy_m: FloatArray,
    *,
    supporting_cell_count: int,
    occupied_cell_area_m2: float | None = None,
) -> FloorPlanMeasurement:
    """Calculate edges, area, perimeter, and minimum-area-box dimensions."""
    vertices = np.asarray(vertices_xy_m, dtype=np.float64)
    if vertices.ndim != 2 or vertices.shape[1] != 2 or len(vertices) < 3:
        raise ValueError("polygon must contain at least three 2D vertices")
    closed = np.vstack((vertices, vertices[0]))
    differences = np.diff(closed, axis=0)
    edge_lengths = np.linalg.norm(differences, axis=1)
    perimeter = float(edge_lengths.sum())
    area = 0.5 * abs(
        float(
            np.dot(vertices[:, 0], np.roll(vertices[:, 1], -1))
            - np.dot(vertices[:, 1], np.roll(vertices[:, 0], -1))
        )
    )
    if area <= 1e-8 or perimeter <= 1e-8:
        raise StructureError("Floor outline has zero measurable area")
    occupied_area = area if occupied_cell_area_m2 is None else occupied_cell_area_m2
    if occupied_area <= 0:
        raise ValueError("occupied_cell_area_m2 must be positive")
    length, width, angle = _minimum_area_dimensions(vertices)
    return FloorPlanMeasurement(
        vertices_xy_m=tuple(_float_tuple2(vertex) for vertex in vertices),
        edge_lengths_m=tuple(float(value) for value in edge_lengths),
        area_m2=area,
        perimeter_m=perimeter,
        length_m=length,
        width_m=width,
        principal_angle_deg=angle,
        supporting_cell_count=supporting_cell_count,
        occupied_cell_area_m2=float(occupied_area),
        convex_fill_ratio=min(1.0, float(occupied_area / area)),
    )


def analyze_structure(
    reconstruction: ReconstructionResult,
    config: StructureConfig | None = None,
) -> StructureResult:
    """Extract trustworthy structural planes and a measured convex floor plan."""
    started = time.perf_counter()
    effective = config or StructureConfig()
    points = _finite_points(reconstruction.points_xyz_m)
    trajectory = _finite_points(reconstruction.trajectory_xyz_m)
    if len(points) < effective.minimum_plane_inliers:
        raise StructureError("Point cloud is too small for structural analysis")
    if len(trajectory) == 0:
        raise StructureError("Camera trajectory is required to identify the floor")

    floor_fit, floor = detect_floor(points, trajectory, effective)
    coordinates = create_floor_coordinate_system(floor_fit)
    floor_points = points[floor_fit.inlier_mask]
    projected = project_points_to_floor(floor_points, coordinates)
    boundary_points = trim_boundary_outliers(projected, effective)
    outline = simplify_polygon(
        build_convex_outline(boundary_points),
        effective.polygon_simplify_tolerance_m,
    )
    floor_plan = measure_polygon(
        outline,
        supporting_cell_count=len(boundary_points),
        occupied_cell_area_m2=(
            len(boundary_points) * effective.boundary_grid_size_m**2
        ),
    )

    ceiling_fit, ceiling, ceiling_height = detect_ceiling(
        points, floor_fit, effective
    )
    walls = detect_wall_planes(
        points,
        floor_fit,
        ceiling_fit,
        effective,
    )

    warnings = [
        "Floor outline is a convex approximation and may overfill concave spaces."
    ]
    if ceiling is None:
        warnings.append(
            "No ceiling plane met the support and geometry checks; ceiling height is unavailable."
        )
    if len(walls) < 2:
        warnings.append(
            f"Only {len(walls)} credible wall plane(s) were detected; wall coverage is limited."
        )
    if floor.rmse_m > effective.floor_rmse_warning_m:
        warnings.append(
            f"Floor-plane residual is {floor.rmse_m:.3f} m; measurements may include surface noise."
        )
    if floor.inlier_ratio < effective.floor_inlier_ratio_warning:
        warnings.append(
            f"Floor support is {floor.inlier_ratio:.1%} of the point cloud; boundary confidence is limited."
        )
    if floor_plan.convex_fill_ratio < effective.minimum_boundary_fill_ratio:
        warnings.append(
            "Only "
            f"{floor_plan.convex_fill_ratio:.1%} of the convex outline is backed by occupied floor cells; "
            "the outline likely bridges unscanned or concave regions and its area should be treated as provisional."
        )
    if (
        floor_plan.area_m2 > effective.maximum_area_warning_m2
        or floor_plan.length_m > effective.maximum_dimension_warning_m
    ):
        warnings.append("Floor-plan extent is unusually large and should be reviewed visually.")

    summary = StructureSummary(
        status="ok_with_warnings" if warnings else "ok",
        source=reconstruction.summary.source,
        config=effective,
        floor=floor,
        ceiling=ceiling,
        walls=walls,
        floor_coordinates=coordinates,
        floor_plan=floor_plan,
        ceiling_height_m=ceiling_height,
        elapsed_seconds=time.perf_counter() - started,
        warnings=tuple(warnings),
        artifacts={
            "structure_summary": "structure.json",
            "floorplan_vector": "floorplan.svg",
            "floorplan_preview": "floorplan.png",
        },
    )
    return StructureResult(summary=summary)


def detect_floor(
    points_xyz_m: FloatArray,
    trajectory_xyz_m: FloatArray,
    config: StructureConfig,
) -> tuple[PlaneFit, PlaneMeasurement]:
    """Detect the dominant horizontal surface below the median camera height."""
    points = _finite_points(points_xyz_m)
    trajectory = _finite_points(trajectory_xyz_m)
    camera_height = float(np.median(trajectory[:, 1]))
    minimum_y = camera_height - config.floor_below_camera_max_m
    maximum_y = camera_height - config.floor_below_camera_min_m
    eligible = (points[:, 1] >= minimum_y) & (points[:, 1] <= maximum_y)
    fit = _detect_horizontal_plane(points, eligible, config, seed_offset=0)
    separation = camera_height - float(fit.centroid_xyz_m[1])
    if not config.floor_below_camera_min_m <= separation <= config.floor_below_camera_max_m:
        raise StructureError(
            f"Detected floor is {separation:.2f} m below the camera, outside the accepted range"
        )
    measurement = _plane_measurement("floor", fit, points)
    _require_horizontal_support(measurement, config, "floor")
    return fit, measurement


def detect_ceiling(
    points_xyz_m: FloatArray,
    floor: PlaneFit,
    config: StructureConfig,
) -> tuple[PlaneFit | None, PlaneMeasurement | None, float | None]:
    """Return a ceiling only when an upper horizontal plane passes strict checks."""
    points = _finite_points(points_xyz_m)
    heights = (points - floor.centroid_xyz_m) @ floor.normal_xyz
    eligible = (heights >= config.ceiling_height_min_m) & (
        heights <= config.ceiling_height_max_m
    )
    if int(eligible.sum()) < config.minimum_plane_inliers:
        return None, None, None
    try:
        fit = _detect_horizontal_plane(points, eligible, config, seed_offset=1)
        measurement = _plane_measurement("ceiling", fit, points)
        minimum_ceiling_span = max(
            config.minimum_horizontal_span_m, config.minimum_ceiling_span_m
        )
        minimum_ceiling_inliers = max(
            config.minimum_plane_inliers,
            config.minimum_ceiling_inliers,
            int(len(points) * config.minimum_ceiling_inlier_ratio),
        )
        if (
            measurement.inlier_count < minimum_ceiling_inliers
            or min(measurement.span_primary_m, measurement.span_secondary_m)
            < minimum_ceiling_span
        ):
            return None, None, None
        height = float((fit.centroid_xyz_m - floor.centroid_xyz_m) @ floor.normal_xyz)
        if not config.ceiling_height_min_m <= height <= config.ceiling_height_max_m:
            return None, None, None
        return fit, measurement, height
    except StructureError:
        return None, None, None


def detect_wall_planes(
    points_xyz_m: FloatArray,
    floor: PlaneFit,
    ceiling: PlaneFit | None,
    config: StructureConfig,
) -> tuple[PlaneMeasurement, ...]:
    """Detect major vertical planes using deterministic 2D line RANSAC in X-Z."""
    if config.maximum_wall_planes == 0:
        return ()
    points = _finite_points(points_xyz_m)
    heights = (points - floor.centroid_xyz_m) @ floor.normal_xyz
    upper_height = (
        float((ceiling.centroid_xyz_m - floor.centroid_xyz_m) @ floor.normal_xyz)
        if ceiling is not None
        else config.ceiling_height_max_m
    )
    working = (heights >= config.floor_clearance_m) & (
        heights <= upper_height + config.floor_clearance_m
    )
    working &= (
        np.abs(points @ floor.normal_xyz + floor.offset_m)
        > config.wall_plane_distance_threshold_m
    )
    generator = np.random.default_rng(config.random_seed + 100)
    results: list[PlaneMeasurement] = []
    wall_threshold = config.wall_plane_distance_threshold_m
    minimum_inliers = max(
        config.minimum_plane_inliers,
        int(len(points) * config.minimum_wall_inlier_ratio),
    )

    while len(results) < config.maximum_wall_planes and int(working.sum()) >= minimum_inliers:
        working_indices = np.flatnonzero(working)
        search_indices = working_indices
        if len(search_indices) > MAX_RANSAC_SAMPLE_POINTS:
            selected = np.linspace(
                0,
                len(search_indices) - 1,
                MAX_RANSAC_SAMPLE_POINTS,
                dtype=np.int64,
            )
            search_indices = search_indices[selected]
        search_xz = points[search_indices][:, (0, 2)]
        best_normal: NDArray[np.float64] | None = None
        best_offset = 0.0
        best_count = 0
        for _ in range(config.ransac_iterations):
            first_index, second_index = generator.choice(
                len(search_xz), size=2, replace=False
            )
            delta = search_xz[second_index] - search_xz[first_index]
            length = float(np.linalg.norm(delta))
            if length < config.minimum_wall_span_m * 0.5:
                continue
            normal = np.asarray([-delta[1], delta[0]], dtype=np.float64) / length
            offset = -float(normal @ search_xz[first_index])
            count = int(
                np.count_nonzero(
                    np.abs(search_xz @ normal + offset) <= wall_threshold
                )
            )
            if count > best_count:
                best_normal = normal
                best_offset = offset
                best_count = count
        if best_normal is None or best_count < max(20, minimum_inliers // 4):
            break

        working_xz = points[working_indices][:, (0, 2)]
        candidate_local = (
            np.abs(working_xz @ best_normal + best_offset) <= wall_threshold
        )
        candidate_indices = working_indices[candidate_local]
        if len(candidate_indices) >= 2:
            best_normal, best_offset = _fit_line_svd(points[candidate_indices][:, (0, 2)])
            candidate_local = (
                np.abs(working_xz @ best_normal + best_offset) <= wall_threshold
            )
            candidate_indices = working_indices[candidate_local]

        if len(candidate_indices) < minimum_inliers:
            working[candidate_indices] = False
            continue
        candidate_points = points[candidate_indices]
        along_axis = np.asarray([-best_normal[1], best_normal[0]])
        along_values = candidate_points[:, (0, 2)] @ along_axis
        height_values = heights[candidate_indices]
        wall_span = _robust_span(along_values)
        wall_height = _robust_span(height_values)
        if (
            wall_span < config.minimum_wall_span_m
            or wall_height < config.minimum_wall_height_m
        ):
            working[candidate_indices] = False
            continue

        if best_normal[0] < -1e-12 or (
            abs(float(best_normal[0])) <= 1e-12 and best_normal[1] < 0
        ):
            best_normal = -best_normal
            best_offset = -best_offset
        normal_xyz = np.asarray(
            [best_normal[0], 0.0, best_normal[1]], dtype=np.float64
        )
        centroid = candidate_points.mean(axis=0)
        distances = np.abs(candidate_points @ normal_xyz + best_offset)
        measurement = PlaneMeasurement(
            kind="wall",
            normal_xyz=_float_tuple3(normal_xyz),
            offset_m=float(best_offset),
            centroid_xyz_m=_float_tuple3(centroid),
            inlier_count=len(candidate_points),
            inlier_ratio=float(len(candidate_points) / len(points)),
            rmse_m=float(np.sqrt(np.mean(np.square(distances)))),
            span_primary_m=wall_span,
            span_secondary_m=wall_height,
        )
        if not _is_duplicate_wall(
            measurement,
            results,
            angle_tolerance_deg=config.duplicate_wall_angle_tolerance_deg,
            offset_tolerance_m=config.duplicate_wall_offset_tolerance_m,
        ):
            results.append(measurement)
        working[candidate_indices] = False

    results.sort(key=lambda plane: (-plane.inlier_count, plane.offset_m))
    return tuple(results)


def trim_boundary_outliers(
    points_xy_m: FloatArray, config: StructureConfig
) -> NDArray[np.float64]:
    """Trim extreme axes and remove isolated occupancy cells before hulling."""
    points = np.asarray(points_xy_m, dtype=np.float64)
    points = points[np.isfinite(points).all(axis=1)]
    if len(points) < 3:
        raise StructureError("Too few projected floor points for a boundary")
    percentile = config.boundary_trim_percentile
    lower = np.percentile(points, percentile, axis=0)
    upper = np.percentile(points, 100.0 - percentile, axis=0)
    trimmed = points[((points >= lower) & (points <= upper)).all(axis=1)]
    if len(trimmed) < 3:
        raise StructureError("Boundary trimming removed too many floor points")

    grid = config.boundary_grid_size_m
    cells = np.floor(trimmed / grid).astype(np.int64)
    unique_cells = np.unique(cells, axis=0)
    occupied = {(int(cell[0]), int(cell[1])) for cell in unique_cells}
    supported: list[tuple[int, int]] = []
    for cell_x, cell_y in sorted(occupied):
        neighbours = sum(
            (cell_x + dx, cell_y + dy) in occupied
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            if dx != 0 or dy != 0
        )
        if neighbours >= 2:
            supported.append((cell_x, cell_y))
    if len(supported) < 3:
        supported = sorted(occupied)
    return (np.asarray(supported, dtype=np.float64) + 0.5) * grid


def _detect_horizontal_plane(
    points: NDArray[np.float64],
    eligible: BoolArray,
    config: StructureConfig,
    *,
    seed_offset: int,
) -> PlaneFit:
    candidate_points = points[eligible]
    if len(candidate_points) < config.minimum_plane_inliers:
        raise StructureError("Not enough points in the accepted horizontal-plane range")
    heights = candidate_points[:, 1]
    minimum = float(heights.min())
    maximum = float(heights.max())
    if maximum - minimum < config.height_histogram_bin_m:
        centre = float(np.median(heights))
    else:
        bins = max(1, math.ceil((maximum - minimum) / config.height_histogram_bin_m))
        counts, edges = np.histogram(heights, bins=bins, range=(minimum, maximum))
        peak = int(np.argmax(counts))
        centre = float((edges[peak] + edges[peak + 1]) / 2)
    seed_points = candidate_points[
        np.abs(heights - centre) <= config.seed_band_half_width_m
    ]
    if len(seed_points) < config.minimum_plane_inliers:
        raise StructureError("Dominant horizontal band has insufficient support")
    seed_fit = fit_plane_ransac(
        seed_points,
        distance_threshold_m=config.plane_distance_threshold_m,
        iterations=config.ransac_iterations,
        random_seed=config.random_seed + seed_offset,
        expected_orientation="horizontal",
        angle_tolerance_deg=config.horizontal_angle_tolerance_deg,
    )
    normal = seed_fit.normal_xyz
    offset = seed_fit.offset_m
    inliers = eligible & (
        np.abs(points @ normal + offset) <= config.plane_distance_threshold_m
    )
    if int(inliers.sum()) < config.minimum_plane_inliers:
        raise StructureError("Refined horizontal plane has insufficient support")
    normal, offset, centroid = _fit_plane_svd(points[inliers])
    if float(normal @ WORLD_UP) < 0:
        normal = -normal
        offset = -offset
    inliers = eligible & (
        np.abs(points @ normal + offset) <= config.plane_distance_threshold_m
    )
    distances = np.abs(points[inliers] @ normal + offset)
    return PlaneFit(
        normal_xyz=normal,
        offset_m=float(offset),
        centroid_xyz_m=centroid,
        inlier_mask=inliers,
        rmse_m=float(np.sqrt(np.mean(np.square(distances)))),
    )


def _plane_measurement(
    kind: Literal["floor", "ceiling"],
    fit: PlaneFit,
    all_points: NDArray[np.float64],
) -> PlaneMeasurement:
    inlier_points = all_points[fit.inlier_mask]
    axis_x, axis_y = _plane_axes(fit.normal_xyz)
    centred = inlier_points - fit.centroid_xyz_m
    span_x = _robust_span(centred @ axis_x)
    span_y = _robust_span(centred @ axis_y)
    return PlaneMeasurement(
        kind=kind,
        normal_xyz=_float_tuple3(fit.normal_xyz),
        offset_m=float(fit.offset_m),
        centroid_xyz_m=_float_tuple3(fit.centroid_xyz_m),
        inlier_count=int(fit.inlier_mask.sum()),
        inlier_ratio=float(fit.inlier_mask.mean()),
        rmse_m=float(fit.rmse_m),
        span_primary_m=max(span_x, span_y),
        span_secondary_m=min(span_x, span_y),
    )


def _require_horizontal_support(
    plane: PlaneMeasurement, config: StructureConfig, label: str
) -> None:
    if plane.inlier_count < config.minimum_plane_inliers:
        raise StructureError(f"Detected {label} has insufficient point support")
    if min(plane.span_primary_m, plane.span_secondary_m) < config.minimum_horizontal_span_m:
        raise StructureError(f"Detected {label} does not cover a credible 2D extent")


def _fit_plane_svd(
    points_xyz_m: FloatArray,
) -> tuple[NDArray[np.float64], float, NDArray[np.float64]]:
    points = np.asarray(points_xyz_m, dtype=np.float64)
    centroid = points.mean(axis=0)
    _, _, right = np.linalg.svd(points - centroid, full_matrices=False)
    normal = _normalized(right[-1])
    offset = -float(normal @ centroid)
    return normal, offset, centroid


def _fit_line_svd(points_xy_m: FloatArray) -> tuple[NDArray[np.float64], float]:
    points = np.asarray(points_xy_m, dtype=np.float64)
    centroid = points.mean(axis=0)
    _, _, right = np.linalg.svd(points - centroid, full_matrices=False)
    direction = _normalized(right[0])
    normal = np.asarray([-direction[1], direction[0]], dtype=np.float64)
    return normal, -float(normal @ centroid)


def _plane_axes(
    normal_xyz: FloatArray,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    normal = _normalized(normal_xyz)
    reference = np.asarray([1.0, 0.0, 0.0])
    if abs(float(reference @ normal)) > 0.9:
        reference = np.asarray([0.0, 0.0, 1.0])
    first = _normalized(reference - float(reference @ normal) * normal)
    second = _normalized(np.cross(first, normal))
    return first, second


def _minimum_area_dimensions(
    vertices: NDArray[np.float64],
) -> tuple[float, float, float]:
    best_area = math.inf
    best_spans = (0.0, 0.0)
    best_angle = 0.0
    for edge in np.diff(np.vstack((vertices, vertices[0])), axis=0):
        if float(np.linalg.norm(edge)) < 1e-12:
            continue
        angle = math.atan2(float(edge[1]), float(edge[0]))
        cosine = math.cos(angle)
        sine = math.sin(angle)
        rotation = np.asarray([[cosine, sine], [-sine, cosine]])
        rotated = vertices @ rotation.T
        spans = np.ptp(rotated, axis=0)
        area = float(spans[0] * spans[1])
        if area < best_area:
            best_area = area
            best_spans = (float(spans[0]), float(spans[1]))
            best_angle = math.degrees(angle)
    length = max(best_spans)
    width = min(best_spans)
    if best_spans[1] > best_spans[0]:
        best_angle += 90.0
    best_angle = ((best_angle + 180.0) % 180.0) - 90.0
    return length, width, best_angle


def _is_duplicate_wall(
    candidate: PlaneMeasurement,
    existing: list[PlaneMeasurement],
    *,
    angle_tolerance_deg: float,
    offset_tolerance_m: float,
) -> bool:
    candidate_normal = np.asarray(candidate.normal_xyz)
    for wall in existing:
        normal = np.asarray(wall.normal_xyz)
        if abs(float(candidate_normal @ normal)) < math.cos(
            math.radians(angle_tolerance_deg)
        ):
            continue
        candidate_offset = candidate.offset_m
        wall_offset = wall.offset_m
        if float(candidate_normal @ normal) < 0:
            candidate_offset = -candidate_offset
        if abs(candidate_offset - wall_offset) < offset_tolerance_m:
            return True
    return False


def _robust_span(values: FloatArray) -> float:
    lower, upper = np.percentile(values, (1.0, 99.0))
    return max(0.0, float(upper - lower))


def _finite_points(points_xyz_m: FloatArray) -> NDArray[np.float64]:
    points = np.asarray(points_xyz_m, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError("points must have shape (N, 3)")
    return points[np.isfinite(points).all(axis=1)]


def _normalized(vector: FloatArray) -> NDArray[np.float64]:
    array = np.asarray(vector, dtype=np.float64)
    norm = float(np.linalg.norm(array))
    if not math.isfinite(norm) or norm < 1e-12:
        raise ValueError("vector must have a finite non-zero norm")
    return array / norm


def _float_tuple2(values: FloatArray) -> tuple[float, float]:
    return float(values[0]), float(values[1])


def _float_tuple3(values: FloatArray) -> tuple[float, float, float]:
    return float(values[0]), float(values[1]), float(values[2])
