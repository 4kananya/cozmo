"""CP10 tests: wall identity, opening evidence gates, adjacency, and contracts."""

from __future__ import annotations

import unittest
from dataclasses import replace

import numpy as np
from pydantic import ValidationError

from cozmo_scan.floorplan import analyze_structure
from cozmo_scan.models import (
    Opening,
    OpeningAnalysis,
    OpeningEvidence,
    RoomAdjacency,
    RunResult,
    StructureConfig,
    StructureSummary,
    WallSegment,
)
from structure_factory import (
    make_room_with_openings,
    make_synthetic_room,
    make_two_rooms_with_doorway,
)

#: The assignment scores opening widths at 2 cm; synthetic truth must clear it.
OPENING_WIDTH_TOLERANCE_M = 0.02
DOOR_WIDTH_M = 0.90
WINDOW_WIDTH_M = 1.20
WINDOW_SILL_M = 0.90
WINDOW_HEAD_M = 2.00


def _analysis(**kwargs: object) -> OpeningAnalysis:
    summary = analyze_structure(make_room_with_openings(**kwargs)).summary
    analysis = summary.openings
    assert analysis is not None
    return analysis


class WallIdentityTests(unittest.TestCase):
    def test_walls_receive_finite_extent_and_stable_identifiers(self) -> None:
        analysis = _analysis()

        self.assertEqual(analysis.status, "available")
        # The fixture includes a corridor beyond the doorway and a surface beyond
        # the window, so more than the four room walls are identified.
        self.assertGreaterEqual(len(analysis.walls), 4)
        self.assertEqual(
            [wall.wall_id for wall in analysis.walls],
            [f"W{index:02d}" for index in range(1, len(analysis.walls) + 1)],
        )
        lengths = sorted(round(wall.length_m, 1) for wall in analysis.walls)
        for expected in (4.0, 6.0):
            self.assertIn(expected, lengths)
        for wall in analysis.walls:
            self.assertGreater(wall.height_m, 2.0)
            self.assertAlmostEqual(
                float(np.linalg.norm(np.asarray(wall.normal_xy))), 1.0, places=6
            )
            start = np.asarray(wall.start_xy_m)
            end = np.asarray(wall.end_xy_m)
            self.assertAlmostEqual(
                float(np.linalg.norm(end - start)), wall.length_m, places=6
            )

    def test_identifiers_and_openings_are_deterministic_across_runs(self) -> None:
        first = _analysis()
        second = _analysis()

        self.assertEqual(first.model_dump_json(), second.model_dump_json())


