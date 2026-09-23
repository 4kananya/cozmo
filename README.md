# Cozmo Scan

Offline media ingestion plus reconstruction and measured floor-plan generation for Stray Scanner/ARKit LiDAR captures.

This repository contains the runnable pipeline, tests, capture instructions, benchmark tooling, fix-loop evidence, and technical documentation for the project.

## Current status

The project provides deterministic photo and video ingestion plus an offline LiDAR geometry pipeline with validation, metric reconstruction, structural measurement, component-aware concave floor outlines, deterministic wall identity, conservative opening detection, evidence-gated room adjacency, independent ground-truth evaluation, precision intervals, and bounded plane-anchored drift-correction ablation. Photo sets are decoded and inventoried; video streams are inspected with local FFprobe. Metric floor-plan reconstruction remains LiDAR-only.

The CLI can ingest photo/video inputs, validate LiDAR captures, reconstruct, measure, produce a complete single-capture result, run the same configuration across a directory, score published results against independent measurements, and publish a drift-correction ablation.

## Architecture

The implementation is an offline, deterministic pipeline. Diagnostic commands expose the early stages; `run` composes one complete capture; `batch` repeatedly calls that same final path with one immutable configuration.

```text
ZIP/directory capture
        |
        v
dataset.py          validate structure, calibration, poses, and frame pairing
        |
        v
reconstruction.py   back-project depth, apply poses, and voxel-fuse metric XYZ
        |
        v
floorplan.py        fit structural planes and measure the supported floor outline
        |
        +---------> openings.py    wall identity, opening evidence gates, adjacency
        |
        v
pipeline.py         combine provenance, quality evidence, warnings, and capabilities
        |
        v
outputs.py          publish the seven-file result bundle
        ^
        |
batch.py            discover captures and reuse the same pipeline sequentially
        |
        v
benchmark.py        compare published results with independent truth and exact gates

drift.py            rebuild both drift-correction arms and publish the ablation
grid.py             occupancy-cell primitives shared by floorplan.py and openings.py
media.py            decode/inventory photo sets and inspect video streams
```

`models.py` contains the immutable versioned contracts, while `cli.py` contains only command parsing and user-facing orchestration. Numerical logic is not duplicated in the CLI, batch runner, or demo script.

## Requirements

- Python 3.12 or newer
- The supplied sample archives, stored locally in the ignored `sample/` directory
- A Windows, Linux, or macOS environment capable of installing the dependencies declared in `pyproject.toml`
- FFmpeg/FFprobe on `PATH` for video ingestion only

No GPU, cloud account, API key, database, or web server is required.

Project documents include the [capability matrix](docs/compliance-matrix.md), [capture route](docs/capture-route.md), [device matrix](docs/device-matrix.md), [technical report](docs/technical-report.md), and the [fix declaration](docs/fix-loop-declaration.md) with its [result](docs/fix-loop-result.md).

## Development setup

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\python -m cozmo_scan --help
```

Platform-neutral commands after activating a Python 3.12 environment:

```text
python -m pip install -e ".[dev]"
python -m cozmo_scan --help
```

## Sample data

Place the three source archives in the ignored `sample/` directory:

```text
sample/
  single_room.zip
  single_scan_floor_only.zip
  single_scan_with_ceiling.zip
```

The samples are deliberately not tracked. Two exceed GitHub's normal 100 MiB per-file limit, and the data is supplied separately.

Local sample fingerprints recorded before repository cleanup:

| File | SHA-256 |
|---|---|
| `single_room.zip` | `0805f742d378e4bda480fef6e5839304364807bb7b77bb459983003727e9699c` |
| `single_scan_floor_only.zip` | `f822287268297d2adab49deff8e0ee5f50f05304b450d8d47d0b5eb476aa74d4` |
| `single_scan_with_ceiling.zip` | `4bfbeb11ee21b114c46ad43cf0c9602d8ada827397f4e8b3c70dd827d0191379` |

These hashes identify the locally audited inputs; they are not download credentials or proof of ground truth.

## Ingest photo or video input

Photo ingestion recursively decodes supported JPEG, PNG, TIFF, BMP, and WebP files. Video ingestion accepts MP4, MOV, and M4V files and validates the primary stream with local FFprobe:

```powershell
python -m cozmo_scan ingest photos\room-a `
  --tier photo `
  --output runs\media\room-a-photos

