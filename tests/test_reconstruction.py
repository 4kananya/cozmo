"""Numerical and integration tests for metric point-cloud reconstruction."""

from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

from tests.capture_factory import create_test_capture
from cozmo_scan.models import FrameSelection, OdometryRecord, ReconstructionProfile
from cozmo_scan.reconstruction import (
    backproject_depth,
    camera_to_world_matrix,
    depth_to_metres,
    filter_depth,
    get_profile_config,
    quaternion_to_rotation,
    reconstruct_capture,
    scale_intrinsics,
    transform_points,
    voxel_downsample,
)


class ProjectionTests(unittest.TestCase):
    def test_depth_converts_from_millimetres_to_metres(self) -> None:
        depth = np.asarray([[0, 250, 1000, 5000]], dtype=np.uint16)

        converted = depth_to_metres(depth)

        np.testing.assert_allclose(converted, [[0.0, 0.25, 1.0, 5.0]])
        self.assertEqual(converted.dtype, np.float32)

    def test_depth_filter_applies_range_confidence_and_finite_rules(self) -> None:
        depth = np.asarray([[0.1, 0.5, 2.0, 6.0, np.nan]], dtype=np.float32)
        confidence = np.asarray([[2, 0, 1, 2, 2]], dtype=np.uint8)

        mask = filter_depth(
            depth,
            confidence,
            minimum_confidence=1,
            minimum_depth_m=0.2,
            maximum_depth_m=5.0,
        )

        np.testing.assert_array_equal(mask, [[False, False, True, False, False]])

    def test_intrinsics_scale_independently_per_axis(self) -> None:
        scaled = scale_intrinsics(
            (1600.0, 1500.0, 960.0, 720.0),
            source_size=(1920, 1440),
            target_size=(256, 192),
        )

        np.testing.assert_allclose(
            scaled,
            (213.3333333333, 200.0, 128.0, 96.0),
        )

    def test_backprojection_uses_pinhole_equations(self) -> None:
        depth = np.full((2, 2), 2.0, dtype=np.float32)
        mask = np.ones((2, 2), dtype=bool)

        points = backproject_depth(
            depth,
            mask,
            (1.0, 1.0, 0.0, 0.0),
            pixel_stride=1,
        )

        np.testing.assert_allclose(
            points,
            [[0.0, 0.0, 2.0], [2.0, 0.0, 2.0], [0.0, 2.0, 2.0], [2.0, 2.0, 2.0]],
        )


class TransformTests(unittest.TestCase):
    def test_identity_quaternion_produces_identity_rotation(self) -> None:
        rotation = quaternion_to_rotation((0.0, 0.0, 0.0, 1.0))

        np.testing.assert_allclose(rotation, np.eye(3), atol=1e-12)

    def test_quaternion_is_normalized_and_rotates_ninety_degrees(self) -> None:
        half_angle = math.pi / 4
        quaternion = (0.0, 0.0, 2 * math.sin(half_angle), 2 * math.cos(half_angle))

        rotation = quaternion_to_rotation(quaternion)
        rotated = rotation @ np.asarray([1.0, 0.0, 0.0])

        np.testing.assert_allclose(rotated, [0.0, 1.0, 0.0], atol=1e-12)

    def test_camera_to_world_transform_applies_recorded_translation(self) -> None:
        odometry = OdometryRecord(
            timestamp=0.0,
            frame_id="000000",
            position_xyz_m=(1.0, 2.0, 3.0),
            quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
            intrinsics_fx_fy_cx_cy=(1.0, 1.0, 0.0, 0.0),
        )
        transform = camera_to_world_matrix(odometry)

        world = transform_points(np.asarray([[0.5, 0.0, 1.0]]), transform)

        np.testing.assert_allclose(world, [[1.5, 2.0, 4.0]])


class FusionTests(unittest.TestCase):
    def test_profile_rejects_zero_frame_override(self) -> None:
        with self.assertRaisesRegex(ValueError, "greater than 0"):
            get_profile_config(ReconstructionProfile.TEST, max_frames=0)

    def test_contiguous_profile_selection_is_recorded(self) -> None:
        config = get_profile_config(
            ReconstructionProfile.TEST,
            frame_selection=FrameSelection.CONTIGUOUS_START,
        )

        self.assertEqual(config.frame_selection, FrameSelection.CONTIGUOUS_START)

    def test_voxel_downsample_returns_deterministic_centroids(self) -> None:
        points = np.asarray(
            [[0.01, 0.01, 0.01], [0.03, 0.01, 0.01], [0.21, 0.0, 0.0]],
            dtype=np.float32,
        )

        first = voxel_downsample(points, 0.1)
        second = voxel_downsample(points[::-1], 0.1)

        np.testing.assert_allclose(first, second)
        np.testing.assert_allclose(first[0], [0.02, 0.01, 0.01])
        self.assertEqual(len(first), 2)

    def test_tiny_capture_reconstructs_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            container = Path(temporary)
            create_test_capture(container, confidence_value=2)
            config = get_profile_config(
                ReconstructionProfile.TEST, max_frames=3
            ).model_copy(
                update={
                    "calibration_width": 4,
                    "calibration_height": 3,
                    "pixel_stride": 1,
                    "voxel_size_m": 0.001,
                }
            )

            result = reconstruct_capture(container, config)

        statistics = result.summary.statistics
        self.assertEqual(statistics.total_matched_frames, 3)
        self.assertEqual(statistics.selected_frame_count, 3)
        self.assertEqual(statistics.processed_frame_count, 3)
        self.assertEqual(statistics.skipped_frame_count, 0)
        self.assertEqual(statistics.valid_point_count_before_voxel, 36)
        self.assertGreater(statistics.output_point_count, 0)
        self.assertTrue(np.isfinite(result.points_xyz_m).all())
        self.assertEqual(result.trajectory_xyz_m.shape, (3, 3))


if __name__ == "__main__":
    unittest.main()