class OpeningDetectionTests(unittest.TestCase):
    def test_door_and_window_are_measured_within_the_assignment_tolerance(self) -> None:
        analysis = _analysis()

        by_class = {opening.classification: opening for opening in analysis.openings}
        self.assertEqual(sorted(by_class), ["door_like", "window_like"])

        door = by_class["door_like"]
        self.assertLess(abs(door.width_m - DOOR_WIDTH_M), OPENING_WIDTH_TOLERANCE_M)
        self.assertLessEqual(door.evidence.sill_height_m or 0.0, 0.20)
        self.assertGreaterEqual(door.height_m or 0.0, 1.50)

        window = by_class["window_like"]
        self.assertLess(abs(window.width_m - WINDOW_WIDTH_M), OPENING_WIDTH_TOLERANCE_M)
        self.assertAlmostEqual(window.evidence.sill_height_m or 0.0, WINDOW_SILL_M, delta=0.10)
        self.assertAlmostEqual(window.evidence.head_height_m or 0.0, WINDOW_HEAD_M, delta=0.10)

        for opening in analysis.openings:
            # Every published opening must be evidenced from behind.
            self.assertTrue(
                opening.evidence.pass_through_point_count
                >= 1
                or opening.evidence.far_floor_support > 0
            )
            self.assertEqual(opening.evidence.void_point_count, 0)
            self.assertIn(opening.wall_id, {wall.wall_id for wall in analysis.walls})
            self.assertTrue(opening.opening_id.startswith(opening.wall_id))

    def test_each_opening_is_found_independently(self) -> None:
        door_only = _analysis(window=False)
        window_only = _analysis(door=False)

        self.assertEqual(
            [opening.classification for opening in door_only.openings], ["door_like"]
        )
        self.assertEqual(
            [opening.classification for opening in window_only.openings], ["window_like"]
        )

    def test_solid_walls_produce_no_candidate_and_no_opening(self) -> None:
        analysis = _analysis(door=False, window=False)

        self.assertEqual(analysis.status, "available")
        self.assertEqual(analysis.openings, ())
        self.assertEqual(analysis.candidate_count, 0)
        self.assertEqual(analysis.rejections, ())

    def test_sparse_walls_are_rejected_with_recorded_reasons(self) -> None:
        analysis = _analysis(wall_points=1200)

        self.assertEqual(analysis.status, "available")
        self.assertEqual(analysis.openings, ())
        self.assertGreater(analysis.candidate_count, 0)
        # Wall-level refusals are recorded alongside per-void ones, so the counts
        # are not required to match; every refusal must carry a reason.
        self.assertGreaterEqual(len(analysis.rejections), 1)
        for rejection in analysis.rejections:
            self.assertTrue(rejection.reason)

    def test_void_at_the_scanned_wall_extent_is_not_an_opening(self) -> None:
        # A void flush against the end of the scanned wall is a coverage
        # boundary. Publishing it would be a phantom opening.
        reconstruction = make_room_with_openings(door=False, window=False)
        points = np.asarray(reconstruction.points_xyz_m, dtype=np.float64)
        cut = (
            (points[:, 1] > 0.06)
            & (np.abs(points[:, 2] + 2.0) < 0.10)
            & (points[:, 0] > 2.2)
            & (points[:, 0] < 2.9)
        )
        trimmed = replace(
            reconstruction, points_xyz_m=points[~cut].astype(np.float32)
        )
        analysis = analyze_structure(trimmed).summary.openings

        assert analysis is not None
        self.assertEqual(analysis.openings, ())

    def test_missing_floor_coverage_in_front_of_a_void_is_rejected(self) -> None:
        reconstruction = make_room_with_openings(window=False)
        points = np.asarray(reconstruction.points_xyz_m, dtype=np.float64)
        unscanned_floor = (
            (points[:, 1] < 0.05)
            & (points[:, 2] < -1.1)
            & (np.abs(points[:, 0]) < 1.4)
        )
        trimmed = replace(
            reconstruction,
            points_xyz_m=points[~unscanned_floor].astype(np.float32),
        )
        analysis = analyze_structure(trimmed).summary.openings

        assert analysis is not None
        self.assertEqual(analysis.openings, ())
        self.assertTrue(
            any("scanned" in rejection.reason for rejection in analysis.rejections),
            msg=f"expected a coverage rejection, got {analysis.rejections}",
        )

    def test_detection_can_be_disabled_and_says_so(self) -> None:
        config = StructureConfig(detect_openings=False)
        summary = analyze_structure(make_room_with_openings(), config).summary
        analysis = summary.openings

        assert analysis is not None
        self.assertEqual(analysis.status, "unavailable")
        self.assertIn("disabled", analysis.unavailable_reason or "")
        self.assertEqual(analysis.openings, ())
        self.assertTrue(
            any("unavailable" in warning for warning in summary.warnings)
        )

    def test_no_wall_plane_makes_the_analysis_unavailable(self) -> None:
        config = StructureConfig(maximum_wall_planes=0)
        analysis = analyze_structure(make_room_with_openings(), config).summary.openings

        assert analysis is not None
        self.assertEqual(analysis.status, "unavailable")
        self.assertEqual(analysis.walls, ())
        self.assertIn("wall plane", analysis.unavailable_reason or "")

    def test_empty_opening_list_is_reported_as_unproven_not_absent(self) -> None:
        summary = analyze_structure(make_synthetic_room()).summary

        assert summary.openings is not None
        if not summary.openings.openings and summary.openings.status == "available":
            self.assertTrue(
                any(
                    "not as absent" in warning or "evidence gates" in warning
                    for warning in summary.warnings
                ),
                msg=f"warnings did not qualify the empty result: {summary.warnings}",
            )


