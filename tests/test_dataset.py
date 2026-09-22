"""Tests for capture discovery, parsing, matching, and validation."""

from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from cozmo_scan.dataset import (
    discover_capture_root,
    match_frames,
    open_capture,
    read_odometry,
    select_keyframes,
    validate_capture,
)
from cozmo_scan.models import FrameRecord, OdometryRecord
from tests.capture_factory import create_test_capture, create_zip


class CaptureValidationTests(unittest.TestCase):
    def test_valid_directory_capture(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            container = Path(temporary)
            create_test_capture(container)

            result = validate_capture(container)

        self.assertTrue(result.valid)
        self.assertEqual(result.error_count, 0)
        self.assertIsNotNone(result.inventory)
        assert result.inventory is not None
        self.assertEqual(result.inventory.source_kind, "directory")
        self.assertEqual(result.inventory.capture_root, "capture123")
        self.assertEqual(result.inventory.depth_frame_count, 3)
        self.assertEqual(result.inventory.confidence_frame_count, 3)
        self.assertEqual(result.inventory.odometry_record_count, 3)
        self.assertEqual(result.inventory.matched_frame_count, 3)
        self.assertEqual(result.inventory.depth_image_size, (4, 3))
        self.assertEqual(result.inventory.confidence_image_size, (4, 3))
        self.assertEqual(result.inventory.image_pairs_inspected, 3)

    def test_capture_root_can_be_input_directory_itself(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            capture_root = create_test_capture(Path(temporary))

            result = validate_capture(capture_root)

        self.assertTrue(result.valid)
        assert result.inventory is not None
        self.assertEqual(result.inventory.capture_root, "")

    def test_valid_zip_capture(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            container = Path(temporary)
            capture_root = create_test_capture(container)
            archive = container / "capture.zip"
            create_zip(capture_root, archive)

            result = validate_capture(archive)

        self.assertTrue(result.valid)
        assert result.inventory is not None
        self.assertEqual(result.inventory.source_kind, "zip")
        self.assertEqual(result.inventory.matched_frame_count, 3)

    def test_missing_input_is_invalid(self) -> None:
        result = validate_capture("definitely-missing-capture.zip")

        self.assertFalse(result.valid)
        self.assertEqual(result.error_count, 1)
        self.assertEqual(result.issues[0].code, "capture_open_failed")

    def test_unsupported_input_file_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            unsupported = Path(temporary) / "capture.txt"
            unsupported.write_text("not a capture", encoding="utf-8")

            result = validate_capture(unsupported)

        self.assertFalse(result.valid)
        self.assertIn("must be a .zip file or directory", result.issues[0].message)

    def test_missing_required_odometry_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            container = Path(temporary)
            root = create_test_capture(container)
            (root / "odometry.csv").unlink()

            result = validate_capture(container)

        self.assertFalse(result.valid)
        self.assertIn("missing_required_file", {issue.code for issue in result.issues})

    def test_zip_traversal_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "unsafe.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("../escape.txt", "unsafe")

            result = validate_capture(archive_path)

        self.assertFalse(result.valid)
        self.assertIn("unsafe member path", result.issues[0].message)

    def test_multiple_capture_roots_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            container = Path(temporary)
            create_test_capture(container, root_name="first")
            create_test_capture(container, root_name="second")

            result = validate_capture(container)

        self.assertFalse(result.valid)
        self.assertIn("Multiple capture roots", result.issues[0].message)

    def test_blank_distortion_values_parse_as_none(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            container = Path(temporary)
            create_test_capture(container)
            with open_capture(container) as source:
                root = discover_capture_root(source.members)
                records = read_odometry(source, f"{root}/odometry.csv")

        self.assertEqual(len(records), 3)
        self.assertIsNone(records[0].distortion_center_xy)

    def test_missing_confidence_frame_is_a_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            container = Path(temporary)
            root = create_test_capture(container)
            (root / "confidence" / "000001.png").unlink()

            result = validate_capture(container)

        self.assertTrue(result.valid)
        assert result.inventory is not None
        self.assertEqual(result.inventory.matched_frame_count, 2)
        self.assertEqual(result.inventory.missing_confidence_count, 1)
        self.assertIn(
            "frames_missing_confidence", {issue.code for issue in result.issues}
        )

    def test_duplicate_odometry_frame_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            container = Path(temporary)
            root = create_test_capture(container)
            odometry_path = root / "odometry.csv"
            rows = odometry_path.read_text(encoding="utf-8").splitlines()
            odometry_path.write_text(
                "\n".join([*rows, rows[1]]) + "\n", encoding="utf-8"
            )

            result = validate_capture(container)

        self.assertFalse(result.valid)
        self.assertIn("invalid_odometry", {issue.code for issue in result.issues})

    def test_malformed_camera_matrix_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            container = Path(temporary)
            root = create_test_capture(container)
            (root / "camera_matrix.csv").write_text("1,2\n3,4\n", encoding="utf-8")

            result = validate_capture(container)

        self.assertFalse(result.valid)
        self.assertIn("invalid_camera_matrix", {issue.code for issue in result.issues})


class KeyframeSelectionTests(unittest.TestCase):
    @staticmethod
    def make_frame(index: int) -> FrameRecord:
        frame_id = f"{index:06d}"
        pose = OdometryRecord(
            timestamp=float(index),
            frame_id=frame_id,
            position_xyz_m=(float(index), 0.0, 0.0),
            quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
            intrinsics_fx_fy_cx_cy=(100.0, 100.0, 2.0, 1.5),
        )
        return FrameRecord(
            frame_id=frame_id,
            depth_path=f"depth/{frame_id}.png",
            confidence_path=f"confidence/{frame_id}.png",
            odometry=pose,
        )

    def test_keyframes_are_deterministic_and_span_capture(self) -> None:
        frames = [self.make_frame(index) for index in reversed(range(5))]

        selected = select_keyframes(frames, max_frames=3)

        self.assertEqual(
            [frame.frame_id for frame in selected],
            ["000000", "000002", "000004"],
        )

    def test_match_frames_uses_ids_not_input_order(self) -> None:
        frames = [self.make_frame(index) for index in range(3)]
        depth = {frame.frame_id: frame.depth_path for frame in reversed(frames)}
        confidence = {
            frame.frame_id: frame.confidence_path for frame in frames
        }
        poses = [frame.odometry for frame in reversed(frames)]

        matches = match_frames(depth, confidence, poses)

        self.assertEqual(
            [frame.frame_id for frame in matches.frames],
            ["000000", "000001", "000002"],
        )

    def test_invalid_selection_parameters_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "stride"):
            select_keyframes([], stride=0)
        with self.assertRaisesRegex(ValueError, "max_frames"):
            select_keyframes([], max_frames=0)


if __name__ == "__main__":
    unittest.main()
