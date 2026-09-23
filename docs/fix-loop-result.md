# Fix loop result

Companion to [fix-loop-declaration.md](fix-loop-declaration.md), which was written and saved before any implementation work began. This file records what shipped, what the numbers actually did, and one thing the fix surfaced that the declaration had flagged only as a risk.

## Verdict in one line

**The declared gate moved from fail to pass on both failing captures, and the prediction was numerically exact. The fix also revealed that two of the three captures are partial sweeps of larger spaces rather than single rooms, which the product now discloses instead of masking behind a convex hull.**

## Prediction versus actual

| Capture | Support before | Support predicted | **Support actual** | Area before | Area predicted | **Area actual** |
|---|---:|---:|---:|---:|---:|---:|
| `single_room.zip` | 94.9% | 94.9% | **94.9%** | 16.40 m² | 16.40 m² | **16.40 m²** |
| `single_scan_floor_only.zip` | 57.4% | 96.9% | **96.9%** | 78.23 m² | 45.52 m² | **45.52 m²** |
| `single_scan_with_ceiling.zip` | 48.5% | 95.2% | **95.2%** | 85.80 m² | 41.12 m² | **41.12 m²** |

Prediction error: **+0.01 percentage points on support and +0.003 m² on area**, on every capture. The boundary-support gate went from **1 of 3 passing to 3 of 3 passing**, and the worst capture moved from **48.5% to 95.2%**. Both provisional area labels were withdrawn. Vertex counts are 27, 63 and 57, inside the raised 200 guard; perimeter ratios are within the raised 3.00 guard.

The prediction was exact because it was not an estimate. Section 2 of the declaration measured the rejected contours on the real captures before implementation, so the prediction was a forecast that the implementation would reproduce an already-measured geometry. It did.

## What shipped

`src/cozmo_scan/models.py`, two thresholds, with no other geometric change:

| Field | Before | After | Role |
|---|---:|---:|---|
| `maximum_concave_vertices` | 36 | 200 | pathology guard, was a readability limit |
| `maximum_concave_perimeter_ratio` | 1.50 | 3.00 | pathology guard, was a readability limit |

Every geometric gate is untouched: component retention 0.80, boundary support 0.55, support improvement 0.08 over the occupancy convex hull, area not exceeding the convex hull, and simple counter-clockwise topology. The 0.24 m concave simplification tolerance is untouched, so this is not tolerance tuning. No per-sample special casing.

`src/cozmo_scan/floorplan.py` gained one disclosure warning, described below.

## Root cause, confirmed

The diagnosis in the declaration was correct and is now demonstrated. Two presentational constraints were sitting in a geometric acceptance path. D-051 introduced them for readability, citing "an unreadable 34.28 m labelled perimeter". D-054 then solved readability at the renderer by capping drawn dimension labels independently of vertex count, which removed the reason the caps existed. Nobody removed the caps, so they went on rejecting contours with 95% to 97% occupied support and forcing a convex fallback that overfilled unscanned space.

The competing hypothesis, that the contours were ragged from cell-scale sampling noise, was tested before implementation and rejected. Morphological smoothing of the occupancy mask across close/open radii from 1/0 to 4/2 cut raw traced vertices only from 1,086 to 660 while inflating area from 45.52 m² to 53.94 m² and collapsing support from 96.9% to 81.9%. The boundaries are genuinely complex, not noisy.

## What the fix surfaced, and the honest cost

The declaration identified a risk that the high perimeter ratios could indicate contours following unscanned inlets rather than walls. The risk materialised, and it is larger than the ratios suggested.

| Capture | Perimeter before | Perimeter after | Area after | Perimeter vs most compact outline of equal area |
|---|---:|---:|---:|---:|
| `single_room.zip` | 31.51 m | 31.51 m | 16.40 m² | 1.95 |
| `single_scan_floor_only.zip` | 33.28 m | **73.10 m** | 45.52 m² | **2.71** |
| `single_scan_with_ceiling.zip` | 36.04 m | **61.15 m** | 41.12 m² | **2.38** |

