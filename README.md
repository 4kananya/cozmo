# Cozmo Scan

Offline reconstruction and measured floor-plan generation for the supplied Stray Scanner/ARKit LiDAR captures.

The project was built as a checkpoint-gated assessment. The detailed scope, audit findings, architecture, acceptance gates, risks, and append-only decision record are maintained in [THOUGHT.md](THOUGHT.md).

## Current status

The seven baseline delivery checkpoints are complete. CP08 adds a ground-truth benchmark and compliance evaluator. CP09 adds a component-aware concave floor outline with strict topology/support gates and the prior convex method retained as a safety fallback. The CLI can validate, reconstruct, measure, produce a reviewer-ready single-capture result, run the same configuration across a directory, and score published results when independent measurements are provided.

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
```

`models.py` contains the immutable versioned contracts, while `cli.py` contains only command parsing and user-facing orchestration. Numerical logic is not duplicated in the CLI, batch runner, or demo script.

## Requirements

- Python 3.12 or newer
- The supplied sample archives, kept outside Git history
- A Windows, Linux, or macOS environment capable of installing the dependencies declared in `pyproject.toml`

No GPU, cloud account, API key, database, or web server is required.

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

Place the three assessment archives in the ignored `sample/` directory:

```text
sample/
  single_room.zip
  single_scan_floor_only.zip
  single_scan_with_ceiling.zip
```

The samples are deliberately not committed. Two exceed GitHub's normal 100 MiB per-file limit, and the assessor already supplies the data separately.

Local sample fingerprints recorded before repository cleanup:

| File | SHA-256 |
|---|---|
| `single_room.zip` | `0805f742d378e4bda480fef6e5839304364807bb7b77bb459983003727e9699c` |
| `single_scan_floor_only.zip` | `f822287268297d2adab49deff8e0ee5f50f05304b450d8d47d0b5eb476aa74d4` |
| `single_scan_with_ceiling.zip` | `4bfbeb11ee21b114c46ad43cf0c9602d8ada827397f4e8b3c70dd827d0191379` |

These hashes identify the locally audited inputs; they are not download credentials or proof of ground truth.

## Reviewer demonstration

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

CP03 uses NumPy, Pillow, and the recorded depth/pose data directly. It does not require Open3D, SciPy, Matplotlib, RGB decoding, a GPU, or network access.

## Measure structural geometry

Run reconstruction plus CP04 structural analysis:

```powershell
python -m cozmo_scan measure `
  "sample\single_room.zip" `
  --output "runs\single-room-measured" `
  --profile fast
```

The measurement directory contains the three reconstruction artifacts above plus:

- `structure.json`: normalized floor/ceiling/wall planes, fit support and residuals, floor-local coordinates, polygon vertices, edge lengths, area, perimeter, principal dimensions, effective thresholds, and warnings;
- `floorplan.svg`: scalable measured floor-plan drawing;
- `floorplan.png`: reviewer-friendly preview with edge dimensions, scale bar, wall-direction markers, and quality evidence.

The structural stage finds the floor relative to the recorded camera trajectory, fits horizontal planes with fixed-seed RANSAC, detects vertical walls with X-Z line RANSAC, and projects floor evidence into a local metric frame. CP09 quantizes that evidence to an occupancy grid, closes only one-cell gaps, finds deterministic connected components, traces the largest outer contour, simplifies it, and verifies that it remains a simple polygon.

The occupancy contour is accepted only when it retains at least 80% of occupied cells, has at least 55% direct occupied support, improves support over the occupancy convex hull by at least 8 percentage points, has no more than 36 simplified vertices, and does not inflate perimeter beyond 1.5 times the convex perimeter. Weak, fragmented, self-intersecting, unsupported, or overly complex contours use the previous convex hull and record the exact fallback reason. The legacy JSON field `convex_fill_ratio` is retained for compatibility; `boundary_support_ratio` is its clearer serialized alias for either outline method.

The audited `single_room.zip` fast run still finds the same floor, wall planes, and missing-ceiling outcome. Its CP09 contour retains 95.7% of occupied cells, has 94.9% direct support, and measures approximately 8.07 x 4.55 m, 16.40 m², with 27 simplified vertices. This is substantially better supported than the old 34.73 m² convex hull, but it is still an internal occupancy estimate—not proof of absolute accuracy without independent room measurements.

## Generate the complete result bundle

The primary single-capture product command is:

```powershell
python -m cozmo_scan run `
  "sample\single_room.zip" `
  --output "runs\single-room-final" `
  --profile fast
