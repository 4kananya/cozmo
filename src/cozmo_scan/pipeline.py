"""Final single-capture pipeline and versioned result composition."""

from __future__ import annotations

import hashlib
import platform
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import PIL
import pydantic

from cozmo_scan import __version__
from cozmo_scan.dataset import CaptureError, open_capture, validate_capture
from cozmo_scan.floorplan import StructureError, StructureResult, analyze_structure
from cozmo_scan.intervals import build_measurement_intervals
from cozmo_scan.models import (
    ArtifactManifest,
    ArtifactRecord,
    CapabilityAssessment,
    CapabilityStatus,
    FrameSelection,
    IntervalConfig,
    InputProvenance,
    IssueSeverity,
    PipelineConfig,
    PipelineTimings,
    QualityMetrics,
    ReconstructionProfile,
    RoomResult,
    RunResult,
    SoftwareProvenance,
    StructureConfig,
    ValidationResult,
)
from cozmo_scan.reconstruction import (
    ReconstructionError,
    ReconstructionResult,
    get_profile_config,
    reconstruct_capture,
)

RESULT_FILENAME = "result.json"
POINT_CLOUD_FILENAME = "reconstruction.ply"
TOPDOWN_FILENAME = "topdown.png"
TRAJECTORY_FILENAME = "trajectory.png"
FLOORPLAN_SVG_FILENAME = "floorplan.svg"
FLOORPLAN_PNG_FILENAME = "floorplan.png"
REPORT_FILENAME = "report.md"

FINAL_ARTIFACT_RECORDS = (
    ArtifactRecord(
        key="result",
        filename=RESULT_FILENAME,
        media_type="application/json",
        description="Versioned machine-readable result, evidence, and provenance.",
    ),
    ArtifactRecord(
        key="point_cloud",
        filename=POINT_CLOUD_FILENAME,
        media_type="application/octet-stream",
        description="Binary little-endian XYZ point cloud in metres.",
    ),
    ArtifactRecord(
        key="topdown_preview",
        filename=TOPDOWN_FILENAME,
        media_type="image/png",
        description="Top-down point-density preview with camera trajectory.",
    ),
    ArtifactRecord(
        key="trajectory_preview",
        filename=TRAJECTORY_FILENAME,
        media_type="image/png",
        description="Camera path with start/end markers and non-drift closure proxy.",
    ),
    ArtifactRecord(
        key="floorplan_vector",
        filename=FLOORPLAN_SVG_FILENAME,
        media_type="image/svg+xml",
        description="Scalable measured floor-plan drawing with outline-method evidence.",
    ),
    ArtifactRecord(
        key="floorplan_preview",
        filename=FLOORPLAN_PNG_FILENAME,
        media_type="image/png",
        description="Raster floor-plan preview with measurements and quality evidence.",
    ),
    ArtifactRecord(
        key="report",
        filename=REPORT_FILENAME,
        media_type="text/markdown",
        description="Human-readable result, method, coverage, and limitations report.",
    ),
)


#: Resamples used by the `test` profile, whose purpose is a fast smoke run.
TEST_PROFILE_RESAMPLES = 8


class PipelineError(ValueError):
    """Raised when a final product run cannot be completed."""


@dataclass(frozen=True, slots=True)
class CaptureHash:
    """Digest details before they are combined with capture inventory."""

    sha256: str
    hash_kind: str
    byte_count: int


@dataclass(frozen=True, slots=True)
class PipelineExecution:
    """In-memory arrays plus the final serializable result."""

    reconstruction: ReconstructionResult
    structure: StructureResult
    result: RunResult


