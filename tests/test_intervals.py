"""Tests for resampling measurement intervals."""

from __future__ import annotations

import unittest

import numpy as np
from pydantic import ValidationError

from cozmo_scan.floorplan import analyze_structure
from cozmo_scan.intervals import (
    bootstrap_floor_plan,
    build_measurement_intervals,
    percentile_interval,
)
from cozmo_scan.models import IntervalConfig, MeasurementInterval, StructureConfig
from structure_factory import make_room_with_openings, make_synthetic_room


def _analysis(*, include_ceiling: bool = True):
    return analyze_structure(make_synthetic_room(include_ceiling=include_ceiling))


class PercentileIntervalTests(unittest.TestCase):
    def test_bounds_bracket_the_requested_mass(self) -> None:
        samples = np.linspace(0.0, 100.0, 1001)

        low, high = percentile_interval(samples, 0.95)

        self.assertAlmostEqual(low, 2.5, delta=0.2)
        self.assertAlmostEqual(high, 97.5, delta=0.2)

    def test_a_wider_level_gives_a_wider_interval(self) -> None:
        samples = np.linspace(0.0, 1.0, 501)

        narrow = percentile_interval(samples, 0.50)
        wide = percentile_interval(samples, 0.99)

        # The wider level must contain the narrower one.
        self.assertLessEqual(wide[0], narrow[0])
        self.assertGreaterEqual(wide[1], narrow[1])
        self.assertGreater(wide[1] - wide[0], narrow[1] - narrow[0])

    def test_a_constant_distribution_gives_a_zero_width_interval(self) -> None:
        low, high = percentile_interval(np.full(50, 2.4), 0.95)

        self.assertAlmostEqual(low, 2.4)
        self.assertAlmostEqual(high, 2.4)

    def test_one_sample_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            percentile_interval(np.asarray([1.0]), 0.95)


class ContractTests(unittest.TestCase):
    def _interval(self, **overrides: object) -> MeasurementInterval:
        values: dict[str, object] = {
            "metric": "floor_area_m2",
            "unit": "square_metre",
            "value": 16.4,
            "low": 15.5,
            "high": 16.9,
            "confidence_level": 0.95,
            "resamples": 64,
        }
        values.update(overrides)
        return MeasurementInterval.model_validate(values)

    def test_inverted_bounds_are_refused(self) -> None:
        with self.assertRaises(ValidationError):
            self._interval(low=17.0, high=15.0)

    def test_an_interval_is_labelled_precision_and_not_accuracy(self) -> None:
        interval = self._interval()

        self.assertEqual(interval.kind, "precision")
        self.assertEqual(interval.method, "nonparametric_bootstrap")

    def test_half_width_is_published(self) -> None:
        interval = self._interval(low=15.0, high=17.0)

        self.assertAlmostEqual(interval.half_width, 1.0)

    def test_an_interval_need_not_contain_the_point_estimate(self) -> None:
        # A percentile interval can exclude the point estimate, and that is a
        # property of the method rather than an error, so it must be accepted.
        interval = self._interval(value=16.4, low=15.0, high=16.2)

        self.assertLess(interval.high, interval.value)


class FloorPlanBootstrapTests(unittest.TestCase):
    def test_resampling_produces_a_distribution_for_every_measurement(self) -> None:
        structure = StructureConfig()
        summary = _analysis().summary
        projected = analyze_structure(make_synthetic_room()).projected_floor_xy_m
        assert projected is not None

        samples, failures = bootstrap_floor_plan(
            projected,
            structure=structure,
            config=IntervalConfig(resamples=12),
        )

        self.assertEqual(failures, 0)
        for metric in (
            "floor_area_m2",
            "perimeter_m",
            "principal_length_m",
            "principal_width_m",
        ):
            self.assertEqual(len(samples[metric]), 12)
            self.assertTrue(np.all(samples[metric] > 0))
        self.assertGreater(summary.floor_plan.area_m2, 0)

    def test_the_bootstrap_is_deterministic_for_a_fixed_seed(self) -> None:
        structure = StructureConfig()
        projected = analyze_structure(make_synthetic_room()).projected_floor_xy_m
        assert projected is not None
        config = IntervalConfig(resamples=10, random_seed=5)

        first, _ = bootstrap_floor_plan(projected, structure=structure, config=config)
        second, _ = bootstrap_floor_plan(projected, structure=structure, config=config)

        np.testing.assert_array_equal(
            first["floor_area_m2"], second["floor_area_m2"]
        )

    def test_too_few_points_yields_no_distribution(self) -> None:
        samples, failures = bootstrap_floor_plan(
            np.zeros((2, 2)),
            structure=StructureConfig(),
            config=IntervalConfig(resamples=16),
        )

        self.assertEqual(samples, {})
        self.assertEqual(failures, 16)


