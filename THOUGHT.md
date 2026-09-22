# Cozmo AI Assessment: Working Plan and Decision Record

> This is the project's living engineering plan. The checklist may be updated as work progresses. The decision log at the end is **append-only**: never delete or rewrite an old decision; add a new entry that supersedes it.

## Project status

- Audit date: 2026-09-22
- Submission deadline: 2026-09-23, 8:00 PM IST
- Repository state at audit: one commit containing the assignment document and three sample ZIP files; no implementation, tests, README, dependency file, or `.gitignore`
- Product constraint agreed with the candidate: build and test against the supplied sample data only
- Delivery strategy: finish one honest, reproducible vertical slice before adding any optional feature

## Executive decision

The baseline will be a **local Python command-line product for Stray Scanner/ARKit LiDAR captures**. Given one of the supplied ZIP files, it will validate the capture, reconstruct a downsampled 3D point cloud from depth plus camera poses, estimate the main structural surfaces, derive a measured 2D room outline, and write a consistent artifact bundle containing JSON, PLY, SVG/PNG, and a human-readable report.

This is a complete baseline for the supplied data, not a false claim that every item in the broad assignment has been solved. The assignment also asks for photo/video-only reconstruction, multi-room stitching, damage detection, concealed-condition flags, repair scope, a self-built benchmark, competitor comparison, and live walk-in processing. The supplied files are three independent LiDAR scans without ground-truth measurements or damage annotations. Implementing all of those features credibly before the deadline is not feasible. Unsupported capabilities will be present in the result contract with an explicit `not_evaluated` status and explanation; they will not return invented results.

## What “complete” means for this submission

The baseline is complete only when a reviewer can clone the code, supply the sample ZIPs outside Git, run one documented command, and receive usable outputs for all three scans without editing source code.

The minimum product must:

- accept a capture ZIP or a directory containing the unpacked capture;
- discover the hash-named capture root rather than hard-code it;
- validate the depth, confidence, odometry, calibration, and optional RGB/IMU assets;
- reconstruct geometry in metric units from selected depth frames and ARKit poses;
- filter invalid depth and low-confidence pixels;
- estimate a floor and, when supported by the data, ceiling and wall planes;
- generate a 2D room polygon and basic measurements in metres;
- attach quality metrics, warnings, parameter values, and provenance to every result;
- render the reconstruction and floor plan into reviewer-friendly files;
- run in a bounded `fast` profile on each supplied ZIP;
- run through a batch command on all three samples;
- fail with a clear message and non-zero exit code for malformed input;
- include unit tests, one short integration test, setup instructions, architecture notes, limitations, and the exact commands used for the reported results.

It must not:

- label random image features as damage;
- turn a missing measurement into zero;
- present first-to-last camera distance as certified drift;
- claim accuracy against ground truth that does not exist;
- hide an algorithm failure behind a plausible-looking drawing;
- require a GPU, cloud service, API key, database, web server, or mobile application.

## Current data facts

The three local inputs are:

| File | Approximate size | Depth/confidence frames | Capture duration | IMU rows |
|---|---:|---:|---:|---:|
| `single_room.zip` | 88.5 MB | 1,715 | 37.17 s | 3,689 |
| `single_scan_floor_only.zip` | 276.8 MB | 5,251 | 114.78 s | 11,397 |
| `single_scan_with_ceiling.zip` | 508.5 MB | 9,745 | 214.93 s | 21,339 |

Observed capture layout:

```text
<capture-id>/
  camera_matrix.csv
  odometry.csv
  imu.csv
  rgb.mp4
  depth/000000.png ...
  confidence/000000.png ...
```

Relevant observed details:

- depth images are `256 x 192` unsigned 16-bit PNGs and represent millimetres;
- confidence images are `256 x 192` unsigned 8-bit PNGs with values `0`, `1`, and `2`, where larger is better;
- RGB video is `1920 x 1440` HEVC;
- odometry includes frame ID, translation, quaternion, and per-frame intrinsics;
- empty distortion-centre fields are valid and must parse as missing values;
- filenames are zero-padded frame IDs, which allows deterministic depth/confidence/pose pairing;
- the calibration principal point is near the centre of the 1920 x 1440 image, so intrinsics must be scaled to the 256 x 192 depth resolution before back-projection.

## Six hard audits

### Audit 1 — Scope truthfulness

**Finding:** The earlier product outline correctly identified the assignment's full surface area, but it was still too broad for the remaining time. Treating every requested feature as a baseline requirement would create many shallow, untested components and almost no trustworthy result.

**Harsh conclusion:** Deliver one geometric vertical slice. Do not build photo-only inference, video-only structure-from-motion, multi-room stitching, a learned damage model, concealed-condition prediction, automated repair scope, model training, or an interactive dashboard.

**Assignment coverage after reduction:**

| Assignment capability | Baseline status | Honest treatment |
|---|---|---|
| LiDAR capture ingestion | Included | All three supplied archives |
| Per-room reconstruction | Included | One independent room result per archive |
| Measured room plan | Included | Floor polygon, dimensions, area, perimeter, optional height |
| Rendered output | Included | PLY plus SVG/PNG |
| Machine-readable output | Included | Versioned JSON schema |
| Confidence/quality | Included | Coverage, plane fit, point counts, warnings, provenance |
| Multiple rooms stitched together | Not demonstrated | Samples are independent scans; report `not_evaluated` |
| Photo-only reconstruction | Not implemented | No supplied photo-only benchmark |
| Video-only reconstruction | Not implemented | RGB exists, but depth/pose is the reliable sample path |
| Damage detection | Not implemented | No damage labels or ground truth |
| Concealed-condition flags | Not implemented | Cannot be inferred reliably from these inputs |
| Automated repair scope | Not implemented | Depends on trustworthy damage classification |
| Absolute accuracy against truth | Not claimed | No reference measurements are supplied |
| Competitor accuracy comparison | Documentation only | No identical-input ground truth or licensed benchmark run |
| Live mobile walk-in | Not implemented | Offline, bounded sample-data pipeline only |