python -m cozmo_scan ingest videos\room-a.mp4 `
  --tier video `
  --output runs\media\room-a-video
```

Each command writes `media-input.json` with relative filenames, SHA-256 hashes, byte counts, dimensions, formats, and available video duration/frame/codec metadata. Absolute source paths are not published. The photo/video tier product is the validated media manifest; calibrated point clouds and measured plans are produced by the LiDAR tier.

## Reproducible demonstration

After installation and placing the samples as shown above, run the complete cross-platform demonstration from the repository root:

```text
python scripts/demo.py --sample-dir sample --output runs/demo --profile fast
```

The script verifies that all three named archives are present, runs the complete unit suite, validates `single_room.zip`, executes the frozen all-sample batch, reads `batch.json`, and prints the key measurements and artifact locations. It uses subprocess argument lists rather than a shell and stops on a failed test or validation command.

The output directory is protected. To deliberately replace a previous demo, append `--overwrite`. If the unit suite was just run separately, append `--skip-tests`. A successful complete demonstration returns exit code `0`; a validation, processing, or evidence failure returns a nonzero code.

## Validate a capture

Human-readable report:

```powershell
python -m cozmo_scan validate "sample\single_room.zip"
```

Machine-readable report:

```powershell
python -m cozmo_scan validate "sample\single_room.zip" --json
```

Validation checks capture-root discovery, required files, calibration, odometry, frame matching, optional IMU/RGB presence, and representative depth/confidence images. It reads ZIP members directly and does not extract the complete capture.

Exit codes are `0` for a valid capture, `2` for an input or validation failure, and `1` for an unexpected internal failure. Warnings do not make an otherwise usable capture invalid.

## Reconstruct a metric point cloud

Run the bounded baseline profile:

```powershell
python -m cozmo_scan reconstruct `
  "sample\single_room.zip" `
  --output "runs\single-room-fast" `
  --profile fast
```

The output directory contains:

- `reconstruction.ply`: binary little-endian XYZ point cloud in metres;
- `topdown.png`: X-Z density view with the camera trajectory in red, start in green, and end in blue;
- `reconstruction.json`: effective parameters, counts, bounds, trajectory evidence, runtime, warnings, and artifact names.

Profiles deliberately bound work:

| Profile | Maximum frames | Pixel stride | Voxel size |
|---|---:|---:|---:|
| `test` | 10 | 8 | 8 cm |
| `fast` | 200 | 4 | 4 cm |
| `quality` | 500 | 2 | 2 cm |

Frames are distributed across the capture by default. `--max-frames` may lower or override the profile limit for audited diagnostic runs. `--frame-selection contiguous-start` exists only to verify nearby-pose overlap. Existing known artifacts are protected unless `--overwrite` is supplied.

The reconstruction stage uses NumPy, Pillow, and the recorded depth/pose data directly. It does not require Open3D, SciPy, Matplotlib, RGB decoding, a GPU, or network access.

## Measure structural geometry

Run reconstruction plus structural analysis:

```powershell
python -m cozmo_scan measure `
  "sample\single_room.zip" `
  --output "runs\single-room-measured" `
  --profile fast
