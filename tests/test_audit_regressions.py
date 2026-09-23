"""Regression tests for adversarial audit findings.

Each test names the audit finding it pins. Every test in this file was written
before the corresponding fix and observed to fail, so the suite records the
defect rather than only the repair.
"""

from __future__ import annotations

import unittest
from dataclasses import replace

import numpy as np
from pydantic import ValidationError

from cozmo_scan.drift import judge_correction
from cozmo_scan.floorplan import analyze_structure
from cozmo_scan.models import DriftConfig, DriftVariant, StructureConfig
from cozmo_scan.openings import wall_sort_angle_deg
from structure_factory import make_room_with_openings


def _variant(label: str, **overrides: object) -> DriftVariant:
    values: dict[str, object] = {
        "label": label,
        "output_point_count": 100_000,
        "floor_rmse_m": 0.0200,
        "floor_inlier_ratio": 0.220,
        "mean_wall_rmse_m": 0.0300,
        "wall_count": 6,
        "floor_area_m2": 78.0,
        "perimeter_m": 33.0,
        "length_m": 10.9,
        "width_m": 9.4,
        "boundary_support_ratio": 0.574,
        "outline_method": "convex_hull",
        "ceiling_height_m": None,
        "opening_count": 2,
    }
    values.update(overrides)
    return DriftVariant.model_validate(values)


def _carve(reconstruction, mask_fn):
    points = np.asarray(reconstruction.points_xyz_m, dtype=np.float64)
    keep = ~mask_fn(points)
    return replace(reconstruction, points_xyz_m=points[keep].astype(np.float32))


class UnscannedWallIsNotAnOpeningTests(unittest.TestCase):
    """A1/A2: an unobserved wall patch must never be published as an opening.

    A bin with no returns is *unknown*, not empty. Curtains, mirrors, dark or
    specular surfaces and grazing incidence all produce a full-height hole in
    the wall points while the floor and ceiling stay intact. Publishing that as
    a doorway is a phantom, and the opening evaluation gate penalises a
    phantom exactly as hard as a miss.
    """

    def test_mid_wall_unscanned_patch_publishes_nothing(self) -> None:
        carved = _carve(
            make_room_with_openings(door=False, window=False),
            lambda p: (
                (p[:, 1] > 0.05)
                & (p[:, 1] < 2.45)
                & (np.abs(p[:, 2] + 2.0) < 0.15)
                & (np.abs(p[:, 0] - 0.5) < 0.40)
            ),
        )

        analysis = analyze_structure(carved).summary.openings

        assert analysis is not None
        self.assertEqual(
            [o.classification for o in analysis.openings],
            [],
            msg="an unscanned wall patch was published as an opening",
        )

    def test_unscanned_patch_records_why_it_was_refused(self) -> None:
        carved = _carve(
            make_room_with_openings(door=False, window=False),
            lambda p: (
                (p[:, 1] > 0.05)
                & (p[:, 1] < 2.45)
                & (np.abs(p[:, 2] + 2.0) < 0.15)
                & (np.abs(p[:, 0] - 0.5) < 0.40)
            ),
        )

        analysis = analyze_structure(carved).summary.openings

        assert analysis is not None
        self.assertTrue(analysis.rejections, "the refusal must be recorded")
        self.assertTrue(
            any(
                "observ" in rejection.reason or "behind" in rejection.reason
                for rejection in analysis.rejections
            ),
            msg=f"no rejection explained the missing observation: {analysis.rejections}",
        )

    def test_a_real_opening_with_space_behind_it_still_publishes(self) -> None:
        # The guard must not simply suppress everything: the same fixture with
        # genuine space beyond the door must still be detected.
        analysis = analyze_structure(make_room_with_openings()).summary.openings

        assert analysis is not None
        self.assertTrue(
            analysis.openings,
            msg="the pass-through guard suppressed a genuine opening",
        )


class OpeningWidthBoundsTests(unittest.TestCase):
    """A6/A7: the published width must respect the configured bounds.

    The maximum was checked against the pre-refinement bin width, so refinement
    could push the published width past the configured maximum.
    """

    def test_refined_width_never_exceeds_the_configured_maximum(self) -> None:
        # The synthetic door is 0.90 m coarse and refines slightly wider, so a
        # maximum just above the coarse width is the minimal reproduction.
        config = StructureConfig(opening_maximum_width_m=0.902)

        analysis = analyze_structure(
            make_room_with_openings(window=False), config
        ).summary.openings

        assert analysis is not None
        for opening in analysis.openings:
            self.assertLessEqual(
                opening.width_m,
                config.opening_maximum_width_m,
                msg=(
                    f"{opening.opening_id} published {opening.width_m:.4f} m, above "
                    f"the configured {config.opening_maximum_width_m} m maximum"
                ),
            )

    def test_published_width_respects_both_bounds_on_every_fixture(self) -> None:
        config = StructureConfig()
        for kwargs in ({}, {"window": False}, {"door": False}):
            analysis = analyze_structure(
                make_room_with_openings(**kwargs), config
            ).summary.openings
            assert analysis is not None
            for opening in analysis.openings:
                self.assertGreaterEqual(
                    opening.width_m, config.opening_minimum_width_m
                )
                self.assertLessEqual(opening.width_m, config.opening_maximum_width_m)