**Pass condition:** The README and generated report state this coverage table plainly. There are no implied claims beyond what was tested.

### Audit 2 — Repository and data hygiene

**Finding:** The repository currently tracks three ZIPs totalling roughly 874 MB, producing about 817 MiB of loose Git objects. Two individual files are larger than GitHub's enforced 100 MiB ordinary-Git object limit. There is no `.gitignore`, and the local `main` branch has no configured upstream.

**Harsh conclusion:** In its current form, the repository is not ready to push as a normal GitHub repository. Adding `.gitignore` now is insufficient because the ZIPs already exist in commit history.

**Required action before normal development commits:**

- confirm whether commit `b71f2fe` has been pushed anywhere;
- preserve the local ZIP files outside destructive history operations;
- with explicit approval, remove sample archives from Git history or migrate them to Git LFS;
- prefer an ignored `sample/` directory plus a documented download/copy step because the assessor already provided the data;
- add `.gitignore` entries for sample archives, extracted captures, generated runs, caches, virtual environments, and editor files;
- never commit generated point clouds, rendered runs, temporary extraction folders, or virtual environments;
- keep a tiny synthetic fixture in Git for tests.

GitHub documents that normal Git objects larger than 100 MiB are blocked and recommends Git LFS or external storage for large binaries: <https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github>.

**Pass condition:** a fresh clone is small; no tracked object exceeds GitHub's limit; sample data can be placed locally using README instructions; tests do not depend on the large archives.

### Audit 3 — Architecture and coding discipline

**Finding:** A service layer, API, UI, database, task queue, plugin system, many abstract interfaces, or one class per processing step would add ceremony without improving this assessment. At the other extreme, a single notebook or 1,000-line script would be hard to test and review.

**Harsh conclusion:** Use one installable Python package with a thin CLI and a small number of modules separated by real responsibilities. No framework.

Target structure:

```text
.
├── pyproject.toml
├── README.md
├── THOUGHT.md
├── src/
│   └── cozmo_scan/
│       ├── __init__.py
│       ├── cli.py              # argparse and exit codes only
│       ├── dataset.py          # archive discovery, validation, CSV/PNG loading
│       ├── reconstruction.py   # back-projection, transforms, filtering, fusion
│       ├── floorplan.py        # planes, 2D boundary, measurements, quality
│       ├── models.py           # Pydantic input/result models and schema version
│       ├── outputs.py          # JSON, PLY, SVG/PNG, Markdown report
│       └── pipeline.py         # orchestration; no geometry implementation
├── tests/
│   ├── fixtures/               # tiny generated or redistributable test capture
│   ├── test_dataset.py
│   ├── test_reconstruction.py
│   ├── test_floorplan.py
│   └── test_smoke.py
└── sample/                     # ignored local input, never imported by the package
```

Coding rules:

- prefer pure functions for numerical transformations;
- use dataclasses/Pydantic only where an object owns validated data or a public contract;
- do not create `utils.py`, generic repositories, factories, adapters, or interfaces without two real implementations;
- use `pathlib.Path`, type hints, docstrings for public functions, and named constants for units and thresholds;
- carry units in field names or models; internal geometry is metres;
- keep I/O at module boundaries and keep numerical kernels independently testable;
- inject processing parameters through one immutable configuration model;
- use structured exceptions at the package boundary and concise user-facing errors in the CLI;
- use the same pipeline for tests, single runs, and batch runs; profiles change parameters, not code paths;
- make output deterministic for the same input, configuration, and package version;
- record the effective configuration in `result.json`;
- add a dependency only when standard library plus existing dependencies cannot do the job simply;
- optimize after profiling; initially bound work with frame and pixel sampling.

**Pass condition:** every module has one obvious reason to change, the CLI contains no geometry logic, and the full baseline can be understood without tracing a framework.

### Audit 4 — Algorithm and data feasibility

**Finding:** The depth, confidence, pose, and intrinsics are sufficient for an offline metric reconstruction. They are not sufficient to validate damage categories or absolute measurement accuracy. Processing every pixel in every frame would create hundreds of millions of points and waste deadline time.

**Harsh conclusion:** Use the recorded ARKit pose as the baseline, deterministic keyframe sampling, confidence/range filtering, voxel downsampling, and simple robust geometry. Do not start with pose-graph optimization or neural networks.

Baseline algorithm:

1. Open the ZIP safely in a temporary directory and reject path traversal.
2. Discover the single capture root and inventory required/optional files.
3. Parse odometry by header name, treating blank optional fields as `None`.
4. Match depth and confidence frames to odometry by zero-padded frame ID.
5. Select deterministic keyframes using a stride and maximum frame count.
6. Read each depth/confidence pair; keep confidence `>= 1` and depth within a configurable metric range.
7. Scale `fx`, `fy`, `cx`, and `cy` from the 1920 x 1440 calibration domain to 256 x 192 depth pixels.
8. Back-project retained pixels into camera coordinates.
9. Convert the recorded quaternion and translation to a camera-to-world transform using the official format convention; verify the convention with trajectory and gravity/plane sanity checks.
10. Transform points into world coordinates and incrementally voxel-downsample to cap memory.
11. Remove statistical outliers only if the measured benefit justifies the runtime.
12. Fit dominant planes with RANSAC. Classify near-horizontal planes as floor/ceiling and near-vertical planes as walls, using ARKit's world-up direction.
13. Flatten the accepted floor into a stable local 2D coordinate system.
14. Build the first room outline from trimmed floor/near-floor projected points using a convex hull. Simplify short/near-collinear edges and optionally snap nearly orthogonal edges only when the fit improves.
15. Calculate edge lengths, perimeter, area, principal dimensions, and ceiling height when a credible ceiling plane exists.
16. Calculate quality evidence: matched/missing frames, valid-depth ratio, retained points, plane inlier ratio, plane residuals, boundary support, trajectory length, and first-to-last pose distance labelled only as a closure proxy.
17. Serialize and render results. Every fallback adds a warning to the JSON and report.

