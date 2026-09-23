"""Resampling intervals for published measurements.

The project publishes a confidence interval wherever the evidence supports one. What can be
produced honestly from these captures is a **precision** interval: resample the
observed points, re-run the same estimator, and report the percentile spread of
the result. That answers "how stable is this number given the points we
collected", which is a real and checkable question.

It does not answer "how far is this number from the real room". No survey, tape
or laser ground truth was supplied, so accuracy is unestablished, and a tight
precision interval is fully compatible with a large bias: a systematic intrinsic
scale error, for instance, would move every resample identically and would not
widen the interval at all. Every interval is therefore labelled `precision`, and
nothing here should be read as an accuracy claim.

The estimator is re-run rather than re-derived. `bootstrap_floor_plan` calls the
same `trim_boundary_outliers`, `select_floor_outline` and `measure_polygon` used
to produce the published outline, so the interval describes the published
estimator and not an approximation of it.

Conformal prediction would convert this into a coverage guarantee, but it needs
ground-truth calibration data that does not exist here. That is recorded as the
next step rather than implied.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from cozmo_scan.floorplan import (
    StructureError,
    measure_polygon,
    select_floor_outline,
    trim_boundary_outliers,
)
from cozmo_scan.models import (
    IntervalConfig,
    MeasurementInterval,
    StructureConfig,
    StructureSummary,
)

#: Resamples that must succeed before an interval is published. A resample can
#: fail legitimately, for example when the resampled points no longer support an
#: outline, and an interval built from a handful of survivors is not meaningful.
MINIMUM_SUCCESSFUL_RESAMPLES = 8


def build_measurement_intervals(
    summary: StructureSummary,
    *,
    projected_floor_xy_m: NDArray[np.float64] | None,
    floor_heights_m: NDArray[np.float64] | None,
    ceiling_heights_m: NDArray[np.float64] | None,
    structure: StructureConfig,
    config: IntervalConfig,
) -> tuple[tuple[MeasurementInterval, ...], tuple[str, ...]]:
    """Return precision intervals for the published measurements, plus warnings.

    Measurements without an interval are reported in the warnings rather than
    silently omitted, so a reader can tell "no interval was computed" from "the
    interval is narrow".
    """
    if not config.enabled:
        return (), ("Measurement intervals are disabled in the effective configuration.",)
    intervals: list[MeasurementInterval] = []
    warnings: list[str] = []

    if projected_floor_xy_m is None or len(projected_floor_xy_m) < 3:
        warnings.append(
            "Floor-plan intervals are unavailable: the projected floor points were not retained."
        )
    else:
        plan, failures = bootstrap_floor_plan(
            projected_floor_xy_m, structure=structure, config=config
        )
        intervals.extend(_floor_plan_intervals(summary, plan, config))
        warnings.extend(_estimator_stability_warnings(summary, plan))
        if not plan:
            warnings.append(
                "Floor-plan intervals are unavailable: too few resamples produced a "
                f"measurable outline ({failures} of {config.resamples} failed)."
            )
        elif failures:
            warnings.append(
                f"{failures} of {config.resamples} floor-plan resamples produced no "
                "measurable outline and were excluded from the interval."
            )

    if summary.ceiling_height_m is None:
        warnings.append(
            "No ceiling-height interval: no ceiling plane passed the evidence checks."
        )
    elif floor_heights_m is None or ceiling_heights_m is None:
        warnings.append(
            "No ceiling-height interval: the plane inlier heights were not retained."
        )
    else:
        intervals.append(
            _ceiling_interval(
                summary.ceiling_height_m,
                floor_heights_m,
                ceiling_heights_m,
                config,
            )
        )

    openings = summary.openings
    if openings is not None and openings.status == "available" and openings.openings:
        warnings.append(
            f"No interval is published for {len(openings.openings)} opening width(s). "
            "The width estimator resolves each edge against individual blocking "
            "points, and resampling it is not yet implemented."
        )
    return tuple(intervals), tuple(warnings)


def _estimator_stability_warnings(
    summary: StructureSummary,
    samples: dict[str, NDArray[np.float64]],
) -> list[str]:
    """Warn when resamples did not agree on which outline estimator to use.

    A spread computed across two different estimators is bimodal, not a
    confidence band around one value, and reporting it as a single interval
    without saying so would be misleading.
    """
    selected = samples.get("_concave_selected")
    if selected is None or len(selected) == 0:
        return []
    concave_share = float(selected.mean())
    published_concave = summary.floor_plan.outline_method == "occupancy_concave"
    agreement = concave_share if published_concave else 1.0 - concave_share
    if agreement >= 0.98:
        return []
    return [
        f"Only {agreement:.0%} of resamples selected the same outline method as the "
        "published result, so the floor-plan intervals span two different estimators "
        "and are bimodal rather than a band around one value. Read the interval as "
        "evidence that this capture sits near the method-selection boundary."
    ]


def bootstrap_floor_plan(
    projected_floor_xy_m: NDArray[np.float64],
    *,
    structure: StructureConfig,
    config: IntervalConfig,
) -> tuple[dict[str, NDArray[np.float64]], int]:
    """Resample floor points and re-run the published outline estimator.

    Returns the resampled measurement distributions and the number of resamples
    that could not produce an outline.
    """
    points = np.asarray(projected_floor_xy_m, dtype=np.float64)
    points = points[np.isfinite(points).all(axis=1)]
    if len(points) < 3:
        return {}, config.resamples

    generator = np.random.default_rng(config.random_seed)
    samples: dict[str, list[float]] = {
        "floor_area_m2": [],
        "perimeter_m": [],
        "principal_length_m": [],
        "principal_width_m": [],
        # Outline method per resample, encoded numerically so the caller can
        # detect an estimator that flips between the concave contour and the
        # convex fallback. When it flips, the interval spans two different
        # estimators and is bimodal rather than a spread around one value.
        "_concave_selected": [],
    }
    failures = 0
    for _ in range(config.resamples):
        drawn = points[generator.integers(0, len(points), len(points))]
        try:
            boundary = trim_boundary_outliers(drawn, structure)
            outline = select_floor_outline(boundary, structure)
            measured = measure_polygon(
                outline.vertices_xy_m,
                supporting_cell_count=outline.supporting_cell_count,
                occupied_cell_area_m2=outline.occupied_cell_area_m2,
                outline_method=outline.method,
                connected_component_count=outline.connected_component_count,
                retained_component_ratio=outline.retained_component_ratio,
                discarded_cell_count=outline.discarded_cell_count,
                fallback_reason=outline.fallback_reason,
            )
        except (StructureError, ValueError):
            # A resample can legitimately fail to support an outline. Count it
            # rather than substituting the published value, which would
            # artificially narrow the interval.
            failures += 1
            continue
        samples["floor_area_m2"].append(measured.area_m2)
        samples["perimeter_m"].append(measured.perimeter_m)
        samples["principal_length_m"].append(measured.length_m)
        samples["principal_width_m"].append(measured.width_m)
        samples["_concave_selected"].append(
            1.0 if measured.outline_method == "occupancy_concave" else 0.0
        )

    if len(samples["floor_area_m2"]) < MINIMUM_SUCCESSFUL_RESAMPLES:
        return {}, failures
    return {
        name: np.asarray(values, dtype=np.float64) for name, values in samples.items()
    }, failures


def percentile_interval(
    samples: NDArray[np.float64], confidence_level: float
) -> tuple[float, float]:
    """Return the two-sided percentile bounds for a resample distribution."""
    if len(samples) < 2:
        raise ValueError("at least two resamples are required for an interval")
    tail = (1.0 - confidence_level) / 2.0 * 100.0
    low, high = np.percentile(samples, (tail, 100.0 - tail))
    return float(low), float(high)


def _floor_plan_intervals(
    summary: StructureSummary,
    samples: dict[str, NDArray[np.float64]],
    config: IntervalConfig,
) -> list[MeasurementInterval]:
    if not samples:
        return []
    plan = summary.floor_plan
    published = {
        "floor_area_m2": (plan.area_m2, "square_metre"),
        "perimeter_m": (plan.perimeter_m, "metre"),
        "principal_length_m": (plan.length_m, "metre"),
        "principal_width_m": (plan.width_m, "metre"),
    }
    intervals: list[MeasurementInterval] = []
    for metric, (value, unit) in published.items():
        drawn = samples.get(metric)
        if drawn is None or len(drawn) < 2:
            continue
        low, high = percentile_interval(drawn, config.confidence_level)
        intervals.append(
            MeasurementInterval(
                metric=metric,
                unit=unit,
                value=value,
                low=low,
                high=high,
                confidence_level=config.confidence_level,
                resamples=int(len(drawn)),
            )
        )
    return intervals


def _ceiling_interval(
    published_height_m: float,
    floor_heights_m: NDArray[np.float64],
    ceiling_heights_m: NDArray[np.float64],
    config: IntervalConfig,
) -> MeasurementInterval:
    """Resample both plane inlier sets and recompute the separation.

    Ceiling height is the separation between two fitted planes, so both
    contribute. Resampling only one would understate the spread.
    """
    generator = np.random.default_rng(config.random_seed + 1)
    floor = np.asarray(floor_heights_m, dtype=np.float64)
    ceiling = np.asarray(ceiling_heights_m, dtype=np.float64)
    drawn = np.empty(config.resamples, dtype=np.float64)
    for index in range(config.resamples):
        floor_mean = float(
            floor[generator.integers(0, len(floor), len(floor))].mean()
        )
        ceiling_mean = float(
            ceiling[generator.integers(0, len(ceiling), len(ceiling))].mean()
        )
        drawn[index] = ceiling_mean - floor_mean
    low, high = percentile_interval(drawn, config.confidence_level)
    return MeasurementInterval(
        metric="ceiling_height_m",
        unit="metre",
        value=published_height_m,
        low=low,
        high=high,
        confidence_level=config.confidence_level,
        resamples=config.resamples,
    )