```

The measurement directory contains the three reconstruction artifacts above plus:

- `structure.json`: normalized floor/ceiling/wall planes, fit support and residuals, floor-local coordinates, polygon vertices, edge lengths, area, perimeter, principal dimensions, the opening analysis, effective thresholds, and warnings;
- `floorplan.svg`: scalable measured floor-plan drawing;
- `floorplan.png`: annotated preview with edge dimensions, scale bar, wall-direction markers, openings, and quality evidence.

In both plan drawings, teal dashes mark detected wall direction, red marks a `door_like` opening, and orange marks a `window_like` one. When the analysis is unavailable or published nothing, no opening is drawn and the side panel says so explicitly rather than leaving an empty plan to imply a room without openings.

The structural stage finds the floor relative to the recorded camera trajectory, fits horizontal planes with fixed-seed RANSAC, detects vertical walls with X-Z line RANSAC, and projects floor evidence into a local metric frame. The outline stage quantizes that evidence to an occupancy grid, closes only one-cell gaps, finds deterministic connected components, traces the largest outer contour, simplifies it, and verifies that it remains a simple polygon.

The occupancy contour is accepted on geometric evidence only: it must retain at least 80% of occupied cells, have at least 55% direct occupied support, improve support over the occupancy convex hull by at least 8 percentage points, stay within the convex hull's area, and be a simple counter-clockwise polygon. A 200-vertex and 3.0x-perimeter bound remain as pathology guards that catch a degenerate trace; they were previously 36 and 1.5x and were rejecting well-supported geometry for a presentational reason, which the fix loop corrected. Weak, fragmented, self-intersecting or unsupported contours use the previous convex hull and record the exact fallback reason.

A concave outline whose perimeter exceeds twice the most compact outline of equal area carries a warning giving both numbers, because occupied support says the boundary hugs observed floor and says nothing about whether that floor is one room. The legacy JSON field `convex_fill_ratio` is retained for compatibility; `boundary_support_ratio` is its clearer serialized alias for either outline method.

The audited `single_room.zip` fast run finds the floor, wall planes, and a missing-ceiling outcome. Its supported contour retains 95.7% of occupied cells, has 94.9% direct support, and measures approximately 8.07 x 4.55 m, 16.40 m², with 27 simplified vertices. This is substantially better supported than the 34.73 m² convex hull, but it is still an internal occupancy estimate, not proof of absolute accuracy without independent room measurements.

## Generate the complete result bundle

The primary single-capture product command is:

```powershell
python -m cozmo_scan run `
  "sample\single_room.zip" `
  --output "runs\single-room-final" `
  --profile fast
```

It writes exactly seven project artifacts:

- `result.json`: versioned result contract containing input SHA-256, inventory, effective parameters, reconstruction statistics, structural measurements, quality evidence, runtime versions, warnings, capability statuses, and artifact manifest;
- `reconstruction.ply`: metric XYZ point cloud;
- `topdown.png`: point-density and camera-path overview;
- `trajectory.png`: dedicated path rendering whose start-to-end distance is explicitly labelled as a closure proxy, not certified drift;
- `floorplan.svg` and `floorplan.png`: vector and raster measured-plan views;
- `report.md`: self-contained human-readable result, evidence, method, limitations, artifact guide, and capability coverage.

The final output is staged before publication. Existing known artifacts require `--overwrite`, and unrelated files in the destination are preserved. ZIP provenance is the SHA-256 of the exact archive bytes. Directory provenance uses a deterministic hash over sorted normalized member names and contents. Local absolute paths are not stored in the final result.

`result.json` also carries `room.openings`: the identified wall segments, every published opening with its width, optional height, classification, confidence and supporting evidence, any adjacency links, and every rejected candidate with the reason it was rejected.

The final schema marks photo/video ingestion as `supported`. Capabilities are tier-specific: media tiers publish validated provenance manifests, while the LiDAR tier publishes metric geometry. Damage detection, concealed-condition prediction, repair-scope generation, and live mobile processing remain outside the current scope; ground-truth accuracy and multi-room stitching are `not_evaluated`. Wall identity, opening detection, and room adjacency report their own status per capture. Missing measurements remain `null`.

The current result, structure, and batch schema is `1.4.0`, including published measurement intervals. Readers remain compatible with `1.0.0` through `1.3.0`; older artifacts load with missing openings as `null` and missing intervals as an empty collection rather than fabricated evidence.

## Openings and adjacency

`run`, `measure`, and `batch` all publish an opening analysis. Each accepted wall plane is given a finite extent and a deterministic identifier (`W01`, `W02`, …), and its surface is profiled in bins along its length. Two independent per-bin signals are kept: whether wall material is present, and whether the bin contains a tall vertical void. A door shows a void with no material; a window shows a void *and* material, from its sill and head.