Why the initial polygon is a convex hull: it is deterministic, available in SciPy, and likely adequate for these simple single-room samples. It will overfill concave rooms, so the limitation must be reported. A grid/concave outline is a later improvement only after the full baseline passes all samples.

Processing profiles:

| Profile | Purpose | Initial bound |
|---|---|---|
| `test` | CI and local smoke test | tiny fixture or at most 10 real frames |
| `fast` | required sample-data deliverable | at most 200 keyframes, coarser pixel stride/voxel |
| `quality` | optional better artifact | at most 500 keyframes, finer sampling |

The exact stride, depth range, voxel size, RANSAC threshold, and minimum support are configuration values, not scattered literals. Tune them on `single_room.zip`, freeze them, then run the other two without per-file secret tweaks. If a dataset needs an exception, expose and report that override.

**Pass condition:** `single_room.zip` produces recognizable geometry and a plausible metric room outline under the `fast` profile without exhausting memory; the exact same path completes on the other two archives.

### Audit 5 — Dependencies and reproducibility

**Finding:** The earlier dependency list included OpenCV, Shapely, Jinja2, FFmpeg, and possible research-model stacks. Each adds installation surface, duplicate capability, or a second pipeline. RGB decoding is unnecessary for the geometric baseline.

**Harsh conclusion:** Keep the runtime dependency set small:

- Python 3.12;
- NumPy for arrays and vectorized projection;
- SciPy for rotations, spatial hulls, and numerical helpers;
- Open3D for point-cloud downsampling, plane fitting, and PLY output;
- Pillow for 16-bit depth and confidence PNGs;
- Pydantic for the versioned result/config contract;
- Matplotlib for deterministic SVG/PNG plots;
- pytest as the only required development dependency.

Do not add OpenCV, Shapely, scikit-image, pandas, Jinja2, PyTorch, CUDA, web frameworks, or database packages to P0. Do not make FFmpeg a requirement while RGB is unused. HTML output is not necessary; SVG/PNG plus Markdown is enough.

Reproducibility rules:

- declare dependencies and supported Python version in `pyproject.toml`;
- pin the environment in a lock file if the chosen installer can do so quickly;
- expose package version, Python version, dependency versions, input SHA-256, and effective configuration in the report;
- seed randomized plane segmentation where the library permits it, otherwise document the remaining nondeterminism;
- write outputs into a new explicit run directory; never mutate the input;
- use atomic writes for JSON/report files where practical;
- supply copy-paste commands for Windows PowerShell and a platform-neutral Python command;
- make reruns safe by requiring `--overwrite` before replacing an existing output directory.

**Pass condition:** setup succeeds in a clean environment and the same command yields equivalent measurements and the same schema on a second run.

### Audit 6 — Testing, evaluation, and deadline risk

**Finding:** There is no supplied ground-truth geometry, so a visually attractive floor plan is not proof of accuracy. Full-resolution processing can consume the remaining time without improving the deliverable. The major risks are transform convention, intrinsic scaling, memory usage, unstable plane selection, and oversized Git history.

**Harsh conclusion:** Test mathematical invariants and pipeline contracts, publish internal quality evidence, and keep a large deadline buffer. Do not invent percentage accuracy.

Required tests:

- ZIP traversal protection and capture-root discovery;
- CSV parsing with the observed 15-column header and blank fields;
- deterministic frame matching and keyframe selection;
- millimetre-to-metre conversion;
- intrinsic scaling from 1920 x 1440 to 256 x 192;
- back-projection of known synthetic pixels;
- quaternion normalization and transform direction on a synthetic pose;
- plane classification for synthetic floor, ceiling, and wall points;
- polygon area/perimeter on a known rectangle;
- JSON schema validation and round-trip serialization;
- clear failure for missing/corrupt required files;
- a tiny end-to-end synthetic capture;
- a bounded real-data smoke run on `single_room.zip` when sample data is present.

Evaluation evidence for each supplied scan:

- input/frame inventory;
- number and percentage of frames matched;
- valid depth and confidence percentages;
- sampled frame count;
- raw and final point counts;
- reconstruction bounds in metres;
- fitted-plane coefficients, support, and residual;
- room polygon vertices and measurements;
- warnings/fallbacks;
- wall-clock time and peak memory if easy to collect;
- rendered trajectory, top-down point projection, and floor plan;
- manual visual QA notes, clearly labelled as manual rather than ground truth.

**Pass condition:** unit tests pass, the integration test is bounded, all three sample runs finish, and the report distinguishes measured facts, proxies, assumptions, and unsupported claims.

## Product data flow

```text
ZIP or capture directory
        |
        v
safe discovery + validation
        |
        v
frame index (depth + confidence + pose + intrinsics)
        |
        v
deterministic keyframe sampler
        |
        v
metric back-projection + camera-to-world transform
        |
        v
filtered/downsampled world point cloud -----------------> reconstruction.ply
        |
        v
dominant planes + local floor coordinates
        |
        v
room boundary + measurements + quality evidence
        |
        +-----------------> result.json
        +-----------------> floorplan.svg / floorplan.png
        +-----------------> trajectory.png / topdown.png
        +-----------------> report.md
```

## Public command surface

Keep the CLI deliberately small:

```powershell
# Validate without reconstructing
python -m cozmo_scan validate "sample\single_room.zip"

# Produce one required baseline run
python -m cozmo_scan run "sample\single_room.zip" --output "runs\single_room" --profile fast

# Process every ZIP using the same profile and write a summary
python -m cozmo_scan batch "sample" --output "runs" --profile fast
```

