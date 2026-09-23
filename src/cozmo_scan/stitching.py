"""Prototype cross-capture wall matching and manually anchored room stitching.

The prototype deliberately requires corresponding anchor points. ICP without a
reasonable initial alignment is easy to make look plausible while joining the
wrong walls; manual doorway endpoints give the transform an auditable origin.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray


class StitchingError(ValueError):
    """Raised when room artifacts cannot support an anchored registration."""


def stitch_result_files(
    source_result: str | Path,
    target_result: str | Path,
    anchors_file: str | Path,
) -> dict[str, Any]:
    """Align one result artifact to another and return prototype evidence."""
    source = _load_json(Path(source_result))
    target = _load_json(Path(target_result))
    anchors = _load_json(Path(anchors_file))
    source_anchors = _points(anchors.get("source"), "source anchors")
    target_anchors = _points(anchors.get("target"), "target anchors")
    if len(source_anchors) != len(target_anchors) or len(source_anchors) < 2:
        raise StitchingError("anchors must contain equal source/target lists with at least two points")

    rotation, translation, residuals = estimate_rigid_transform(source_anchors, target_anchors)
    source_walls = _walls(source)
    target_walls = _walls(target)
    transformed_walls = tuple(_transform_wall(wall, rotation, translation) for wall in source_walls)
    matches = match_walls(transformed_walls, target_walls)

    return {
        "schema_version": "1.0.0",
        "status": "prototype",
        "method": "manual_anchor_rigid_2d_with_wall_consistency",
        "source_result": Path(source_result).name,
        "target_result": Path(target_result).name,
        "transform_source_to_target": {
            "rotation_radians": float(math.atan2(rotation[1, 0], rotation[0, 0])),
            "rotation_matrix": rotation.tolist(),
            "translation_m": translation.tolist(),
            "anchor_rmse_m": float(np.sqrt(np.mean(residuals * residuals))),
            "anchor_max_residual_m": float(residuals.max()),
        },
        "wall_matches": matches,
        "transformed_source_walls": transformed_walls,
        "source_floor_plan_xy_m": _transform_floor_plan(source, rotation, translation),
        "target_floor_plan_xy_m": _floor_vertices(target),
        "limitations": [
            "Registration depends on user-supplied corresponding anchors.",
            "Wall matches are geometric candidates, not established physical identities.",
            "No automatic loop closure or non-rigid correction is performed.",
        ],
    }


def estimate_rigid_transform(
    source_xy: NDArray[np.float64], target_xy: NDArray[np.float64]
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """Return the least-squares 2D rigid transform and per-anchor residuals."""
    source = np.asarray(source_xy, dtype=np.float64)
    target = np.asarray(target_xy, dtype=np.float64)
    if source.shape != target.shape or source.ndim != 2 or source.shape[1] != 2:
        raise StitchingError("source and target anchors must have shape (N, 2)")
    if len(source) < 2:
        raise StitchingError("at least two anchor correspondences are required")
    source_centroid = source.mean(axis=0)
    target_centroid = target.mean(axis=0)
    source_centered = source - source_centroid
    target_centered = target - target_centroid
    if np.linalg.matrix_rank(source_centered) < 1:
        raise StitchingError("source anchors must not all be identical")
    u, _, vt = np.linalg.svd(source_centered.T @ target_centered)
    rotation = vt.T @ u.T
    if np.linalg.det(rotation) < 0:
        vt[-1, :] *= -1
        rotation = vt.T @ u.T
    translation = target_centroid - source_centroid @ rotation.T
    transformed = source @ rotation.T + translation
    residuals = np.linalg.norm(transformed - target, axis=1)
    return rotation, translation, residuals


def match_walls(
    source_walls: tuple[dict[str, Any], ...],
    target_walls: tuple[dict[str, Any], ...],
    *,
    maximum_angle_degrees: float = 15.0,
    maximum_midpoint_distance_m: float = 1.0,
    maximum_relative_length_error: float = 0.35,
) -> list[dict[str, Any]]:
    """Greedily select unique wall pairs using orientation, length, and placement."""
    candidates: list[tuple[float, int, int, float, float, float]] = []
    for source_index, source in enumerate(source_walls):
        for target_index, target in enumerate(target_walls):
            angle = _undirected_angle_degrees(source, target)
            midpoint = float(np.linalg.norm(_midpoint(source) - _midpoint(target)))
            length_error = abs(float(source["length_m"]) - float(target["length_m"])) / max(
                float(source["length_m"]), float(target["length_m"])
            )
            if (
                angle <= maximum_angle_degrees
                and midpoint <= maximum_midpoint_distance_m
                and length_error <= maximum_relative_length_error
            ):
                score = (
                    angle / maximum_angle_degrees
                    + midpoint / maximum_midpoint_distance_m
                    + length_error / maximum_relative_length_error
                ) / 3.0
                candidates.append((score, source_index, target_index, angle, midpoint, length_error))
    used_source: set[int] = set()
    used_target: set[int] = set()
    matches: list[dict[str, Any]] = []
    for score, source_index, target_index, angle, midpoint, length_error in sorted(candidates):
        if source_index in used_source or target_index in used_target:
            continue
        used_source.add(source_index)
        used_target.add(target_index)
        matches.append(
            {
                "source_wall_id": source_walls[source_index]["wall_id"],
                "target_wall_id": target_walls[target_index]["wall_id"],
                "score": score,
                "orientation_error_degrees": angle,
                "midpoint_distance_m": midpoint,
                "relative_length_error": length_error,
            }
        )
    return matches


def write_stitching_result(result: dict[str, Any], path: str | Path, *, overwrite: bool = False) -> Path:
    destination = Path(path)
    if destination.exists() and not overwrite:
        raise StitchingError(f"Output already exists: {destination}; pass --overwrite to replace it")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    temporary.replace(destination)
    return destination


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StitchingError(f"Cannot read JSON artifact {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise StitchingError(f"JSON artifact must contain an object: {path}")
    return value


def _points(value: Any, label: str) -> NDArray[np.float64]:
    try:
        points = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise StitchingError(f"{label} must be numeric [x, y] pairs") from exc
    if points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all():
        raise StitchingError(f"{label} must be finite numeric [x, y] pairs")
    return points


def _opening_analysis(payload: dict[str, Any]) -> dict[str, Any]:
    room = payload.get("room", payload)
    openings = room.get("openings") if isinstance(room, dict) else None
    if not isinstance(openings, dict):
        raise StitchingError("result contains no room.openings analysis")
    return openings


def _walls(payload: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    walls = _opening_analysis(payload).get("walls")
    if not isinstance(walls, list) or not walls:
        raise StitchingError("result contains no finite wall segments")
    return tuple(dict(wall) for wall in walls)


def _transform_wall(
    wall: dict[str, Any], rotation: NDArray[np.float64], translation: NDArray[np.float64]
) -> dict[str, Any]:
    start = np.asarray(wall["start_xy_m"], dtype=np.float64) @ rotation.T + translation
    end = np.asarray(wall["end_xy_m"], dtype=np.float64) @ rotation.T + translation
    normal = np.asarray(wall["normal_xy"], dtype=np.float64) @ rotation.T
    return {
        "wall_id": wall["wall_id"],
        "start_xy_m": start.tolist(),
        "end_xy_m": end.tolist(),
        "normal_xy": normal.tolist(),
        "length_m": float(wall["length_m"]),
    }


def _floor_vertices(payload: dict[str, Any]) -> list[list[float]]:
    room = payload.get("room", payload)
    plan = room.get("floor_plan") if isinstance(room, dict) else None
    vertices = plan.get("vertices_xy_m") if isinstance(plan, dict) else None
    if not isinstance(vertices, list):
        return []
    return _points(vertices, "floor-plan vertices").tolist()


def _transform_floor_plan(
    payload: dict[str, Any], rotation: NDArray[np.float64], translation: NDArray[np.float64]
) -> list[list[float]]:
    vertices = _floor_vertices(payload)
    if not vertices:
        return []
    return (np.asarray(vertices, dtype=np.float64) @ rotation.T + translation).tolist()


def _midpoint(wall: dict[str, Any]) -> NDArray[np.float64]:
    return (
        np.asarray(wall["start_xy_m"], dtype=np.float64)
        + np.asarray(wall["end_xy_m"], dtype=np.float64)
    ) / 2.0


def _undirected_angle_degrees(source: dict[str, Any], target: dict[str, Any]) -> float:
    source_direction = np.asarray(source["end_xy_m"], dtype=np.float64) - np.asarray(
        source["start_xy_m"], dtype=np.float64
    )
    target_direction = np.asarray(target["end_xy_m"], dtype=np.float64) - np.asarray(
        target["start_xy_m"], dtype=np.float64
    )
    cosine = abs(
        float(source_direction @ target_direction)
        / (float(np.linalg.norm(source_direction)) * float(np.linalg.norm(target_direction)))
    )
    return math.degrees(math.acos(float(np.clip(cosine, -1.0, 1.0))))
