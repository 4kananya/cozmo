"""Tests for manually anchored room stitching and wall correspondence."""

from __future__ import annotations

import math
import unittest

import numpy as np

from cozmo_scan.stitching import estimate_rigid_transform, match_walls


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


if __name__ == "__main__":
    unittest.main()