Only add flags that correspond to real configuration fields. Avoid dozens of experimental switches. A `--config` JSON file may be added only if the command becomes unwieldy.

## Output contract

Each run directory should contain:

```text
result.json             # authoritative versioned machine-readable result
reconstruction.ply      # filtered, downsampled metric point cloud
floorplan.svg           # vector plan with scale and dimensions
floorplan.png           # convenient preview
topdown.png             # evidence behind the derived boundary
trajectory.png          # camera path and start/end markers
report.md               # assumptions, metrics, warnings, artifact links
```

Minimum `result.json` shape:

```json
{
  "schema_version": "1.0.0",
  "status": "ok_with_warnings",
  "units": "metre",
  "input": {
    "source_name": "single_room.zip",
    "sha256": "...",
    "capture_format": "stray_scanner"
  },
  "processing": {
    "profile": "fast",
    "parameters": {},
    "versions": {},
    "elapsed_seconds": 0.0
  },
  "reconstruction": {
    "matched_frames": 0,
    "sampled_frames": 0,
    "point_count": 0,
    "bounds_m": {}
  },
  "room": {
    "polygon_xy_m": [],
    "area_m2": null,
    "perimeter_m": null,
    "principal_dimensions_m": null,
    "ceiling_height_m": null
  },
  "planes": [],
  "quality": {
    "valid_depth_ratio": null,
    "floor_inlier_ratio": null,
    "floor_rmse_m": null,
    "boundary_support": null,
    "closure_proxy_m": null
  },
  "capabilities": {
    "damage_detection": {"status": "not_evaluated", "reason": "No labelled damage data"},
    "concealed_conditions": {"status": "not_evaluated", "reason": "Not observable from the supplied samples"},
    "repair_scope": {"status": "not_evaluated", "reason": "Depends on validated damage findings"},
    "multi_room_stitching": {"status": "not_evaluated", "reason": "Inputs are independent scans"}
  },
  "warnings": [],
  "artifacts": {}
}
```

`null` means “not available.” It must never be silently replaced with `0`. A run can return `ok`, `ok_with_warnings`, or `failed`; the CLI exit code must agree with the result.

## Implementation checkpoints and stop conditions

Time estimates are focused engineering hours, not promises. Finish a checkpoint and commit it before entering the next one.

No checkpoint may be implemented merely because the preceding checkpoint passed. Before each checkpoint, present its exact proposed files, functions, dependencies, risks, tests, and acceptance gate for audit; begin work only after the user explicitly approves that checkpoint. After implementation, report the evidence and wait for approval before continuing.

### Checkpoint overview table

| Checkpoint | What it is about | Main functions or components to build | Concrete deliverable | Completion gate | Current status |
|---|---|---|---|---|---|
| **CP01 — Repository foundation** | Make the repository safe to push, install, and test before algorithm work begins. | `.gitignore`; `pyproject.toml`; minimal package entry point; `build_parser()`; `main()`; package version; initial CLI test. Preserve local samples, then remove/migrate the already-committed large objects only with explicit approval. | Small installable Python package; working `python -m cozmo_scan --help`; ignored local samples and generated outputs; safe Git state. | Samples still exist locally; no oversized ZIP remains in ordinary Git history; package imports; CLI help and initial tests pass. | **Complete — audited 2026-09-22** |
| **CP02 — Capture ingestion and validation** | Understand and validate the supplied Stray Scanner format before using its geometry. | `open_capture()`; `discover_capture_root()`; `inventory_capture()`; `read_camera_matrix()`; `read_odometry()`; `match_frames()`; `select_keyframes()`; `validate_capture()`; `validate` CLI command. | Structured validation result for ZIP/directory inputs, frame inventory, errors/warnings, and tiny synthetic fixture/tests. | All three samples report the known inventory; frame matching is deterministic; blank CSV fields parse correctly; unsafe/malformed inputs fail clearly. | **Complete — audited 2026-09-22** |
| **CP03 — Metric 3D reconstruction** | Convert selected depth/confidence frames and recorded ARKit poses into a bounded metric point cloud. | `scale_intrinsics()`; `depth_to_metres()`; `filter_depth()`; `backproject_depth()`; `quaternion_to_rotation()`; `camera_to_world_matrix()`; `transform_points()`; `reconstruct_keyframe()`; `fuse_keyframes()`; `downsample_cloud()`; `reconstruct_capture()`. | Coherent downsampled PLY/top-down preview from `single_room.zip`, with reconstruction statistics and numerical tests. | Synthetic projection/transform tests pass; a 50-frame real run has plausible scale and coherent floor/walls; the `fast` path stays within bounded memory. | **Not started — approval required** |
| **CP04 — Structural planes and floor plan** | Turn the reconstruction into an understandable measured room result. | `fit_dominant_planes()`; `classify_plane()`; `select_floor_plane()`; `select_ceiling_plane()`; `select_wall_planes()`; `create_floor_coordinate_system()`; `project_points_to_floor()`; `trim_boundary_outliers()`; `build_convex_outline()`; `simplify_polygon()`; `measure_polygon()`; plane/boundary quality functions. | Floor polygon, edge lengths, area, perimeter, principal dimensions, optional ceiling height, plane metrics, and warnings. | Synthetic plane/rectangle tests pass; `single_room` produces a plausible outline; unsupported height is `null`; no coordinates or geometry are hard-coded per sample. | **Not started — approval required** |
| **CP05 — Complete artifact bundle** | Turn the algorithms into one reviewable command-line product with stable outputs. | `PipelineConfig`; `RunResult`; `RoomResult`; `QualityMetrics`; `CapabilityStatus`; `ArtifactManifest`; `run_pipeline()`; `write_result_json()`; `write_point_cloud()`; `render_floorplan()`; `render_topdown()`; `render_trajectory()`; `write_report()`; `run` CLI command. | `result.json`, `reconstruction.ply`, `floorplan.svg`, `floorplan.png`, `topdown.png`, `trajectory.png`, and `report.md` from one command. | JSON validates against the versioned contract; units/provenance/parameters/warnings are present; overwrite protection and exit codes work; artifacts are understandable without reading source. | **Not started — approval required** |
| **CP06 — All-sample batch validation** | Prove the same pipeline and frozen profile work across all three supplied captures. | `discover_captures()`; `run_batch()`; `summarize_runs()`; `write_batch_summary()`; `batch` CLI command; regression fixes that remain general. | Per-scan artifact bundles plus combined JSON/Markdown summary of runtime, geometry, measurements, quality, warnings, and failures. | All three runs finish without source changes; parameters are shared or overrides are disclosed; floor-only data handles missing ceiling correctly; full tests pass. | **Not started — approval required** |
| **CP07 — Submission and demonstration** | Make the project reproducible, explainable, and ready for assessor review. | Final README; setup/run commands; architecture and method documentation; schema/limitations; assignment coverage; demo script; clean-environment verification; dependency, secret, path, and Git audit. No new algorithm. | Submission-ready repository with reproducibility evidence and a short repeatable demonstration flow. | Clean install, tests, and sample commands succeed; tracked files are appropriate; claims match evidence; outputs are inspectable; delivery buffer remains. | **Not started — approval required** |

