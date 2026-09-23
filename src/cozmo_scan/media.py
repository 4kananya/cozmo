"""Deterministic photo and video ingestion with explicit geometry boundaries."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, model_validator

MEDIA_MANIFEST_FILENAME = "media-input.json"
PHOTO_SUFFIXES = frozenset(
    {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
)
VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".m4v"})


class MediaIngestionError(ValueError):
    """Raised when media cannot be validated or published safely."""


class MediaTier(StrEnum):
    """Supported non-LiDAR input tiers."""

    PHOTO = "photo"
    VIDEO = "video"


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

    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["ingested"] = "ingested"
    tier: MediaTier
    source_name: str
    source_kind: Literal["file", "directory"]
    asset_count: int = Field(gt=0)
    byte_count: int = Field(gt=0)
    assets: tuple[MediaAsset, ...]
    processing_scope: Literal["media_ingestion"] = "media_ingestion"
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
    return MediaIngestion(
        tier=selected_tier,
        source_name=source.name,
        source_kind="file" if source.is_file() else "directory",
        asset_count=len(assets),
        byte_count=sum(asset.byte_count for asset in assets),
        assets=assets,
    )


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
    except (OSError, UnidentifiedImageError) as exc:
        raise MediaIngestionError(f"Cannot decode photo {path.name}: {exc}") from exc
    return MediaAsset(
        relative_path=_relative_name(path, root),
        byte_count=path.stat().st_size,
        sha256=_sha256(path),
        media_format=media_format,
        width=width,
        height=height,
    )


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