class WallIdentityStabilityTests(unittest.TestCase):
    """A11: the wall ordering key must not wrap at axis-aligned orientations.

    `angle % 180` is discontinuous exactly where real rooms sit. Two normals a
    microradian apart must not sort to opposite ends of the ordering, because
    the ordering names every wall and therefore every opening.
    """

    def test_sort_key_is_continuous_across_the_zero_crossing(self) -> None:
        above = wall_sort_angle_deg(np.asarray([1.0, 1e-6]))
        below = wall_sort_angle_deg(np.asarray([1.0, -1e-6]))

        self.assertLess(
            abs(above - below),
            0.01,
            msg=(
                f"a microradian normal flip moved the sort key from {below} to "
                f"{above}; wall and opening identifiers are not stable"
            ),
        )

    def test_opposite_normals_of_one_wall_share_a_sort_key(self) -> None:
        forward = wall_sort_angle_deg(np.asarray([0.0, 1.0]))
        backward = wall_sort_angle_deg(np.asarray([0.0, -1.0]))

        self.assertAlmostEqual(forward, backward, places=6)


class NoUnsupportableRegionClaimTests(unittest.TestCase):
    """A5: region identifiers were regenerated per wall and are not joinable.

    D-052 already refuses to call occupancy fragments rooms. Publishing a
    per-wall `R01`/`R02` alongside that refusal implied a property-wide region
    graph that does not exist, so the claim is withdrawn in favour of measured
    far-side evidence.
    """

    def test_openings_do_not_publish_a_global_region_identifier(self) -> None:
        analysis = analyze_structure(make_room_with_openings()).summary.openings

        assert analysis is not None
        for opening in analysis.openings:
            self.assertFalse(
                hasattr(opening, "adjacent_region_id")
                and getattr(opening, "adjacent_region_id") is not None,
                msg="a per-wall region identifier is still being published",
            )


class CoupledThresholdTests(unittest.TestCase):
    """A10: thresholds that must relate to each other are now validated.

    Two planes closer than the duplicate tolerance are merged into one wall. If
    the profiling band reached that far, two walls that survived de-duplication
    would capture each other's surface points and each would fill the other's
    openings, silently deleting them.
    """

    def test_band_wider_than_the_duplicate_tolerance_is_refused(self) -> None:
        with self.assertRaises(ValidationError):
            StructureConfig(
                opening_wall_band_m=0.20, duplicate_wall_offset_tolerance_m=0.15
            )

    def test_probe_must_reach_beyond_the_band(self) -> None:
        with self.assertRaises(ValidationError):
            StructureConfig(opening_wall_band_m=0.12, opening_probe_distance_m=0.10)

    def test_defaults_satisfy_their_own_invariants(self) -> None:
        config = StructureConfig()

        self.assertLess(
            config.opening_wall_band_m, config.duplicate_wall_offset_tolerance_m
        )
        self.assertGreater(
            config.opening_probe_distance_m, config.opening_wall_band_m
        )


class SupportQuantisationTests(unittest.TestCase):
    """A21: a support threshold must be finer than the probe grid that measures it.

    With nine probes every floor-support ratio was a multiple of 1/9, so a
    configured 0.60 behaved as 0.667 and 0.85 as 0.889. The configured numbers
    were not the numbers in force.
    """

    def test_floor_probes_resolve_the_configured_thresholds(self) -> None:
        from cozmo_scan.openings import (
            FLOOR_PROBE_SAMPLES,
            HIGH_CONFIDENCE_FLOOR_SUPPORT,
        )

        resolution = 1.0 / FLOOR_PROBE_SAMPLES
        config = StructureConfig()

        self.assertLess(resolution, 0.05)
        for threshold in (
            config.opening_minimum_floor_support,
            config.opening_minimum_far_floor_support,
            HIGH_CONFIDENCE_FLOOR_SUPPORT,
        ):
            nearest = round(threshold * FLOOR_PROBE_SAMPLES) / FLOOR_PROBE_SAMPLES
            self.assertLess(
                abs(nearest - threshold),
                resolution,
                msg=f"threshold {threshold} is not representable on the probe grid",
            )

    def test_high_flank_confidence_states_what_it_actually_requires(self) -> None:
        from cozmo_scan.openings import HIGH_CONFIDENCE_FLANK_SUPPORT

        # Flank support is quantised to 1/opening_flank_bins, so any value above
        # the last step behaves as 1.0. The constant must say so.
        self.assertEqual(HIGH_CONFIDENCE_FLANK_SUPPORT, 1.0)