def get_pipeline_config(
    profile: ReconstructionProfile | str,
    *,
    max_frames: int | None = None,
    frame_selection: FrameSelection | str = FrameSelection.DISTRIBUTED,
    structure: StructureConfig | None = None,
    intervals: IntervalConfig | None = None,
) -> PipelineConfig:
    """Build the complete effective configuration for a final run.

    The `test` profile bounds interval resampling as well as reconstruction. Its
    purpose is a fast smoke run, and a full resample budget would dominate it.
    """
    return PipelineConfig(
        reconstruction=get_profile_config(
            profile,
            max_frames=max_frames,
            frame_selection=frame_selection,
        ),
        structure=structure or StructureConfig(),
        intervals=intervals
        or (
            IntervalConfig(resamples=TEST_PROFILE_RESAMPLES)
            if ReconstructionProfile(profile) is ReconstructionProfile.TEST
            else IntervalConfig()
        ),
    )


def hash_capture_input(path: str | Path) -> CaptureHash:
    """Hash a ZIP byte-for-byte or a directory by canonical member content."""
    capture_path = Path(path)
    if capture_path.is_file():
        digest = hashlib.sha256()
        byte_count = 0
        try:
            with capture_path.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
                    byte_count += len(chunk)
        except OSError as exc:
            raise PipelineError(f"Cannot hash capture input: {capture_path}") from exc
        return CaptureHash(digest.hexdigest(), "file_bytes", byte_count)

    digest = hashlib.sha256()
    byte_count = 0
    try:
        with open_capture(capture_path) as source:
            for member in source.members:
                encoded_name = member.encode("utf-8")
                content = source.read_bytes(member)
                digest.update(len(encoded_name).to_bytes(8, "big"))
                digest.update(encoded_name)
                digest.update(len(content).to_bytes(8, "big"))
                digest.update(content)
                byte_count += len(content)
    except CaptureError as exc:
        raise PipelineError(str(exc)) from exc
    return CaptureHash(digest.hexdigest(), "canonical_directory", byte_count)


def build_run_result(
    *,
    validation: ValidationResult,
    capture_hash: CaptureHash,
    config: PipelineConfig,
    reconstruction: ReconstructionResult,
    structure: StructureResult,
    total_seconds: float,
) -> RunResult:
    """Combine validated stage outputs into the final public contract."""
    inventory = validation.inventory
    if not validation.valid or inventory is None:
        raise PipelineError("A valid capture inventory is required for a final result")
    provenance = InputProvenance(
        name=Path(validation.source).name or inventory.source_name,
        source_kind=inventory.source_kind,
        sha256=capture_hash.sha256,
        hash_kind=capture_hash.hash_kind,
        byte_count=capture_hash.byte_count,
        inventory=inventory,
    )
    room = RoomResult(
        floor=structure.summary.floor,
        ceiling=structure.summary.ceiling,
        walls=structure.summary.walls,
        floor_coordinates=structure.summary.floor_coordinates,
        floor_plan=structure.summary.floor_plan,
        openings=structure.summary.openings,
        ceiling_height_m=structure.summary.ceiling_height_m,
    )
    intervals, interval_warnings = build_measurement_intervals(
        structure.summary,
        projected_floor_xy_m=structure.projected_floor_xy_m,
        floor_heights_m=structure.floor_heights_m,
        ceiling_heights_m=structure.ceiling_heights_m,
        structure=config.structure,
        config=config.intervals,
    )
    warnings = _unique_warnings(
        tuple(
            issue.message
            for issue in validation.issues
            if issue.severity is IssueSeverity.WARNING
        ),
        reconstruction.summary.warnings,
        structure.summary.warnings,
        interval_warnings,
    )
    quality = build_quality_metrics(reconstruction, structure, config, warnings)
    return RunResult(
        status="ok_with_warnings" if warnings else "ok",
        input=provenance,
        config=config,
        reconstruction=reconstruction.summary.statistics,
        room=room,
        quality=quality,
        timings=PipelineTimings(
            reconstruction_seconds=reconstruction.summary.elapsed_seconds,
            structure_seconds=structure.summary.elapsed_seconds,
            total_seconds=total_seconds,
        ),
        software=SoftwareProvenance(
            package_version=__version__,
            python_version=platform.python_version(),
            numpy_version=np.__version__,
            pillow_version=PIL.__version__,
            pydantic_version=pydantic.__version__,
        ),
        capabilities=build_capability_assessments(structure),
        intervals=intervals,
        warnings=warnings,
        artifacts=ArtifactManifest(artifacts=FINAL_ARTIFACT_RECORDS),
    )


