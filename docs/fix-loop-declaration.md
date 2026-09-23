# Fix loop declaration

Written **before** the fix was implemented. The prediction below was produced by a read-only experiment against the existing pipeline, not by running the fix, and the implementation had not been started when this file was committed. The after-run is recorded separately in [fix-loop-result.md](fix-loop-result.md).

## 1. The single worst-performing gate, with the failing number

**Boundary support.** `StructureConfig.minimum_boundary_fill_ratio` requires that at least **60%** of a published floor outline be backed by occupied floor cells. Below that threshold the pipeline labels the area provisional and sets measurement confidence to `caution`.

Measured on the three supplied captures under the frozen `fast` profile, from `runs/r5-a/*/result.json`:

| Capture | Boundary support | Requirement | Outline method | Published area |
|---|---:|---:|---|---:|
| `single_room.zip` | 94.9% | 60% | occupancy concave | 16.40 m² |
| `single_scan_floor_only.zip` | **57.4%** | 60% | convex fallback | 78.23 m² provisional |
| `single_scan_with_ceiling.zip` | **48.5%** | 60% | convex fallback | 85.80 m² provisional |

The worst is `single_scan_with_ceiling.zip` at **48.5%, which is 11.5 percentage points below the requirement**. Two of three captures fail. This is the correct gate to declare: it is the only self-imposed numerical gate currently failing on real data, it governs the headline floor-area number, and it is measurable without ground truth. The opening, ceiling and repeatability accuracy gates cannot be scored because no survey, tape or laser ground truth was supplied.

## 2. Root-cause hypothesis

**Two presentational constraints are being applied as geometric acceptance criteria, and they reject a contour that the evidence supports.**

`select_floor_outline` in `src/cozmo_scan/floorplan.py` accepts an occupancy contour only if it passes six gates. Four are geometric: component retention, direct boundary support, support improvement over the occupancy convex hull, and simple counter-clockwise topology. Two are not: a **36-vertex cap** and a **1.5x perimeter-ratio cap**. Both failing captures are rejected by those two gates alone, and by nothing else.

The recorded reasons in the artifacts are explicit:

```
single_scan_floor_only:   "occupancy contour has 63 vertices; maximum is 36"
single_scan_with_ceiling: "occupancy contour has 57 vertices; maximum is 36"
```

The decision record shows where the caps came from and why they are now obsolete. D-051 introduced them, and its stated evidence was readability, not geometry:

> The first real contour had 80 vertices and an **unreadable 34.28 m labelled perimeter** despite 97.5% support.

Three decisions later, D-054 fixed readability directly, at the renderer:

> Preserve every polygon edge and length in machine-readable output, but when a plan has more than 12 edges render at most the 14 longest edges of at least 0.50 m as dimension labels.

D-054 removed the reason D-051's caps existed. The caps were left in the acceptance path, where they now silently discard geometry that is well supported by the data. The drawing is already protected by a label cap that is independent of vertex count.

### Evidence that the rejected contours are geometrically sound

A read-only experiment reconstructed each capture, rebuilt the occupancy contour at the unchanged 0.24 m simplification tolerance, and measured what the rejected candidate would have scored:

| Capture | Rejected contour | Support | Area | vs convex fallback |
|---|---:|---:|---:|---|
| `single_scan_floor_only.zip` | 63 vertices | **96.9%** | 45.52 m² | convex: 57.4%, 78.23 m² |
| `single_scan_with_ceiling.zip` | 57 vertices | **95.2%** | 41.12 m² | convex: 48.5%, 85.80 m² |

Both rejected candidates pass every geometric gate: retention 98.3% and 94.2% against an 80% requirement, support 96.9% and 95.2% against 55%, both simple polygons, and both smaller in area than their convex hulls. They fail only on vertex count and perimeter ratio.

### A competing hypothesis that was tested and rejected

