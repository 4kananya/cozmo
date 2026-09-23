"""Validated data models shared by capture ingestion and later pipeline stages."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


class FrozenModel(BaseModel):
    """Base model for immutable validated records."""

    model_config = ConfigDict(frozen=True)


class IssueSeverity(StrEnum):
    """Severity of a capture validation issue."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ValidationIssue(FrozenModel):
    """One structured validation finding."""

    severity: IssueSeverity
    code: str
    message: str


class CameraMatrix(FrozenModel):
    """A row-major 3 x 3 camera calibration matrix."""

    rows: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ]

    @property
    def fx(self) -> float:
        return self.rows[0][0]

    @property
    def fy(self) -> float:
        return self.rows[1][1]

    @property
    def cx(self) -> float:
        return self.rows[0][2]

    @property
    def cy(self) -> float:
        return self.rows[1][2]


class OdometryRecord(FrozenModel):
    """One timestamped camera pose and its per-frame intrinsics."""

    timestamp: float
    frame_id: str
    position_xyz_m: tuple[float, float, float]
    quaternion_xyzw: tuple[float, float, float, float]
    intrinsics_fx_fy_cx_cy: tuple[float, float, float, float]
    distortion_center_xy: tuple[float, float] | None = None


class FrameRecord(FrozenModel):
    """Paths and pose for one usable LiDAR frame."""

    frame_id: str
    depth_path: str
    confidence_path: str
    odometry: OdometryRecord


class FrameMatchResult(FrozenModel):
    """Matched frames plus bounded lists of unmatched IDs."""

    frames: tuple[FrameRecord, ...]
    missing_depth_ids: tuple[str, ...] = ()
    missing_confidence_ids: tuple[str, ...] = ()
    missing_odometry_ids: tuple[str, ...] = ()


class CaptureIndex(FrozenModel):
    """Calibration and matched frame records needed by reconstruction."""

    capture_root: str
    camera_matrix: CameraMatrix
    frames: tuple[FrameRecord, ...]


class ImageInspection(FrozenModel):
    """Properties observed while decoding one image."""

    member: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    mode: str
    minimum: int | float
    maximum: int | float


class ImuSummary(FrozenModel):
    """Small summary of an optional IMU CSV."""

    record_count: int = Field(ge=0)
    first_timestamp: float | None = None
    last_timestamp: float | None = None


class CaptureInventory(FrozenModel):
    """Compact summary of a discovered capture."""

    source_name: str
    source_kind: Literal["zip", "directory"]
    capture_root: str
    camera_matrix_present: bool
    odometry_present: bool
    imu_present: bool
    rgb_video_present: bool
    rgb_video_bytes: int | None = Field(default=None, ge=0)
    depth_frame_count: int = Field(ge=0)
    confidence_frame_count: int = Field(ge=0)
    odometry_record_count: int = Field(ge=0)
    matched_frame_count: int = Field(ge=0)
    missing_depth_count: int = Field(ge=0)
    missing_confidence_count: int = Field(ge=0)
    missing_odometry_count: int = Field(ge=0)
    imu_record_count: int | None = Field(default=None, ge=0)
    first_timestamp: float | None = None
    last_timestamp: float | None = None
    duration_seconds: float | None = Field(default=None, ge=0)
    image_pairs_inspected: int = Field(default=0, ge=0)
    depth_image_size: tuple[int, int] | None = None
    confidence_image_size: tuple[int, int] | None = None
    depth_modes: tuple[str, ...] = ()
    confidence_modes: tuple[str, ...] = ()


