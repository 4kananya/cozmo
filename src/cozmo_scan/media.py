"""Deterministic photo and video ingestion with explicit geometry boundaries."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal

import numpy as np
from PIL import Image, ImageDraw, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, model_validator

MEDIA_MANIFEST_FILENAME = "media-input.json"
PHOTO_SUFFIXES = frozenset(
    {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
)
VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".m4v"})
DEFAULT_EXTRACTED_FRAME_COUNT = 12


class MediaIngestionError(ValueError):
    """Raised when media cannot be validated or published safely."""


class MediaTier(StrEnum):
    """Supported non-LiDAR input tiers."""

    PHOTO = "photo"
    VIDEO = "video"


class PhotoQuality(BaseModel):
    """Fast, deterministic capture-screening evidence for one decoded image."""

    model_config = ConfigDict(frozen=True)

    accepted: bool
    rejection_reasons: tuple[str, ...] = ()
    sharpness_score: float = Field(ge=0)
    mean_luminance: float = Field(ge=0, le=1)
    dark_pixel_fraction: float = Field(ge=0, le=1)
    bright_pixel_fraction: float = Field(ge=0, le=1)
    perceptual_hash: str = Field(pattern=r"^[0-9a-f]{16}$")
    duplicate_of: str | None = None


class MediaAsset(BaseModel):
    """Validated metadata and provenance for one media file."""

    model_config = ConfigDict(frozen=True)

    relative_path: str
    byte_count: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_format: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    duration_seconds: float | None = Field(default=None, gt=0)
    frame_count: int | None = Field(default=None, gt=0)
    codec: str | None = None
    source_timestamp_seconds: float | None = Field(default=None, ge=0)
    quality: PhotoQuality | None = None

    @model_validator(mode="after")
    def validate_relative_path(self) -> MediaAsset:
        """Keep host-specific and traversal paths out of the public manifest."""
        relative = PurePosixPath(self.relative_path)
        if (
            not self.relative_path
            or relative.is_absolute()
            or ".." in relative.parts
            or "\\" in self.relative_path
        ):
            raise ValueError("relative_path must be a safe POSIX relative path")
        return self


class MediaIngestion(BaseModel):
    """Versioned ingestion result for a photo set or one or more videos."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal["1.1.0"] = "1.1.0"
    status: Literal["ingested"] = "ingested"
    tier: MediaTier
    source_name: str
    source_kind: Literal["file", "directory"]
    asset_count: int = Field(gt=0)
    byte_count: int = Field(gt=0)
    assets: tuple[MediaAsset, ...]
    derived_frames: tuple[MediaAsset, ...] = ()
    contact_sheet: str | None = None
    processing_scope: Literal["media_ingestion", "media_evidence"] = "media_ingestion"
    processing_note: str = (
        "The manifest records validated media provenance. Metric geometry uses the "
        "separate LiDAR path with calibrated depth and camera poses."
    )
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_inventory_totals(self) -> MediaIngestion:
        """Bind declared totals to the exact asset inventory."""
        if self.asset_count != len(self.assets):
            raise ValueError("asset_count must equal the number of assets")
        if self.byte_count != sum(asset.byte_count for asset in self.assets):
            raise ValueError("byte_count must equal the sum of asset bytes")
        names = [asset.relative_path.casefold() for asset in self.assets]
        if len(names) != len(set(names)):
            raise ValueError("asset relative paths must be unique case-insensitively")
        return self


