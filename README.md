# Cozmo Scan

Offline reconstruction and measured floor-plan generation for the supplied Stray Scanner/ARKit LiDAR captures.

The project is being built as a checkpoint-gated assessment. The detailed scope, audit findings, architecture, acceptance gates, risks, and append-only decision record are maintained in [THOUGHT.md](THOUGHT.md).

## Current status

CP01 (repository foundation), CP02 (capture validation), CP03 (metric point-cloud reconstruction), and CP04 (structural planes and measured convex floor plan) are complete. The CLI can validate, reconstruct, and measure a supplied ZIP or extracted capture without unpacking the full archive. The final versioned product bundle and all-sample batch runner are intentionally added in later approved checkpoints.

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

CP04 finds the floor relative to the recorded camera trajectory, fits horizontal planes with fixed-seed RANSAC, detects vertical walls with X-Z line RANSAC, projects floor evidence into a local metric frame, filters isolated occupancy cells, and measures a simplified convex hull. A ceiling is returned only when its support, span, orientation, and height are credible; otherwise both the ceiling plane and height remain `null`.

The floor polygon is deliberately a convex baseline. `convex_fill_ratio` reports how much of its area is backed by occupied floor cells. When that ratio is below the configured threshold, the CLI and drawing label area as provisional and warn that the hull may bridge concave or unscanned regions. These values are internal geometric estimates, not accuracy claims against ground truth.

The audited `single_room.zip` fast run found a near-horizontal floor with 14,640 inliers, 20.6% cloud support, and 1.6 cm fit RMSE. It found six supported vertical planes and no credible ceiling. Its convex outline is approximately 7.44 x 6.59 m and 34.73 m², but occupied support is only 46.8%; the area is therefore explicitly reported as provisional rather than as a certified room measurement.

## Run tests

The test suite creates tiny temporary captures; it does not require the large assessment ZIPs:

```text
python -m unittest discover -s tests -v
```

The suite currently contains 50 validation, reconstruction, structural-geometry, rendering, determinism, output-safety, and CLI tests. Later checkpoints will add the final `run` and `batch` commands only after their implementation and tests exist.

## Scope boundary

The deadline baseline targets the three supplied LiDAR captures. It does not claim validated photo-only reconstruction, damage classification, concealed-condition prediction, automated repair scope, or multi-room stitching. Unsupported capabilities will be represented explicitly in the final result contract instead of returning fabricated values.