class ValidationResult(FrozenModel):
    """Public result returned by capture validation."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    capture_format: Literal["stray_scanner"] = "stray_scanner"
    source: str
    valid: bool
    inventory: CaptureInventory | None = None
    camera_matrix: CameraMatrix | None = None
    issues: tuple[ValidationIssue, ...] = ()

    @computed_field
    @property
    def error_count(self) -> int:
        return sum(issue.severity is IssueSeverity.ERROR for issue in self.issues)

    @computed_field
    @property
    def warning_count(self) -> int:
        return sum(issue.severity is IssueSeverity.WARNING for issue in self.issues)


class ReconstructionProfile(StrEnum):
    """Bounded processing profiles for reconstruction."""

    TEST = "test"
    FAST = "fast"
    QUALITY = "quality"


class FrameSelection(StrEnum):
    """Deterministic frame-selection strategies used during audit runs."""

    DISTRIBUTED = "distributed"
    CONTIGUOUS_START = "contiguous-start"


class ReconstructionConfig(FrozenModel):
    """Effective metric reconstruction configuration."""

    profile: ReconstructionProfile
    frame_selection: FrameSelection = FrameSelection.DISTRIBUTED
    max_frames: int = Field(gt=0)
    pixel_stride: int = Field(gt=0)
    voxel_size_m: float = Field(gt=0)
    minimum_confidence: int = Field(ge=0, le=2)
    minimum_depth_m: float = Field(gt=0)
    maximum_depth_m: float = Field(gt=0)
    calibration_width: int = Field(gt=0)
    calibration_height: int = Field(gt=0)
    fusion_batch_frames: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_depth_range(self) -> ReconstructionConfig:
        if self.maximum_depth_m <= self.minimum_depth_m:
            raise ValueError("maximum_depth_m must exceed minimum_depth_m")
        return self


class ReconstructionStatistics(FrozenModel):
    """Counts and geometric evidence from one reconstruction."""

    total_matched_frames: int = Field(ge=0)
    selected_frame_count: int = Field(ge=0)
    processed_frame_count: int = Field(ge=0)
    skipped_frame_count: int = Field(ge=0)
    sampled_pixel_count: int = Field(ge=0)
    valid_point_count_before_voxel: int = Field(ge=0)
    output_point_count: int = Field(ge=0)
    bounds_min_xyz_m: tuple[float, float, float] | None = None
    bounds_max_xyz_m: tuple[float, float, float] | None = None
    trajectory_start_xyz_m: tuple[float, float, float] | None = None
    trajectory_end_xyz_m: tuple[float, float, float] | None = None
    trajectory_path_length_m: float | None = Field(default=None, ge=0)
    closure_proxy_m: float | None = Field(default=None, ge=0)


class ReconstructionSummary(FrozenModel):
    """Machine-readable reconstruction diagnostic summary."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["ok", "ok_with_warnings"]
    units: Literal["metre"] = "metre"
    source: str
    config: ReconstructionConfig
    statistics: ReconstructionStatistics
    elapsed_seconds: float = Field(ge=0)
    warnings: tuple[str, ...] = ()
    artifacts: dict[str, str] = Field(default_factory=dict)