A void is published only when all of the following hold:

- **something was observed behind it** — either the sensor saw through the void (points beyond the wall plane inside the void's own along and height window) or scanned floor continues across the wall line. This is the decisive gate. From the room side, an aperture and a wall patch that returned nothing are identical, so a curtain, mirror, dark panel or grazing-incidence hole would otherwise publish as a doorway;
- the wall is at least 60% solid, so voids on a fragmented wall are treated as unscanned surface;
- the wall is long enough to hold the opening plus its flanking wall, and a wall that is not says so rather than silently never producing one;
- solid, unperforated wall flanks the void on both sides, so the end of the scanned wall can never pass as an opening;
- the bins share a common vertical void, so unrelated per-bin sampling gaps do not accumulate into a false opening;
- the width falls between the configured minimum and maximum, re-checked after edge refinement.

Widths are refined below the profile bin size, because a 5 cm bin cannot meet the 2 cm opening-width gate. Each edge is bracketed within a local flank window and corrected inward by half the local sampling interval, so the estimator is two-sided rather than only ever widening the opening. On synthetic rooms a 0.90 m door measures 0.9043 m and a 1.20 m window measures 1.2053 m, both inside 2 cm, and the window's 0.90 m sill and 2.00 m head are recovered.

Every wall also reports whether its observed height was bounded by scan coverage rather than by a detected ceiling. Height-derived judgements are measured against the wall height, so that flag identifies when such a judgement was made against partial coverage. On the supplied captures all walls are coverage-limited for the two scans with no detected ceiling, and none are for the third.

Classification is deliberately hedged as `door_like`, `window_like`, or `unclassified_gap`. Confidence is graded on supporting evidence rather than on classification, so a strongly observed void of unclear purpose is not penalised and a weakly observed doorway is not flattered. Rejected candidates are kept with their reasons, so an empty opening list reads as "no candidate passed the gates" rather than "this room has no doors".

Adjacency is claimed only when occupancy cut along the whole wall line leaves substantial scanned floor on both sides, with probes agreeing. It is reported as measured near-side and far-side areas, not as named regions: components are re-derived per wall from a different cut each time, so a region *identity* would not be comparable between openings. Otherwise the far side stays `unknown`. This is not multi-room stitching, which remains unsupported.

On the supplied captures this is intentionally sparse: `single_room` publishes no opening because its three long walls are only 41–51% solid, `single_scan_floor_only` publishes one `window_like` at 0.77 m backed by 217 pass-through points, and `single_scan_with_ceiling` publishes none because no candidate had anything observable behind it. No capture claims adjacency, which is correct for three independent single-room scans.

## Drift correction and ablation

Recorded ARKit poses are not used as-is. The floor is one physical plane, so a keyframe whose own near-floor points sit systematically off the globally fitted floor is showing pose error rather than architecture. The `ablate` command measures that per-keyframe residual, smooths it along keyframe order, centres and clamps it, applies it as a rigid per-frame translation along the floor normal, then rebuilds the structure both ways and publishes the comparison:

```powershell
python -m cozmo_scan ablate `
  "sample\single_room.zip" `
  --output "runs\drift\single-room" `
  --profile fast
```

It writes `drift-ablation.json` and `drift-ablation.md` containing both arms, the correction magnitude, and the accept-or-roll-back decision. A correction is kept only when the floor residual improves by at least 5% *and* wall residual, supported wall count, and boundary support do not materially regress. The recorded-pose arm stays the control and remains bit-for-bit reproducible, and correction is disabled in `run` and `batch`.

Point count and inlier support are checked first and unconditionally, because a residual measured over a band-limited inlier subset falls when inliers simply leave the band. The acceptance metric is a trimmed residual over a fixed fraction of every point, which a change of voxel partition cannot game. The band RMSE is still reported for continuity but does not decide anything.

The audited ablation rejects on all three captures, each for a different and defensible reason:

| Capture | Decision | Band RMSE off → on | Trimmed residual off → on |
|---|---|---:|---:|
| `single_room.zip` | rolled back, trimmed residual −1.4% | 0.01581 → 0.01509 | 0.07932 → 0.08044 |
| `single_scan_floor_only.zip` | rolled back, lost 1.0% of points | 0.01576 → 0.01413 | 0.06994 → 0.07554 |
| `single_scan_with_ceiling.zip` | rolled back, trimmed residual +1.5% | 0.01432 → 0.01468 | 0.39240 → 0.38636 |

`single_room` and `single_scan_floor_only` both *improve* on the old band metric and get worse on the honest one, which is precisely why the metric was changed. An earlier version of this pipeline accepted the `single_scan_floor_only` correction and published a 4% larger footprint on that basis; the audit reproduced the error and D-071/D-073 record it.

Applied corrections were small: maximum 2.4–5.8 cm per frame, mean 0.5–0.8 cm, none clamped at the bound. The start-to-end closure proxy is deliberately excluded, because this correction does not move the recorded camera path and an unchanged proxy would invite a false reading. A footprint that moves between arms shows sensitivity to pose error; it does not show which arm is closer to the real room, and no ground truth was supplied to settle that.

## Run every supplied capture

The batch command discovers top-level ZIPs and valid capture directories, orders them deterministically, and reuses the unchanged final pipeline sequentially:

```powershell
python -m cozmo_scan batch `
  "sample" `
  --output "runs\all-samples" `
  --profile fast
```

The output root contains `batch.json`, `batch-report.md`, and one named directory per capture containing the same seven artifacts produced by `run`. One effective configuration is shared by every capture. Known output collisions are rejected before processing starts unless `--overwrite` is supplied; unrelated files are preserved. An expected failure in one capture is recorded and later captures still run. The command returns `0` only when every capture succeeds and `2` for a partial or fully failed batch.

The audited frozen-profile run completed all three supplied archives. The contour selector accepts the supported outline only for `single_room`; the other two candidates remain too complex and therefore use the convex safety fallback:

| Capture | Points | Outline | Area | Dimensions | Perimeter | Walls | Openings | Ceiling | Occupied support |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| `single_room.zip` | 70,928 | occupancy concave | 16.40 m² | 8.07 × 4.55 m | 31.51 m | 6 | 0 of 5 candidates | unavailable | 94.9% |
| `single_scan_floor_only.zip` | 171,537 | occupancy concave | 45.52 m² | 10.39 × 9.49 m | 73.10 m | 6 | 1 of 7 candidates | unavailable | 96.9% |
| `single_scan_with_ceiling.zip` | 242,402 | occupancy concave | 41.12 m² | 10.67 × 8.66 m | 61.15 m | 6 | 0 of 9 candidates | 2.40 m | 95.2% |

The last two rows changed in the fix loop, declared in [docs/fix-loop-declaration.md](docs/fix-loop-declaration.md) and reported in [docs/fix-loop-result.md](docs/fix-loop-result.md). They previously published 78.23 m² and 85.80 m² from a convex fallback at 57.4% and 48.5% support. Read the new areas as **measured extents of observed floor, not room areas**: their perimeters are 2.7 and 2.4 times the most compact outline enclosing the same area, which the result discloses in a warning, because both captures are partial sweeps of larger spaces rather than single rooms.

These are internal geometric estimates, not ground-truth accuracy claims. In particular, the floor-only capture remains honestly nullable rather than receiving an inferred ceiling, and a zero opening count means no candidate passed the evidence gates rather than a verified absence of doors and windows. No area on this table is validated, because no ground truth was supplied.

## Evaluate against independent ground truth

After a batch run, compare its published `result.json` files with real survey/tape/laser measurements:

```powershell
python -m cozmo_scan evaluate `
  "runs\demo" `
  --ground-truth "benchmark\ground-truth.local.json" `
  --output "runs\evaluation"
```

The command writes `evaluation.json`, `evaluation-report.md`, and `compliance-matrix.md`. It reports absolute/percentage error, the applicable evaluation gate, missing predictions, phantom openings, repeatability, and interval-calibration availability. Creating the report successfully returns exit code `0`; inspect the report's `passed`, `failed_gates`, or `incomplete` product status to determine the benchmark outcome.

No real ground-truth values were supplied with the three archives, so the repository does not invent them. The strict manifest format, a clearly fictional example, measurement rules, and exact encoded thresholds are documented in [benchmark/README.md](benchmark/README.md).

## Measurement intervals

Every published floor-plan measurement and the ceiling height carry a two-sided 95% **precision** interval, produced by resampling the observed points and re-running the same estimator. `result.json` carries them under `intervals`, and the report tabulates them.

They are labelled `precision` and never `accuracy`, and the distinction matters: a systematic error such as a wrong intrinsic scale would move every resample identically and would not widen the interval at all, so a tight interval is fully compatible with a large bias. Conformal prediction would turn this into a coverage guarantee but needs calibration ground truth that was not supplied.

| Capture | Floor area | Ceiling height |
|---|---|---|
| `single_room.zip` | 16.40, [15.52, 16.32] | no ceiling |
| `single_scan_floor_only.zip` | 45.52, [43.98, 45.50] | no ceiling |
| `single_scan_with_ceiling.zip` | 41.12, [38.73, 84.45] | 2.4012, [2.4011, 2.4025] |

The ceiling height is precise to under a millimetre, well inside the 1.5 cm evaluation gate, which is a statement about estimator stability and not about whether 2.40 m is correct. The wide area interval on the third capture is not noise: 8% of resamples selected the convex fallback instead of the concave contour, so the interval is bimodal across two estimators and the result says so in a warning. Opening widths have no interval yet and report that explicitly.

Intervals cost runtime: a three-capture batch goes from about 8 s to about 32 s at the default 64 resamples. The `test` profile uses 8.

## Evaluating against independent ground truth

The evaluator receives named-wall and opening predictions, so the opening gate can be scored when matching truth is supplied. Because opening identifiers are deterministic per capture and configuration rather than a cross-capture physical identity, a manifest must adopt the published identifiers before a width can match; an identifier the results do not predict is counted as a miss, and an identifier the truth does not contain is counted as a phantom. Interval coverage is computed wherever the manifest supplies a truth value for a measurement that carries an interval, and is reported descriptively because no coverage threshold is defined.

## Run tests

The test suite creates tiny temporary captures; it does not require the large source ZIPs:

```text
python -m unittest discover -s tests -v
```

The automated suite covers media ingestion, LiDAR validation, reconstruction, structural geometry, pipeline contracts, provenance, rendering, batch discovery, failure isolation, demo flow, determinism, staged-output safety, overwrite safety, benchmark contracts, gates, repeatability, and the CLI.

`tests/test_audit_regressions.py` covers adversarial regression cases. The opening and drift suites use synthetic scenes with known answers rather than only contract checks: a room with a measured door and window, the same room with solid walls, a sparsely sampled room, a void flush against the scanned wall extent, a void with unscanned floor in front of it, two rooms sharing a doorway, and the same two rooms with a solid shared wall. The drift tests verify that smoothing preserves a linear trend, that offsets oppose the residual and stay bounded, that every acceptance gate rejects for the right reason, and that a recorded-pose reconstruction is reproducible.

## Scope boundary

The three input tiers have explicit products: photo and video produce validated, versioned provenance manifests; LiDAR produces metric geometry and measured plans. Damage classification, concealed-condition prediction, automated repair scope, calibrated interval coverage, and multi-room stitching are outside the current scope. Published intervals are precision only, in the sense of the [Measurement intervals](#measurement-intervals) section, and opening width still carries none. Capability boundaries are represented explicitly instead of returning fabricated values.

Known limitations:

- No survey, tape, or laser ground truth was supplied, so absolute accuracy is not established for any measurement, opening width, or ablation arm.
- Wall and opening identifiers are stable per capture and configuration, not across captures, so repeated-capture wall matching is not available.
- Opening detection is conservative by design and misses openings on poorly covered walls; an undetected ceiling can also suppress detection, which is the safe direction.
- Drift correction addresses vertical drift relative to the floor plane. Horizontal drift and yaw error are untouched.
- Room adjacency requires two independently supported floor regions and is not multi-room stitching. The supplied captures are independent single rooms and claim no adjacency.