The table is the high-level control board. The sections below are the authoritative detailed checklist and stop conditions for each checkpoint. Status values should be changed only after recording the corresponding implementation evidence; they do not replace the append-only decision log.

### CP01 — Repair repository hygiene (30–60 minutes)

- [x] Confirm whether the initial large-file commit exists on the remote.
- [x] Preserve all three local sample archives.
- [x] With explicit approval, remove ordinary-Git copies from history or choose Git LFS.
- [x] Add `.gitignore` for samples, runs, extracted files, caches, environments, and IDE files.
- [x] Add the package/test skeleton and `pyproject.toml`.
- [x] Verify `git status` shows only intended source files.

**Stop condition:** do not try a normal GitHub push while the 276.8 MB and 508.5 MB ZIP objects remain in ordinary Git history.

**Completion evidence (2026-09-22):** the configured remote returned no branch heads; the unpublished root commit was amended to `021253a`; all three ZIPs remain present locally and match the SHA-256 values recorded in `README.md`; `sample/` is ignored and absent from the reachable Git tree; the package imports; `python -m cozmo_scan --help` and `--version` work; all three foundation tests pass; and the working tree was clean immediately after the amended commit.

### CP02 — Data contract and validator (1–2 hours)

- [x] Discover the hash-named root in ZIP and directory modes.
- [x] Parse calibration and observed odometry rows, including blanks.
- [x] Pair depth/confidence/pose by frame ID.
- [x] Produce a validation summary for all three ZIPs without extracting everything.
- [x] Add parser and malformed-input tests.

**Gate:** frame counts and required files match the known inventory. If they do not, fix ingestion before writing geometry.

**Completion evidence (2026-09-22):** 21 unit/CLI tests pass. ZIP and directory inputs use the same read-only code path; unsafe/ambiguous paths are rejected; CSV fields are addressed by header; blank distortion-centre values parse as `None`; missing frame components are reported; and keyframe selection is deterministic. Real-data validation completed without extracting the archives: `single_room.zip` has 1,715 matched frames, 3,689 IMU rows, and 37.17 seconds duration; `single_scan_floor_only.zip` has 5,251 matched frames, 11,397 IMU rows, and 114.78 seconds duration; `single_scan_with_ceiling.zip` has 9,745 matched frames, 21,339 IMU rows, and 214.93 seconds duration. All three returned valid with zero errors and zero warnings, and sampled depth/confidence images were consistently 256 x 192 in `I;16`/`L` modes.

### CP03 — Metric reconstruction on `single_room.zip` (2–3 hours)

- [ ] Implement intrinsic scaling, depth conversion, back-projection, and pose transform.
- [ ] Add synthetic numerical tests.
- [ ] Process at most 50 frames first and write a PLY/top-down preview.
- [ ] Confirm visually that floor/walls form coherent surfaces and units are plausible.
- [ ] Raise to the `fast` bound only after the small run is correct.

**Stop condition:** if geometry is mirrored, exploded, or scaled incorrectly, do not tune RANSAC. Resolve transform/intrinsic conventions first.

### CP04 — Structural geometry and measurements (2–4 hours)

- [ ] Fit and classify dominant planes.
- [ ] Select a credible floor and optional ceiling.
- [ ] Build the trimmed 2D hull and simplify it.
- [ ] Calculate dimensions, area, perimeter, height, and quality evidence.
- [ ] Add rectangle/plane unit tests.

**Fallback:** if wall-plane intersections are unstable, ship the supported floor-point hull with a warning. Do not create complex topology code under deadline pressure.

### CP05 — Stable artifact bundle (1–2 hours)

- [ ] Define Pydantic models and schema version.
- [ ] Write JSON, PLY, SVG/PNG, plots, and Markdown report.
- [ ] Include effective parameters, versions, hash, warnings, and unsupported capabilities.
- [ ] Add explicit overwrite protection and useful exit codes.

**Gate:** a reviewer can understand the result without opening source code.

### CP06 — All samples and regression fixes (2–3 hours)

- [ ] Run the same frozen `fast` profile on all three archives.
- [ ] Generate a batch summary table.
- [ ] Inspect every rendering and record manual QA notes.
- [ ] Fix general failures only; avoid per-sample hard-coded geometry.
- [ ] Re-run the unit and smoke tests.

**Stop condition:** if one sample cannot yield a credible ceiling or wall, report the missing output and warning. Do not tune thresholds until the picture merely looks nice.