class StructureConfig(FrozenModel):
    """Effective parameters for deterministic structural analysis."""

    height_histogram_bin_m: float = Field(default=0.04, gt=0)
    seed_band_half_width_m: float = Field(default=0.08, gt=0)
    plane_distance_threshold_m: float = Field(default=0.05, gt=0)
    horizontal_angle_tolerance_deg: float = Field(default=15.0, gt=0, lt=90)
    floor_below_camera_min_m: float = Field(default=0.50, gt=0)
    floor_below_camera_max_m: float = Field(default=2.50, gt=0)
    ceiling_height_min_m: float = Field(default=1.80, gt=0)
    ceiling_height_max_m: float = Field(default=4.50, gt=0)
    minimum_plane_inliers: int = Field(default=100, ge=3)
    minimum_horizontal_span_m: float = Field(default=0.75, gt=0)
    minimum_ceiling_inliers: int = Field(default=200, ge=3)
    minimum_ceiling_inlier_ratio: float = Field(default=0.01, gt=0, le=1)
    minimum_ceiling_span_m: float = Field(default=1.25, gt=0)
    floor_clearance_m: float = Field(default=0.08, gt=0)
    wall_plane_distance_threshold_m: float = Field(default=0.0625, gt=0)
    minimum_wall_inlier_ratio: float = Field(default=0.004, gt=0, le=1)
    minimum_wall_span_m: float = Field(default=0.60, gt=0)
    minimum_wall_height_m: float = Field(default=0.50, gt=0)
    duplicate_wall_angle_tolerance_deg: float = Field(default=10.0, gt=0, lt=90)
    duplicate_wall_offset_tolerance_m: float = Field(default=0.15, gt=0)
    maximum_wall_planes: int = Field(default=6, ge=0, le=20)
    ransac_iterations: int = Field(default=300, gt=0)
    boundary_grid_size_m: float = Field(default=0.08, gt=0)
    boundary_trim_percentile: float = Field(default=0.5, ge=0, lt=25)
    polygon_simplify_tolerance_m: float = Field(default=0.08, ge=0)
    concave_simplify_tolerance_m: float = Field(default=0.24, ge=0)
    boundary_close_radius_cells: int = Field(default=1, ge=0, le=3)
    minimum_component_cell_ratio: float = Field(default=0.80, gt=0, le=1)
    minimum_concave_support_ratio: float = Field(default=0.55, gt=0, le=1)
    minimum_concave_support_improvement: float = Field(default=0.08, ge=0, le=1)
    # Pathology guards, not readability limits. They exist to catch a degenerate
    # trace, such as a contour that follows sampling noise around the whole
    # boundary. They are deliberately loose: D-051 originally set them at 1.50
    # and 36 to keep the *drawing* readable, but D-054 solved readability at the
    # renderer by capping drawn dimension labels independently of vertex count.
    # Left tight, they rejected contours with 95% to 97% occupied support and
    # forced a convex fallback that overfilled unscanned space. See D-077.
    maximum_concave_perimeter_ratio: float = Field(default=3.00, ge=1)
    maximum_concave_vertices: int = Field(default=200, ge=4, le=2000)
    detect_openings: bool = True
    opening_wall_band_m: float = Field(default=0.12, gt=0)
    opening_profile_bin_m: float = Field(default=0.05, gt=0)
    opening_solid_height_ratio: float = Field(default=0.45, gt=0, le=1)
    opening_minimum_bin_points: int = Field(default=3, ge=1)
    opening_minimum_width_m: float = Field(default=0.55, gt=0)
    opening_maximum_width_m: float = Field(default=3.00, gt=0)
    opening_flank_bins: int = Field(default=4, ge=1)
    opening_minimum_flank_support: float = Field(default=0.75, gt=0, le=1)
    opening_minimum_wall_solid_ratio: float = Field(default=0.60, gt=0, le=1)
    opening_minimum_floor_support: float = Field(default=0.60, gt=0, le=1)
    opening_pass_through_depth_m: float = Field(default=1.00, gt=0)
    opening_minimum_pass_through_points: int = Field(default=10, ge=1)
    opening_minimum_far_floor_support: float = Field(default=0.50, gt=0, le=1)
    opening_door_sill_maximum_m: float = Field(default=0.20, gt=0)
    opening_door_minimum_height_m: float = Field(default=1.50, gt=0)
    opening_window_sill_minimum_m: float = Field(default=0.30, gt=0)
    opening_probe_distance_m: float = Field(default=0.45, gt=0)
    opening_ceiling_clearance_m: float = Field(default=0.12, gt=0)
    opening_void_inset_m: float = Field(default=0.05, gt=0)
    opening_window_head_margin_m: float = Field(default=0.12, gt=0)
    opening_minimum_void_height_m: float = Field(default=0.40, gt=0)
    maximum_openings_per_wall: int = Field(default=6, ge=0, le=20)
    minimum_boundary_fill_ratio: float = Field(default=0.60, gt=0, le=1)
    floor_rmse_warning_m: float = Field(default=0.03, gt=0)
    floor_inlier_ratio_warning: float = Field(default=0.05, gt=0, le=1)
    maximum_area_warning_m2: float = Field(default=200.0, gt=0)
    maximum_dimension_warning_m: float = Field(default=20.0, gt=0)
    random_seed: int = 17

    @model_validator(mode="after")
    def validate_structure_ranges(self) -> StructureConfig:
        if self.floor_below_camera_max_m <= self.floor_below_camera_min_m:
            raise ValueError("floor camera-height range is reversed")
        if self.ceiling_height_max_m <= self.ceiling_height_min_m:
            raise ValueError("ceiling-height range is reversed")
        if self.opening_maximum_width_m <= self.opening_minimum_width_m:
            raise ValueError("opening width range is reversed")
        if self.opening_window_sill_minimum_m <= self.opening_door_sill_maximum_m:
            raise ValueError("window sill minimum must exceed the door sill maximum")
        if self.opening_wall_band_m >= self.duplicate_wall_offset_tolerance_m:
            # Two planes closer than the duplicate tolerance are merged into one
            # wall. If the profiling band reached that far, two walls that
            # survived de-duplication would capture each other's surface points
            # and each would fill the other's openings.
            raise ValueError(
                "opening_wall_band_m must stay below duplicate_wall_offset_tolerance_m"
            )
        if self.opening_probe_distance_m <= self.opening_wall_band_m:
            raise ValueError(
                "opening_probe_distance_m must reach beyond opening_wall_band_m"
            )
        return self


class PlaneMeasurement(FrozenModel):
    """One normalized plane with fit evidence in world coordinates."""

    kind: Literal["floor", "ceiling", "wall"]
    normal_xyz: tuple[float, float, float]
    offset_m: float
    centroid_xyz_m: tuple[float, float, float]
    inlier_count: int = Field(ge=0)
    inlier_ratio: float = Field(ge=0, le=1)
    rmse_m: float = Field(ge=0)
    span_primary_m: float = Field(ge=0)
    span_secondary_m: float = Field(ge=0)


