"""Synthetic final-pipeline objects shared by CP05 tests."""

from __future__ import annotations

from cozmo_scan.floorplan import analyze_structure
from cozmo_scan.models import (
    CaptureInventory,
    IntervalConfig,
    PipelineConfig,
    ValidationResult,
)
from cozmo_scan.pipeline import (
    CaptureHash,
    PipelineExecution,
    build_run_result,
)
from tests.structure_factory import make_synthetic_room


def make_validation() -> ValidationResult:
    inventory = CaptureInventory(
        source_name="synthetic-room.zip",
        source_kind="zip",
        capture_root="capture123",
        camera_matrix_present=True,
        odometry_present=True,
        imu_present=True,
        rgb_video_present=True,
        rgb_video_bytes=22,
        depth_frame_count=3,
        confidence_frame_count=3,
        odometry_record_count=3,
        matched_frame_count=3,
        missing_depth_count=0,
        missing_confidence_count=0,
        missing_odometry_count=0,
        imu_record_count=2,
        first_timestamp=10.0,
        last_timestamp=12.0,
        duration_seconds=2.0,
        image_pairs_inspected=3,
        depth_image_size=(4, 3),
        confidence_image_size=(4, 3),
        depth_modes=("I;16",),
        confidence_modes=("L",),
    )
    return ValidationResult(
        source="synthetic-room.zip",
        valid=True,
        inventory=inventory,
    )


def make_pipeline_execution(*, include_ceiling: bool = True) -> PipelineExecution:
    reconstruction = make_synthetic_room(include_ceiling=include_ceiling)
    structure = analyze_structure(reconstruction)
    config = PipelineConfig(
        reconstruction=reconstruction.summary.config,
        structure=structure.summary.config,
        # Intervals are still exercised, but a full resample budget would
        # dominate the suite: the outline estimator is re-run once per resample.
        intervals=IntervalConfig(resamples=8),
    )
    result = build_run_result(
        validation=make_validation(),
        capture_hash=CaptureHash("a" * 64, "file_bytes", 12345),
        config=config,
        reconstruction=reconstruction,
        structure=structure,
        total_seconds=0.5,
    )
    return PipelineExecution(reconstruction, structure, result)