def ingest_media(path: str | Path, tier: MediaTier | str) -> MediaIngestion:
    """Validate a photo set or video input and return deterministic provenance."""
    source = Path(path)
    selected_tier = MediaTier(tier)
    if not source.exists():
        raise MediaIngestionError(f"Media input does not exist: {source}")
    if not source.is_file() and not source.is_dir():
        raise MediaIngestionError(f"Media input must be a file or directory: {source}")

    allowed = PHOTO_SUFFIXES if selected_tier is MediaTier.PHOTO else VIDEO_SUFFIXES
    if source.is_file():
        candidates = [source] if source.suffix.lower() in allowed else []
        root = source.parent
    else:
        candidates = sorted(
            (
                item
                for item in source.rglob("*")
                if item.is_file()
                and not item.is_symlink()
                and item.suffix.lower() in allowed
            ),
            key=lambda item: item.relative_to(source).as_posix().casefold(),
        )
        root = source
    if not candidates:
        expected = ", ".join(sorted(allowed))
        raise MediaIngestionError(
            f"No {selected_tier.value} files found; supported extensions: {expected}"
        )

    assets = tuple(
        (
            _inspect_photo(item, root)
            if selected_tier is MediaTier.PHOTO
            else _inspect_video(item, root)
        )
        for item in candidates
    )
    if selected_tier is MediaTier.PHOTO:
        assets = _mark_duplicates(assets)
    return MediaIngestion(
        tier=selected_tier,
        source_name=source.name,
        source_kind="file" if source.is_file() else "directory",
        asset_count=len(assets),
        byte_count=sum(asset.byte_count for asset in assets),
        assets=assets,
    )


def build_media_evidence(
    path: str | Path,
    tier: MediaTier | str,
    output_directory: str | Path,
    *,
    extracted_frame_count: int = DEFAULT_EXTRACTED_FRAME_COUNT,
    overwrite: bool = False,
) -> tuple[MediaIngestion, Path]:
    """Ingest media and publish quality evidence, sampled frames, and a contact sheet.

    Video frames are selected at evenly spaced timestamps inside the stream bounds.
    The output remains capture evidence; it is not metric reconstruction.
    """
    if extracted_frame_count < 1:
        raise MediaIngestionError("extracted_frame_count must be at least one")
    source = Path(path)
    selected_tier = MediaTier(tier)
    ingestion = ingest_media(source, selected_tier)
    directory = Path(output_directory)
    destination = directory / MEDIA_MANIFEST_FILENAME
    if destination.exists() and not overwrite:
        raise MediaIngestionError(
            f"Output artifact already exists ({destination.name}); pass --overwrite to replace it"
        )
    directory.mkdir(parents=True, exist_ok=True)

    derived: tuple[MediaAsset, ...] = ()
    preview_inputs: list[Path]
    if selected_tier is MediaTier.VIDEO:
        videos = _discover_media(source, VIDEO_SUFFIXES)
        frame_directory = directory / "frames"
        frame_directory.mkdir(parents=True, exist_ok=True)
        frames: list[MediaAsset] = []
        preview_inputs = []
        for video_index, (video, video_asset) in enumerate(zip(videos, ingestion.assets)):
            duration = video_asset.duration_seconds
            if duration is None:
                raise MediaIngestionError(f"Video duration is unavailable: {video.name}")
            timestamps = _even_timestamps(duration, extracted_frame_count)
            for frame_index, timestamp in enumerate(timestamps, start=1):
                frame_path = frame_directory / (
                    f"v{video_index + 1:02d}-{video.stem}-frame-{frame_index:03d}.jpg"
                )
                _extract_frame(video, timestamp, frame_path)
                asset = _inspect_photo(frame_path, directory).model_copy(
                    update={"source_timestamp_seconds": timestamp}
                )
                frames.append(asset)
                preview_inputs.append(frame_path)
        derived = _mark_duplicates(tuple(frames))
    else:
        preview_inputs = _discover_media(source, PHOTO_SUFFIXES)

    sheet_path = directory / "contact-sheet.jpg"
    _write_contact_sheet(preview_inputs, sheet_path)
    enhanced = ingestion.model_copy(
        update={
            "processing_scope": "media_evidence",
            "derived_frames": derived,
            "contact_sheet": sheet_path.name,
            "warnings": ingestion.warnings
            + (
                "Capture-quality thresholds are screening heuristics and are not a geometric accuracy result.",
            ),
        }
    )
    manifest = write_media_manifest(enhanced, directory, overwrite=overwrite)
    return enhanced, manifest


