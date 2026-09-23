# Cozmo Scan technical report

Cozmo Scan is a local Python 3.12 pipeline that validates and inventories photo/video media and turns Stray Scanner LiDAR captures into measured coverage outlines, structural evidence, and inspectable artifacts. It runs successfully on the three supplied LiDAR captures and is deliberately conservative when evidence is missing. Each tier has an explicit output contract: media manifests for photo/video and measured geometry for LiDAR. Global multi-room stitching, damage analysis, repair scope, and physical benchmark evidence are outside the current processing scope.

No survey, tape, or laser reference was supplied. Consequently, no number in this report is an absolute-accuracy claim. Fit residuals describe internal consistency, bootstrap intervals describe estimator precision, and synthetic fixtures test known geometry. None substitutes for measurements of the physical rooms.

## 1 Architecture

The pipeline keeps acquisition, numerical geometry, orchestration, and presentation separate:

```text
ZIP or capture directory
        |
        v
dataset.py          safe read-only discovery, parsing, validation, frame matching
        |
        v
reconstruction.py   depth filtering, back-projection, poses, voxel fusion
        |
        v
floorplan.py        floor, ceiling, walls, supported floor outline
        +------> openings.py   wall identity, void evidence, width, adjacency
        +------> intervals.py  bootstrap precision intervals
        |
        v
pipeline.py         provenance, capabilities, warnings, result contract
        |
        v
outputs.py          JSON, PLY, SVG, PNG, and Markdown artifacts
        |
        +------> batch.py      same pipeline across all captures
        +------> benchmark.py  comparison with independent truth
        +------> drift.py      recorded-pose versus corrected ablation

photo/video file or directory
        |
        v
media.py            decode images, inspect video streams, hash, publish manifest
```

Depth pixels that pass confidence and range checks are back-projected with scaled camera intrinsics, transformed by recorded ARKit camera-to-world poses, and fused into a deterministic voxel cloud. Structural analysis identifies the floor relative to the camera trajectory, defines a floor-local coordinate system, and builds an occupancy-supported outline from floor inliers. A concave outline is accepted only when retention, direct support, support improvement, topology, area, and pathology guards pass; otherwise the convex fallback is explicit.

Wall planes receive deterministic per-capture identifiers and finite spans. Opening candidates are vertical void runs bounded by credible wall material. A candidate must have solid flanks, acceptable dimensions, sufficient wall coverage, and positive evidence behind the void through pass-through points or far-side floor. Absence of wall returns alone is never treated as a door.

`ingest` publishes `media-input.json` for a photo set or video. `run` publishes exactly seven LiDAR files: `result.json`, `reconstruction.ply`, `topdown.png`, `trajectory.png`, `floorplan.svg`, `floorplan.png`, and `report.md`. `batch` adds `batch.json` and `batch-report.md`; `evaluate` produces an evaluation JSON, report, and capability matrix; `ablate` produces JSON and Markdown. Current result, structure, and batch schema is `1.4.0`, with readers for `1.0.0` through `1.3.0`.

## 2 Tier design and device matrix

| Tier | Status | Input | Output |
|---|---|---|---|
| LiDAR | Implemented with limitations | Stray Scanner depth, confidence, intrinsics, and ARKit poses from a LiDAR-equipped Pro iPhone | Measured coverage outline, walls, optional ceiling, conservative openings, PLY, SVG/PNG, JSON, report |
| Video | Implemented ingestion | MP4, MOV, or M4V inspected by local FFprobe | Versioned media manifest with stream metadata and provenance |
| Photo | Implemented ingestion | Decoded JPEG, PNG, TIFF, BMP, or WebP file set | Versioned media manifest with dimensions, formats, and provenance |

The implementation is CPU-only and uses NumPy, Pillow, and Pydantic; video inspection uses a local FFprobe executable. It requires no GPU, account, API key, database, hosted service, or network during processing. Three bounded LiDAR profiles share one pipeline: `test` uses 10 frames and 8 cm voxels, `fast` uses 200 frames and 4 cm voxels, and `quality` uses 500 frames and 2 cm voxels.

The architectural boundary between ingestion and geometry is the metric point cloud. Photo and video inputs are genuinely decoded or stream-validated, hashed, and recorded without absolute paths. They still lack defensible metric scale, camera placement, uncertainty, and cross-room registration, so the media command stops at ingestion rather than emitting a fabricated point cloud or floor plan.

## 3 Drift handling

Recorded ARKit poses remain the published control. The ablation estimates a bounded vertical correction by measuring each keyframe's near-floor residual against the global floor plane, smoothing the residual sequence, centring it, and translating the keyframe along the floor normal. Both arms are fully reconstructed and measured.

A correction is rejected before residual comparison if it loses too many fused points or floor inliers. It is accepted only when the trimmed floor residual improves by at least 5% without material regression in wall residual, wall count, or boundary support. This gate replaced an earlier band-limited metric that could improve simply because difficult inliers left the band.

| Capture | Decision | Band RMSE off to on | Trimmed residual off to on |
|---|---|---:|---:|
| `single_room.zip` | Rejected; improvement below gate | 0.01581 to 0.01509 m | 0.07932 to 0.08044 m |
| `single_scan_floor_only.zip` | Rejected; 1.0% point loss | 0.01576 to 0.01413 m | 0.06994 to 0.07554 m |
| `single_scan_with_ceiling.zip` | Rejected; improvement below gate | 0.01432 to 0.01468 m | 0.39240 to 0.38636 m |

All supplied captures therefore publish recorded-pose geometry. The negative result is intentional evidence: the available vertical correction is not strong enough to justify changing the product. Horizontal drift and yaw remain uncorrected, and the ablation does not prove global accuracy.