A 45.52 m² room bounded by 73.10 m of perimeter is not a shape a homeowner would recognise. Visual inspection of `floorplan.png` confirms it: the outline is legible, correctly drawn and correctly labelled, but it is a sprawling star-shaped extent with many spurs and inlets, not a room. The project aims to produce a plan a homeowner would recognise, and this outline does not meet that standard even though it passes the support gate.

The support metric is not wrong. At 96.9% it is correctly reporting that the boundary hugs observed floor. What it cannot report, and never could, is whether that floor is **one room**. These two captures sweep parts of larger spaces, and there is no single room for either outline to be. That is why neither candidate was ever good: the convex hull overfilled unscanned space at 48.5% support, and the occupancy contour tracks coverage at 96.9% support. Both are honest answers to different questions, and neither is a room plan.

## How that was resolved

Three options were considered. Reverting would restore a gate that is demonstrably rejecting well-supported geometry for a presentational reason. Reinstating a tightened perimeter cap would have meant choosing a threshold that happens to separate these three samples, which is exactly the per-sample tuning the project forbids. Publishing the sprawling outline with no comment would let the product imply a room where there is none.

What shipped instead is quantitative disclosure with no accept or reject behaviour. When a concave outline's perimeter exceeds twice the most compact outline enclosing the same area, the result carries:

> The outline perimeter is 73.1 m for 45.5 m2, which is 2.7 times the most compact outline of that area. The boundary follows scanned coverage, so this is the measured extent of observed floor and should not be read as one room's wall layout without inspecting the plan.

The threshold is 2.0, a disclosure trigger only. It never rejects an outline, because no evidence available here can establish how many rooms were scanned. A rectangular room sits near 1.0 to 1.3. `single_room` measures 1.95 and is not flagged; the two sweeps measure 2.71 and 2.38 and are. Note honestly that 1.95 is close to the trigger, and the threshold was not moved to create separation, in the same way the 36-vertex cap and the 5% drift threshold were left where they were when they produced awkward near-misses.

## Downstream effects, checked

| Effect | Result |
|---|---|
| Opening counts | unchanged: 0 of 5, 1 of 7, 0 of 9 |
| Measurement confidence | unchanged at `caution` on all three, now driven by remaining warnings rather than by weak boundary support |
| Result status | unchanged at `ok_with_warnings` |
| Warnings resolved | the convex-fallback warning and the "only 57.4% / 48.5% backed by occupied floor cells" warning, on both captures |
| Warnings added | the concave-contour caveat, plus the new sprawl disclosure on the two sweeps |
| Principal dimensions | `10.88 x 9.44` to `10.39 x 9.49` m, and `12.40 x 9.28` to `10.67 x 8.66` m |
| Test suite | 169 tests, all passing, unchanged count |
| Determinism | preserved |

## Regenerating both runs

Both arms are regenerable from raw inputs, not narrated. The before run is preserved and was generated by the pre-fix code; the after run is reproduced by the current code with the same command.

```text
# after, current code
python -m cozmo_scan batch sample --output runs/fixloop-after --profile fast

# before, preserved
runs/r5-a/          post-audit, pre-fix-loop batch: support 94.9% / 57.4% / 48.5%
runs/baseline-before/   recorded baseline, retained for comparison
```

The readable diff is the two thresholds in the table under "What shipped" plus one added warning block in `floorplan.py`. Nothing else in the numerical path changed.

## Scoring this honestly

Correct root cause: yes, established from the decision record and confirmed by a rejected competing hypothesis. Shipped fix: yes, two thresholds and one disclosure. Gate moved from fail to pass: yes, on both failing captures, 48.5% to 95.2% and 57.4% to 96.9%. Prediction accuracy: exact to 0.01 percentage points.

Passing the gate did not make the product better in every respect. It made the published boundary honest about what was observed, and it exposed that two of the three supplied captures are not single rooms, which the convex fallback had been concealing behind a plausible-looking but 48.5%-supported rectangle. The new areas are measured coverage extents, not validated room areas, because no ground truth was supplied.