### CP07 — Submission and demo (2–3 hours plus buffer)

- [ ] Write README setup, commands, architecture, method, limitations, and results.
- [ ] Include the assignment coverage table and exact reproducibility commands.
- [ ] Add a concise demo script: validate, run, inspect JSON, open artifacts.
- [ ] Confirm no local absolute paths or secrets appear in committed outputs.
- [ ] Test from a clean environment/clone with samples copied into `sample/`.
- [ ] Review the Git diff and commit history.
- [ ] Reserve at least 2–3 hours before the deadline for packaging and failure recovery.

**Definition of submission-ready:** a clean clone installs, tests, runs the sample pipeline, and tells the truth about both results and limitations.

## Optional work, strictly after all P0 gates pass

Do these in order. Stop whenever the remaining deadline buffer would fall below two hours.

1. Improve the floor outline from a convex hull to an occupancy-grid/concave boundary while preserving the hull fallback.
2. Add lightweight sequential point-to-plane ICP and compare it against raw ARKit poses; keep it only if measurable plane residual or overlap improves.
3. Add Manhattan/orthogonal wall snapping when data supports it, with before/after quality evidence.
4. Add a small static HTML index that links existing artifacts; do not build a web application.
5. Decode a few RGB keyframes for visual context only. Do not call this damage detection.

Explicitly out of scope for this deadline even if P0 is early: training a model, adopting RoomFormer/PromptDA, iOS capture, cloud deployment, database persistence, user accounts, collaborative editing, production APIs, or fabricated damage/scope outputs.

## Risk register

| Risk | Likelihood | Impact | Mitigation / fallback |
|---|---|---|---|
| Large ZIPs cannot be pushed | Certain with ordinary Git for two files | Critical | clean history or Git LFS after approval; keep samples ignored locally |
| Camera transform convention is wrong | Medium | Critical | synthetic tests plus trajectory/plane sanity plots before feature work |
| Intrinsics are not scaled | High if overlooked | Critical | explicit source/depth dimensions and numerical unit test |
| Full captures exhaust RAM/time | High | High | bounded keyframes, pixel stride, incremental voxel downsampling |
| Floor RANSAC selects a table | Medium | High | orientation, support, vertical position, and extent checks |
| Convex hull overfills concavity | Known limitation | Medium | quality warning; optional grid boundary only after P0 |
| No ceiling in floor-only scan | Expected | Low | `null` plus explanation, not failure |
| Point cloud looks good but measurements are wrong | Medium | High | top-down evidence, plane residuals, units, sanity bounds, manual QA |
| Open3D install/runtime problem | Low/medium | High | use a supported Python 3.12 wheel; time-box diagnosis; only then fall back to NumPy/SciPy RANSAC and a small ASCII PLY writer |
| Scope expands during implementation | High | Critical | enforce checkpoint gates and append every material scope change below |
| No ground truth prevents accuracy score | Certain | Medium | report repeatability/internal fit metrics and state the limitation |

## Review standards

Before accepting code, ask:

- Does this line/component directly support a P0 acceptance criterion?
- Is there already a simpler library or standard-library operation for it?
- Is the code path tested with synthetic data before a large scan?
- Are units and coordinate frames explicit?
- Can a failure be distinguished from “no result”?
- Does the output carry evidence for the claim it makes?
- Is this logic general, or is it tuned to one filename/scan?
- Will a reviewer understand the choice from README, report, tests, or this decision log?

Reject code that introduces speculative abstractions, silent exception handling, global mutable configuration, unexplained constants, duplicated geometry logic, output files in source directories, or claims that cannot be evaluated.

## Research basis

- Stray Scanner format documentation: <https://github.com/strayrobots/scanner/blob/main/docs/format.md>
- Stray Scanner source repository: <https://github.com/strayrobots/scanner>
- OpenVPS Stray-to-COLMAP parser, useful for understanding the newer odometry columns and blank values: <https://github.com/OpenArCloud/openvps/blob/main/mapbuilder/scripts_mapping/stray_to_colmap.py>
- StrayVisualizer, useful as a reference for confidence filtering and TSDF/pose conventions but not to copy blindly: <https://github.com/kekeblom/StrayVisualizer>
- Open3D scalable TSDF API, reserved for later if simple fusion is insufficient: <https://www.open3d.org/docs/latest/python_api/open3d.pipelines.integration.ScalableTSDFVolume.html>
- Open3D point-cloud plane segmentation: <https://www.open3d.org/docs/release/tutorial/geometry/pointcloud.html>
- RoomFormer research implementation, deliberately rejected for P0 because of its older CUDA/PyTorch/compiled-op stack: <https://github.com/ywyue/RoomFormer>
- Prompt Depth Anything, deliberately deferred despite Stray support because it solves an unnecessary learned-depth problem for these LiDAR samples: <https://github.com/DepthAnything/PromptDA>

External repositories are research references, not dependencies by default. Before copying any code, verify its license, preserve required attribution, and prefer a small original implementation against documented formats/APIs.

## Decision log — append only

Rules for this section:

1. Never delete or edit a prior decision entry, even when it was wrong.
2. To change a decision, append a new entry whose status is `supersedes D-XXX` and explain why evidence changed.
3. Log decisions that affect scope, architecture, public schema, algorithms, dependencies, evaluation, data handling, or delivery.
4. Minor refactors that do not change behaviour do not need an entry.

Entry template:

```text
### D-XXX — Short title

- Date:
- Status: accepted | supersedes D-XXX | rejected
- Decision:
- Evidence/reasoning:
- Consequences:
- Revisit when:
```

### D-001 — Build only against the supplied LiDAR samples

- Date: 2026-09-22
- Status: accepted
- Decision: The deadline baseline supports the supplied Stray Scanner/ARKit LiDAR ZIPs and no additional input modality.
- Evidence/reasoning: These are the only concrete test inputs. Building untestable photo/video pathways would reduce reliability of the demonstrable product.
- Consequences: The package contract is intentionally narrow; other modalities are documented as unsupported.
- Revisit when: P0 is complete and a real, evaluable non-LiDAR dataset is available.

