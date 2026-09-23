"""Tests for deterministic photo and video input ingestion."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from cozmo_scan.media import (
    MEDIA_MANIFEST_FILENAME,
    MediaIngestion,
    MediaIngestionError,
    MediaTier,
    ingest_media,
    write_media_manifest,
)


class PhotoIngestionTests(unittest.TestCase):
    def test_image_directory_is_decoded_sorted_and_hashed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "photos"
            (root / "nested").mkdir(parents=True)
            Image.new("RGB", (12, 8), (20, 30, 40)).save(root / "b.jpg")
            Image.new("RGB", (5, 7), (40, 30, 20)).save(root / "nested" / "a.png")

            result = ingest_media(root, MediaTier.PHOTO)

            self.assertEqual(result.tier, MediaTier.PHOTO)
            self.assertEqual(result.asset_count, 2)
            self.assertEqual(
                [asset.relative_path for asset in result.assets],
                ["b.jpg", "nested/a.png"],
            )
            self.assertEqual(result.assets[0].width, 12)
            self.assertEqual(result.assets[1].height, 7)
            self.assertTrue(all(len(asset.sha256) == 64 for asset in result.assets))
            self.assertNotIn(str(root.resolve()), result.model_dump_json())
            self.assertEqual(result.processing_scope, "media_ingestion")

    def test_corrupt_photo_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.jpg"
            path.write_bytes(b"not an image")

            with self.assertRaisesRegex(MediaIngestionError, "Cannot decode photo"):
                ingest_media(path, "photo")


class VideoIngestionTests(unittest.TestCase):
    def test_video_stream_metadata_is_validated_and_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "room.mp4"
            path.write_bytes(b"video-placeholder")
            payload = {
                "streams": [
                    {
                        "codec_name": "h264",
                        "width": 1920,
                        "height": 1080,
                        "nb_frames": "90",
                    }
                ],
                "format": {"format_name": "mov,mp4", "duration": "3.0"},
            }
            completed = subprocess.CompletedProcess(
                args=["ffprobe"], returncode=0, stdout=json.dumps(payload), stderr=""
            )

            with patch("cozmo_scan.media.shutil.which", return_value="ffprobe"), patch(
                "cozmo_scan.media.subprocess.run", return_value=completed
            ) as run:
                result = ingest_media(path, "video")

            self.assertEqual(result.asset_count, 1)
            self.assertEqual(result.assets[0].codec, "h264")
            self.assertEqual(result.assets[0].duration_seconds, 3.0)
            self.assertEqual(result.assets[0].frame_count, 90)
            self.assertNotIn(str(path.parent.resolve()), result.model_dump_json())
            self.assertFalse(run.call_args.kwargs["shell"] if "shell" in run.call_args.kwargs else False)

    def test_video_requires_local_ffprobe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "room.mp4"
            path.write_bytes(b"video-placeholder")
            with patch("cozmo_scan.media.shutil.which", return_value=None):
                with self.assertRaisesRegex(MediaIngestionError, "requires ffprobe"):
                    ingest_media(path, "video")


class ManifestTests(unittest.TestCase):
    def test_manifest_round_trip_and_overwrite_protection(self) -> None:
        ingestion = MediaIngestion(
            tier=MediaTier.PHOTO,
            source_name="photos",
            source_kind="directory",
            asset_count=1,
            byte_count=3,
            assets=(
                {
                    "relative_path": "room.jpg",
                    "byte_count": 3,
                    "sha256": "0" * 64,
                    "media_format": "JPEG",
                    "width": 2,
                    "height": 2,
                },
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "out"
            destination = write_media_manifest(ingestion, output)
            decoded = MediaIngestion.model_validate_json(
                destination.read_text(encoding="utf-8")
            )
            self.assertEqual(decoded, ingestion)
            self.assertEqual(destination.name, MEDIA_MANIFEST_FILENAME)
            with self.assertRaisesRegex(MediaIngestionError, "--overwrite"):
                write_media_manifest(ingestion, output)
            write_media_manifest(ingestion, output, overwrite=True)

    def test_manifest_rejects_false_totals_and_unsafe_paths(self) -> None:
        asset = {
            "relative_path": "room.jpg",
            "byte_count": 3,
            "sha256": "0" * 64,
            "media_format": "JPEG",
            "width": 2,
            "height": 2,
        }
        common = {
            "tier": MediaTier.PHOTO,
            "source_name": "photos",
            "source_kind": "directory",
            "asset_count": 1,
            "byte_count": 3,
            "assets": (asset,),
        }
        with self.assertRaisesRegex(ValueError, "asset_count"):
            MediaIngestion(**(common | {"asset_count": 2}))
        with self.assertRaisesRegex(ValueError, "byte_count"):
            MediaIngestion(**(common | {"byte_count": 4}))
        with self.assertRaisesRegex(ValueError, "safe POSIX"):
            MediaIngestion(**(common | {"assets": (asset | {"relative_path": "../room.jpg"},)}))


if __name__ == "__main__":
    unittest.main()