class FloorCoordinateSystem(FrozenModel):
    """Stable two-dimensional frame embedded in the detected floor plane."""

    origin_xyz_m: tuple[float, float, float]
    x_axis_xyz: tuple[float, float, float]
    y_axis_xyz: tuple[float, float, float]
    up_axis_xyz: tuple[float, float, float]


class FloorPlanMeasurement(FrozenModel):
    """Measured floor boundary in floor-local metres with selection evidence."""

    vertices_xy_m: tuple[tuple[float, float], ...]
    edge_lengths_m: tuple[float, ...]
    area_m2: float = Field(gt=0)
    perimeter_m: float = Field(gt=0)
    length_m: float = Field(gt=0)
    width_m: float = Field(gt=0)
    principal_angle_deg: float
    supporting_cell_count: int = Field(gt=0)
    occupied_cell_area_m2: float = Field(gt=0)
    # Kept for 1.0 contract compatibility. For either method this is the
    # occupied-cell area divided by the selected outline area.
    convex_fill_ratio: float = Field(gt=0, le=1)
    outline_method: Literal["convex_hull", "occupancy_concave"] = "convex_hull"
    connected_component_count: int = Field(default=1, ge=1)
    retained_component_ratio: float = Field(default=1.0, gt=0, le=1)
    discarded_cell_count: int = Field(default=0, ge=0)
    fallback_reason: str | None = None

    @computed_field
    @property
    def boundary_support_ratio(self) -> float:
        """Return occupied support for the selected outline."""
        return self.convex_fill_ratio


class WallSegment(FrozenModel):
    """One finite wall run with a deterministic identifier in floor-local metres.

    The identifier is stable for a given capture and configuration. It is not a
    cross-capture physical identity, so a benchmark manifest must adopt these
    identifiers before named-wall gates can be scored.
    """

    wall_id: str = Field(min_length=1)
    plane_index: int = Field(ge=0)
    start_xy_m: tuple[float, float]
    end_xy_m: tuple[float, float]
    normal_xy: tuple[float, float]
    length_m: float = Field(gt=0)
    height_m: float = Field(gt=0)
    #: True when the observed top of the wall is bounded by scan coverage rather
    #: than by a detected ceiling. Thresholds expressed as a fraction of the wall
    #: height are then relative to what was seen, not to the real wall.
    height_is_coverage_limited: bool = False
    inlier_count: int = Field(ge=0)
    solid_bin_ratio: float = Field(ge=0, le=1)
    rmse_m: float = Field(ge=0)


class OpeningEvidence(FrozenModel):
    """Why one opening was accepted, with the numbers behind the decision."""

    profile_bin_count: int = Field(gt=0)
    gap_bin_count: int = Field(gt=0)
    bin_size_m: float = Field(gt=0)
    left_flank_support: float = Field(ge=0, le=1)
    right_flank_support: float = Field(ge=0, le=1)
    interior_floor_support: float = Field(ge=0, le=1)
    void_point_count: int = Field(ge=0)
    wall_height_m: float = Field(gt=0)
    sill_height_m: float | None = Field(default=None, ge=0)
    head_height_m: float | None = Field(default=None, ge=0)
    # An unobserved bin is not a void. These fields record the positive evidence
    # that space exists behind the opening, which is what separates a real
    # aperture from a patch of wall that simply returned nothing.
    pass_through_point_count: int = Field(default=0, ge=0)
    far_floor_support: float = Field(default=0.0, ge=0, le=1)
    unobserved_bin_ratio: float = Field(default=0.0, ge=0, le=1)
    #: When true, the wall's observed height was too low for a door-height void
    #: to be reachable, so a full-height void cannot classify as `door_like`.
    wall_height_is_coverage_limited: bool = False


class Opening(FrozenModel):
    """One conservatively supported door, window, or open wall transition.

    `width_m` is the measured span along the wall. Classification is deliberately
    hedged: `unclassified_gap` means the void is supported but its semantics are
    not. `other_side` stays `unknown` unless a second independently supported
    floor region shares the opening.
    """

    opening_id: str = Field(min_length=1)
    wall_id: str = Field(min_length=1)
    classification: Literal["door_like", "window_like", "unclassified_gap"]
    confidence: Literal["high", "medium", "low"]
    width_m: float = Field(gt=0)
    height_m: float | None = Field(default=None, gt=0)
    centre_xy_m: tuple[float, float]
    start_xy_m: tuple[float, float]
    end_xy_m: tuple[float, float]
    # `observed_space` means scanned floor was found on the far side of this
    # wall through this opening. It deliberately does not name a room: an
    # occupancy fragment is scan evidence, not a semantic room, and identifiers
    # derived per wall would not be comparable between openings.
    other_side: Literal["unknown", "observed_space"] = "unknown"
    far_side_area_m2: float | None = Field(default=None, gt=0)
    evidence: OpeningEvidence

    @model_validator(mode="after")
    def validate_far_side_fields(self) -> Opening:
        if self.other_side == "observed_space" and self.far_side_area_m2 is None:
            raise ValueError("observed far-side space must report its measured area")
        if self.other_side == "unknown" and self.far_side_area_m2 is not None:
            raise ValueError("an unknown other side cannot report a far-side area")
        return self


