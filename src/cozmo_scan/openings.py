"""Deterministic wall identity, opening detection, and adjacency evidence.

This module gives the anonymous vertical planes produced by plane fitting a
finite extent and a stable identifier, then looks for wall voids that are
supported strongly enough to publish as doors, windows, or open transitions.

Design rules that must not be relaxed:

- A void is proposed only when solid wall material flanks it on both sides, so
  the scanned wall extent itself can never masquerade as an opening.
- A void is published only when the floor in front of it was actually scanned,
  so missing coverage is rejected instead of being reported as a doorway.
- Classification stays hedged. `unclassified_gap` means the void is real but its
  semantics are not established.
- The far side of an opening is `unknown` unless a second independently
  supported floor region shares it. Two regions are never assumed.

The module depends only on `models`, keeping the dependency on `floorplan`
one-way: `floorplan` calls into here, never the reverse.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

from cozmo_scan.grid import connected_occupancy_components
from cozmo_scan.models import (
    FloorCoordinateSystem,
    Opening,
    OpeningAnalysis,
    OpeningEvidence,
    OpeningRejection,
    PlaneMeasurement,
    RoomAdjacency,
    StructureConfig,
    WallSegment,
)

FloatArray = NDArray[np.floating]

#: Number of positions sampled along a candidate void when probing the floor.
#: Floor probes taken along a span. Each probe contributes 1/N to a support
#: ratio, so N sets the resolution of every floor-support threshold. Nine probes
#: quantised 0.60 into an effective 0.667 and 0.85 into 0.889, which made the
#: configured values misleading; 21 resolves them to under 0.05.
FLOOR_PROBE_SAMPLES = 21
#: Evidence levels at or above which an accepted opening is called `high`.
#: Flank support is quantised to 1/opening_flank_bins, so with the default four
#: flank bins the only meaningful high tier is fully solid flanking wall. Stating
#: 1.0 is honest; stating 0.90 would have behaved identically while implying
#: tolerance that does not exist.
HIGH_CONFIDENCE_FLANK_SUPPORT = 1.0
HIGH_CONFIDENCE_FLOOR_SUPPORT = 0.85
HIGH_CONFIDENCE_WALL_SOLID_RATIO = 0.80
#: Scanned floor area a side of a wall must reach before it counts as a region.
MINIMUM_REGION_AREA_M2 = 1.0
#: Probes that must agree on both sides before adjacency is claimed.
MINIMUM_ADJACENCY_PROBES = 3
#: Rounding applied to the doubled-angle orientation key. Coarse on purpose, so
#: that near-identical orientations tie and the wall offset breaks the tie.
ORIENTATION_KEY_DECIMALS = 3
#: Bins of clear wall a run needs on each side beyond the flank window, so that
#: the boundary bins which straddle the physical edge are not counted as flank.
EDGE_BOUNDARY_BINS = 1


def analyze_openings(
    *,
    points_xyz_m: FloatArray,
    floor_normal_xyz: FloatArray,
    floor_centroid_xyz_m: FloatArray,
    ceiling_height_m: float | None,
    coordinates: FloorCoordinateSystem,
    walls: Sequence[PlaneMeasurement],
    occupancy_cells: frozenset[tuple[int, int]] | set[tuple[int, int]],
    grid_size_m: float,
    config: StructureConfig,
) -> OpeningAnalysis:
    """Identify walls and their supported openings for one measured capture.

    Returns an `available` analysis with an empty opening tuple when the walls
    are measurable but no void passes the evidence gates. That is a real
    negative result, not a failure.
    """
    if not config.detect_openings:
        return OpeningAnalysis(
            status="unavailable",
            unavailable_reason="Opening detection is disabled in the effective configuration.",
        )
    wall_planes = [wall for wall in walls if wall.kind == "wall"]
    if not wall_planes:
        return OpeningAnalysis(
            status="unavailable",
            unavailable_reason="No supported wall plane is available to carry an opening.",
        )
    if grid_size_m <= 0:
        raise ValueError("grid_size_m must be positive")

    points = np.asarray(points_xyz_m, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError("points must have shape (N, 3)")
    points = points[np.isfinite(points).all(axis=1)]
    if len(points) < config.minimum_plane_inliers:
        return OpeningAnalysis(
            status="unavailable",
            unavailable_reason="The reconstruction is too sparse to profile wall material.",
        )

    normal = _normalized(floor_normal_xyz)
    centroid = np.asarray(floor_centroid_xyz_m, dtype=np.float64)
    heights = (points - centroid) @ normal
    floor_xy = _project_to_floor(points, coordinates)
    # The band must exclude both horizontal planes. Floor or ceiling points that
    # leak into a wall band land in every along-wall bin and would make a real
    # doorway look like solid material.
    if ceiling_height_m is not None:
        band_top = float(ceiling_height_m) - config.opening_ceiling_clearance_m
    else:
        # Without a detected ceiling the configured ceiling maximum is the only
        # defensible bound. Any undetected ceiling that leaks in suppresses
        # openings rather than inventing them, which is the safe direction.
        band_top = config.ceiling_height_max_m
    if band_top <= config.floor_clearance_m:
        return OpeningAnalysis(
            status="unavailable",
            unavailable_reason=(
                "The space between the floor and ceiling planes is too shallow to "
                "profile wall material."
            ),
        )
    vertical = (heights >= config.floor_clearance_m) & (heights <= band_top)

    cells = frozenset(occupancy_cells)

    profiles: list[_WallProfile] = []
    rejections: list[OpeningRejection] = []
    for plane_index, wall in enumerate(wall_planes):
        profile = _profile_wall(
            plane_index=plane_index,
            wall=wall,
            points=points,
            floor_xy=floor_xy,
            heights=heights,
            vertical=vertical,
            coordinates=coordinates,
            band_top_m=band_top,
            ceiling_known=ceiling_height_m is not None,
            config=config,
        )
        if profile is not None:
            profiles.append(profile)

    if not profiles:
        return OpeningAnalysis(
            status="unavailable",
            unavailable_reason=(
                "No wall plane had enough continuous scanned extent to build a "
                "reliable material profile."
            ),
        )

    # Deterministic geometric identity: orientation first, then signed offset.
    profiles.sort(
        key=lambda item: (
            item.orientation_key[0],
            item.orientation_key[1],
            item.sort_offset_m,
            item.plane_index,
        )
    )
    segments: list[WallSegment] = []
    openings: list[Opening] = []
    adjacency: list[RoomAdjacency] = []
    candidate_count = 0

    for ordinal, profile in enumerate(profiles, start=1):
        wall_id = f"W{ordinal:02d}"
        segments.append(profile.as_segment(wall_id))
        solid_ratio = float(profile.material.mean())
        if solid_ratio < config.opening_minimum_wall_solid_ratio:
            # A wall observed this incompletely is a fragment. Its voids are
            # overwhelmingly unscanned surface, so nothing on it can be published
            # as an opening without inventing structure.
            if profile.open_bin.any():
                rejections.append(
                    OpeningRejection(
                        wall_id=wall_id,
                        reason=(
                            f"The wall is only {solid_ratio:.0%} solid, below the "
                            f"{config.opening_minimum_wall_solid_ratio:.0%} minimum; "
                            "voids on a fragmented wall are unscanned surface, not openings."
                        ),
                    )
                )
            continue
        interior_sign = _interior_sign(profile, cells, grid_size_m, config)
        region_areas = _wall_side_areas(profile, cells, grid_size_m, config)
        accepted: list[Opening] = []
        # Runs narrower than a supported opening are per-bin sampling noise. They
        # are not candidates and are deliberately not reported, so the rejection
        # list stays readable. Counting happens up front so that the per-wall cap
        # below cannot leave later runs uncounted.
        required_bins = (
            int(np.ceil(config.opening_minimum_width_m / profile.bin_size_m))
            + 2 * (config.opening_flank_bins + EDGE_BOUNDARY_BINS)
        )
        if profile.bin_count < required_bins:
            if profile.open_bin.any():
                rejections.append(
                    OpeningRejection(
                        wall_id=wall_id,
                        reason=(
                            f"The wall spans {profile.length_m:.2f} m, too short to hold a "
                            f"{config.opening_minimum_width_m:.2f} m opening plus the "
                            "flanking wall needed to confirm it is bounded."
                        ),
                    )
                )
            continue
        runs = [
            (start, end)
            for start, end in _void_runs(profile.open_bin)
            if (end - start + 1) * profile.bin_size_m >= config.opening_minimum_width_m
        ]
        candidate_count += len(runs)
        for run_start, run_end in runs:
            if len(accepted) >= config.maximum_openings_per_wall:
                rejections.append(
                    OpeningRejection(
                        wall_id=wall_id,
                        reason=(
                            "The per-wall opening cap of "
                            f"{config.maximum_openings_per_wall} was already reached."
                        ),
                        width_m=(run_end - run_start + 1) * profile.bin_size_m,
                    )
                )
                continue
            rejection = _reject_run(
                profile=profile,
                run_start=run_start,
                run_end=run_end,
                wall_id=wall_id,
                config=config,
            )
            if rejection is not None:
                rejections.append(rejection)
                continue
            vertical_result = _classify_void(
                profile=profile,
                run_start=run_start,
                run_end=run_end,
                config=config,
            )
            if vertical_result is None:
                rejections.append(
                    OpeningRejection(
                        wall_id=wall_id,
                        reason=(
                            "The bins share no common vertical void; the evidence is "
                            "more consistent with sparse sampling or occlusion than "
                            "with an opening."
                        ),
                        width_m=(run_end - run_start + 1) * profile.bin_size_m,
                    )
                )
                continue
            classification, sill_m, head_m, void_height_m, void_points = vertical_result
            start_along, end_along = _refine_void_edges(
                profile=profile,
                run_start=run_start,
                run_end=run_end,
                sill_m=sill_m,
                head_m=head_m,
                config=config,
            )
            width_m = end_along - start_along
            # Both bounds must be re-checked. Refinement moves the edges, so a
            # width that passed on the coarse bin span can fall outside the
            # configured range once it is measured properly.
            if not (
                config.opening_minimum_width_m
                <= width_m
                <= config.opening_maximum_width_m
            ):
                rejections.append(
                    OpeningRejection(
                        wall_id=wall_id,
                        reason=(
                            f"Refined width is {width_m:.2f} m, outside the supported "
                            f"{config.opening_minimum_width_m:.2f}-"
                            f"{config.opening_maximum_width_m:.2f} m range."
                        ),
                        width_m=width_m,
                    )
                )
                continue
            floor_support = _floor_support_across(
                profile=profile,
                start_along_m=start_along,
                end_along_m=end_along,
                sign=interior_sign,
                cells=cells,
                grid_size_m=grid_size_m,
                config=config,
            )
            # The decisive gate. An unobserved wall patch and a real aperture
            # look identical from the room side, so the void must be evidenced
            # from behind: either the sensor saw through it, or scanned floor
            # continues across the wall line.
            pass_through = _pass_through_points(
                profile=profile,
                start_along_m=start_along,
                end_along_m=end_along,
                sill_m=sill_m if sill_m is not None else 0.0,
                head_m=head_m if head_m is not None else profile.height_m,
                exterior_sign=-interior_sign,
                config=config,
            )
            far_floor = _floor_support_across(
                profile=profile,
                start_along_m=start_along,
                end_along_m=end_along,
                sign=-interior_sign,
                cells=cells,
                grid_size_m=grid_size_m,
                config=config,
            )
            seen_through = pass_through >= config.opening_minimum_pass_through_points
            floor_continues = far_floor >= config.opening_minimum_far_floor_support
            if not (seen_through or floor_continues):
                rejections.append(
                    OpeningRejection(
                        wall_id=wall_id,
                        reason=(
                            f"Nothing was observed behind the void: {pass_through} "
                            f"point(s) beyond the wall and {far_floor:.0%} far-side floor "
                            "support. An unscanned wall surface is indistinguishable from "
                            "an opening from the room side, so this is not published."
                        ),
                        width_m=width_m,
                    )
                )
                continue
            unobserved = float(
                1.0 - profile.observed[run_start : run_end + 1].mean()
            )
            left_support, right_support = _flank_support(profile, run_start, run_end, config)
            evidence = OpeningEvidence(
                profile_bin_count=profile.bin_count,
                gap_bin_count=run_end - run_start + 1,
                bin_size_m=profile.bin_size_m,
                left_flank_support=left_support,
                right_flank_support=right_support,
                interior_floor_support=floor_support,
                void_point_count=void_points,
                wall_height_m=profile.height_m,
                sill_height_m=sill_m,
                head_height_m=head_m,
                pass_through_point_count=pass_through,
                far_floor_support=far_floor,
                unobserved_bin_ratio=unobserved,
                wall_height_is_coverage_limited=profile.height_is_coverage_limited,
            )
            start_xy = profile.floor_point(start_along, 0.0)
            end_xy = profile.floor_point(end_along, 0.0)
            centre_xy = (start_xy + end_xy) / 2
            opening_id = f"{wall_id}-O{len(accepted) + 1}"
            confidence = _confidence(
                left_support=left_support,
                right_support=right_support,
                floor_support=floor_support,
                wall_solid_ratio=solid_ratio,
                minimum_flank_support=config.opening_minimum_flank_support,
            )
            # Resolve the far side before constructing the opening so the model
            # validator sees a complete, self-consistent record. A low-confidence
            # void is not allowed to assert that two regions are connected.
            link = (
                None
                if confidence == "low"
                else _adjacency_across_void(
                    profile=profile,
                    centre_along_m=(start_along + end_along) / 2,
                    width_m=width_m,
                    interior_sign=interior_sign,
                    region_areas=region_areas,
                    grid_size_m=grid_size_m,
                    config=config,
                )
            )
            accepted.append(
                Opening(
                    opening_id=opening_id,
                    wall_id=wall_id,
                    classification=classification,
                    confidence=confidence,
                    width_m=width_m,
                    height_m=void_height_m,
                    centre_xy_m=_tuple2(centre_xy),
                    start_xy_m=_tuple2(start_xy),
                    end_xy_m=_tuple2(end_xy),
                    other_side="unknown" if link is None else "observed_space",
                    far_side_area_m2=None if link is None else link[1],
                    evidence=evidence,
                )
            )
            if link is not None:
                near_area, far_area, agreement = link
                adjacency.append(
                    RoomAdjacency(
                        opening_id=opening_id,
                        wall_id=wall_id,
                        near_side_area_m2=near_area,
                        far_side_area_m2=far_area,
                        probe_agreement=agreement,
                    )
                )

        openings.extend(accepted)

    return OpeningAnalysis(
        status="available",
        walls=tuple(segments),
        openings=tuple(openings),
        adjacency=tuple(adjacency),
        rejections=tuple(rejections),
        candidate_count=candidate_count,
    )


class _WallProfile:
    """One wall's finite extent plus its along-wall material and void profiles.

    Two independent per-bin signals are kept because a door and a window look
    nothing alike in the data. `material` records that wall surface exists in the
    bin at all; `open_bin` records that the bin contains a tall vertical void. A
    doorway has a void and no material; a window has a void *and* material, from
    its sill and head.
    """

    __slots__ = (
        "plane_index",
        "wall",
        "normal_xy",
        "along_xy",
        "offset_c",
        "along_start_m",
        "bin_size_m",
        "material",
        "observed",
        "open_bin",
        "void_low_m",
        "void_high_m",
        "bin_counts",
        "height_m",
        "height_is_coverage_limited",
        "along_values",
        "point_heights",
        "inlier_count",
        "floor_xy",
        "heights_all",
    )

    def __init__(
        self,
        *,
        plane_index: int,
        wall: PlaneMeasurement,
        normal_xy: NDArray[np.float64],
        along_xy: NDArray[np.float64],
        offset_c: float,
        along_start_m: float,
        bin_size_m: float,
        material: NDArray[np.bool_],
        observed: NDArray[np.bool_],
        open_bin: NDArray[np.bool_],
        void_low_m: NDArray[np.float64],
        void_high_m: NDArray[np.float64],
        bin_counts: NDArray[np.int64],
        height_m: float,
        height_is_coverage_limited: bool,
        along_values: NDArray[np.float64],
        point_heights: NDArray[np.float64],
        inlier_count: int,
        floor_xy: NDArray[np.float64],
        heights_all: NDArray[np.float64],
    ) -> None:
        self.plane_index = plane_index
        self.wall = wall
        self.normal_xy = normal_xy
        self.along_xy = along_xy
        self.offset_c = offset_c
        self.along_start_m = along_start_m
        self.bin_size_m = bin_size_m
        self.material = material
        self.observed = observed
        self.open_bin = open_bin
        self.void_low_m = void_low_m
        self.void_high_m = void_high_m
        self.bin_counts = bin_counts
        self.height_m = height_m
        self.height_is_coverage_limited = height_is_coverage_limited
        self.along_values = along_values
        self.point_heights = point_heights
        self.inlier_count = inlier_count
        # Shared references, not copies: needed to look behind the wall.
        self.floor_xy = floor_xy
        self.heights_all = heights_all

    @property
    def bin_count(self) -> int:
        return int(len(self.material))

    @property
    def length_m(self) -> float:
        return float(self.bin_count * self.bin_size_m)

    @property
    def orientation_key(self) -> tuple[float, float]:
        return wall_orientation_key(self.normal_xy)

    @property
    def sort_offset_m(self) -> float:
        return round(self.offset_c, 4)

    def along_value(self, bin_index: int) -> float:
        return self.along_start_m + bin_index * self.bin_size_m

    def floor_point(self, along_m: float, offset_m: float) -> NDArray[np.float64]:
        return self.along_xy * along_m + self.normal_xy * (self.offset_c + offset_m)

    def as_segment(self, wall_id: str) -> WallSegment:
        start = self.floor_point(self.along_value(0), 0.0)
        end = self.floor_point(self.along_value(self.bin_count), 0.0)
        return WallSegment(
            wall_id=wall_id,
            plane_index=self.plane_index,
            start_xy_m=_tuple2(start),
            end_xy_m=_tuple2(end),
            normal_xy=_tuple2(self.normal_xy),
            length_m=self.length_m,
            height_m=self.height_m,
            height_is_coverage_limited=self.height_is_coverage_limited,
            inlier_count=self.inlier_count,
            solid_bin_ratio=float(self.material.mean()),
            rmse_m=self.wall.rmse_m,
        )


def wall_orientation_key(normal_xy: FloatArray) -> tuple[float, float]:
    """Return a continuous orientation key that a normal flip cannot move.

    A wall has no facing direction, so a normal and its negation describe the
    same wall and must produce the same key. Taking the angle modulo 180
    satisfies that identity but is *discontinuous* exactly at the axis-aligned
    orientations real rooms have: a normal component of +1e-6 gives 0 degrees
    and -1e-6 gives 179.999, so a sub-microradian change in a fitted plane
    reshuffles every wall identifier and therefore every opening identifier.

    Doubling the angle removes the discontinuity, because the doubled angle is
    identical for a direction and its negation. The key is then rounded coarsely
    so that orientations which agree to well under a degree compare equal and
    the wall offset decides their order instead.
    """
    angle = math.atan2(float(normal_xy[1]), float(normal_xy[0]))
    return (
        round(math.cos(2.0 * angle), ORIENTATION_KEY_DECIMALS),
        round(math.sin(2.0 * angle), ORIENTATION_KEY_DECIMALS),
    )


def wall_sort_angle_deg(normal_xy: FloatArray) -> float:
    """Return the doubled-angle orientation in degrees, for diagnostics.

    Derived from the rounded key, so it inherits the key's stability. Mapped to
    [0, 360) so that a signed zero cannot present as two different values.
    """
    key = wall_orientation_key(normal_xy)
    return round(math.degrees(math.atan2(key[1], key[0])) % 360.0, 6)


def _profile_wall(
    *,
    plane_index: int,
    wall: PlaneMeasurement,
    points: NDArray[np.float64],
    floor_xy: NDArray[np.float64],
    heights: NDArray[np.float64],
    vertical: NDArray[np.bool_],
    coordinates: FloorCoordinateSystem,
    band_top_m: float,
    ceiling_known: bool,
    config: StructureConfig,
) -> _WallProfile | None:
    normal_world = np.asarray(wall.normal_xyz, dtype=np.float64)
    x_axis = np.asarray(coordinates.x_axis_xyz, dtype=np.float64)
    y_axis = np.asarray(coordinates.y_axis_xyz, dtype=np.float64)
    normal_xy = np.asarray(
        [float(normal_world @ x_axis), float(normal_world @ y_axis)], dtype=np.float64
    )
    norm = float(np.linalg.norm(normal_xy))
    if norm < 1e-9:
        # The plane normal is parallel to the floor up axis: not a usable wall.
        return None
    normal_xy = normal_xy / norm
    along_xy = np.asarray([-normal_xy[1], normal_xy[0]], dtype=np.float64)

    distance = np.abs(points @ normal_world + wall.offset_m)
    selected = (distance <= config.opening_wall_band_m) & vertical
    if int(selected.sum()) < config.minimum_plane_inliers:
        return None

    selected_xy = floor_xy[selected]
    along = selected_xy @ along_xy
    point_heights = heights[selected]
    lower, upper = (float(value) for value in np.percentile(along, (1.0, 99.0)))
    length = upper - lower
    if length < config.minimum_wall_span_m:
        return None
    wall_height = float(np.percentile(point_heights, 99.0))
    if wall_height < config.minimum_wall_height_m:
        return None
    # `opening_door_minimum_height_m` reads like an absolute height but is
    # compared against a void bounded by this value, so on a wall whose top was
    # never scanned a real doorway could never reach it. Record that rather than
    # letting the threshold quietly mean something different per wall.
    coverage_limited = (not ceiling_known) or (
        wall_height < band_top_m - config.opening_ceiling_clearance_m
    )

    bin_count = int(round(length / config.opening_profile_bin_m))
    if bin_count < 3:
        # Too few bins to form a run with any flank at all.
        return None
    bin_size = length / bin_count
    inside = (along >= lower) & (along <= upper)
    indices = np.clip(
        np.floor((along[inside] - lower) / bin_size).astype(np.int64), 0, bin_count - 1
    )
    inside_heights = np.clip(point_heights[inside], 0.0, wall_height)
    counts = np.bincount(indices, minlength=bin_count).astype(np.int64)
    max_height = np.zeros(bin_count, dtype=np.float64)
    np.maximum.at(max_height, indices, inside_heights)
    material = (counts >= config.opening_minimum_bin_points) & (
        max_height >= config.opening_solid_height_ratio * wall_height
    )
    if not bool(material.any()):
        return None

    # Per-bin tallest vertical void, bounded by the floor and the wall top.
    order = np.lexsort((inside_heights, indices))
    ordered_bins = indices[order]
    ordered_heights = inside_heights[order]
    bin_range = np.arange(bin_count)
    starts = np.searchsorted(ordered_bins, bin_range, side="left")
    ends = np.searchsorted(ordered_bins, bin_range, side="right")
    void_low = np.zeros(bin_count, dtype=np.float64)
    void_high = np.zeros(bin_count, dtype=np.float64)
    for index in bin_range:
        low, high, _ = _largest_vertical_void(
            ordered_heights[starts[index] : ends[index]], wall_height
        )
        void_low[index] = low
        void_high[index] = high
    # A bin with no returns is *unknown*, not empty. Record it so the run-level
    # gate can require positive evidence that space exists behind the void.
    observed = counts > 0
    open_bin = (void_high - void_low) >= config.opening_minimum_void_height_m

    return _WallProfile(
        plane_index=plane_index,
        wall=wall,
        normal_xy=normal_xy,
        along_xy=along_xy,
        offset_c=float(np.median(selected_xy @ normal_xy)),
        along_start_m=lower,
        bin_size_m=bin_size,
        material=material,
        observed=observed,
        open_bin=open_bin,
        void_low_m=void_low,
        void_high_m=void_high,
        bin_counts=counts,
        height_m=wall_height,
        height_is_coverage_limited=coverage_limited,
        along_values=along[inside],
        point_heights=inside_heights,
        inlier_count=int(selected.sum()),
        floor_xy=floor_xy,
        heights_all=heights,
    )


def _void_runs(open_bin: NDArray[np.bool_]) -> list[tuple[int, int]]:
    """Return inclusive index ranges of consecutive bins holding a vertical void."""
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, value in enumerate(open_bin):
        if value and start is None:
            start = index
        elif not value and start is not None:
            runs.append((start, index - 1))
            start = None
    if start is not None:
        runs.append((start, len(open_bin) - 1))
    return runs


def _flank_support(
    profile: _WallProfile,
    run_start: int,
    run_end: int,
    config: StructureConfig,
) -> tuple[float, float]:
    """Fraction of flanking bins that hold closed, solid wall.

    A flank bin counts only when it has wall material *and* no tall void of its
    own, so a fragmented or repeatedly perforated wall cannot vouch for a void.
    """
    flank = config.opening_flank_bins
    closed = profile.material & ~profile.open_bin
    left = closed[max(0, run_start - flank) : run_start]
    right = closed[run_end + 1 : run_end + 1 + flank]
    left_support = float(left.mean()) if len(left) else 0.0
    right_support = float(right.mean()) if len(right) else 0.0
    return left_support, right_support


def _reject_run(
    *,
    profile: _WallProfile,
    run_start: int,
    run_end: int,
    wall_id: str,
    config: StructureConfig,
) -> OpeningRejection | None:
    bin_count = profile.bin_count
    width_m = (run_end - run_start + 1) * profile.bin_size_m
    if run_start == 0 or run_end == bin_count - 1:
        return OpeningRejection(
            wall_id=wall_id,
            reason=(
                "The void touches the end of the scanned wall extent, so it is a "
                "coverage boundary rather than a bounded opening."
            ),
            width_m=width_m,
        )
    flank = config.opening_flank_bins
    if run_start < flank or bin_count - 1 - run_end < flank:
        return OpeningRejection(
            wall_id=wall_id,
            reason="Too little wall remains beside the void to confirm it is bounded.",
            width_m=width_m,
        )
    if width_m > config.opening_maximum_width_m:
        return OpeningRejection(
            wall_id=wall_id,
            reason=(
                f"The void is {width_m:.2f} m wide, above the "
                f"{config.opening_maximum_width_m:.2f} m maximum; this is more "
                "consistent with missing wall coverage."
            ),
            width_m=width_m,
        )
    left_support, right_support = _flank_support(profile, run_start, run_end, config)
    if (
        left_support < config.opening_minimum_flank_support
        or right_support < config.opening_minimum_flank_support
    ):
        return OpeningRejection(
            wall_id=wall_id,
            reason=(
                f"Flanking wall support is {left_support:.0%} and {right_support:.0%}; "
                "a fragmented wall cannot confirm an opening."
            ),
            width_m=width_m,
        )
    return None


def _interior_sign(
    profile: _WallProfile,
    cells: frozenset[tuple[int, int]],
    grid_size_m: float,
    config: StructureConfig,
) -> float:
    """Return +1 or -1 for whichever side of the wall holds the scanned floor."""
    positive = 0
    negative = 0
    for index in np.linspace(0, profile.bin_count, FLOOR_PROBE_SAMPLES):
        along = profile.along_value(float(index))
        for sign, counter in ((1.0, "positive"), (-1.0, "negative")):
            probe = profile.floor_point(
                along, sign * config.opening_probe_distance_m
            )
            if _cell_of(probe, grid_size_m) in cells:
                if counter == "positive":
                    positive += 1
                else:
                    negative += 1
    if positive == negative:
        # Deterministic tie-break; the floor-support gate still has to pass.
        return 1.0
    return 1.0 if positive > negative else -1.0


def _floor_support_across(
    *,
    profile: _WallProfile,
    start_along_m: float,
    end_along_m: float,
    sign: float,
    cells: frozenset[tuple[int, int]],
    grid_size_m: float,
    config: StructureConfig,
) -> float:
    """Fraction of probes along a span, offset to one side, that hit scanned floor."""
    occupied = 0
    for along in np.linspace(start_along_m, end_along_m, FLOOR_PROBE_SAMPLES):
        probe = profile.floor_point(
            float(along), sign * config.opening_probe_distance_m
        )
        if _cell_of(probe, grid_size_m) in cells:
            occupied += 1
    return occupied / FLOOR_PROBE_SAMPLES


def _pass_through_points(
    *,
    profile: _WallProfile,
    start_along_m: float,
    end_along_m: float,
    sill_m: float,
    head_m: float,
    exterior_sign: float,
    config: StructureConfig,
) -> int:
    """Count points observed *behind* the void, within its own along/height window.

    This is the evidence that separates an aperture from an unscanned surface. A
    doorway or an open transition lets the sensor see into the space beyond, so
    returns appear past the wall plane. A curtain, mirror, dark or specular
    panel, or a grazing-incidence coverage hole leaves the wall band empty and
    nothing behind it, because the surface is still physically there.
    """
    signed = profile.floor_xy @ profile.normal_xy - profile.offset_c
    beyond = exterior_sign * signed
    along = profile.floor_xy @ profile.along_xy
    selected = (
        (beyond > config.opening_wall_band_m)
        & (beyond <= config.opening_wall_band_m + config.opening_pass_through_depth_m)
        & (along >= start_along_m)
        & (along <= end_along_m)
        & (profile.heights_all >= sill_m)
        & (profile.heights_all <= head_m)
    )
    return int(np.count_nonzero(selected))


def _classify_void(
    *,
    profile: _WallProfile,
    run_start: int,
    run_end: int,
    config: StructureConfig,
) -> tuple[str, float | None, float | None, float, int] | None:
    """Return classification, sill, head, void height, and void point count.

    The reported void is the band common to every bin in the run, not the union.
    Requiring a shared sill and head is what separates a real opening from a
    scatter of unrelated per-bin sampling gaps.
    """
    # The first and last bin of a run straddle the physical edge, so they hold a
    # mixture of void and wall material. Including them would shrink the shared
    # band towards whatever the partial samples happen to contain, which turns a
    # full-height doorway into a narrow band. Use the interior bins when there
    # are any.
    if run_end - run_start >= 2:
        interior_start, interior_end = run_start + 1, run_end
    else:
        interior_start, interior_end = run_start, run_end + 1
    span = slice(interior_start, interior_end)
    sill = float(profile.void_low_m[span].max())
    head = float(profile.void_high_m[span].min())
    void_height = head - sill
    if void_height < config.opening_minimum_void_height_m:
        return None

    # Count intruding points over the confidently void interior bins only. The
    # boundary bins legitimately hold the wall material that defines the edge.
    start = profile.along_value(interior_start)
    end = profile.along_value(interior_end)
    inside = (profile.along_values >= start) & (profile.along_values < end)
    heights = profile.point_heights[inside]
    void_points = int(np.count_nonzero((heights > sill) & (heights < head)))

    material_above = head < profile.height_m - config.opening_window_head_margin_m
    if sill <= config.opening_door_sill_maximum_m:
        if void_height >= config.opening_door_minimum_height_m:
            return "door_like", sill, head, void_height, void_points
        return "unclassified_gap", sill, head, void_height, void_points
    if sill >= config.opening_window_sill_minimum_m and material_above:
        return "window_like", sill, head, void_height, void_points
    return "unclassified_gap", sill, head, void_height, void_points


def _refine_void_edges(
    *,
    profile: _WallProfile,
    run_start: int,
    run_end: int,
    sill_m: float | None,
    head_m: float | None,
    config: StructureConfig,
) -> tuple[float, float]:
    """Locate the opening edges from blocking points instead of bin boundaries.

    Bin quantisation alone caps width resolution at the profile bin size, which
    is coarser than the 2 cm opening-width gate. The physical edge is
    where wall material at the opening's own height stops, so the nearest such
    point on each side is a far tighter estimate. Falls back to the bin edges
    when no blocking point is available.
    """
    coarse_start = profile.along_value(run_start)
    coarse_end = profile.along_value(run_end + 1)
    if sill_m is None or head_m is None:
        return coarse_start, coarse_end
    inset = config.opening_void_inset_m
    low = sill_m + inset
    high = head_m - inset
    if high <= low:
        return coarse_start, coarse_end
    blocking = (profile.point_heights >= low) & (profile.point_heights <= high)
    if not bool(blocking.any()):
        return coarse_start, coarse_end
    positions = profile.along_values[blocking]
    window = config.opening_flank_bins * profile.bin_size_m
    left = positions[
        (positions <= coarse_start) & (positions >= coarse_start - window)
    ]
    right = positions[(positions >= coarse_end) & (positions <= coarse_end + window)]
    if len(left) == 0 or len(right) == 0:
        return coarse_start, coarse_end

    # The physical edge lies past the last blocking point, by roughly half the
    # local sampling interval. Correcting inward by that amount makes the
    # estimator two-sided; the previous version could only ever widen an
    # opening, so every published width was biased large.
    start = float(left.max()) + _half_spacing(len(left), window)
    end = float(right.min()) - _half_spacing(len(right), window)
    if end <= start:
        return coarse_start, coarse_end
    return start, end


def _half_spacing(sample_count: int, window_m: float) -> float:
    """Half the mean along-wall spacing of blocking points in one flank window."""
    if sample_count < 1 or window_m <= 0:
        return 0.0
    return float(window_m / sample_count) / 2.0


def _largest_vertical_void(
    heights_m: NDArray[np.float64], wall_height_m: float
) -> tuple[float, float, float]:
    ordered = np.sort(heights_m)
    edges = np.concatenate(([0.0], ordered, [wall_height_m]))
    diffs = np.diff(edges)
    if len(diffs) == 0:
        return 0.0, 0.0, 0.0
    index = int(np.argmax(diffs))
    return float(edges[index]), float(edges[index + 1]), float(diffs[index])


def _confidence(
    *,
    left_support: float,
    right_support: float,
    floor_support: float,
    wall_solid_ratio: float,
    minimum_flank_support: float,
) -> str:
    """Grade an opening on its supporting evidence, not on its classification.

    Classification and confidence answer different questions. `unclassified_gap`
    means the void's semantics are unknown; confidence means how well the void
    itself is evidenced. A strongly supported void whose purpose is unclear is
    still a reliable observation, and a weakly supported doorway is not.
    """
    flank = min(left_support, right_support)
    if (
        flank >= HIGH_CONFIDENCE_FLANK_SUPPORT
        and floor_support >= HIGH_CONFIDENCE_FLOOR_SUPPORT
        and wall_solid_ratio >= HIGH_CONFIDENCE_WALL_SOLID_RATIO
    ):
        return "high"
    # `medium` means the candidate cleared the configured gates. There is no
    # separate intermediate flank threshold, because flank support is quantised
    # to 1/opening_flank_bins and a second level would collapse onto the gate.
    if flank >= minimum_flank_support and floor_support >= HIGH_CONFIDENCE_FLOOR_SUPPORT:
        return "medium"
    return "low"


def _wall_side_areas(
    profile: _WallProfile,
    cells: frozenset[tuple[int, int]],
    grid_size_m: float,
    config: StructureConfig,
) -> dict[tuple[int, int], float]:
    """Map each occupancy cell to the area of the region it belongs to.

    The wall is cut out of the grid along its whole line, so the floor on either
    side becomes its own region. That is what makes "this opening connects two
    scanned areas" checkable: a doorway physically joins the floors, so a plain
    connected-component split would merge exactly the two areas the opening is
    supposed to connect.

    Areas are returned rather than identifiers. Region *identity* is not
    published, because components are re-derived per wall from a different line
    cut and would not be comparable between openings.
    """
    cell_area = grid_size_m * grid_size_m
    minimum_cells = max(1, int(round(MINIMUM_REGION_AREA_M2 / cell_area)))
    dead_band = config.opening_wall_band_m + grid_size_m
    sides: dict[int, set[tuple[int, int]]] = {1: set(), -1: set()}
    for cell in cells:
        centre = (np.asarray(cell, dtype=np.float64) + 0.5) * grid_size_m
        signed = float(centre @ profile.normal_xy) - profile.offset_c
        if abs(signed) <= dead_band:
            continue
        sides[1 if signed > 0 else -1].add(cell)
    areas: dict[tuple[int, int], float] = {}
    for sign in (1, -1):
        for component in connected_occupancy_components(sides[sign]):
            if len(component) < minimum_cells:
                continue
            area = len(component) * cell_area
            for cell in component:
                areas[cell] = area
    return areas


def _adjacency_across_void(
    *,
    profile: _WallProfile,
    centre_along_m: float,
    width_m: float,
    interior_sign: float,
    region_areas: dict[tuple[int, int], float],
    grid_size_m: float,
    config: StructureConfig,
) -> tuple[float, float, int] | None:
    """Return near area, far area and probe agreement when both sides are scanned."""
    near_areas: list[float] = []
    far_areas: list[float] = []
    span = width_m / 2
    for offset in np.linspace(-span, span, FLOOR_PROBE_SAMPLES):
        along = centre_along_m + float(offset)
        for sign, collected in ((interior_sign, near_areas), (-interior_sign, far_areas)):
            # Probe twice so a one-cell sliver beyond the wall cannot pass as
            # space a homeowner would recognise as another room.
            found = {
                region_areas.get(
                    _cell_of(profile.floor_point(along, sign * distance), grid_size_m)
                )
                for distance in (
                    config.opening_probe_distance_m,
                    config.opening_probe_distance_m * 2,
                )
            }
            found.discard(None)
            if len(found) == 1:
                collected.append(float(found.pop()))
    agreement = min(len(near_areas), len(far_areas))
    if agreement < MINIMUM_ADJACENCY_PROBES:
        return None
    near = float(np.median(near_areas))
    far = float(np.median(far_areas))
    if near <= 0 or far <= 0:
        return None
    return near, far, agreement


def _cell_of(point_xy_m: NDArray[np.float64], grid_size_m: float) -> tuple[int, int]:
    cell = np.floor(point_xy_m / grid_size_m).astype(np.int64)
    return int(cell[0]), int(cell[1])


def _project_to_floor(
    points_xyz_m: NDArray[np.float64], coordinates: FloorCoordinateSystem
) -> NDArray[np.float64]:
    origin = np.asarray(coordinates.origin_xyz_m, dtype=np.float64)
    axes = np.column_stack(
        (
            np.asarray(coordinates.x_axis_xyz, dtype=np.float64),
            np.asarray(coordinates.y_axis_xyz, dtype=np.float64),
        )
    )
    return (points_xyz_m - origin) @ axes


def _normalized(vector: FloatArray) -> NDArray[np.float64]:
    array = np.asarray(vector, dtype=np.float64)
    norm = float(np.linalg.norm(array))
    if not math.isfinite(norm) or norm < 1e-12:
        raise ValueError("vector must have a finite non-zero norm")
    return array / norm


def _tuple2(values: FloatArray) -> tuple[float, float]:
    return float(values[0]), float(values[1])
