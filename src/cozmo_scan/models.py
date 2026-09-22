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
    """Reviewer-sized summary of a discovered capture."""

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
    """Machine-readable diagnostic summary for CP03 output."""

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
    """Measured convex floor boundary in floor-local metres."""

    vertices_xy_m: tuple[tuple[float, float], ...]
    edge_lengths_m: tuple[float, ...]
    area_m2: float = Field(gt=0)
    perimeter_m: float = Field(gt=0)
    length_m: float = Field(gt=0)
    width_m: float = Field(gt=0)
    principal_angle_deg: float
    supporting_cell_count: int = Field(gt=0)
    occupied_cell_area_m2: float = Field(gt=0)
    convex_fill_ratio: float = Field(gt=0, le=1)


class StructureSummary(FrozenModel):
    """Machine-readable CP04 structural geometry and measurement result."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["ok", "ok_with_warnings"]
    units: Literal["metre"] = "metre"
    source: str
    config: StructureConfig
    floor: PlaneMeasurement
    ceiling: PlaneMeasurement | None = None
    walls: tuple[PlaneMeasurement, ...] = ()
    floor_coordinates: FloorCoordinateSystem
    floor_plan: FloorPlanMeasurement
    ceiling_height_m: float | None = Field(default=None, gt=0)
    elapsed_seconds: float = Field(ge=0)
    warnings: tuple[str, ...] = ()
    artifacts: dict[str, str] = Field(default_factory=dict)


class CapabilityStatus(StrEnum):
    """Truthful implementation/evaluation status for an assignment capability."""

    SUPPORTED = "supported"
    SUPPORTED_WITH_LIMITATIONS = "supported_with_limitations"
    NOT_IMPLEMENTED = "not_implemented"
    NOT_EVALUATED = "not_evaluated"


class PipelineConfig(FrozenModel):
    """Complete effective configuration for one final product run."""

    reconstruction: ReconstructionConfig
    structure: StructureConfig = Field(default_factory=StructureConfig)


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
    """One assignment capability with an explicit evidence-based status."""

    capability: str
    status: CapabilityStatus
    explanation: str


class ArtifactRecord(FrozenModel):
    """One file in the final reviewer-facing bundle."""

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
    ceiling_height_m: float | None = Field(default=None, gt=0)


class RunResult(FrozenModel):
    """Versioned, reviewer-facing product result for one capture."""

    schema_version: Literal["1.0.0"] = "1.0.0"
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
    warnings: tuple[str, ...] = ()
    artifacts: ArtifactManifest