class RoomAdjacency(FrozenModel):
    """One opening joining the scanned space on both sides of a single wall.

    This is measured adjacency, not a property-wide room graph. It states that
    this wall separates two substantially scanned floor areas and that this
    opening connects them, with the area on each side reported so a reader can
    judge the claim. No room identity is asserted, because none is supported.
    """

    opening_id: str = Field(min_length=1)
    wall_id: str = Field(min_length=1)
    near_side_area_m2: float = Field(gt=0)
    far_side_area_m2: float = Field(gt=0)
    probe_agreement: int = Field(gt=0)


class OpeningRejection(FrozenModel):
    """One rejected candidate, kept so silence is never mistaken for absence."""

    wall_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    width_m: float | None = Field(default=None, gt=0)


class OpeningAnalysis(FrozenModel):
    """Wall identity, openings, and adjacency evidence for one capture.

    `status` is `unavailable` when the capture cannot support the analysis at
    all. An `available` analysis with no openings is a real negative result.
    """

    status: Literal["available", "unavailable"]
    walls: tuple[WallSegment, ...] = ()
    openings: tuple[Opening, ...] = ()
    adjacency: tuple[RoomAdjacency, ...] = ()
    rejections: tuple[OpeningRejection, ...] = ()
    candidate_count: int = Field(default=0, ge=0)
    unavailable_reason: str | None = None

    @model_validator(mode="after")
    def validate_analysis(self) -> OpeningAnalysis:
        if self.status == "unavailable":
            if not self.unavailable_reason:
                raise ValueError("an unavailable analysis must give a reason")
            if self.openings or self.adjacency:
                raise ValueError("an unavailable analysis cannot publish openings")
            return self
        if self.unavailable_reason is not None:
            raise ValueError("an available analysis cannot carry an unavailable reason")
        wall_ids = {wall.wall_id for wall in self.walls}
        if len(wall_ids) != len(self.walls):
            raise ValueError("wall identifiers must be unique")
        opening_ids = {opening.opening_id for opening in self.openings}
        if len(opening_ids) != len(self.openings):
            raise ValueError("opening identifiers must be unique")
        for opening in self.openings:
            if opening.wall_id not in wall_ids:
                raise ValueError(
                    f"opening {opening.opening_id} references unknown wall "
                    f"{opening.wall_id}"
                )
        for link in self.adjacency:
            if link.opening_id not in opening_ids:
                raise ValueError(
                    f"adjacency references unknown opening {link.opening_id}"
                )
        return self


class StructureSummary(FrozenModel):
    """Machine-readable structural geometry and measurement result."""

    schema_version: Literal["1.0.0", "1.1.0", "1.2.0", "1.3.0", "1.4.0"] = "1.4.0"
    status: Literal["ok", "ok_with_warnings"]
    units: Literal["metre"] = "metre"
    source: str
    config: StructureConfig
    floor: PlaneMeasurement
    ceiling: PlaneMeasurement | None = None
    walls: tuple[PlaneMeasurement, ...] = ()
    floor_coordinates: FloorCoordinateSystem
    floor_plan: FloorPlanMeasurement
    openings: OpeningAnalysis | None = None
    ceiling_height_m: float | None = Field(default=None, gt=0)
    elapsed_seconds: float = Field(ge=0)
    warnings: tuple[str, ...] = ()
    artifacts: dict[str, str] = Field(default_factory=dict)


class CapabilityStatus(StrEnum):
    """Truthful implementation/evaluation status for a project capability."""

    SUPPORTED = "supported"
    SUPPORTED_WITH_LIMITATIONS = "supported_with_limitations"
    NOT_IMPLEMENTED = "not_implemented"
    NOT_EVALUATED = "not_evaluated"


class IntervalConfig(FrozenModel):
    """Settings for resampling-based measurement intervals."""

    enabled: bool = True
    resamples: int = Field(default=64, ge=8, le=2000)
    confidence_level: float = Field(default=0.95, gt=0, lt=1)
    random_seed: int = 29