### D-002 — Deliver an offline CLI, not a UI or service

- Date: 2026-09-22
- Status: accepted
- Decision: The product surface is `validate`, `run`, and `batch` commands plus generated artifacts.
- Evidence/reasoning: The evaluator needs reproducibility and visible results, neither of which requires a frontend or server. A UI would introduce unrelated failure modes.
- Consequences: No API framework, database, deployment, authentication, or JavaScript application.
- Revisit when: The core pipeline and all submission checks pass with more than the protected deadline buffer remaining.

### D-003 — Use recorded LiDAR depth and ARKit poses as the baseline

- Date: 2026-09-22
- Status: accepted
- Decision: Back-project depth with scaled intrinsics and transform points with recorded camera poses. Do not begin with learned depth or global pose optimization.
- Evidence/reasoning: The files already contain metric depth and per-frame motion. Using the strongest supplied signal is simpler and more defensible.
- Consequences: Pose drift can remain visible; quality fields and warnings must disclose it. ICP is optional only after P0.
- Revisit when: The raw-pose reconstruction fails coherence checks or P0 is complete and measured ICP improvement is possible.

### D-004 — Bound reconstruction work deterministically

- Date: 2026-09-22
- Status: accepted
- Decision: Use frame limits/stride, pixel sampling, depth/confidence filtering, and incremental voxel downsampling.
- Evidence/reasoning: The inputs contain up to 9,745 depth frames. Processing every pixel of every frame is unnecessary for a deadline baseline and risks memory exhaustion.
- Consequences: Fine detail is sacrificed for repeatable runtime; the effective sampling parameters are recorded in each result.
- Revisit when: Profiling shows the complete baseline has ample time and memory headroom.

### D-005 — Use simple robust geometry before learned floor-plan models

- Date: 2026-09-22
- Status: accepted
- Decision: Use RANSAC planes and a trimmed convex hull for the first measured room outline.
- Evidence/reasoning: The supplied scans appear to be individual rooms, SciPy/Open3D provide the needed primitives, and research floor-plan models add incompatible legacy ML stacks and training assumptions.
- Consequences: Concave geometry may be overfilled and must be reported. Occupancy/concave boundaries are the first optional improvement.
- Revisit when: A supplied sample clearly fails because concavity, rather than bad reconstruction, is the dominant error.

### D-006 — Do not fabricate damage, concealed-condition, or repair-scope results

- Date: 2026-09-22
- Status: accepted
- Decision: These capabilities remain explicit `not_evaluated` entries in the result schema.
- Evidence/reasoning: There are no labels, ground-truth examples, taxonomy, or validated rules in the supplied data. A demo heuristic would look complete while producing unverifiable claims.
- Consequences: The submission covers less of the assignment but is technically honest and testable.
- Revisit when: Labelled examples and acceptance criteria exist, or after P0 if a clearly labelled research-only prototype is requested.

### D-007 — Keep one small Python package

- Date: 2026-09-22
- Status: accepted
- Decision: Use seven responsibility-based modules, one configuration/result model layer, and one pipeline; add no framework.
- Evidence/reasoning: This is enough separation for tests without creating architecture for hypothetical scale.
- Consequences: New modules require a concrete cohesion/testability reason. No generic `utils` dumping ground.
- Revisit when: A module develops two independent reasons to change or becomes difficult to test.

### D-008 — Minimize required dependencies

- Date: 2026-09-22
- Status: accepted
- Decision: P0 uses NumPy, SciPy, Open3D, Pillow, Pydantic, Matplotlib, and pytest only.
- Evidence/reasoning: OpenCV, Shapely, scikit-image, Jinja2, FFmpeg, PyTorch, and web packages duplicate capability or support out-of-scope features.
- Consequences: Some operations may need small focused implementations; dependency installation and reviewer setup remain manageable.
- Revisit when: A P0 requirement cannot be implemented correctly and simply with the selected set.

### D-009 — Use a versioned, evidence-carrying JSON contract

- Date: 2026-09-22
- Status: accepted
- Decision: `result.json` is authoritative and includes schema version, units, provenance, parameters, metrics, warnings, capability statuses, and artifact paths.
- Evidence/reasoning: Renderings alone cannot be tested or integrated. A strict contract prevents silent missing/zero values and lets the reviewer inspect evidence.
- Consequences: Schema changes require a decision-log entry and tests. Missing values use `null` with a warning/reason.
- Revisit when: An evaluator-provided schema conflicts with this contract.

### D-010 — Treat absolute accuracy as unmeasured

- Date: 2026-09-22
- Status: accepted
- Decision: Report internal fit/coverage/repeatability evidence and manual visual QA, but no absolute accuracy percentage.
- Evidence/reasoning: None of the three samples includes reference dimensions, surveyed geometry, or damage labels.
- Consequences: The report must separate measurements, proxies, and assumptions. Future benchmark work needs independently measured ground truth.
- Revisit when: Ground-truth dimensions or a licensed labelled benchmark is available.

### D-011 — Remove sample archives from ordinary Git history before pushing

- Date: 2026-09-22
- Status: accepted, action pending explicit approval
- Decision: Keep supplied samples locally and ignored; remove or migrate their already-committed objects before a normal GitHub push.
- Evidence/reasoning: The Git object store is already about 817 MiB, and two archives exceed GitHub's 100 MiB ordinary-file limit. The branch has no configured upstream, but remote publication has not been conclusively checked.
- Consequences: History manipulation must preserve the only local sample copies and must not be performed implicitly. The README will explain where to place externally supplied samples.
- Revisit when: The user confirms the remote/history state and chooses ignored external data versus Git LFS.