def write_media_manifest(
    ingestion: MediaIngestion,
    output_directory: str | Path,
    *,
    overwrite: bool = False,
) -> Path:
    """Publish one atomic media-ingestion manifest with overwrite protection."""
    directory = Path(output_directory)
    if directory.exists() and not directory.is_dir():
        raise MediaIngestionError(f"Output path is not a directory: {directory}")
    destination = directory / MEDIA_MANIFEST_FILENAME
    if destination.exists() and not overwrite:
        raise MediaIngestionError(
            f"Output artifact already exists ({destination.name}); pass --overwrite to replace it"
        )
    directory.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f"{destination.name}.tmp")
    try:
        temporary.write_text(
            ingestion.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(destination)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise MediaIngestionError(f"Cannot write media manifest: {destination}") from exc
    return destination


def _inspect_photo(path: Path, root: Path) -> MediaAsset:
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            width, height = image.size
            media_format = image.format or path.suffix.removeprefix(".").upper()
            quality = _photo_quality(image.convert("L"), width, height)
    except (OSError, UnidentifiedImageError) as exc:
        raise MediaIngestionError(f"Cannot decode photo {path.name}: {exc}") from exc
    return MediaAsset(
        relative_path=_relative_name(path, root),
        byte_count=path.stat().st_size,
        sha256=_sha256(path),
        media_format=media_format,
        width=width,
        height=height,
        quality=quality,
    )


def _photo_quality(image: Image.Image, width: int, height: int) -> PhotoQuality:
    reduced = image.copy()
    reduced.thumbnail((640, 640))
    pixels = np.asarray(reduced, dtype=np.float64) / 255.0
    mean_luminance = float(pixels.mean())
    dark_fraction = float((pixels <= 0.03).mean())
    bright_fraction = float((pixels >= 0.97).mean())
    dx = np.diff(pixels, axis=1)
    dy = np.diff(pixels, axis=0)
    sharpness = float((np.mean(dx * dx) + np.mean(dy * dy)) / 2.0)
    reasons: list[str] = []
    if width < 640 or height < 480:
        reasons.append(f"resolution {width}x{height} is below 640x480")
    if mean_luminance < 0.08:
        reasons.append("mean exposure is too dark")
    elif mean_luminance > 0.92:
        reasons.append("mean exposure is too bright")
    if dark_fraction > 0.65:
        reasons.append("too many clipped dark pixels")
    if bright_fraction > 0.65:
        reasons.append("too many clipped bright pixels")
    if sharpness < 0.0004:
        reasons.append("insufficient high-frequency detail; image may be blurred")
    return PhotoQuality(
        accepted=not reasons,
        rejection_reasons=tuple(reasons),
        sharpness_score=sharpness,
        mean_luminance=mean_luminance,
        dark_pixel_fraction=dark_fraction,
        bright_pixel_fraction=bright_fraction,
        perceptual_hash=_difference_hash(image),
    )


def _difference_hash(image: Image.Image) -> str:
    sample = np.asarray(image.resize((9, 8), Image.Resampling.LANCZOS), dtype=np.int16)
    bits = (sample[:, 1:] > sample[:, :-1]).reshape(-1)
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return f"{value:016x}"


def _mark_duplicates(assets: tuple[MediaAsset, ...]) -> tuple[MediaAsset, ...]:
    seen: dict[str, str] = {}
    marked: list[MediaAsset] = []
    for asset in assets:
        quality = asset.quality
        if quality is None:
            marked.append(asset)
            continue
        original = seen.get(quality.perceptual_hash)
        if original is None:
            seen[quality.perceptual_hash] = asset.relative_path
            marked.append(asset)
            continue
        reasons = quality.rejection_reasons + (f"visual duplicate of {original}",)
        marked.append(
            asset.model_copy(
                update={
                    "quality": quality.model_copy(
                        update={
                            "accepted": False,
                            "duplicate_of": original,
                            "rejection_reasons": reasons,
                        }
                    )
                }
            )
        )
    return tuple(marked)


def _discover_media(source: Path, allowed: frozenset[str]) -> list[Path]:
    if source.is_file():
        return [source]
    return sorted(
        (
            item
            for item in source.rglob("*")
            if item.is_file() and not item.is_symlink() and item.suffix.lower() in allowed
        ),
        key=lambda item: item.relative_to(source).as_posix().casefold(),
    )


def _even_timestamps(duration: float, count: int) -> tuple[float, ...]:
    # Stay away from container boundaries, where a nominal timestamp can decode
    # no frame. A single requested frame is taken from the middle.
    if count == 1:
        return (duration / 2.0,)
    margin = min(0.25, duration * 0.02)
    start = margin
    end = max(start, duration - margin)
    return tuple(float(value) for value in np.linspace(start, end, count))


def _extract_frame(video: Path, timestamp: float, destination: Path) -> None:
    executable = shutil.which("ffmpeg")
    if executable is None:
        raise MediaIngestionError(
            "Video frame extraction requires ffmpeg from a local FFmpeg installation"
        )
    command = [
        executable,
        "-v",
        "error",
        "-ss",
        f"{timestamp:.6f}",
        "-i",
        str(video),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        "-y",
        str(destination),
    ]
    completed = subprocess.run(command, capture_output=True, check=False, text=True, timeout=60)
    if completed.returncode != 0 or not destination.is_file():
        reason = completed.stderr.strip() or "FFmpeg produced no frame"
        raise MediaIngestionError(f"Cannot extract video frame at {timestamp:.3f}s: {reason}")


def _write_contact_sheet(paths: list[Path], destination: Path) -> None:
    if not paths:
        raise MediaIngestionError("Cannot make a contact sheet without images")
    columns = min(4, len(paths))
    rows = math.ceil(len(paths) / columns)
    tile_width, tile_height, caption_height = 240, 180, 24
    sheet = Image.new("RGB", (columns * tile_width, rows * (tile_height + caption_height)), "white")
    draw = ImageDraw.Draw(sheet)
    for index, path in enumerate(paths):
        with Image.open(path) as opened:
            image = opened.convert("RGB")
            image.thumbnail((tile_width, tile_height))
            left = (index % columns) * tile_width + (tile_width - image.width) // 2
            top = (index // columns) * (tile_height + caption_height) + (tile_height - image.height) // 2
            sheet.paste(image, (left, top))
        caption = path.name[:36]
        draw.text(((index % columns) * tile_width + 4, (index // columns) * (tile_height + caption_height) + tile_height + 4), caption, fill="black")
    sheet.save(destination, "JPEG", quality=88)


def _inspect_video(path: Path, root: Path) -> MediaAsset:
    executable = shutil.which("ffprobe")
    if executable is None:
        raise MediaIngestionError(
            "Video ingestion requires ffprobe from a local FFmpeg installation"
        )
    command = [
        executable,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,width,height,nb_frames:format=format_name,duration",
        "-of",
        "json",
        str(path),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MediaIngestionError(f"Cannot inspect video {path.name}: {exc}") from exc
    if completed.returncode != 0:
        reason = completed.stderr.strip() or "ffprobe rejected the file"
        raise MediaIngestionError(f"Cannot decode video {path.name}: {reason}")
    try:
        payload = json.loads(completed.stdout)
        stream = payload["streams"][0]
        container = payload["format"]
        width = int(stream["width"])
        height = int(stream["height"])
        duration = float(container["duration"])
        raw_frames = stream.get("nb_frames")
        frame_count = int(raw_frames) if raw_frames not in (None, "N/A") else None
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise MediaIngestionError(
            f"Video {path.name} has no readable primary video stream"
        ) from exc
    return MediaAsset(
        relative_path=_relative_name(path, root),
        byte_count=path.stat().st_size,
        sha256=_sha256(path),
        media_format=str(container.get("format_name", path.suffix.removeprefix("."))),
        width=width,
        height=height,
        duration_seconds=duration,
        frame_count=frame_count,
        codec=str(stream.get("codec_name")) if stream.get("codec_name") else None,
    )


def _relative_name(path: Path, root: Path) -> str:
    return path.name if path.parent == root else path.relative_to(root).as_posix()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise MediaIngestionError(f"Cannot read media file: {path}") from exc
    return digest.hexdigest()