class MeasurementInterval(FrozenModel):
    """A resampling interval around one published measurement.

    `kind` is `precision` and never `accuracy`. The interval says how far the
    measurement moves when the observed points are resampled, which is a
    statement about the stability of the estimator on this capture. It is not a
    statement about distance from the real room: no ground truth was supplied,
    and a perfectly precise measurement can be biased. A percentile interval is
    also not guaranteed to contain the point estimate, so that is not asserted.
    """

    metric: str = Field(min_length=1)
    target_id: str | None = None
    unit: str = Field(min_length=1)
    value: float
    low: float
    high: float
    confidence_level: float = Field(gt=0, lt=1)
    resamples: int = Field(ge=2)
    kind: Literal["precision"] = "precision"
    method: Literal["nonparametric_bootstrap"] = "nonparametric_bootstrap"

    @model_validator(mode="after")
    def validate_bounds(self) -> MeasurementInterval:
        if self.low > self.high:
            raise ValueError("interval lower bound exceeds upper bound")
        return self

    @computed_field
    @property
    def half_width(self) -> float:
        """Half the interval width, for quick reading alongside the value."""
        return (self.high - self.low) / 2


class DriftConfig(FrozenModel):
    """Bounds and acceptance thresholds for plane-anchored drift correction.

    Correction is disabled by default. A lower closure proxy is not proof of
    better geometry, so a correction is kept only when the broader structural
    evidence improves and nothing important regresses.
    """

    enabled: bool = False
    floor_band_m: float = Field(default=0.12, gt=0)
    minimum_frame_floor_points: int = Field(default=40, ge=3)
    minimum_corrected_frames: int = Field(default=8, ge=2)
    smoothing_window_frames: int = Field(default=9, ge=1)
    maximum_offset_m: float = Field(default=0.10, gt=0)
    minimum_rmse_improvement: float = Field(default=0.05, gt=0, le=1)
    maximum_wall_rmse_regression: float = Field(default=0.05, ge=0, le=1)
    maximum_support_regression: float = Field(default=0.02, ge=0, le=1)
    # A residual computed over a band-limited inlier subset falls when inliers
    # leave the subset, so a correction can lower it without improving anything.
    # These three fields exist to make that impossible: the primary metric is a
    # fixed quantile of every point, and losing points or inlier support is a
    # hard rejection regardless of what the residual does.
    residual_quantile: float = Field(default=0.30, gt=0, le=1)
    maximum_point_loss_ratio: float = Field(default=0.005, ge=0, le=1)
    maximum_inlier_ratio_regression: float = Field(default=0.002, ge=0, le=1)


class DriftVariant(FrozenModel):
    """Comparable structural evidence from one arm of the drift ablation."""

    label: Literal["recorded_poses", "plane_anchored_correction"]
    output_point_count: int = Field(ge=0)
    floor_rmse_m: float = Field(ge=0)
    #: RMS distance over a fixed quantile of *every* point, so it cannot be
    #: lowered by shedding points from a band-limited inlier subset.
    floor_trimmed_rmse_m: float | None = Field(default=None, ge=0)
    floor_inlier_ratio: float = Field(ge=0, le=1)
    mean_wall_rmse_m: float | None = Field(default=None, ge=0)
    wall_count: int = Field(ge=0)
    floor_area_m2: float = Field(gt=0)
    perimeter_m: float = Field(gt=0)
    length_m: float = Field(gt=0)
    width_m: float = Field(gt=0)
    boundary_support_ratio: float = Field(gt=0, le=1)
    outline_method: Literal["convex_hull", "occupancy_concave"]
    ceiling_height_m: float | None = Field(default=None, gt=0)
    opening_count: int = Field(ge=0)


class DriftCorrectionEvidence(FrozenModel):
    """Size and shape of the correction that was estimated."""

    measured_frame_count: int = Field(ge=0)
    corrected_frame_count: int = Field(ge=0)
    clamped_frame_count: int = Field(ge=0)
    maximum_absolute_offset_m: float = Field(ge=0)
    mean_absolute_offset_m: float = Field(ge=0)
    residual_trend_m: float
    raw_residual_span_m: float = Field(ge=0)


