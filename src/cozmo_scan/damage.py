"""Experimental visual-anomaly screening and inspection-scope output.

This is intentionally a screening prototype, not a structural diagnosis. It
finds thin dark regions that contrast with their local neighbourhood and keeps
the numerical evidence so a reviewer can accept or reject each candidate.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageFilter, UnidentifiedImageError

from cozmo_scan.media import PHOTO_SUFFIXES


class DamageScreenError(ValueError):
    """Raised when visual screening cannot be completed."""


def screen_damage_candidates(path: str | Path) -> dict[str, Any]:
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
    results = [_screen_image(image, root) for image in images]
    candidate_count = sum(item["status"] == "review_required" for item in results)
    return {
        "schema_version": "1.0.0",
        "status": "experimental_screening",
        "method": "local_dark_line_contrast",
        "image_count": len(results),
        "candidate_count": candidate_count,
        "images": results,
        "inspection_scope": {
            "action": (
                "Review the highlighted candidate regions on site before defining repairs."
                if candidate_count
                else "No candidate passed this screen; this does not prove absence of damage."
            ),
            "repair_quantity_status": "not_estimated",
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


def write_damage_screen(result: dict[str, Any], path: str | Path, *, overwrite: bool = False) -> Path:
    destination = Path(path)
    if destination.exists() and not overwrite:
        raise DamageScreenError(f"Output already exists: {destination}; pass --overwrite to replace it")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    temporary.replace(destination)
    return destination


def _screen_image(path: Path, root: Path) -> dict[str, Any]:
    try:
        with Image.open(path) as opened:
            grayscale = opened.convert("L")
            original_width, original_height = grayscale.size
            grayscale.thumbnail((1024, 1024))
            local_mean = grayscale.filter(ImageFilter.BoxBlur(radius=6))
            pixels = np.asarray(grayscale, dtype=np.float64) / 255.0
            neighbourhood = np.asarray(local_mean, dtype=np.float64) / 255.0
    except (OSError, UnidentifiedImageError) as exc:
        raise DamageScreenError(f"Cannot decode image {path.name}: {exc}") from exc
    contrast = neighbourhood - pixels
    mask = (contrast >= 0.14) & (pixels <= 0.65)
    candidate_fraction = float(mask.mean())
    # Broad dark regions are normally occlusion/shadow rather than thin damage.
    review_required = 0.00015 <= candidate_fraction <= 0.08
    bounding_box = None
    if mask.any():
        y, x = np.nonzero(mask)
        bounding_box = [
            float(x.min() / mask.shape[1]),
            float(y.min() / mask.shape[0]),
            float((x.max() + 1) / mask.shape[1]),
            float((y.max() + 1) / mask.shape[0]),
        ]
    return {
        "relative_path": path.name if path.parent == root else path.relative_to(root).as_posix(),
        "sha256": _sha256(path),
        "width": original_width,
        "height": original_height,
        "status": "review_required" if review_required else "no_candidate_from_screen",
        "candidate_pixel_fraction": candidate_fraction,
        "candidate_bounding_box_normalized": bounding_box,
        "classification": "crack_like_visual_anomaly" if review_required else None,
        "confidence": "screening_only",
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise DamageScreenError(f"Cannot read image: {path}") from exc
    return digest.hexdigest()