The obvious alternative was that the contours are ragged from cell-scale sampling noise, which morphological smoothing of the occupancy mask would remove. This was tested across close/open radii from 1/0 to 4/2 cells and **it does not hold**. Raw traced vertices fell only from 1,086 to 660 for the floor-only capture, still 38 after simplification and still above the cap, while the area inflated from 45.52 m² to 53.94 m² and support collapsed from 96.9% to 81.9%. Smoothing trades away precisely the support the gate measures. The boundaries are not noisy; they are genuinely complex, because both captures are partial scans of larger spaces where the observed floor has many real lobes and inlets. A 57 to 63 vertex description of that is honest, and forcing it to 36 is not.

## 3. The fix I intend to ship

Separate presentational constraints from geometric acceptance in `select_floor_outline`:

1. Raise `maximum_concave_vertices` from 36 to 200 and `maximum_concave_perimeter_ratio` from 1.50 to 3.00, and redocument both as pathology guards that catch a degenerate trace, not readability limits.
2. Leave every geometric gate untouched: retention 0.80, support 0.55, support improvement 0.08, area not exceeding the convex hull, simple counter-clockwise topology.
3. Leave the 0.24 m concave simplification tolerance untouched, so the change is not tolerance tuning.
4. Rely on D-054's existing label cap for drawing readability, and verify the rendered plans are still legible rather than assuming it.

No other threshold changes, and no per-sample special casing.

## 4. Predicted numbers after the fix

The prediction is the measured result of the read-only experiment in section 2, so it is a forecast of the implementation reproducing an already-measured geometry, not an estimate of an unknown.

| Capture | Support before | **Support predicted** | Area before | **Area predicted** | Gate |
|---|---:|---:|---:|---:|---|
| `single_room.zip` | 94.9% | 94.9%, unchanged | 16.40 m² | 16.40 m², unchanged | passes, stays passing |
| `single_scan_floor_only.zip` | 57.4% | **96.9%** | 78.23 m² | **45.52 m²** | fail to **pass** |
| `single_scan_with_ceiling.zip` | 48.5% | **95.2%** | 85.80 m² | **41.12 m²** | fail to **pass** |

Headline prediction: **the boundary-support gate goes from 1 of 3 passing to 3 of 3 passing, and the worst capture moves from 48.5% to 95.2%.** Both provisional area labels are withdrawn and measurement confidence stops being driven by this warning. Vertex counts become 63 and 57, within the raised 200 guard. Perimeter ratios become 2.20 and 1.85, within the raised 3.00 guard.

Confidence: **high** for the support and area numbers, because they were measured on the real captures before writing this. Medium for the secondary consequences, listed next.

## 5. What would make this prediction wrong, and what it does not claim

- **It does not claim the new areas are more accurate.** No ground truth was supplied, so neither 78.23 m² nor 45.52 m² can be called correct. The defensible claim is narrower and is the one the gate measures: the published boundary goes from 57.4% and 48.5% backed by observed floor to 96.9% and 95.2%. A 42% and 52% area reduction is consistent with the documented convex-hull failure mode of overfilling unscanned gaps, which has been a known structural-analysis limitation, but consistency is not verification.
- **Readability is a genuine risk.** A 63-vertex plan may be hard to read even with at most 14 dimension labels drawn. If the rendered plan is not legible, the fix is incomplete and the honest outcome is to ship the measurement change and record the rendering shortfall rather than reinstate the cap.
- **Perimeter ratios of 2.20 and 1.85 are high.** The contour may follow unscanned inlets rather than walls. The counter-evidence is the support metric itself, which is exactly the measure of whether the boundary hugs observed floor, at 96.9% and 95.2%.
- **Downstream effects are possible.** Opening detection consumes the same occupancy grid, and the published areas feed the batch summary and the evaluator. If opening counts or the drift ablation move, that must be reported rather than filtered out.
- **If the measurement is right but the drawing is unusable**, the correct resolution is a rendering improvement, not re-tightening a geometric gate with a presentational number.