class BuildIntervalsTests(unittest.TestCase):
    def _build(self, result, *, config: IntervalConfig | None = None):
        return build_measurement_intervals(
            result.summary,
            projected_floor_xy_m=result.projected_floor_xy_m,
            floor_heights_m=result.floor_heights_m,
            ceiling_heights_m=result.ceiling_heights_m,
            structure=StructureConfig(),
            config=config or IntervalConfig(resamples=12),
        )

    def test_floor_plan_and_ceiling_intervals_are_published(self) -> None:
        intervals, _ = self._build(_analysis(include_ceiling=True))

        metrics = {interval.metric for interval in intervals}
        self.assertEqual(
            metrics,
            {
                "floor_area_m2",
                "perimeter_m",
                "principal_length_m",
                "principal_width_m",
                "ceiling_height_m",
            },
        )
        for interval in intervals:
            self.assertLessEqual(interval.low, interval.high)
            self.assertEqual(interval.kind, "precision")

    def test_a_missing_ceiling_is_explained_rather_than_omitted_silently(self) -> None:
        intervals, warnings = self._build(_analysis(include_ceiling=False))

        self.assertNotIn(
            "ceiling_height_m", {interval.metric for interval in intervals}
        )
        self.assertTrue(
            any("ceiling" in warning for warning in warnings),
            msg=f"the missing ceiling interval was not explained: {warnings}",
        )

    def test_disabling_intervals_says_so(self) -> None:
        intervals, warnings = self._build(
            _analysis(), config=IntervalConfig(enabled=False)
        )

        self.assertEqual(intervals, ())
        self.assertTrue(any("disabled" in warning for warning in warnings))

    def test_uncovered_opening_widths_are_declared(self) -> None:
        result = analyze_structure(make_room_with_openings())
        assert result.summary.openings is not None
        if not result.summary.openings.openings:
            self.skipTest("fixture published no opening to report on")

        _, warnings = self._build(result)

        self.assertTrue(
            any("opening width" in warning for warning in warnings),
            msg=f"openings without intervals were not declared: {warnings}",
        )

    def test_opening_width_interval_is_built_from_retained_points(self) -> None:
        reconstruction = make_room_with_openings()
        result = analyze_structure(reconstruction)
        assert result.summary.openings is not None
        if not result.summary.openings.openings:
            self.skipTest("fixture published no opening to resample")

        intervals, warnings = build_measurement_intervals(
            result.summary,
            projected_floor_xy_m=result.projected_floor_xy_m,
            floor_heights_m=result.floor_heights_m,
            ceiling_heights_m=result.ceiling_heights_m,
            structure=StructureConfig(),
            config=IntervalConfig(resamples=8),
            points_xyz_m=reconstruction.points_xyz_m,
        )

        opening_intervals = [
            interval for interval in intervals if interval.metric == "opening_width_m"
        ]
        self.assertTrue(opening_intervals, msg=f"opening intervals failed: {warnings}")
        self.assertTrue(all(interval.target_id for interval in opening_intervals))

    def test_ceiling_interval_is_tight_on_a_well_sampled_plane(self) -> None:
        # Two planes fitted from thousands of inliers separate very precisely.
        # This is a precision statement only: the synthetic ceiling is at 2.5 m
        # by construction, and accuracy is not what the interval measures.
        intervals, _ = self._build(_analysis(include_ceiling=True))
        ceiling = next(i for i in intervals if i.metric == "ceiling_height_m")

        self.assertLess(ceiling.half_width, 0.02)


class PipelineIntegrationTests(unittest.TestCase):
    def test_intervals_reach_the_published_result(self) -> None:
        from pipeline_factory import make_pipeline_execution

        execution = make_pipeline_execution(include_ceiling=True)

        self.assertTrue(execution.result.intervals)
        for interval in execution.result.intervals:
            self.assertEqual(interval.kind, "precision")
        # Round-trip through the public contract.
        from cozmo_scan.models import RunResult

        decoded = RunResult.model_validate_json(execution.result.model_dump_json())
        self.assertEqual(
            [i.metric for i in decoded.intervals],
            [i.metric for i in execution.result.intervals],
        )

    def test_a_result_without_intervals_still_validates(self) -> None:
        from pipeline_factory import make_pipeline_execution
        from cozmo_scan.models import RunResult

        execution = make_pipeline_execution()
        legacy = execution.result.model_copy(
            update={"intervals": (), "schema_version": "1.3.0"}
        )

        decoded = RunResult.model_validate_json(legacy.model_dump_json())

        self.assertEqual(decoded.intervals, ())
        self.assertEqual(decoded.schema_version, "1.3.0")


if __name__ == "__main__":
    unittest.main()
