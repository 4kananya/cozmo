"""Known-pose sparse metric reconstruction for photo and video observations.

The implementation uses linear multi-view triangulation. Metric scale comes
only from the supplied camera translations; arbitrary or unitless poses produce
geometry in those same arbitrary units and must not be described as metric.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

MEDIA_RECONSTRUCTION_FILENAME = "media-reconstruction.json"
MEDIA_POINT_CLOUD_FILENAME = "media-reconstruction.ply"


class PhotogrammetryError(ValueError):
    """Raised when known-pose observations cannot support reconstruction."""


def reconstruct_known_pose_manifest(path: str | Path) -> tuple[dict[str, Any], NDArray[np.float64]]:
    """Triangulate named observations from calibrated, metric camera poses."""
    manifest_path = Path(path)
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PhotogrammetryError(f"Cannot read observation manifest {manifest_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise PhotogrammetryError("observation manifest must contain a JSON object")
    intrinsics = _matrix(payload.get("camera_matrix"), (3, 3), "camera_matrix")
    views = payload.get("views")
    if not isinstance(views, list) or len(views) < 2:
        raise PhotogrammetryError("at least two calibrated views are required")
    unit = payload.get("translation_unit")
    if unit != "metre":
        raise PhotogrammetryError(
            'translation_unit must be "metre"; metric output requires metric camera translations'
        )
    projection_by_view: dict[str, NDArray[np.float64]] = {}
    observation_tracks: dict[str, list[tuple[str, NDArray[np.float64]]]] = {}
    for view in views:
        if not isinstance(view, dict) or not isinstance(view.get("view_id"), str):
            raise PhotogrammetryError("every view requires a string view_id")
        view_id = view["view_id"]
        if view_id in projection_by_view:
            raise PhotogrammetryError(f"duplicate view_id: {view_id}")
        world_from_camera = _matrix(
            view.get("world_from_camera"), (4, 4), f"world_from_camera for {view_id}"
        )
        if not np.allclose(world_from_camera[3], [0.0, 0.0, 0.0, 1.0], atol=1e-8):
            raise PhotogrammetryError(f"world_from_camera for {view_id} is not homogeneous")
        try:
            camera_from_world = np.linalg.inv(world_from_camera)
        except np.linalg.LinAlgError as exc:
            raise PhotogrammetryError(f"world_from_camera for {view_id} is singular") from exc
        projection_by_view[view_id] = intrinsics @ camera_from_world[:3, :]
        observations = view.get("observations")
        if not isinstance(observations, dict):
            raise PhotogrammetryError(f"view {view_id} requires an observations object")
        for track_id, pixel in observations.items():
            point = np.asarray(pixel, dtype=np.float64)
            if point.shape != (2,) or not np.isfinite(point).all():
                raise PhotogrammetryError(f"observation {track_id} in {view_id} must be [u, v]")
            observation_tracks.setdefault(str(track_id), []).append((view_id, point))

    maximum_error = float(payload.get("maximum_reprojection_error_px", 3.0))
    if maximum_error <= 0:
        raise PhotogrammetryError("maximum_reprojection_error_px must be positive")
    reconstructed: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    points: list[NDArray[np.float64]] = []
    for track_id in sorted(observation_tracks, key=str.casefold):
        observations = observation_tracks[track_id]
        if len(observations) < 2:
            rejected.append({"track_id": track_id, "reason": "fewer than two observations"})
            continue
        point = triangulate_observations(observations, projection_by_view)
        errors = []
        positive_depth = True
        for view_id, pixel in observations:
            projection = projection_by_view[view_id]
            homogeneous = projection @ np.append(point, 1.0)
            if homogeneous[2] <= 0:
                positive_depth = False
                break
            predicted = homogeneous[:2] / homogeneous[2]
            errors.append(float(np.linalg.norm(predicted - pixel)))
        if not positive_depth:
            rejected.append({"track_id": track_id, "reason": "point is behind at least one camera"})
            continue
        rmse = float(np.sqrt(np.mean(np.square(errors))))
        if rmse > maximum_error:
            rejected.append(
                {"track_id": track_id, "reason": f"reprojection RMSE {rmse:.3f}px exceeds gate"}
            )
            continue
        points.append(point)
        reconstructed.append(
            {
                "track_id": track_id,
                "xyz_m": point.tolist(),
                "observation_count": len(observations),
                "reprojection_rmse_px": rmse,
            }
        )
    if not points:
        raise PhotogrammetryError("no observation track passed triangulation and reprojection gates")
    array = np.asarray(points, dtype=np.float64)
    result = {
        "schema_version": "1.0.0",
        "status": "prototype",
        "method": "known_pose_linear_multiview_triangulation",
        "units": "metre",
        "source_manifest": manifest_path.name,
        "view_count": len(views),
        "track_count": len(observation_tracks),
        "reconstructed_point_count": len(reconstructed),
        "rejected_track_count": len(rejected),
        "points": reconstructed,
        "rejections": rejected,
        "artifacts": {
            "result": MEDIA_RECONSTRUCTION_FILENAME,
            "point_cloud": MEDIA_POINT_CLOUD_FILENAME,
        },
        "limitations": [
            "Feature observations and calibrated world-from-camera poses must be supplied.",
            "The result is sparse triangulation, not dense multi-view stereo.",
            "Metric scale is inherited from camera translations and is not independently verified.",
        ],
    }
    return result, array


def triangulate_observations(
    observations: list[tuple[str, NDArray[np.float64]]],
    projection_by_view: dict[str, NDArray[np.float64]],
) -> NDArray[np.float64]:
    """Triangulate one track with homogeneous DLT across two or more views."""
    rows: list[NDArray[np.float64]] = []
    for view_id, pixel in observations:
        projection = projection_by_view[view_id]
        rows.append(pixel[0] * projection[2] - projection[0])
        rows.append(pixel[1] * projection[2] - projection[1])
    _, _, vt = np.linalg.svd(np.asarray(rows, dtype=np.float64))
    homogeneous = vt[-1]
    if abs(float(homogeneous[3])) < 1e-12:
        raise PhotogrammetryError("triangulated point is at infinity")
    point = homogeneous[:3] / homogeneous[3]
    if not np.isfinite(point).all():
        raise PhotogrammetryError("triangulation produced a non-finite point")
    return point


def write_media_reconstruction(
    result: dict[str, Any],
    points_xyz_m: NDArray[np.float64],
    output_directory: str | Path,
    *,
    overwrite: bool = False,
) -> dict[str, Path]:
    directory = Path(output_directory)
    result_path = directory / MEDIA_RECONSTRUCTION_FILENAME
    ply_path = directory / MEDIA_POINT_CLOUD_FILENAME
    conflicts = [path for path in (result_path, ply_path) if path.exists()]
    if conflicts and not overwrite:
        raise PhotogrammetryError(
            f"Output artifact already exists ({conflicts[0].name}); pass --overwrite to replace it"
        )
    directory.mkdir(parents=True, exist_ok=True)
    result_temp = result_path.with_name(result_path.name + ".tmp")
    ply_temp = ply_path.with_name(ply_path.name + ".tmp")
    try:
        result_temp.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        _write_ascii_ply(ply_temp, points_xyz_m)
        result_temp.replace(result_path)
        ply_temp.replace(ply_path)
    except OSError as exc:
        result_temp.unlink(missing_ok=True)
        ply_temp.unlink(missing_ok=True)
        raise PhotogrammetryError(f"Cannot publish media reconstruction: {exc}") from exc
    return {"result": result_path, "point_cloud": ply_path}


def _matrix(value: Any, shape: tuple[int, int], label: str) -> NDArray[np.float64]:
    try:
        matrix = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise PhotogrammetryError(f"{label} must be a numeric {shape[0]}x{shape[1]} matrix") from exc
    if matrix.shape != shape or not np.isfinite(matrix).all():
        raise PhotogrammetryError(f"{label} must be a finite numeric {shape[0]}x{shape[1]} matrix")
    return matrix


def _write_ascii_ply(path: Path, points: NDArray[np.float64]) -> None:
    lines = [
        "ply",
        "format ascii 1.0",
        f"element vertex {len(points)}",
        "property float x",
        "property float y",
        "property float z",
        "end_header",
    ]
    lines.extend(f"{point[0]:.9g} {point[1]:.9g} {point[2]:.9g}" for point in points)
    path.write_text("\n".join(lines) + "\n", encoding="ascii")
