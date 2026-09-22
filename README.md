# Cozmo Scan

Offline reconstruction and measured floor-plan generation for the supplied Stray Scanner/ARKit LiDAR captures.

The project is being built as a checkpoint-gated assessment. The detailed scope, audit findings, architecture, acceptance gates, risks, and append-only decision record are maintained in [THOUGHT.md](THOUGHT.md).

## Current status

CP01 (repository foundation) and CP02 (capture ingestion and validation) are complete. The CLI can now audit a supplied ZIP or extracted capture without unpacking the full archive. Reconstruction, floor-plan extraction, and final artifact generation are intentionally added in later approved checkpoints.

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

## Run tests

The test suite creates tiny temporary captures; it does not require the large assessment ZIPs:

```text
python -m unittest discover -s tests -v
```

Later checkpoints will add the `run` and `batch` commands only after their implementation and tests exist.

## Scope boundary

The deadline baseline targets the three supplied LiDAR captures. It does not claim validated photo-only reconstruction, damage classification, concealed-condition prediction, automated repair scope, or multi-room stitching. Unsupported capabilities will be represented explicitly in the final result contract instead of returning fabricated values.
