"""Experimental visual-anomaly screening and inspection-scope output.

This is intentionally a screening prototype, not a structural diagnosis. It
finds thin dark regions that contrast with their local neighbourhood and keeps
the numerical evidence so a reviewer can accept or reject each candidate.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageFilter, UnidentifiedImageError

from cozmo_scan.media import PHOTO_SUFFIXES


class DamageScreenError(ValueError):
    """Raised when visual screening cannot be completed."""


def screen_damage_candidates(
    path: str | Path, *, metres_per_pixel: float | None = None
) -> dict[str, Any]:
    """Screen one image or directory and return reviewable anomaly candidates."""
    source = Path(path)
    if not source.exists():
        raise DamageScreenError(f"Input does not exist: {source}")
    if source.is_file():
        images = [source] if source.suffix.lower() in PHOTO_SUFFIXES else []
    else:
        images = sorted(
            (
                item
                for item in source.rglob("*")
                if item.is_file() and item.suffix.lower() in PHOTO_SUFFIXES
            ),
            key=lambda item: item.relative_to(source).as_posix().casefold(),
        )
    if not images:
        raise DamageScreenError("No supported images were found")
    root = source.parent if source.is_file() else source
    if metres_per_pixel is not None and metres_per_pixel <= 0:
        raise DamageScreenError("metres_per_pixel must be positive")
    results = [_screen_image(image, root, metres_per_pixel) for image in images]
    candidate_count = sum(item["status"] == "review_required" for item in results)
    return {
        "schema_version": "1.0.0",
        "status": "experimental_screening",
        "method": "multiscale_local_dark_line_contrast",
        "image_count": len(results),
        "candidate_count": candidate_count,
        "images": results,
        "inspection_scope": {
            "action": (
                "Review the highlighted candidate regions on site before defining repairs."
                if candidate_count
                else "No candidate passed this screen; this does not prove absence of damage."
            ),
            "repair_quantity_status": (
                "candidate_geometry_only" if metres_per_pixel is not None else "not_estimated"
            ),
            "reason": (
                "Pixel anomalies are not a material diagnosis and the images have no "
                "validated surface scale or labelled damage ground truth."
            ),
        },
        "limitations": [
            "Dark joints, shadows, cables, texture and markings can produce false positives.",
            "Low-contrast or non-visual damage can be missed.",
            "A qualified inspection is required before specifying repair work.",
        ],
    }


def build_repair_scope(
    screen_path: str | Path, decisions_path: str | Path
) -> dict[str, Any]:
    """Create reviewer-approved draft scope lines from scaled screening evidence."""
    screen = _load_json(Path(screen_path), "screening result")
    decisions = _load_json(Path(decisions_path), "review decisions")
    reviewer = decisions.get("reviewer")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise DamageScreenError("review decisions require a non-empty reviewer")
    raw_decisions = decisions.get("decisions")
    if not isinstance(raw_decisions, list):
        raise DamageScreenError("review decisions require a decisions list")
    images = {
        image["relative_path"]: image
        for image in screen.get("images", [])
        if isinstance(image, dict) and isinstance(image.get("relative_path"), str)
    }
    line_items: list[dict[str, Any]] = []
    for decision in raw_decisions:
        if not isinstance(decision, dict) or not decision.get("confirmed"):
            continue
        relative_path = decision.get("relative_path")
        image = images.get(relative_path)
        if image is None:
            raise DamageScreenError(f"review decision references unknown image: {relative_path}")
        action = decision.get("action")
        if not isinstance(action, str) or not action.strip():
            raise DamageScreenError(f"confirmed decision for {relative_path} requires an action")
        basis = decision.get("quantity_basis", "maximum_candidate_extent_m")
        if basis not in {"maximum_candidate_extent_m", "candidate_area_m2"}:
            raise DamageScreenError(f"unsupported quantity basis for {relative_path}: {basis}")
        quantity = image.get(basis)
        if not isinstance(quantity, (int, float)) or quantity <= 0:
            raise DamageScreenError(
                f"confirmed decision for {relative_path} requires scaled screening evidence"
            )
        unit = "metre" if basis.endswith("extent_m") else "square_metre"
        unit_rate = decision.get("unit_rate")
        if unit_rate is not None and (not isinstance(unit_rate, (int, float)) or unit_rate < 0):
            raise DamageScreenError(f"unit_rate for {relative_path} must be non-negative")
        line_items.append(
            {
                "relative_path": relative_path,
                "classification": image.get("classification"),
                "action": action.strip(),
                "quantity": float(quantity),
                "unit": unit,
                "quantity_basis": basis,
                "unit_rate": unit_rate,
                "estimated_cost": None if unit_rate is None else float(quantity) * float(unit_rate),
                "reviewer_note": decision.get("note"),
            }
        )
    return {
        "schema_version": "1.0.0",
        "status": "draft_requires_engineer_approval",
        "reviewer": reviewer.strip(),
        "source_screen": Path(screen_path).name,
        "line_item_count": len(line_items),
        "line_items": line_items,
        "limitations": [
            "Actions and confirmations are reviewer supplied, not inferred by the model.",
            "Quantities are image-plane candidate geometry and can be distorted by perspective.",
            "The draft must be approved against an on-site inspection before use.",
        ],
    }


def write_damage_screen(result: dict[str, Any], path: str | Path, *, overwrite: bool = False) -> Path:
    destination = Path(path)
    if destination.exists() and not overwrite:
        raise DamageScreenError(f"Output already exists: {destination}; pass --overwrite to replace it")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    temporary.replace(destination)
    return destination


def _screen_image(
    path: Path, root: Path, metres_per_pixel: float | None
) -> dict[str, Any]:
    try:
        with Image.open(path) as opened:
            grayscale = opened.convert("L")
            original_width, original_height = grayscale.size
            grayscale.thumbnail((1024, 1024))
            pixels = np.asarray(grayscale, dtype=np.float64) / 255.0
    except (OSError, UnidentifiedImageError) as exc:
        raise DamageScreenError(f"Cannot decode image {path.name}: {exc}") from exc
    contrasts = []
    for radius in (3, 6, 12):
        local_mean = np.asarray(
            grayscale.filter(ImageFilter.BoxBlur(radius=radius)), dtype=np.float64
        ) / 255.0
        contrasts.append(local_mean - pixels)
    contrast = np.maximum.reduce(contrasts)
    mask = (contrast >= 0.12) & (pixels <= 0.68)
    mask &= _neighbour_count(mask) >= 2
    components = _components(mask, contrast)
    component_pixels = sum(component["pixel_count"] for component in components)
    candidate_fraction = float(component_pixels / mask.size)
    # Broad dark regions are normally occlusion/shadow rather than thin damage.
    review_required = bool(components) and candidate_fraction <= 0.08
    bounding_box = None
    retained_mask = np.zeros_like(mask)
    for component in components:
        y0, x0, y1, x1 = component.pop("_pixel_bbox")
        retained_mask[y0:y1, x0:x1] |= mask[y0:y1, x0:x1]
    if retained_mask.any():
        y, x = np.nonzero(retained_mask)
        bounding_box = [
            float(x.min() / mask.shape[1]),
            float(y.min() / mask.shape[0]),
            float((x.max() + 1) / mask.shape[1]),
            float((y.max() + 1) / mask.shape[0]),
        ]
    scale_x = original_width / mask.shape[1]
    scale_y = original_height / mask.shape[0]
    area_m2 = None
    maximum_extent_m = None
    if metres_per_pixel is not None and component_pixels:
        area_m2 = component_pixels * scale_x * scale_y * metres_per_pixel**2
        maximum_extent_m = max(
            math.hypot(
                (
                    component["bounding_box_normalized"][2]
                    - component["bounding_box_normalized"][0]
                )
                * original_width,
                (
                    component["bounding_box_normalized"][3]
                    - component["bounding_box_normalized"][1]
                )
                * original_height,
            )
            * metres_per_pixel
            for component in components
        )
    return {
        "relative_path": path.name if path.parent == root else path.relative_to(root).as_posix(),
        "sha256": _sha256(path),
        "width": original_width,
        "height": original_height,
        "status": "review_required" if review_required else "no_candidate_from_screen",
        "candidate_pixel_fraction": candidate_fraction,
        "candidate_bounding_box_normalized": bounding_box,
        "candidate_component_count": len(components),
        "components": components,
        "metres_per_pixel": metres_per_pixel,
        "candidate_area_m2": area_m2,
        "maximum_candidate_extent_m": maximum_extent_m,
        "classification": "crack_like_visual_anomaly" if review_required else None,
        "confidence": "screening_only",
    }


def _neighbour_count(mask: np.ndarray) -> np.ndarray:
    padded = np.pad(mask.astype(np.uint8), 1)
    count = np.zeros(mask.shape, dtype=np.uint8)
    height, width = mask.shape
    for y_offset in range(3):
        for x_offset in range(3):
            if y_offset == 1 and x_offset == 1:
                continue
            count += padded[y_offset : y_offset + height, x_offset : x_offset + width]
    return count


def _components(mask: np.ndarray, contrast: np.ndarray) -> list[dict[str, Any]]:
    height, width = mask.shape
    visited = np.zeros_like(mask)
    results: list[dict[str, Any]] = []
    for start_y, start_x in np.argwhere(mask):
        if visited[start_y, start_x]:
            continue
        stack = [(int(start_y), int(start_x))]
        visited[start_y, start_x] = True
        points: list[tuple[int, int]] = []
        while stack:
            y, x = stack.pop()
            points.append((y, x))
            for next_y in range(max(0, y - 1), min(height, y + 2)):
                for next_x in range(max(0, x - 1), min(width, x + 2)):
                    if mask[next_y, next_x] and not visited[next_y, next_x]:
                        visited[next_y, next_x] = True
                        stack.append((next_y, next_x))
        if len(points) < 6:
            continue
        coordinates = np.asarray(points, dtype=np.int32)
        y0, x0 = coordinates.min(axis=0)
        y1, x1 = coordinates.max(axis=0) + 1
        box_area = int((y1 - y0) * (x1 - x0))
        # Dense, block-like components are usually shadows/objects. Retain line-
        # like structures while allowing junctions and branching cracks.
        fill_ratio = len(points) / box_area
        aspect = max((x1 - x0) / max(y1 - y0, 1), (y1 - y0) / max(x1 - x0, 1))
        if fill_ratio > 0.72 and aspect < 2.0:
            continue
        component_contrast = contrast[coordinates[:, 0], coordinates[:, 1]]
        results.append(
            {
                "pixel_count": len(points),
                "bounding_box_normalized": [x0 / width, y0 / height, x1 / width, y1 / height],
                "fill_ratio": float(fill_ratio),
                "aspect_ratio": float(aspect),
                "mean_local_contrast": float(component_contrast.mean()),
                "_pixel_bbox": [int(y0), int(x0), int(y1), int(x1)],
            }
        )
    results.sort(key=lambda item: item["pixel_count"], reverse=True)
    return results


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DamageScreenError(f"Cannot read {label} {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise DamageScreenError(f"{label} must contain a JSON object")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise DamageScreenError(f"Cannot read image: {path}") from exc
    return digest.hexdigest()