### D-012 — Prefer graceful partial output over invented fallback values

- Date: 2026-09-22
- Status: accepted
- Decision: A missing ceiling, low-support wall, or unstable boundary yields `null`, a warning, and `ok_with_warnings` when core output remains valid.
- Evidence/reasoning: The floor-only sample legitimately may not support a ceiling, and geometric evidence varies by capture. Returning zero or guessed dimensions would corrupt downstream interpretation.
- Consequences: Models and renderers must handle optional fields explicitly.
- Revisit when: A required P0 field lacks evidence so often that the overall product definition must change.

### D-013 — Freeze general parameters before cross-sample testing

- Date: 2026-09-22
- Status: accepted
- Decision: Tune on `single_room.zip`, record parameters, then run the same `fast` profile unchanged on both longer scans.
- Evidence/reasoning: Per-sample hidden constants create a demonstration, not a pipeline. Cross-sample failure is useful evidence about robustness.
- Consequences: Any override is public, serialized, justified, and treated as a limitation.
- Revisit when: There is evidence for an input-derived adaptive rule that can be tested generally.

### D-014 — Protect a final delivery buffer

- Date: 2026-09-22
- Status: accepted
- Decision: Stop optional development with at least 2–3 hours remaining before 2026-09-23 8:00 PM IST.
- Evidence/reasoning: Clean-clone testing, documentation, packaging, and Git failures commonly appear at the end and are part of the deliverable.
- Consequences: Optional algorithm improvements are dropped before documentation or reproducibility work.
- Revisit when: The deadline changes in writing.

### D-015 — Keep supplied captures as ignored external data

- Date: 2026-09-22
- Status: supersedes the unresolved storage choice in D-011
- Decision: Preserve all supplied ZIPs in the local ignored `sample/` directory and remove them from the unpublished ordinary-Git root commit. Do not use Git LFS for the assessment baseline.
- Evidence/reasoning: The configured remote had no branch heads, the assessor already distributes the samples separately, and two archives exceed GitHub's ordinary 100 MiB limit. Local SHA-256 values were recorded before the commit was amended.
- Consequences: A fresh clone remains small and requires the user to copy the supplied archives into `sample/`. The former large blobs may remain temporarily as unreachable local Git objects until normal garbage collection, but they are not reachable from `main` and will not be pushed with it.
- Revisit when: The assessor explicitly requires the sample binaries to be distributed from this repository.

### D-016 — Label implementation checkpoints CP01 through CP07

- Date: 2026-09-22
- Status: accepted
- Decision: Use the user-facing labels CP01 through CP07, with CP01 representing the repository foundation that was originally numbered Checkpoint 0.
- Evidence/reasoning: The user referred to the first approved build stage as CP01. Matching that vocabulary prevents approval and progress-report ambiguity.
- Consequences: The overview table and detailed checkpoint headings use CP01–CP07. Historical references to P0 still mean baseline priority, not a checkpoint number.
- Revisit when: No revisit is expected unless the checkpoint structure itself changes.

### D-017 — Validate ZIP and directory inputs through one read-only source

- Date: 2026-09-22
- Status: accepted
- Decision: Use one `CaptureSource` boundary that exposes normalized member names, sizes, text, and bytes for both ZIP archives and directories. Do not extract a complete capture during validation.
- Evidence/reasoning: The three archives contain up to 19,490 depth/confidence PNGs plus video. Direct member access makes validation fast, prevents temporary-disk duplication, and gives one place to reject traversal, absolute, drive-qualified, and duplicate archive paths.
- Consequences: Later reconstruction can read selected frames from the same source. Code outside `dataset.py` does not need ZIP-specific branches.
- Revisit when: A downstream library strictly requires filesystem paths and selected-member temporary extraction is measurably simpler.

### D-018 — Inspect three representative image pairs during normal validation

- Date: 2026-09-22
- Status: accepted
- Decision: Decode the first, middle, and last matched depth/confidence pairs during `validate`; inventory all filenames and records but do not decode every image.
- Evidence/reasoning: Decoding every PNG would turn a quick structural validator into a full-data scan. Three capture-spanning pairs verify dimensions, PNG decoding, pixel modes, and confidence range while keeping validation near-instant on the supplied archives.
- Consequences: An isolated corrupt image outside the inspected set may be discovered later when reconstruction selects it. The validation result records exactly how many pairs were inspected rather than implying a full pixel audit.
- Revisit when: A separate explicit deep-validation mode is required or reconstruction exposes meaningful corruption rates.

### D-019 — Allow partial frame mismatch but require at least one complete frame

- Date: 2026-09-22
- Status: accepted
- Decision: Missing depth, confidence, or odometry for individual IDs produces a warning and excludes those IDs; zero fully matched frames is an error.
- Evidence/reasoning: A mostly complete capture remains reconstructable, while silently pairing lists by position would corrupt geometry. Matching by canonical frame ID makes exclusion explicit and deterministic.
- Consequences: Inventory and warnings disclose all mismatch counts with bounded ID examples. Duplicate frame IDs remain errors because their intended pairing is ambiguous.
- Revisit when: Evaluation requirements mandate failure on any missing frame.

### D-020 — Inventory RGB and IMU without making them reconstruction prerequisites

- Date: 2026-09-22
- Status: accepted
- Decision: Validate IMU CSV timestamps and record RGB video presence/size, but do not decode video or require either asset for a valid LiDAR capture.
- Evidence/reasoning: CP03 reconstructs from depth, confidence, intrinsics, and odometry. Adding FFmpeg or synchronisation logic now would enlarge the dependency and failure surface without supporting the approved checkpoint.
- Consequences: Missing/invalid optional data creates a warning. RGB decoding remains outside P0 geometry unless a later approved checkpoint demonstrates a need.
- Revisit when: A validated feature consumes RGB or IMU rather than merely reporting it.
