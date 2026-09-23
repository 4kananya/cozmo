"""CP11 tests: bounded plane-anchored drift correction, gates, and ablation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
from pydantic import ValidationError

from capture_factory import create_test_capture, create_zip
from cozmo_scan.drift import (
    DRIFT_ABLATION_JSON_FILENAME,
    DRIFT_ABLATION_REPORT_FILENAME,
    DriftError,
    _smooth,
    estimate_pose_offsets,
    judge_correction,
    render_drift_report,
    write_drift_outputs,
)
from cozmo_scan.models import (
    DriftAblation,
    DriftConfig,
    DriftCorrectionEvidence,
    DriftVariant,
)
from cozmo_scan.reconstruction import (
    ReconstructionResult,
    get_profile_config,
    offset_frame_pose,
    reconstruct_capture,
)

FLOOR_NORMAL = np.asarray([0.0, 1.0, 0.0])


def _variant(label: str, **overrides: object) -> DriftVariant:
    values: dict[str, object] = {
        "label": label,
        "output_point_count": 70_000,
        "floor_rmse_m": 0.0200,
        "floor_inlier_ratio": 0.20,
        "mean_wall_rmse_m": 0.0200,
        "wall_count": 6,
        "floor_area_m2": 16.0,
        "perimeter_m": 20.0,
        "length_m": 8.0,
        "width_m": 4.5,
        "boundary_support_ratio": 0.90,
        "outline_method": "occupancy_concave",
        "ceiling_height_m": 2.4,
        "opening_count": 1,
    }
    values.update(overrides)
    return DriftVariant.model_validate(values)


def _evidence() -> DriftCorrectionEvidence:
    return DriftCorrectionEvidence(
        measured_frame_count=120,
        corrected_frame_count=118,
        clamped_frame_count=0,
        maximum_absolute_offset_m=0.03,
        mean_absolute_offset_m=0.01,
        residual_trend_m=0.02,
        raw_residual_span_m=0.05,
    )


class SmoothingTests(unittest.TestCase):
    def test_smoothing_preserves_length_and_reduces_single_frame_noise(self) -> None:
        values = np.asarray([0.0, 0.0, 1.0, 0.0, 0.0])

        smoothed = _smooth(values, 3)

        self.assertEqual(len(smoothed), len(values))
        self.assertLess(float(smoothed.max()), 1.0)

    def test_smoothing_preserves_a_linear_trend(self) -> None:
        values = np.linspace(0.0, 1.0, 21)

        smoothed = _smooth(values, 5)

        np.testing.assert_allclose(smoothed, values, atol=1e-9)

    def test_short_and_unit_windows_are_returned_unchanged(self) -> None:
        values = np.asarray([0.3, -0.2])

        np.testing.assert_allclose(_smooth(values, 9), values)
        np.testing.assert_allclose(_smooth(np.linspace(0, 1, 5), 1), np.linspace(0, 1, 5))


class OffsetEstimationTests(unittest.TestCase):
    def test_linear_drift_produces_centred_opposing_offsets(self) -> None:
        frame_ids = tuple(f"{index:06d}" for index in range(21))
        residuals = np.linspace(-0.05, 0.05, 21)

        offsets, evidence = estimate_pose_offsets(
            frame_ids, residuals, FLOOR_NORMAL, DriftConfig()
        )

        self.assertEqual(evidence.measured_frame_count, 21)
        self.assertGreater(evidence.corrected_frame_count, 15)
        self.assertEqual(evidence.clamped_frame_count, 0)
        # The correction opposes the residual: a frame whose floor sits below the
        # fitted plane is lifted, and one sitting above is lowered.
        self.assertGreater(offsets[frame_ids[0]][1], 0.0)
        self.assertLess(offsets[frame_ids[-1]][1], 0.0)
        # Only the floor normal is touched; the correction is not a free 3D shift.
        for shift in offsets.values():
            self.assertAlmostEqual(shift[0], 0.0, places=12)
            self.assertAlmostEqual(shift[2], 0.0, places=12)
        # Centred, so the whole room is not translated.
        applied = np.asarray([shift[1] for shift in offsets.values()])
        self.assertAlmostEqual(float(applied.mean()), 0.0, delta=0.01)
        self.assertAlmostEqual(evidence.residual_trend_m, 0.10, delta=0.01)

    def test_offsets_are_clamped_to_the_configured_bound(self) -> None:
        frame_ids = tuple(f"{index:06d}" for index in range(21))
        residuals = np.linspace(-1.0, 1.0, 21)
        config = DriftConfig(maximum_offset_m=0.10)

        offsets, evidence = estimate_pose_offsets(
            frame_ids, residuals, FLOOR_NORMAL, config
        )

        self.assertGreater(evidence.clamped_frame_count, 0)
        self.assertLessEqual(evidence.maximum_absolute_offset_m, 0.10 + 1e-9)
        for shift in offsets.values():
            self.assertLessEqual(abs(shift[1]), 0.10 + 1e-9)

    def test_no_drift_produces_no_correction(self) -> None:
        frame_ids = tuple(f"{index:06d}" for index in range(15))
        residuals = np.zeros(15)

        offsets, evidence = estimate_pose_offsets(
            frame_ids, residuals, FLOOR_NORMAL, DriftConfig()
        )

        self.assertEqual(offsets, {})
        self.assertEqual(evidence.corrected_frame_count, 0)
        self.assertAlmostEqual(evidence.residual_trend_m, 0.0, places=9)

    def test_no_measured_frames_returns_empty_evidence(self) -> None:
        offsets, evidence = estimate_pose_offsets(
            (), np.asarray([]), FLOOR_NORMAL, DriftConfig()
        )

        self.assertEqual(offsets, {})
        self.assertEqual(evidence.measured_frame_count, 0)
        self.assertEqual(evidence.maximum_absolute_offset_m, 0.0)


class CorrectionGateTests(unittest.TestCase):
    def test_clear_residual_improvement_is_accepted(self) -> None:
        control = _variant("recorded_poses", floor_rmse_m=0.0200)
        corrected = _variant("plane_anchored_correction", floor_rmse_m=0.0160)

        accepted, reason = judge_correction(control, corrected, DriftConfig())

        self.assertTrue(accepted)
        self.assertIn("20.0%", reason)

    def test_insufficient_improvement_is_rejected(self) -> None:
        control = _variant("recorded_poses", floor_rmse_m=0.0200)
        corrected = _variant("plane_anchored_correction", floor_rmse_m=0.0199)

        accepted, reason = judge_correction(control, corrected, DriftConfig())

        self.assertFalse(accepted)
        self.assertIn("short of the required", reason)

    def test_a_worse_result_is_rejected(self) -> None:
        control = _variant("recorded_poses", floor_rmse_m=0.0200)
        corrected = _variant("plane_anchored_correction", floor_rmse_m=0.0300)

        accepted, _ = judge_correction(control, corrected, DriftConfig())

        self.assertFalse(accepted)

    def test_trading_the_floor_against_the_walls_is_rejected(self) -> None:
        control = _variant("recorded_poses", floor_rmse_m=0.0200, mean_wall_rmse_m=0.0200)
        corrected = _variant(
            "plane_anchored_correction", floor_rmse_m=0.0100, mean_wall_rmse_m=0.0400
        )

        accepted, reason = judge_correction(control, corrected, DriftConfig())

        self.assertFalse(accepted)
        self.assertIn("wall residual", reason)

    def test_losing_supported_walls_is_rejected(self) -> None:
        control = _variant("recorded_poses", floor_rmse_m=0.0200, wall_count=6)
        corrected = _variant(
            "plane_anchored_correction", floor_rmse_m=0.0100, wall_count=4
        )

        accepted, reason = judge_correction(control, corrected, DriftConfig())

        self.assertFalse(accepted)
        self.assertIn("wall planes", reason)

    def test_losing_boundary_support_is_rejected(self) -> None:
        control = _variant(
            "recorded_poses", floor_rmse_m=0.0200, boundary_support_ratio=0.90
        )
        corrected = _variant(
            "plane_anchored_correction",
            floor_rmse_m=0.0100,
            boundary_support_ratio=0.80,
        )

        accepted, reason = judge_correction(control, corrected, DriftConfig())

        self.assertFalse(accepted)
        self.assertIn("boundary", reason)

    def test_a_zero_control_residual_cannot_be_improved(self) -> None:
        control = _variant("recorded_poses", floor_rmse_m=0.0)
        corrected = _variant("plane_anchored_correction", floor_rmse_m=0.0)

        accepted, reason = judge_correction(control, corrected, DriftConfig())

        self.assertFalse(accepted)
        self.assertIn("zero", reason)


class AblationContractTests(unittest.TestCase):
    def _ablation(self, **overrides: object) -> DriftAblation:
        values: dict[str, object] = {
            "source_name": "single_room.zip",
            "input_sha256": "a" * 64,
            "decision": "correction_rejected",
            "decision_reason": "not enough improvement",
            "selected_variant": "recorded_poses",
            "drift": DriftConfig(enabled=True),
            "variants": (_variant("recorded_poses"),),
            "evidence": _evidence(),
            "elapsed_seconds": 1.0,
        }
        values.update(overrides)
        return DriftAblation.model_validate(values)

    def test_the_control_arm_is_mandatory(self) -> None:
        with self.assertRaises(ValidationError):
            self._ablation(variants=(_variant("plane_anchored_correction"),))

    def test_duplicate_arms_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            self._ablation(
                variants=(_variant("recorded_poses"), _variant("recorded_poses"))
            )

    def test_an_accepted_correction_must_be_the_published_geometry(self) -> None:
        with self.assertRaises(ValidationError):
            self._ablation(
                decision="correction_accepted", selected_variant="recorded_poses"
            )
        accepted = self._ablation(
            decision="correction_accepted",
            decision_reason="improved",
            selected_variant="plane_anchored_correction",
            variants=(_variant("recorded_poses"), _variant("plane_anchored_correction")),
        )
        self.assertEqual(accepted.selected_variant, "plane_anchored_correction")

    def test_a_rejected_correction_must_publish_the_control(self) -> None:
        with self.assertRaises(ValidationError):
            self._ablation(
                decision="correction_rejected",
                selected_variant="plane_anchored_correction",
                variants=(
                    _variant("recorded_poses"),
                    _variant("plane_anchored_correction"),
                ),
            )

    def test_an_unavailable_correction_cannot_publish_evidence(self) -> None:
        with self.assertRaises(ValidationError):
            self._ablation(decision="correction_unavailable", evidence=_evidence())
        unavailable = self._ablation(
            decision="correction_unavailable",
            decision_reason="too few measurable keyframes",
            evidence=None,
        )
        self.assertIsNone(unavailable.evidence)

    def test_round_trip_preserves_both_arms(self) -> None:
        ablation = self._ablation(
            variants=(_variant("recorded_poses"), _variant("plane_anchored_correction"))
        )

        decoded = DriftAblation.model_validate_json(ablation.model_dump_json())

        self.assertEqual(decoded.schema_version, "1.0.0")
        self.assertEqual([v.label for v in decoded.variants], [v.label for v in ablation.variants])


class PoseOffsetTests(unittest.TestCase):
    def test_offsetting_a_pose_moves_only_the_translation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = create_test_capture(Path(temporary))
            from cozmo_scan.dataset import build_capture_index, open_capture

            with open_capture(root) as source:
                frame = build_capture_index(source).frames[0]

        moved = offset_frame_pose(frame, (0.1, -0.2, 0.3))

        self.assertEqual(
            moved.odometry.position_xyz_m,
            (
                frame.odometry.position_xyz_m[0] + 0.1,
                frame.odometry.position_xyz_m[1] - 0.2,
                frame.odometry.position_xyz_m[2] + 0.3,
            ),
        )
        self.assertEqual(moved.odometry.quaternion_xyzw, frame.odometry.quaternion_xyzw)
        self.assertEqual(
            moved.odometry.intrinsics_fx_fy_cx_cy, frame.odometry.intrinsics_fx_fy_cx_cy
        )
        self.assertEqual(moved.frame_id, frame.frame_id)
        self.assertIs(offset_frame_pose(frame, None), frame)

    def test_recorded_poses_remain_the_reproducible_control(self) -> None:
        config = get_profile_config("test")
        with tempfile.TemporaryDirectory() as temporary:
            container = Path(temporary)
            root = create_test_capture(container, confidence_value=2)
            archive = container / "capture.zip"
            create_zip(root, archive)

            control = reconstruct_capture(archive, config)
            repeated = reconstruct_capture(archive, config, pose_offsets_xyz_m=None)
            shifted = reconstruct_capture(
                archive,
                config,
                pose_offsets_xyz_m={"000001": (0.0, 5.0, 0.0)},
            )

        np.testing.assert_allclose(control.points_xyz_m, repeated.points_xyz_m)
        self.assertFalse(
            np.allclose(
                np.sort(control.points_xyz_m[:, 1]),
                np.sort(shifted.points_xyz_m[:, 1]),
            ),
            msg="a pose offset must change the reconstructed cloud",
        )
        self.assertGreater(
            float(shifted.points_xyz_m[:, 1].max()),
            float(control.points_xyz_m[:, 1].max()) + 1.0,
        )


class DriftReportTests(unittest.TestCase):
    def _ablation(self, *, single_arm: bool) -> DriftAblation:
        variants = (
            (_variant("recorded_poses"),)
            if single_arm
            else (_variant("recorded_poses"), _variant("plane_anchored_correction"))
        )
        return DriftAblation.model_validate(
            {
                "source_name": "single_room.zip",
                "input_sha256": "b" * 64,
                "decision": (
                    "correction_unavailable" if single_arm else "correction_rejected"
                ),
                "decision_reason": "reason recorded",
                "selected_variant": "recorded_poses",
                "drift": DriftConfig(enabled=True),
                "variants": variants,
                "evidence": None if single_arm else _evidence(),
                "elapsed_seconds": 2.0,
                "warnings": () if single_arm else ("rolled back",),
            }
        )

    def test_report_states_poses_are_not_used_as_is(self) -> None:
        report = render_drift_report(self._ablation(single_arm=False))

        self.assertIn("not** used as-is", report)
        self.assertIn("recorded_poses", report)
        self.assertIn("plane_anchored_correction", report)
        self.assertIn("Footprint area", report)
        self.assertIn("Correction magnitude", report)
        self.assertIn("rolled back", report)
        # The closure proxy must not be offered as evidence of accuracy.
        self.assertIn("not used as evidence", report)

    def test_single_arm_report_explains_the_missing_arm(self) -> None:
        report = render_drift_report(self._ablation(single_arm=True))

        self.assertIn("Only the recorded-pose control is present", report)
        self.assertNotIn("Correction magnitude", report)

    def test_outputs_are_published_together_with_overwrite_protection(self) -> None:
        ablation = self._ablation(single_arm=False)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "drift"
            paths = write_drift_outputs(ablation, directory)

            self.assertEqual(
                sorted(path.name for path in directory.iterdir()),
                sorted([DRIFT_ABLATION_JSON_FILENAME, DRIFT_ABLATION_REPORT_FILENAME]),
            )
            for path in paths.values():
                self.assertTrue(path.exists())

            unrelated = directory / "keep.txt"
            unrelated.write_text("keep", encoding="utf-8")
            with self.assertRaises(DriftError):
                write_drift_outputs(ablation, directory)

            write_drift_outputs(ablation, directory, overwrite=True)
            self.assertEqual(unrelated.read_text(encoding="utf-8"), "keep")
            decoded = DriftAblation.model_validate_json(
                (directory / DRIFT_ABLATION_JSON_FILENAME).read_text(encoding="utf-8")
            )
            self.assertEqual(decoded.decision, ablation.decision)


if __name__ == "__main__":
    unittest.main()
