"""Tests for manually anchored room stitching and wall correspondence."""

from __future__ import annotations

import math
import unittest

import numpy as np

from cozmo_scan.stitching import auto_stitch_result_files, estimate_rigid_transform, match_walls


class RigidTransformTests(unittest.TestCase):
    def test_recovers_rotation_and_translation(self) -> None:
        source = np.asarray([[0.0, 0.0], [2.0, 0.0], [0.0, 1.0]])
        angle = math.radians(30)
        expected_rotation = np.asarray(
            [[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]]
        )
        expected_translation = np.asarray([4.0, -2.0])
        target = source @ expected_rotation.T + expected_translation

        rotation, translation, residuals = estimate_rigid_transform(source, target)

        np.testing.assert_allclose(rotation, expected_rotation, atol=1e-12)
        np.testing.assert_allclose(translation, expected_translation, atol=1e-12)
        np.testing.assert_allclose(residuals, 0.0, atol=1e-12)


class WallMatchingTests(unittest.TestCase):
    def test_matches_only_consistent_unique_walls(self) -> None:
        source = (
            {
                "wall_id": "A",
                "start_xy_m": [0.0, 0.0],
                "end_xy_m": [3.0, 0.0],
                "length_m": 3.0,
            },
            {
                "wall_id": "B",
                "start_xy_m": [0.0, 2.0],
                "end_xy_m": [0.0, 4.0],
                "length_m": 2.0,
            },
        )
        target = (
            {
                "wall_id": "X",
                "start_xy_m": [0.1, 0.1],
                "end_xy_m": [3.1, 0.1],
                "length_m": 3.0,
            },
            {
                "wall_id": "Y",
                "start_xy_m": [0.1, 2.0],
                "end_xy_m": [0.1, 4.0],
                "length_m": 2.0,
            },
        )

        matches = match_walls(source, target)

        self.assertEqual(
            {(item["source_wall_id"], item["target_wall_id"]) for item in matches},
            {("A", "X"), ("B", "Y")},
        )

    def test_automatic_alignment_recovers_transformed_room(self) -> None:
        import json
        import tempfile
        from pathlib import Path

        source_walls = [
            {"wall_id": "A", "start_xy_m": [0.0, 0.0], "end_xy_m": [4.0, 0.0], "normal_xy": [0.0, 1.0], "length_m": 4.0},
            {"wall_id": "B", "start_xy_m": [4.0, 0.0], "end_xy_m": [4.0, 3.0], "normal_xy": [-1.0, 0.0], "length_m": 3.0},
            {"wall_id": "C", "start_xy_m": [4.0, 3.0], "end_xy_m": [0.0, 3.0], "normal_xy": [0.0, -1.0], "length_m": 4.0},
        ]
        angle = math.radians(25.0)
        rotation = np.asarray([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
        translation = np.asarray([6.0, -2.0])
        target_walls = []
        for index, wall in enumerate(source_walls):
            start = np.asarray(wall["start_xy_m"]) @ rotation.T + translation
            end = np.asarray(wall["end_xy_m"]) @ rotation.T + translation
            normal = np.asarray(wall["normal_xy"]) @ rotation.T
            target_walls.append(
                {**wall, "wall_id": f"T{index}", "start_xy_m": start.tolist(), "end_xy_m": end.tolist(), "normal_xy": normal.tolist()}
            )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_path = root / "source.json"
            target_path = root / "target.json"
            source_path.write_text(json.dumps({"room": {"openings": {"walls": source_walls}}}), encoding="utf-8")
            target_path.write_text(json.dumps({"room": {"openings": {"walls": target_walls}}}), encoding="utf-8")

            result = auto_stitch_result_files(source_path, target_path)

        self.assertEqual(len(result["wall_matches"]), 3)
        self.assertEqual(result["confidence"], "medium")
        self.assertLess(result["transform_source_to_target"]["wall_midpoint_rmse_m"], 1e-8)


if __name__ == "__main__":
    unittest.main()