class AdjacencyTests(unittest.TestCase):
    def test_doorway_between_two_scanned_rooms_creates_adjacency(self) -> None:
        analysis = analyze_structure(make_two_rooms_with_doorway()).summary.openings

        assert analysis is not None
        self.assertEqual(len(analysis.openings), 1)
        opening = analysis.openings[0]
        self.assertEqual(opening.classification, "door_like")
        self.assertLess(abs(opening.width_m - DOOR_WIDTH_M), OPENING_WIDTH_TOLERANCE_M)
        self.assertEqual(opening.other_side, "observed_space")
        self.assertIsNotNone(opening.far_side_area_m2)

        self.assertEqual(len(analysis.adjacency), 1)
        link = analysis.adjacency[0]
        self.assertEqual(link.opening_id, opening.opening_id)
        self.assertEqual(link.wall_id, opening.wall_id)
        self.assertGreater(link.near_side_area_m2, 1.0)
        self.assertGreater(link.far_side_area_m2, 1.0)
        self.assertAlmostEqual(link.far_side_area_m2, opening.far_side_area_m2)

    def test_solid_shared_wall_claims_neither_opening_nor_adjacency(self) -> None:
        analysis = analyze_structure(
            make_two_rooms_with_doorway(doorway=False)
        ).summary.openings

        assert analysis is not None
        self.assertEqual(analysis.openings, ())
        self.assertEqual(analysis.adjacency, ())

    def test_a_void_with_nothing_behind_it_keeps_the_far_side_unknown(self) -> None:
        # No space beyond means no evidence, so nothing may be published at all.
        analysis = _analysis(space_beyond=False)

        self.assertEqual(analysis.openings, ())
        self.assertEqual(analysis.adjacency, ())


class OpeningContractTests(unittest.TestCase):
    def _evidence(self) -> OpeningEvidence:
        return OpeningEvidence(
            profile_bin_count=100,
            gap_bin_count=18,
            bin_size_m=0.05,
            left_flank_support=1.0,
            right_flank_support=1.0,
            interior_floor_support=1.0,
            void_point_count=0,
            wall_height_m=2.4,
        )

    def _wall(self, wall_id: str = "W01") -> WallSegment:
        return WallSegment(
            wall_id=wall_id,
            plane_index=0,
            start_xy_m=(0.0, 0.0),
            end_xy_m=(4.0, 0.0),
            normal_xy=(0.0, 1.0),
            length_m=4.0,
            height_m=2.4,
            inlier_count=900,
            solid_bin_ratio=0.9,
            rmse_m=0.01,
        )

    def _opening(self, opening_id: str = "W01-O1", wall_id: str = "W01") -> Opening:
        return Opening(
            opening_id=opening_id,
            wall_id=wall_id,
            classification="door_like",
            confidence="high",
            width_m=0.9,
            height_m=2.0,
            centre_xy_m=(2.0, 0.0),
            start_xy_m=(1.55, 0.0),
            end_xy_m=(2.45, 0.0),
            evidence=self._evidence(),
        )

    def test_unavailable_analysis_cannot_publish_openings(self) -> None:
        with self.assertRaises(ValidationError):
            OpeningAnalysis(
                status="unavailable",
                unavailable_reason="sparse",
                openings=(self._opening(),),
            )

    def test_unavailable_analysis_requires_a_reason(self) -> None:
        with self.assertRaises(ValidationError):
            OpeningAnalysis(status="unavailable")

    def test_available_analysis_rejects_duplicate_and_dangling_identifiers(self) -> None:
        with self.assertRaises(ValidationError):
            OpeningAnalysis(
                status="available",
                walls=(self._wall(), self._wall()),
            )
        with self.assertRaises(ValidationError):
            OpeningAnalysis(
                status="available",
                walls=(self._wall(),),
                openings=(self._opening(wall_id="W09"),),
            )
        with self.assertRaises(ValidationError):
            OpeningAnalysis(
                status="available",
                walls=(self._wall(),),
                openings=(self._opening(),),
                adjacency=(
                    RoomAdjacency(
                        opening_id="W01-O9",
                        wall_id="W01",
                        near_side_area_m2=16.0,
                        far_side_area_m2=12.0,
                        probe_agreement=3,
                    ),
                ),
            )

    def test_observed_far_side_must_report_its_measured_area(self) -> None:
        base = self._opening().model_dump()
        with self.assertRaises(ValidationError):
            Opening.model_validate({**base, "other_side": "observed_space"})
        with self.assertRaises(ValidationError):
            Opening.model_validate({**base, "far_side_area_m2": 12.0})
        linked = Opening.model_validate(
            {**base, "other_side": "observed_space", "far_side_area_m2": 12.0}
        )
        self.assertEqual(linked.far_side_area_m2, 12.0)

    def test_openings_survive_a_structure_summary_round_trip(self) -> None:
        summary = analyze_structure(make_room_with_openings()).summary
        decoded = StructureSummary.model_validate_json(summary.model_dump_json())

        self.assertEqual(decoded.schema_version, "1.4.0")
        assert decoded.openings is not None
        assert summary.openings is not None
        self.assertEqual(
            [opening.opening_id for opening in decoded.openings.openings],
            [opening.opening_id for opening in summary.openings.openings],
        )

    def test_results_without_an_opening_analysis_remain_valid(self) -> None:
        summary = analyze_structure(make_room_with_openings()).summary
        legacy = summary.model_copy(
            update={"openings": None, "schema_version": "1.1.0"}
        )
        decoded = StructureSummary.model_validate_json(legacy.model_dump_json())

        self.assertIsNone(decoded.openings)
        self.assertEqual(decoded.schema_version, "1.1.0")


