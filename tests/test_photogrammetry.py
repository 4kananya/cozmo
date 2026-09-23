"""Tests for known-pose sparse media reconstruction."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from cozmo_scan.photogrammetry import (
    PhotogrammetryError,
    reconstruct_known_pose_manifest,
    write_media_reconstruction,
)


class KnownPoseTriangulationTests(unittest.TestCase):
    def _manifest(self) -> dict[str, object]:
        return {
            "camera_matrix": [[100.0, 0.0, 50.0], [0.0, 100.0, 50.0], [0.0, 0.0, 1.0]],
            "translation_unit": "metre",
            "maximum_reprojection_error_px": 0.1,
            "views": [
                {
                    "view_id": "left",
                    "world_from_camera": np.eye(4).tolist(),
                    "observations": {"P1": [50.0, 50.0], "P2": [70.0, 50.0]},
                },
                {
                    "view_id": "right",
                    "world_from_camera": [
                        [1.0, 0.0, 0.0, 1.0],
                        [0.0, 1.0, 0.0, 0.0],
                        [0.0, 0.0, 1.0, 0.0],
                        [0.0, 0.0, 0.0, 1.0],
                    ],
                    "observations": {"P1": [30.0, 50.0], "P2": [50.0, 50.0]},
                },
            ],
        }

    def test_recovers_metric_points_and_writes_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = root / "observations.json"
            manifest.write_text(json.dumps(self._manifest()), encoding="utf-8")

            result, points = reconstruct_known_pose_manifest(manifest)
            paths = write_media_reconstruction(result, points, root / "out")

            np.testing.assert_allclose(points, [[0.0, 0.0, 5.0], [1.0, 0.0, 5.0]], atol=1e-8)
            self.assertEqual(result["reconstructed_point_count"], 2)
            self.assertTrue(paths["result"].is_file())
            self.assertIn("element vertex 2", paths["point_cloud"].read_text(encoding="ascii"))

    def test_refuses_unverified_translation_units(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary) / "observations.json"
            payload = self._manifest()
            payload["translation_unit"] = "unknown"
            manifest.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(PhotogrammetryError, "metric"):
                reconstruct_known_pose_manifest(manifest)


if __name__ == "__main__":
    unittest.main()