def build_quality_metrics(
    reconstruction: ReconstructionResult,
    structure: StructureResult,
    config: PipelineConfig,
    warnings: tuple[str, ...],
) -> QualityMetrics:
    """Calculate bounded ratios and clear measurement-quality indicators."""
    statistics = reconstruction.summary.statistics
    valid_ratio = _safe_ratio(
        statistics.valid_point_count_before_voxel,
        statistics.sampled_pixel_count,
    )
    retention_ratio = _safe_ratio(
        statistics.output_point_count,
        statistics.valid_point_count_before_voxel,
    )
    floor = structure.summary.floor
    floor_normal = np.asarray(floor.normal_xyz, dtype=np.float64)
    alignment = abs(float(floor_normal @ np.asarray([0.0, 1.0, 0.0])))
    boundary_fill = structure.summary.floor_plan.boundary_support_ratio
    caution = bool(warnings) or (
        boundary_fill < config.structure.minimum_boundary_fill_ratio
    )
    return QualityMetrics(
        valid_sampled_depth_ratio=valid_ratio,
        voxel_retention_ratio=retention_ratio,
        floor_inlier_ratio=floor.inlier_ratio,
        floor_rmse_m=floor.rmse_m,
        floor_world_up_alignment=min(1.0, alignment),
        detected_wall_count=len(structure.summary.walls),
        ceiling_available=structure.summary.ceiling is not None,
        boundary_fill_ratio=boundary_fill,
        measurement_confidence="caution" if caution else "good",
        closure_proxy_m=statistics.closure_proxy_m,
    )