class DriftAblation(FrozenModel):
    """Machine-readable drift-correction-on/off comparison for one capture."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    product: Literal["cozmo-scan-drift-ablation"] = "cozmo-scan-drift-ablation"
    units: Literal["metre"] = "metre"
    source_name: str
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: Literal[
        "correction_accepted", "correction_rejected", "correction_unavailable"
    ]
    decision_reason: str = Field(min_length=1)
    selected_variant: Literal["recorded_poses", "plane_anchored_correction"]
    drift: DriftConfig
    variants: tuple[DriftVariant, ...]
    evidence: DriftCorrectionEvidence | None = None
    elapsed_seconds: float = Field(ge=0)
    warnings: tuple[str, ...] = ()
    artifacts: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_ablation(self) -> DriftAblation:
        labels = [variant.label for variant in self.variants]
        if "recorded_poses" not in labels:
            raise ValueError("the ablation must always include the recorded-pose control")
        if len(labels) != len(set(labels)):
            raise ValueError("each ablation arm may appear only once")
        if self.selected_variant not in labels:
            raise ValueError("the selected variant must be present in the ablation")
        if self.decision == "correction_accepted":
            if self.selected_variant != "plane_anchored_correction":
                raise ValueError("an accepted correction must be the selected variant")
        elif self.selected_variant != "recorded_poses":
            raise ValueError("without an accepted correction the control must be selected")
        if self.decision == "correction_unavailable" and self.evidence is not None:
            raise ValueError("an unavailable correction cannot publish correction evidence")
        return self


class PipelineConfig(FrozenModel):
    """Complete effective configuration for one final product run."""

    reconstruction: ReconstructionConfig
    structure: StructureConfig = Field(default_factory=StructureConfig)
    intervals: IntervalConfig = Field(default_factory=IntervalConfig)
    # Drift settings are deliberately absent. `run` and `batch` publish the
    # recorded-pose control, so carrying drift thresholds here would advertise
    # settings that had no effect on any number in the same file. The ablation
    # publishes its own configuration in `drift-ablation.json`.


class InputProvenance(FrozenModel):
    """Stable identity and inventory of the capture supplied to the pipeline."""

    name: str
    source_kind: Literal["zip", "directory"]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    hash_kind: Literal["file_bytes", "canonical_directory"]
    byte_count: int = Field(ge=0)
    capture_format: Literal["stray_scanner"] = "stray_scanner"
    inventory: CaptureInventory


class SoftwareProvenance(FrozenModel):
    """Runtime versions needed to reproduce and audit a result."""

    package_name: Literal["cozmo-scan"] = "cozmo-scan"
    package_version: str
    python_version: str
    numpy_version: str
    pillow_version: str
    pydantic_version: str


class PipelineTimings(FrozenModel):
    """Observed wall-clock durations; geometry remains deterministic."""

    reconstruction_seconds: float = Field(ge=0)
    structure_seconds: float = Field(ge=0)
    total_seconds: float = Field(ge=0)


class QualityMetrics(FrozenModel):
    """Compact evidence used to interpret one room measurement."""

    valid_sampled_depth_ratio: float = Field(ge=0, le=1)
    voxel_retention_ratio: float = Field(ge=0, le=1)
    floor_inlier_ratio: float = Field(ge=0, le=1)
    floor_rmse_m: float = Field(ge=0)
    floor_world_up_alignment: float = Field(ge=0, le=1)
    detected_wall_count: int = Field(ge=0)
    ceiling_available: bool
    boundary_fill_ratio: float = Field(gt=0, le=1)
    measurement_confidence: Literal["good", "caution"]
    closure_proxy_m: float | None = Field(default=None, ge=0)
    closure_proxy_label: Literal["start_to_end_distance_not_certified_drift"] = (
        "start_to_end_distance_not_certified_drift"
    )


class CapabilityAssessment(FrozenModel):
    """One project capability with an explicit evidence-based status."""

    capability: str
    status: CapabilityStatus
    explanation: str


class ArtifactRecord(FrozenModel):
    """One file in the final project bundle."""

    key: str
    filename: str
    media_type: str
    description: str


class ArtifactManifest(FrozenModel):
    """Expected artifacts written together by the final run command."""

    artifacts: tuple[ArtifactRecord, ...]


class RoomResult(FrozenModel):
    """Final room geometry, measurements, and optional height."""

    floor: PlaneMeasurement
    ceiling: PlaneMeasurement | None = None
    walls: tuple[PlaneMeasurement, ...] = ()
    floor_coordinates: FloorCoordinateSystem
    floor_plan: FloorPlanMeasurement
    openings: OpeningAnalysis | None = None
    ceiling_height_m: float | None = Field(default=None, gt=0)


class RunResult(FrozenModel):
    """Versioned product result for one capture."""

    schema_version: Literal["1.0.0", "1.1.0", "1.2.0", "1.3.0", "1.4.0"] = "1.4.0"
    product: Literal["cozmo-scan"] = "cozmo-scan"
    status: Literal["ok", "ok_with_warnings"]
    units: Literal["metre"] = "metre"
    input: InputProvenance
    config: PipelineConfig
    reconstruction: ReconstructionStatistics
    room: RoomResult
    quality: QualityMetrics
    timings: PipelineTimings
    software: SoftwareProvenance
    capabilities: tuple[CapabilityAssessment, ...]
    intervals: tuple[MeasurementInterval, ...] = ()
    warnings: tuple[str, ...] = ()
    artifacts: ArtifactManifest


class BatchItemResult(FrozenModel):
    """Compact comparable outcome for one capture in a batch."""

    input_name: str
    status: Literal["succeeded", "failed"]
    output_directory: str
    input_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    selected_frame_count: int | None = Field(default=None, ge=0)
    output_point_count: int | None = Field(default=None, ge=0)
    floor_area_m2: float | None = Field(default=None, gt=0)
    area_is_provisional: bool | None = None
    outline_method: Literal["convex_hull", "occupancy_concave"] | None = None
    length_m: float | None = Field(default=None, gt=0)
    width_m: float | None = Field(default=None, gt=0)
    perimeter_m: float | None = Field(default=None, gt=0)
    floor_inlier_ratio: float | None = Field(default=None, ge=0, le=1)
    floor_rmse_m: float | None = Field(default=None, ge=0)
    boundary_fill_ratio: float | None = Field(default=None, gt=0, le=1)
    detected_wall_count: int | None = Field(default=None, ge=0)
    identified_wall_count: int | None = Field(default=None, ge=0)
    opening_count: int | None = Field(default=None, ge=0)
    opening_status: Literal["available", "unavailable"] | None = None
    ceiling_height_m: float | None = Field(default=None, gt=0)
    measurement_confidence: Literal["good", "caution"] | None = None
    elapsed_seconds: float | None = Field(default=None, ge=0)
    warnings: tuple[str, ...] = ()
    error: str | None = None

    @model_validator(mode="after")
    def validate_outcome_fields(self) -> BatchItemResult:
        if self.status == "failed":
            if not self.error:
                raise ValueError("failed batch item must include an error")
            return self
        required = {
            "input_sha256": self.input_sha256,
            "selected_frame_count": self.selected_frame_count,
            "output_point_count": self.output_point_count,
            "floor_area_m2": self.floor_area_m2,
            "area_is_provisional": self.area_is_provisional,
            "length_m": self.length_m,
            "width_m": self.width_m,
            "perimeter_m": self.perimeter_m,
            "floor_inlier_ratio": self.floor_inlier_ratio,
            "floor_rmse_m": self.floor_rmse_m,
            "boundary_fill_ratio": self.boundary_fill_ratio,
            "detected_wall_count": self.detected_wall_count,
            "measurement_confidence": self.measurement_confidence,
            "elapsed_seconds": self.elapsed_seconds,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise ValueError(
                "successful batch item is missing: " + ", ".join(missing)
            )
        if self.error is not None:
            raise ValueError("successful batch item cannot include an error")
        return self


class BatchSummary(FrozenModel):
    """Versioned cross-capture outcome from one sequential batch run."""

    schema_version: Literal["1.0.0", "1.1.0", "1.2.0", "1.3.0", "1.4.0"] = "1.4.0"
    product: Literal["cozmo-scan-batch"] = "cozmo-scan-batch"
    status: Literal["ok", "partial", "failed"]
    input_name: str
    config: PipelineConfig
    total_capture_count: int = Field(gt=0)
    succeeded_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    elapsed_seconds: float = Field(ge=0)
    items: tuple[BatchItemResult, ...]
    artifacts: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_batch_counts(self) -> BatchSummary:
        if self.succeeded_count + self.failed_count != self.total_capture_count:
            raise ValueError("batch success/failure counts do not match total")
        if len(self.items) != self.total_capture_count:
            raise ValueError("batch item count does not match total")
        actual_succeeded = sum(item.status == "succeeded" for item in self.items)
        actual_failed = len(self.items) - actual_succeeded
        if (
            actual_succeeded != self.succeeded_count
            or actual_failed != self.failed_count
        ):
            raise ValueError("batch counts do not agree with item statuses")
        expected_status = (
            "failed"
            if self.succeeded_count == 0
            else "partial"
            if self.failed_count
            else "ok"
        )
        if self.status != expected_status:
            raise ValueError("batch status does not agree with success/failure counts")
        return self