class OpeningEvaluationTests(unittest.TestCase):
    def test_evaluator_scores_named_openings_and_counts_phantoms(self) -> None:
        from cozmo_scan.benchmark import _prediction_from_result

        summary = analyze_structure(make_room_with_openings()).summary
        assert summary.openings is not None
        analysis = summary.openings

        stub = RunResult.model_construct(
            room=type(
                "Room",
                (),
                {
                    "floor_plan": summary.floor_plan,
                    "ceiling_height_m": summary.ceiling_height_m,
                    "openings": analysis,
                },
            )()
        )
        prediction = _prediction_from_result(stub)

        self.assertEqual(
            set(prediction.openings_m),
            {opening.opening_id for opening in analysis.openings},
        )
        self.assertEqual(
            set(prediction.walls_m), {wall.wall_id for wall in analysis.walls}
        )
        for opening in analysis.openings:
            self.assertAlmostEqual(
                prediction.openings_m[opening.opening_id], opening.width_m
            )

    def test_unavailable_analysis_yields_no_prediction(self) -> None:
        from cozmo_scan.benchmark import _prediction_from_result

        summary = analyze_structure(make_room_with_openings()).summary
        unavailable = OpeningAnalysis(
            status="unavailable", unavailable_reason="disabled"
        )
        stub = RunResult.model_construct(
            room=type(
                "Room",
                (),
                {
                    "floor_plan": summary.floor_plan,
                    "ceiling_height_m": None,
                    "openings": unavailable,
                },
            )()
        )
        prediction = _prediction_from_result(stub)

        self.assertEqual(prediction.openings_m, {})
        self.assertEqual(prediction.walls_m, {})


class OpeningRenderTests(unittest.TestCase):
    def test_renderers_draw_openings_only_when_they_exist(self) -> None:
        from cozmo_scan.outputs import _opening_segment_pixels, _opening_panel_lines

        summary = analyze_structure(make_room_with_openings()).summary
        vertices = np.asarray(summary.floor_plan.vertices_xy_m, dtype=np.float64)
        segments = _opening_segment_pixels(
            summary, vertices, width=1200, height=800, panel_width=330
        )

        assert summary.openings is not None
        self.assertEqual(len(segments), len(summary.openings.openings))
        self.assertTrue(
            any("Openings:" in line for line in _opening_panel_lines(summary))
        )

        unavailable = summary.model_copy(
            update={
                "openings": OpeningAnalysis(
                    status="unavailable", unavailable_reason="disabled"
                )
            }
        )
        self.assertEqual(
            _opening_segment_pixels(
                unavailable, vertices, width=1200, height=800, panel_width=330
            ),
            [],
        )
        self.assertIn("unavailable", " ".join(_opening_panel_lines(unavailable)))

    def test_panel_never_implies_a_verified_absence(self) -> None:
        from cozmo_scan.outputs import _opening_panel_lines

        summary = analyze_structure(make_room_with_openings(door=False, window=False)).summary
        lines = " ".join(_opening_panel_lines(summary))

        self.assertIn("none passed", lines)
        self.assertIn("not evidence of absence", lines)


if __name__ == "__main__":
    unittest.main()