class CoverageLimitedHeightTests(unittest.TestCase):
    """A9: a wall height bounded by coverage must be declared as such.

    `opening_door_minimum_height_m` reads as absolute but is compared against a
    void bounded by the observed wall height, so on a wall whose top was never
    scanned no doorway can reach it.
    """

    def test_a_capture_without_a_ceiling_flags_its_walls(self) -> None:
        from structure_factory import make_synthetic_room

        analysis = analyze_structure(
            make_synthetic_room(include_ceiling=False)
        ).summary.openings

        assert analysis is not None
        self.assertTrue(analysis.walls)
        self.assertTrue(
            all(wall.height_is_coverage_limited for wall in analysis.walls),
            msg="walls under an undetected ceiling must be flagged coverage-limited",
        )

    def test_a_capture_with_a_ceiling_does_not_flag_full_height_walls(self) -> None:
        analysis = analyze_structure(make_room_with_openings()).summary.openings

        assert analysis is not None
        room_walls = [wall for wall in analysis.walls if wall.length_m > 3.0]
        self.assertTrue(room_walls)
        self.assertFalse(
            any(wall.height_is_coverage_limited for wall in room_walls),
            msg="fully scanned walls under a detected ceiling must not be flagged",
        )


class ShortWallIsNotSilentTests(unittest.TestCase):
    """A22: a wall too short to host an opening must say so.

    The old `opening_minimum_wall_bin_count` could never fire at the defaults,
    while walls between roughly 0.60 m and 1.05 m were published as identified
    segments that could never produce an opening, with nothing recorded.
    """

    def test_a_wall_too_short_for_flanks_records_a_reason(self) -> None:
        # Demanding a very wide flank makes every fixture wall too short.
        config = StructureConfig(opening_flank_bins=60)

        analysis = analyze_structure(
            make_room_with_openings(), config
        ).summary.openings

        assert analysis is not None
        self.assertEqual(analysis.openings, ())
        self.assertTrue(
            any("too short" in rejection.reason for rejection in analysis.rejections),
            msg=f"no rejection explained the short wall: {analysis.rejections}",
        )


class DriftGateAttritionTests(unittest.TestCase):
    """A3: the acceptance gate must not be satisfiable by losing points.

    `floor_rmse_m` is an RMS over a band-limited inlier subset recomputed per
    arm, so shedding inliers lowers it without improving alignment. Verified on
    real data: the accepted arm's residual was 10.3% better on the published
    metric and 20.7% worse at matched point count.
    """

    def test_a_correction_that_sheds_inliers_is_rejected(self) -> None:
        control = _variant("recorded_poses", floor_rmse_m=0.01576, floor_inlier_ratio=0.2249, output_point_count=171_537)
        corrected = _variant(
            "plane_anchored_correction",
            floor_rmse_m=0.01413,
            floor_inlier_ratio=0.2184,
            output_point_count=169_820,
        )

        accepted, reason = judge_correction(control, corrected, DriftConfig())

        self.assertFalse(
            accepted,
            msg=f"accepted a correction that lost 1,717 points and 2.9% inlier support: {reason}",
        )

    def test_the_rejection_names_the_attrition(self) -> None:
        control = _variant("recorded_poses", floor_rmse_m=0.0200, floor_inlier_ratio=0.2200, output_point_count=100_000)
        corrected = _variant(
            "plane_anchored_correction",
            floor_rmse_m=0.0150,
            floor_inlier_ratio=0.2000,
            output_point_count=95_000,
        )

        _, reason = judge_correction(control, corrected, DriftConfig())

        self.assertTrue(
            "point" in reason or "inlier" in reason or "support" in reason,
            msg=f"rejection reason did not mention attrition: {reason}",
        )

    def test_an_honest_improvement_is_still_accepted(self) -> None:
        # The gate must stay useful: same point count and inlier support, real
        # residual improvement.
        control = _variant("recorded_poses", floor_rmse_m=0.0200)
        corrected = _variant("plane_anchored_correction", floor_rmse_m=0.0160)

        accepted, reason = judge_correction(control, corrected, DriftConfig())

        self.assertTrue(accepted, msg=f"rejected a genuine improvement: {reason}")


if __name__ == "__main__":
    unittest.main()
