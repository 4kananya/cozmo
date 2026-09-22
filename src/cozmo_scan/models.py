"""Validated data models shared by capture ingestion and later pipeline stages."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field


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