def build_capability_assessments(
    structure: StructureResult,
) -> tuple[CapabilityAssessment, ...]:
    """State project capability coverage without inventing unsupported results."""
    openings = structure.summary.openings
    if openings is None or openings.status == "unavailable":
        reason = (
            openings.unavailable_reason
            if openings is not None and openings.unavailable_reason
            else "No opening analysis was produced for this capture."
        )
        wall_identity_status = CapabilityStatus.NOT_EVALUATED
        wall_identity_explanation = reason
        opening_status = CapabilityStatus.NOT_EVALUATED
        opening_explanation = reason
    else:
        wall_identity_status = CapabilityStatus.SUPPORTED_WITH_LIMITATIONS
        wall_identity_explanation = (
            f"{len(openings.walls)} wall segment(s) carry deterministic identifiers that "
            "are stable for this capture and configuration, not across captures."
        )
        opening_status = CapabilityStatus.SUPPORTED_WITH_LIMITATIONS
        opening_explanation = (
            f"{len(openings.openings)} opening(s) passed the evidence gates out of "
            f"{openings.candidate_count} candidate(s). Widths are geometric estimates; "
            "no opening ground truth was supplied, so accuracy is unevaluated."
        )
    if openings is not None and openings.adjacency:
        adjacency_status = CapabilityStatus.SUPPORTED_WITH_LIMITATIONS
        adjacency_explanation = (
            f"{len(openings.adjacency)} opening(s) join two independently supported "
            "floor regions. Regions are scan evidence, not named rooms."
        )
    else:
        adjacency_status = CapabilityStatus.NOT_EVALUATED
        adjacency_explanation = (
            "No opening was observed to join two independently supported floor "
            "regions, so no adjacency is claimed."
        )
    ceiling_explanation = (
        "A ceiling plane passed support checks for this capture."
        if structure.summary.ceiling is not None
        else (
            "Implemented, but this capture did not contain a ceiling plane "
            "that passed support checks."
        )
    )
    return (
        _capability(
            "lidar_capture_ingestion",
            CapabilityStatus.SUPPORTED,
            "Validated Stray Scanner ZIP and directory inputs.",
        ),
        _capability(
            "metric_reconstruction",
            CapabilityStatus.SUPPORTED,
            "Uses recorded depth, confidence, intrinsics, and camera poses.",
        ),
        _capability(
            "measured_floor_plan",
            CapabilityStatus.SUPPORTED_WITH_LIMITATIONS,
            (
                "Produces a component-aware occupancy contour when it passes support "
                "and topology checks, with an explicit convex safety fallback."
            ),
        ),
        _capability(
            "ceiling_measurement",
            CapabilityStatus.SUPPORTED_WITH_LIMITATIONS,
            ceiling_explanation,
        ),
        _capability(
            "wall_identity",
            wall_identity_status,
            wall_identity_explanation,
        ),
        _capability(
            "opening_detection",
            opening_status,
            opening_explanation,
        ),
        _capability(
            "room_adjacency",
            adjacency_status,
            adjacency_explanation,
        ),
        _capability(
            "independent_sample_processing",
            CapabilityStatus.SUPPORTED,
            "Processes one independent capture per run.",
        ),
        _capability(
            "multi_room_stitching",
            CapabilityStatus.NOT_EVALUATED,
            "Supplied captures are independent and provide no stitching ground truth.",
        ),
        _capability(
            "photo_only_reconstruction",
            CapabilityStatus.NOT_IMPLEMENTED,
            "No supplied photo-only benchmark supports a credible implementation.",
        ),
        _capability(
            "video_only_reconstruction",
            CapabilityStatus.NOT_IMPLEMENTED,
            "RGB is inventoried, but the reliable baseline uses LiDAR depth and poses.",
        ),
        _capability(
            "damage_detection",
            CapabilityStatus.NOT_IMPLEMENTED,
            "The supplied data has no damage annotations or evaluation ground truth.",
        ),
        _capability(
            "concealed_condition_prediction",
            CapabilityStatus.NOT_IMPLEMENTED,
            "Concealed conditions cannot be established from visible geometry.",
        ),
        _capability(
            "repair_scope_generation",
            CapabilityStatus.NOT_IMPLEMENTED,
            "Repair scope depends on unavailable validated damage classification.",
        ),
        _capability(
            "ground_truth_accuracy",
            CapabilityStatus.NOT_EVALUATED,
            "No reference dimensions or survey ground truth were supplied.",
        ),
        _capability(
            "live_mobile_processing",
            CapabilityStatus.NOT_IMPLEMENTED,
            "This baseline is a bounded offline command-line pipeline.",
        ),
    )


def run_pipeline(path: str | Path, config: PipelineConfig) -> PipelineExecution:
    """Run validation, provenance, reconstruction, and structural measurement."""
    started = time.perf_counter()
    validation = validate_capture(path)
    if not validation.valid:
        errors = [
            issue.message
            for issue in validation.issues
            if issue.severity is IssueSeverity.ERROR
        ]
        raise PipelineError("; ".join(errors) or "Capture validation failed")
    try:
        capture_hash = hash_capture_input(path)
        reconstruction = reconstruct_capture(path, config.reconstruction)
        structure = analyze_structure(reconstruction, config.structure)
    except (CaptureError, ReconstructionError, StructureError) as exc:
        raise PipelineError(str(exc)) from exc
    result = build_run_result(
        validation=validation,
        capture_hash=capture_hash,
        config=config,
        reconstruction=reconstruction,
        structure=structure,
        total_seconds=time.perf_counter() - started,
    )
    return PipelineExecution(reconstruction, structure, result)


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return min(1.0, max(0.0, float(numerator / denominator)))


def _unique_warnings(*groups: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(warning for group in groups for warning in group))


def _capability(
    capability: str,
    status: CapabilityStatus,
    explanation: str,
) -> CapabilityAssessment:
    return CapabilityAssessment(
        capability=capability,
        status=status,
        explanation=explanation,
    )