```

It writes exactly seven reviewer-facing artifacts:

- `result.json`: versioned result contract containing input SHA-256, inventory, effective parameters, reconstruction statistics, structural measurements, quality evidence, runtime versions, warnings, assignment capability statuses, and artifact manifest;
- `reconstruction.ply`: metric XYZ point cloud;
- `topdown.png`: point-density and camera-path overview;
- `trajectory.png`: dedicated path rendering whose start-to-end distance is explicitly labelled as a closure proxy, not certified drift;
- `floorplan.svg` and `floorplan.png`: vector and raster measured-plan views;
- `report.md`: self-contained human-readable result, evidence, method, limitations, artifact guide, and assignment coverage.

The final output is staged before publication. Existing known artifacts require `--overwrite`, and unrelated files in the destination are preserved. ZIP provenance is the SHA-256 of the exact archive bytes. Directory provenance uses a deterministic hash over sorted normalized member names and contents. Local absolute paths are not stored in the final result.

The final schema explicitly marks unsupported features such as photo-only reconstruction, damage detection, concealed-condition prediction, repair-scope generation, and live mobile processing as `not_implemented`; ground-truth accuracy and multi-room stitching are `not_evaluated`. Missing measurements remain `null`.

CP09 publishes result/structure/batch schema `1.1.0`, adding outline method, component retention, discarded-cell count, fallback reason, and `boundary_support_ratio`. Readers remain backward-compatible with the CP07/CP08 `1.0.0` artifacts.

## Run every supplied capture

The batch command discovers top-level ZIPs and valid capture directories, orders them deterministically, and reuses the unchanged final pipeline sequentially:

```powershell
python -m cozmo_scan batch `
  "sample" `
  --output "runs\all-samples" `
  --profile fast
```

The output root contains `batch.json`, `batch-report.md`, and one named directory per capture containing the same seven artifacts produced by `run`. One effective configuration is shared by every capture. Known output collisions are rejected before processing starts unless `--overwrite` is supplied; unrelated files are preserved. An expected failure in one capture is recorded and later captures still run. The command returns `0` only when every capture succeeds and `2` for a partial or fully failed batch.

The audited frozen-profile run completed all three supplied archives. CP09 accepts the supported contour only for `single_room`; the other two candidates remain too complex and therefore use the unchanged convex safety fallback:

| Capture | Points | Outline | Area | Dimensions | Walls | Ceiling | Occupied support |
|---|---:|---|---:|---:|---:|---:|---:|
| `single_room.zip` | 70,928 | occupancy concave | 16.40 m² | 8.07 × 4.55 m | 6 | unavailable | 94.9% |
| `single_scan_floor_only.zip` | 171,537 | convex fallback | 78.23 m² provisional | 10.88 × 9.44 m | 6 | unavailable | 57.4% |
| `single_scan_with_ceiling.zip` | 242,402 | convex fallback | 85.80 m² provisional | 12.40 × 9.28 m | 6 | 2.40 m | 48.5% |

These are internal geometric estimates, not ground-truth accuracy claims. In particular, the floor-only capture remains honestly nullable rather than receiving an inferred ceiling.

## Evaluate against independent ground truth

After a batch run, compare its published `result.json` files with real survey/tape/laser measurements:

```powershell
python -m cozmo_scan evaluate `
  "runs\demo" `
  --ground-truth "benchmark\ground-truth.local.json" `
  --output "runs\evaluation"
```

The command writes `evaluation.json`, `evaluation-report.md`, and `compliance-matrix.md`. It reports absolute/percentage error, the applicable assignment gate, missing predictions, phantom openings, repeatability, and interval-calibration availability. Creating the report successfully returns exit code `0`; inspect the report's `passed`, `failed_gates`, or `incomplete` product status to determine the benchmark outcome.

No real ground-truth values were supplied with the three archives, so the repository does not invent them. The strict manifest format, a clearly fictional example, measurement rules, and exact encoded thresholds are documented in [benchmark/README.md](benchmark/README.md). Current named-wall/opening and numerical-interval checks remain honestly missing or not evaluated until those predictions and real reference data exist.

## Run tests

The test suite creates tiny temporary captures; it does not require the large assessment ZIPs:

```text
python -m unittest discover -s tests -v
```

The suite includes validation, reconstruction, structural-geometry, pipeline-contract, provenance, rendering, batch-discovery, failure-isolation, demo-flow, determinism, staged-output-safety, overwrite-safety, benchmark-contract, gate, repeatability, and CLI tests.

## Scope boundary

The deadline baseline targets the three supplied LiDAR captures. It does not claim validated photo-only reconstruction, damage classification, concealed-condition prediction, automated repair scope, or multi-room stitching. Unsupported capabilities will be represented explicitly in the final result contract instead of returning fabricated values.