## 4 Error budget

| Source | Current control | Remaining limitation |
|---|---|---|
| Camera calibration and depth scale | Recorded intrinsics, metric depth, bounded range | No independent scale calibration |
| ARKit pose error | Distributed keyframes, trajectory evidence, drift ablation | Horizontal drift and yaw remain |
| Depth noise and incidence angle | Confidence filtering, voxel fusion, robust plane fitting | Mirrors, glass, gloss, darkness, and grazing views reduce or distort returns |
| Incomplete floor coverage | Occupancy support and retention gates, explicit sprawl warning | Coverage boundary may not be a room boundary |
| Ceiling coverage | Minimum support and geometry gates | Missing ceiling remains `null`; wall height may be coverage-limited |
| Wall and opening evidence | Wall solidity, flanks, common void, behind-void evidence | Conservative gates can miss true openings |
| Estimator stability | Bootstrap resampling and method-agreement warning | Precision does not measure bias |
| Physical accuracy | Evaluator accepts independent truth and exact gates | No genuine truth manifest exists |

The most important product distinction is between observed coverage and architecture. The two larger supplied captures produce well-supported but sprawling outlines. Their warnings state that the result is a measured extent of observed floor and must not be read as a single room's wall layout without inspecting the plan.

## 5 Calibration and measurement analysis

The three captures validate without errors and run with one frozen `fast` configuration:

| Capture | Points | Area | Principal dimensions | Perimeter | Ceiling | Boundary support |
|---|---:|---:|---:|---:|---:|---:|
| `single_room.zip` | 70,928 | 16.40 m2 | 8.07 by 4.55 m | 31.51 m | unavailable | 94.9% |
| `single_scan_floor_only.zip` | 171,537 | 45.52 m2 | 10.39 by 9.49 m | 73.10 m | unavailable | 96.9% |
| `single_scan_with_ceiling.zip` | 242,402 | 41.12 m2 | 10.67 by 8.66 m | 61.15 m | 2.40 m | 95.2% |

Every floor-plan scalar and available ceiling height carries a two-sided 95% nonparametric bootstrap precision interval using 64 resamples and seed 29. The estimator is rerun for each resample. Opening width does not yet have an interval and the result warns accordingly.

The ceiling estimate on the third capture is 2.4012 m with interval `[2.4011, 2.4025] m`, showing high estimator stability but not verified accuracy. Its floor-area interval is `[38.73, 84.45] m2` because 8% of resamples switch from the concave estimator to the convex fallback. The output labels this interval bimodal; the width is evidence that the capture is near a method-selection boundary, not random reporting noise.

Opening detection is also deliberately sparse. `single_room` publishes none because its long walls are only 41% to 51% solid. `single_scan_floor_only` publishes one `window_like` opening at 0.77 m with 217 pass-through points. `single_scan_with_ceiling` publishes none because no candidate has evidence behind it. No capture claims room adjacency.

The evaluator encodes ceiling, opening, photo/video wall, and repeatability gates. It also counts missing and phantom openings and reports interval coverage descriptively. Without physical truth, the gates remain unevaluated rather than being scored against the pipeline's own output.

## 6 Fix loop

The declared failing gate was minimum boundary support. Before the fix, two captures fell back to convex outlines with 57.4% and 48.5% direct support against a 60% requirement. The root cause was not noisy geometry: renderer-driven vertex and perimeter limits remained in the geometric acceptance path after label density had been solved separately.

The fix reclassified the vertex and perimeter limits as broad pathology guards while leaving the evidence gates and simplification tolerance unchanged. Boundary support became 94.9%, 96.9%, and 95.2%, so all three pass the declared gate. The prediction for the worst capture was accurate to 0.01 percentage points of support and 0.003 m2 of area.

The improvement also exposed a product limitation. Areas fell from 78.23 to 45.52 m2 and from 85.80 to 41.12 m2, while perimeters became 2.7 and 2.4 times the most compact outline of equal area. The convex fallback had concealed partial sweeps behind plausible rectangles. The new result is more faithful to observed evidence but less like a conventional floor plan. That cost is reported rather than tuned away.

The declaration and result are in `docs/fix-loop-declaration.md` and `docs/fix-loop-result.md`. Before and after runs can be regenerated from the local sample archives. Two fresh batches produce 18 of 23 artifacts byte-identically; the other five differ only in recorded durations.

## 7 Known failure modes and scope boundary

- Mirrors and glass can remove returns or create reflected/pass-through geometry.
- Poor light damages ARKit tracking even when LiDAR depth remains available.
- Furniture and missing wall coverage suppress wall and opening evidence.
- A coverage-supported outline can be a partial sweep rather than a semantic room.
- Opening detection prefers a miss over a phantom and can reject real glazed or poorly observed openings.
- Wall and opening IDs are deterministic per capture and configuration, not stable physical identities across captures.
- Adjacency evidence is local to one wall and is not a property-wide room graph.
- Published intervals measure precision, not accuracy, and opening width has no interval.
- The drift ablation addresses vertical floor-relative error only.
- Photo/video ingestion is implemented; metric reconstruction is the LiDAR-tier product. Stitching, damage, concealed-condition, repair-scope, and incumbent comparison remain outside the current scope.
- Real accuracy, calibration coverage, and repeatability remain unmeasured because the required physical benchmark data is absent.

The project's strongest claim is reproducibility: the dependency set can be installed locally, media can be validated into deterministic manifests, the supplied LiDAR archives can be validated, the same geometry and identifiers can be reproduced, every warning and evidence field can be inspected, the automated suite can be run, and independent truth can be supplied to the evaluator. The complete capability status is in `docs/compliance-matrix.md`.
