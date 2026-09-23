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
- Pillow for 16-bit depth and confidence PNGs;
- Pydantic for the versioned result/config contract;
- pytest as the only required development dependency.

CP03 demonstrated that quaternion rotation, point fusion, deterministic voxel centroids, binary PLY output, and diagnostic PNG rendering are small and testable with NumPy/Pillow. SciPy may be added in CP04 only if its convex hull is selected. Open3D and Matplotlib are not baseline requirements unless a later measured need justifies them.

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
| **CP03 — Metric 3D reconstruction** | Convert selected depth/confidence frames and recorded ARKit poses into a bounded metric point cloud. | `scale_intrinsics()`; `depth_to_metres()`; `filter_depth()`; `backproject_depth()`; `quaternion_to_rotation()`; `camera_to_world_matrix()`; `transform_points()`; `reconstruct_keyframe()`; `voxel_downsample()`; `reconstruct_capture()`. | Coherent downsampled PLY/top-down preview from `single_room.zip`, with reconstruction statistics and numerical tests. | Synthetic projection/transform tests pass; a 50-frame real run has plausible scale and coherent floor/walls; the `fast` path stays within bounded memory. | **Complete — audited 2026-09-22** |
| **CP04 — Structural planes and floor plan** | Turn the reconstruction into an understandable measured room result. | `fit_plane_ransac()`; `classify_plane()`; `detect_floor()`; `detect_ceiling()`; `detect_wall_planes()`; `create_floor_coordinate_system()`; `project_points_to_floor()`; `trim_boundary_outliers()`; `build_convex_outline()`; `simplify_polygon()`; `measure_polygon()`; plane/boundary quality functions. | Floor polygon, edge lengths, area, perimeter, principal dimensions, optional ceiling height, plane metrics, and warnings. | Synthetic plane/rectangle tests pass; `single_room` produces an inspectable outline; unsupported height is `null`; weak convex support is marked provisional; no coordinates or geometry are hard-coded per sample. | **Complete — audited 2026-09-22** |
| **CP05 — Complete artifact bundle** | Turn the algorithms into one reviewable command-line product with stable outputs. | `PipelineConfig`; `RunResult`; `RoomResult`; `QualityMetrics`; `CapabilityStatus`; `ArtifactManifest`; `run_pipeline()`; `write_result_json()`; `write_ply()`; `render_floorplan_svg()`/`render_floorplan_png()`; `render_topdown()`; `render_trajectory()`; `write_report()`; `run` CLI command. | `result.json`, `reconstruction.ply`, `floorplan.svg`, `floorplan.png`, `topdown.png`, `trajectory.png`, and `report.md` from one command. | JSON validates against the versioned contract; units/provenance/parameters/warnings are present; overwrite protection and exit codes work; artifacts are understandable without reading source. | **Complete — audited 2026-09-22** |
| **CP06 — All-sample batch validation** | Prove the same pipeline and frozen profile work across all three supplied captures. | `discover_captures()`; `run_batch()`; `summarize_runs()`; `write_batch_outputs()`; `batch` CLI command; regression fixes that remain general. | Per-scan artifact bundles plus combined JSON/Markdown summary of runtime, geometry, measurements, quality, warnings, and failures. | All three runs finish without source changes; parameters are shared or overrides are disclosed; floor-only data handles missing ceiling correctly; full tests pass. | **Complete — audited 2026-09-22** |
| **CP07 — Submission and demonstration** | Make the project reproducible, explainable, and ready for assessor review. | Final README; setup/run commands; architecture and method documentation; schema/limitations; assignment coverage; demo script; clean-environment verification; dependency, secret, path, and Git audit. No new algorithm. | Submission-ready repository with reproducibility evidence and a short repeatable demonstration flow. | Clean install, tests, and sample commands succeed; tracked files are appropriate; claims match evidence; outputs are inspectable; delivery buffer remains. | **Complete — audited 2026-09-22** |
| **CP08 — Ground-truth benchmark and compliance evaluator** | Add an honest scoring layer over existing results without changing reconstruction mathematics. | Ground-truth manifest models; result/truth matching; absolute and percentage errors; assignment-gate evaluation; repeatability checks; confidence-interval coverage; compliance matrix; `evaluate` CLI command. | `evaluation.json`, `evaluation-report.md`, and `compliance-matrix.md` generated from a real measurement manifest and an existing batch run. | Synthetic truth tests pass; missing/phantom measurements are counted rather than hidden; unsupported gates remain `not_evaluated`; no sample measurements are fabricated; CP01–CP07 regressions pass. | **Complete — audited 2026-09-23** |
| **CP09 — Floor-plan 2.0: concavity and room segmentation** | Replace the knowingly overfilled convex outline when scan support is sufficient, while preserving the safe fallback. | Occupancy-grid cleanup; connected components; contour tracing; topology validation; concave polygon simplification; optional room-region segmentation; before/after support metrics. | More faithful concave floor outlines and explicit fallback evidence in the existing artifact contract. | Synthetic L/U-shaped tests pass; polygons are simple and deterministic; real support improves without unstable slivers; convex fallback still works. | **Complete — audited 2026-09-23** |
| **CP10 — Openings and adjacency** | Detect and represent doors/windows/open wall transitions so the plan covers the assignment's opening requirements. | Wall-aligned evidence profiles; opening proposal/filtering; width measurement; missed/phantom-ready IDs; wall/opening schema; adjacency graph; renderer/report updates. | Named openings with widths, confidence/evidence, and room adjacency in JSON and plans. | Synthetic openings are measured within tolerance; weak evidence returns unavailable rather than a guess; CP08 can score named openings including phantoms. | **Proposed — approval required** |
| **CP11 — Drift correction and ablation** | Add a bounded optional correction pass and prove whether it improves results compared with recorded poses as-is. | Overlap selection; lightweight pose/point alignment; correction acceptance gate; raw/corrected dual run; residual/closure/repeatability comparison; ablation report. | Explicit drift-correction-on/off benchmark evidence with automatic rollback when correction is worse. | Synthetic perturbation is improved; unchanged good poses remain stable; real-data ablation is reproducible; no accuracy claim is made without ground truth. | **Proposed — approval required** |

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

- [x] Implement intrinsic scaling, depth conversion, back-projection, and pose transform.
- [x] Add synthetic numerical tests.
- [x] Process at most 50 frames first and write a PLY/top-down preview.
- [x] Confirm visually that floor/walls form coherent surfaces and units are plausible.
- [x] Raise to the `fast` bound only after the small run is correct.

**Stop condition:** if geometry is mirrored, exploded, or scaled incorrectly, do not tune RANSAC. Resolve transform/intrinsic conventions first.

**Completion evidence (2026-09-22):** the approved ladder passed at 1 frame, 10 contiguous frames, 10 distributed frames, 50 distributed frames, and finally the 200-frame `fast` profile. The contiguous 10-frame bounds remained nearly identical to the one-frame bounds, supporting the pose direction and nearby-frame overlap. The 50-frame preview showed coherent repeated planar/rectangular structure with finite room-scale bounds. The final `single_room.zip` fast run processed all 200 selected frames in 2.01 seconds: 614,400 sampled pixels, 599,538 valid points before voxel fusion, and 70,928 output points. Bounds were approximately 9.31 x 2.90 x 7.19 m; trajectory path length was 14.49 m; the start/end distance was recorded only as a 3.18 m closure proxy. The binary PLY was about 851 KB, JSON about 1.5 KB, and the PNG preview about 83 KB. No warnings or skipped frames occurred. A repeated fast run produced byte-identical PLY and PNG SHA-256 hashes. All 37 synthetic, integration, CLI, and output tests passed after implementation.

### CP04 — Structural geometry and measurements (2–4 hours)

- [x] Fit and classify dominant planes.
- [x] Select a credible floor and optional ceiling.
- [x] Build the trimmed 2D hull and simplify it.
- [x] Calculate dimensions, area, perimeter, height, and quality evidence.
- [x] Add rectangle/plane unit tests.

**Fallback:** if wall-plane intersections are unstable, ship the supported floor-point hull with a warning. Do not create complex topology code under deadline pressure.

**Completion evidence (2026-09-22):** 50 tests pass, including noisy and tilted planes, known rotated-rectangle measurements, a synthetic 4 x 3 m room with floor/ceiling/four walls, missing-ceiling behavior, deterministic repeats, rendering, output protection, and CLI failures. The real `single_room.zip` fast run completed CP03 plus CP04 in under five seconds at the command boundary. Its floor has 14,640 inliers (20.6% of the cloud), 1.58 cm RMSE, and a normal whose world-up component is 0.99995. Six vertical planes were retained with 1.7–2.9 cm residuals. No ceiling passed the conservative evidence gate, so ceiling and height are `null`. The convex polygon measures 7.44 x 6.59 m, 34.73 m², and 23.02 m perimeter, but only 46.8% of that convex area is backed by occupied floor cells; the CLI, JSON, README, SVG, and PNG therefore mark the area as provisional and warn about concavity/unscanned gaps. Two independent real runs produced identical PLY, top-down PNG, SVG, floor-plan PNG, and structural geometry after excluding elapsed time. Generated run directories remain ignored.

### CP05 — Stable artifact bundle (1–2 hours)

- [x] Define Pydantic models and schema version.
- [x] Write JSON, PLY, SVG/PNG, plots, and Markdown report.
- [x] Include effective parameters, versions, hash, warnings, and unsupported capabilities.
- [x] Add explicit overwrite protection and useful exit codes.

**Gate:** a reviewer can understand the result without opening source code.

**Completion evidence (2026-09-22):** 58 tests pass. The final `run` command validates, hashes, reconstructs, measures, evaluates, and stages a seven-file bundle. Tests cover result-schema round trips, exact and canonical-directory hashes, truthful capability statuses, nullable ceiling preservation, report wording, trajectory rendering, manifest completeness, overwrite protection, unrelated-file preservation, and an injected render failure that publishes no partial directory. The real `single_room.zip` fast run finished in 2.41 seconds on the first audited run and produced the recorded SHA-256 `0805f742...e9699c`, exactly matching the prior fingerprint. The manifest and directory contain the same seven names; JSON validates; SVG parses; all PNGs verify; and the report clearly labels the 34.73 m² convex area provisional, ceiling unavailable, and the 3.18 m start/end distance as not certified drift. A second independent run had byte-identical PLY, top-down PNG, trajectory PNG, SVG, floor-plan PNG, and Markdown report; `result.json` matched after removing observed timings. A real rerun without `--overwrite` returned exit code 2 and named all conflicts. Both reviewer-facing PNGs were visually inspected.

### CP06 — All samples and regression fixes (2–3 hours)

- [x] Run the same frozen `fast` profile on all three archives.
- [x] Generate a batch summary table.
- [x] Inspect every rendering and record manual QA notes.
- [x] Fix general failures only; avoid per-sample hard-coded geometry.
- [x] Re-run the unit and smoke tests.

**Stop condition:** if one sample cannot yield a credible ceiling or wall, report the missing output and warning. Do not tune thresholds until the picture merely looks nice.

**Completion evidence (2026-09-22):** 73 tests pass, including stable discovery, unrelated-entry filtering, empty-input rejection, case-insensitive output-name collision detection, frozen-config reuse, expected per-capture failure isolation, unexpected-error propagation, summary-schema round trips, staged JSON/Markdown publication, injected staging failure, preflight collision checks, overwrite behavior, and CLI exit codes. One unmodified `fast`/distributed configuration with a 200-frame cap processed all three real archives sequentially: `single_room` produced 70,928 points, a provisional 34.73 m² convex outline, six walls, and no supported ceiling; `single_scan_floor_only` produced 171,537 points, a provisional 78.23 m² outline, six walls, and no supported ceiling; `single_scan_with_ceiling` produced 242,402 points, a provisional 85.80 m² outline, six walls, and an evidence-supported 2.40 m ceiling. Each capture wrote all seven CP05 artifacts, and the batch wrote its two aggregate artifacts. The effective configurations in all three `result.json` files are identical. All nine top-down, trajectory, and floor-plan PNGs were manually inspected; geometry is visible, paths align with the scans, labels are legible, and no floor-only ceiling was fabricated. A second independent batch produced byte-identical PLY, top-down, trajectory, SVG, floor-plan, and per-capture Markdown files; every `result.json` and `batch.json` matched after excluding observed durations. No sample-specific threshold or coordinate was added.

### CP07 — Submission and demo (2–3 hours plus buffer)

- [x] Write README setup, commands, architecture, method, limitations, and results.
- [x] Include the assignment coverage table and exact reproducibility commands.
- [x] Add a concise demo script: validate, run, and inspect batch evidence.
- [x] Confirm no local absolute paths or secrets appear in tracked source/docs.
- [x] Test a clean package build/install from a temporary source copy.
- [x] Review the Git diff and commit history.
- [x] Preserve the remaining deadline buffer by adding no new algorithm or dependency.

**Definition of submission-ready:** a clean clone installs, tests, runs the sample pipeline, and tells the truth about both results and limitations.

**Completion evidence (2026-09-22):** the final documented command `python scripts/demo.py --sample-dir sample --output runs/submission-demo --profile fast` completed from the repository root. It ran the complete suite, validated `single_room.zip` with zero errors/warnings and 1,715 matched frames, processed all three real samples with the frozen `fast` configuration, returned `OK` with three successes and zero failures, and printed the expected provisional areas/dimensions plus the supported 2.40 m ceiling only for the with-ceiling sample. The final suite contains 79 passing tests, including stale-summary rejection on a failed demo rerun. A no-network temporary packaging audit used `pip install --no-deps --no-build-isolation --target`; the wheel built, installed outside the repository, imported from that target, reported version `0.1.0`, and exposed `validate`, `reconstruct`, `measure`, `run`, and `batch` in CLI help. `batch.json` and every per-capture `result.json` validate against their Pydantic contracts; all three effective configs are equal; and README measurements match the generated evidence. Git hygiene checks found no tracked file over 10 MiB, while `sample/`, `runs/`, and caches remain ignored. Common private-key/API-token patterns, local user-profile paths, and the workspace path do not occur in the tracked source/documentation set. The demo uses only the standard library, shell-free subprocess argument lists, explicit sample checks, overwrite protection, and propagated exit codes. No numerical pipeline code or dependency changed in CP07.

### CP08 — Ground-truth benchmark and compliance evaluator (1–2 hours)

- [x] Define a strict, versioned manifest for survey/tape/laser truth without adding invented sample values.
- [x] Load successful `result.json` files from an existing `batch.json` and match them to truth by capture name.
- [x] Score available area, principal dimensions, ceiling height, named wall lengths, and named opening widths.
- [x] Encode the assignment thresholds exactly where they apply; mark unspecified or unsupported gates `not_evaluated`.
- [x] Count missing predictions and phantom openings explicitly.
- [x] Evaluate repeated-capture ceiling/wall spread and confidence-interval coverage when those inputs exist.
- [x] Write machine-readable evaluation, reviewer report, and requirement-to-evidence compliance matrix.
- [x] Add an `evaluate` CLI command, focused unit/CLI tests, benchmark instructions, and README usage.
- [x] Re-run the full test suite and a real batch-result evaluation with a deliberately incomplete, clearly synthetic audit manifest.

**Gate:** CP08 must never turn current fit residuals or quality labels into ground-truth accuracy. A successful evaluator run may still report `failed_gates` or `incomplete`; the CLI should fail only when it cannot create a valid evaluation.

**Approved scope (2026-09-23):** add a separate evaluator over CP06/CP07 artifacts. Freeze all numerical reconstruction and floor-plan functions. Add no dependency. Do not create a fake `ground-truth.json` for the supplied samples.

**Completion evidence (2026-09-23):** 97 tests pass, including 18 CP08 contract, error, exact-threshold-boundary, missing/phantom-opening, repeatability-versus-accuracy, interval-coverage, batch/result-integrity, staged-publication, overwrite, and CLI tests. `evaluate` reads strict versioned truth plus existing `batch.json`/`result.json` contracts and writes `evaluation.json`, `evaluation-report.md`, and `compliance-matrix.md`. A real artifact-path smoke audit loaded all three existing `runs/demo` results, verified their bound input SHA-256 values, and published all three valid outputs; it correctly returned product status `incomplete` and protocol warnings for a deliberately fictional LiDAR-only/no-repeat manifest. That temporary manifest was then removed and its output remains ignored; no fabricated ground truth is tracked. A no-network package build/import exposed the new command. `dataset.py`, `reconstruction.py`, `floorplan.py`, `pipeline.py`, `outputs.py`, `batch.py`, and `models.py` are byte-for-byte unchanged from CP07, and no dependency was added.

### CP09 — Floor-plan 2.0: concavity and room segmentation (2–4 hours)

- [x] Build a cleaned floor-occupancy mask from existing projected support.
- [x] Trace deterministic outer contours and reject invalid/self-intersecting polygons; treat inner holes as unsupported area rather than emitting unsupported room topology.
- [x] Simplify while protecting topology, support, corners, and credible recesses.
- [x] Count and retain connected-component evidence; explicitly avoid labelling scan fragments as rooms without wall/opening adjacency evidence.
- [x] Compare occupied support, component retention, perimeter, complexity, and topology against the convex baseline.
- [x] Preserve the convex hull as an explicit fallback with the rejection reason in JSON/report warnings.

**Gate:** no implementation before a separate checkpoint overview and explicit approval. Do not replace a stable convex result with a visually attractive but topologically invalid contour.

**Completion evidence (2026-09-23):** 101 tests pass. New synthetic tests cover exact L- and U-shaped occupancy area, a deep recess, deterministic four-neighbour components, disconnected-evidence fallback, simple-polygon validation, self-intersection rejection, and serialized outline evidence. A candidate must retain at least 80% of occupied cells, achieve at least 55% direct support, improve support by 8 percentage points over the occupancy convex hull, stay at or below 36 vertices, keep perimeter at or below 1.5 times the convex perimeter, and remain simple; otherwise the old convex result is used. The frozen `fast` profile completed all three supplied scans: `single_room` accepted a 27-vertex occupancy contour measuring 16.40 m² with 94.9% support and 95.7% component retention; `single_scan_floor_only` retained its 78.23 m² convex fallback because the simplified candidate still had 63 vertices; `single_scan_with_ceiling` retained its 85.80 m² fallback because the candidate had 57 vertices. All three plans were visually inspected. Two independent batches produced byte-identical PLY/SVG/PNG/Markdown artifacts and equivalent result/batch JSON after removing only durations. New structure/result/batch artifacts use schema `1.1.0`, while the CP08 loader successfully parsed all three existing real `1.0.0` results. The complete reviewer demo succeeded and prints each outline method. No dependency was added and multi-room stitching/semantic room segmentation remains explicitly unsupported.

### CP10 — Openings and adjacency (2–4 hours)

- [ ] Assign stable IDs to supported wall segments.
- [ ] Build height/occupancy evidence profiles along walls.
- [ ] Propose and validate door/window/open-transition gaps with width and uncertainty evidence.
- [ ] Represent rooms, walls, openings, and adjacency in the public result contract.
- [ ] Render openings without implying unsupported classifications.
- [ ] Connect the new predictions to CP08's opening gate and phantom/miss accounting.

**Gate:** no implementation before a separate checkpoint overview and explicit approval. Missing structure or occlusion must yield unavailable/low confidence, never an invented opening.

### CP11 — Drift correction and ablation (2–4 hours)

- [ ] Measure overlap candidates and baseline residuals using recorded poses.
- [ ] Apply a small, bounded correction only to sufficiently supported overlaps.
- [ ] Reject corrections that worsen structural residual, consistency, or physical plausibility.
- [ ] Run identical inputs with correction off and on.
- [ ] Publish configuration, residual, closure-proxy, and ground-truth/repeatability comparisons.
- [ ] Keep the original recorded-pose result reproducible as the control.

**Gate:** no implementation before a separate checkpoint overview and explicit approval. A lower closure proxy alone is not proof of accuracy; keep correction disabled unless the ablation supplies broader evidence.

## Optional work, strictly after all P0 gates pass

Do these in order. Stop whenever the remaining deadline buffer would fall below two hours.

1. **Completed in CP09:** improve the floor outline from a convex hull to an occupancy-grid/concave boundary while preserving the hull fallback.
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
| Structural plane fitting is unstable without a geometry framework | Medium | High | begin CP04 with tested NumPy RANSAC; add SciPy/Open3D only if measured evidence shows the small implementation is insufficient |
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

### D-021 — Use a NumPy-first reconstruction and defer heavy geometry dependencies

- Date: 2026-09-22
- Status: supersedes the CP03 dependency portion of D-008
- Decision: Implement projection, quaternion rotation, point transformation, voxel centroids, binary PLY output, and PNG diagnostics with NumPy and Pillow. Remove SciPy, Open3D, and Matplotlib from current runtime dependencies.
- Evidence/reasoning: Each CP03 operation is small and has an exact numerical test. The 200-frame real run completed in 2.01 seconds and produced a 70,928-point cloud without a geometry framework.
- Consequences: Installation remains small and CPU-only. CP04 may add SciPy for a convex hull or Open3D only after showing a specific measured need.
- Revisit when: The tested small implementation cannot meet a CP04 correctness or runtime requirement.

### D-022 — Apply the recorded pose as camera-to-world

- Date: 2026-09-22
- Status: accepted
- Decision: Back-project depth into OpenCV-style camera coordinates and transform points directly with the normalized quaternion/translation matrix `T_WC`.
- Evidence/reasoning: The Stray reference implementation names the recorded pose `T_WC` and supplies its inverse to APIs that expect a world-to-camera extrinsic. Exact identity/rotation/translation tests pass; 10 contiguous real frames overlap within nearly unchanged bounds; distributed 50/200-frame clouds remain finite and structurally coherent.
- Consequences: No automatic transform guessing or sample-specific axis switch exists. If later plane evidence contradicts world-up assumptions, the convention must be re-audited rather than silently flipped.
- Revisit when: CP04 plane orientation or independent reference geometry provides contradictory evidence.

### D-023 — Use explicit bounded reconstruction profiles

- Date: 2026-09-22
- Status: accepted
- Decision: Define `test`, `fast`, and `quality` profiles centrally, with frame limits of 10/200/500, pixel strides of 8/4/2, and voxel sizes of 8/4/2 cm respectively. Fuse fixed frame batches and voxel-downsample between batches.
- Evidence/reasoning: The largest sample has 9,745 frames. The bounds make runtime and memory predictable while distributing selected frames over the full capture. The fast single-room run sampled 614,400 pixels rather than every pixel in all frames.
- Consequences: Fine detail is intentionally traded for bounded repeatability. Every effective value is serialized in `reconstruction.json`; an explicit `--max-frames` override is also recorded.
- Revisit when: Cross-sample evaluation shows insufficient structural support or excessive detail loss.

### D-024 — Retain a low-level reconstruction diagnostic command

- Date: 2026-09-22
- Status: accepted
- Decision: Add `cozmo-scan reconstruct` as an auditable lower-level command that writes PLY, top-down PNG, and diagnostic JSON before the final `run` product command exists.
- Evidence/reasoning: Transform and scale errors must be inspectable independently of CP04 floor-plan logic. The three small artifacts provide geometry, a visual check, and machine-readable evidence without a UI.
- Consequences: CP05 will compose this tested core rather than replacing it. Existing artifacts require `--overwrite`, and only the three known filenames are replaced.
- Revisit when: The final CLI becomes confusing; if so, retain the function API and document the command as advanced diagnostics.

### D-025 — Keep contiguous-start selection only as an audit mode

- Date: 2026-09-22
- Status: accepted
- Decision: Default to capture-spanning deterministic selection, but expose `--frame-selection contiguous-start` for nearby-pose overlap checks.
- Evidence/reasoning: Distributed frames test global coverage, while the approved CP03 ladder also required 10 nearby frames to isolate local transform correctness. The nearby run stayed within the one-frame bounds and did not explode.
- Consequences: Product runs remain distributed. Contiguous-start is documented as diagnostic, and the selected mode is serialized with the configuration.
- Revisit when: The transform convention is independently validated and the audit flag no longer provides useful debugging value.

### D-026 — Keep CP04 NumPy-only and deterministic

- Date: 2026-09-22
- Status: accepted
- Decision: Implement plane fitting, 2D line fitting, convex hull, polygon simplification, and minimum-area dimensions directly with focused NumPy functions. Use fixed random seeds and stable sorting; add no CP04 dependency.
- Evidence/reasoning: The required kernels are small enough to test numerically. The complete 70,928-point real structural analysis takes a fraction of a second, and independent runs produce identical geometry and rendered artifacts.
- Consequences: Installation remains limited to NumPy, Pillow, and Pydantic. The project owns roughly 790 lines of explicit structural logic, but avoids a large geometry framework and keeps every threshold in the serialized configuration.
- Revisit when: A later approved concave-boundary or mesh capability has a demonstrated correctness/runtime need that the focused implementation cannot meet.

### D-027 — Identify horizontal structure relative to the camera and floor

- Date: 2026-09-22
- Status: accepted
- Decision: Seed the floor from the densest height band 0.5–2.5 m below median camera height, refine it with fixed-seed horizontal RANSAC/SVD, and search for a ceiling only 1.8–4.5 m above that floor. Reject weak support, span, orientation, or height rather than guessing.
- Evidence/reasoning: `single_room.zip` contains a dominant surface near world Y -1.48 m while median camera Y is near -0.07 m. The fitted floor has 14,640 inliers, 1.58 cm RMSE, and normal Y 0.99995. No upper plane passed the ceiling evidence gate.
- Consequences: The real result reports `ceiling: null` and `ceiling_height_m: null`. A missing ceiling is a supported outcome, not zero height or a pipeline failure.
- Revisit when: CP06 runs the frozen configuration on the explicitly floor-only and with-ceiling captures.

### D-028 — Use vertical 2D line RANSAC for wall planes

- Date: 2026-09-22
- Status: accepted
- Decision: After removing the floor and optional ceiling, detect walls as robust lines in world X-Z and lift them to vertical planes. Require horizontal span, vertical span, minimum support, and duplicate rejection.
- Evidence/reasoning: ARKit world-up was independently supported by the floor normal. A 2D model uses that evidence, requires two samples instead of three, and is simpler and more stable than unrestricted 3D RANSAC for vertical walls. The real fast run retains six supported planes with 1.7–2.9 cm residuals.
- Consequences: This baseline assumes gravity-aligned walls and does not fit arbitrarily leaning surfaces as walls. Full spans live in JSON; short teal direction markers are used in the drawing to avoid obscuring the outline.
- Revisit when: A supplied scan contains meaningful non-vertical structural walls or floor/world-up evidence fails.

### D-029 — Treat the convex floor outline as provisional when support is sparse

- Date: 2026-09-22
- Status: accepted
- Decision: Build the baseline boundary from trimmed, neighbour-supported floor occupancy cells and a simplified convex hull. Serialize occupied-cell area and convex-fill ratio. Below 60% fill, label the convex area provisional everywhere and emit an explicit warning.
- Evidence/reasoning: The real `single_room` top-down view is visibly non-convex or incompletely scanned. Its hull is 34.73 m², while supported 8 cm cells cover 46.8% of that area. Reporting the hull as an unqualified room area would hide a known limitation.
- Consequences: CP04 remains deterministic and bounded but does not claim a precise concave room boundary. Concave occupancy contours remain optional work after the complete P0 pipeline and documentation pass.
- Revisit when: The final baseline is complete and deadline buffer permits a tested concave-boundary method with the convex result retained as fallback.

### D-030 — Retain `measure` as the CP04 diagnostic command

- Date: 2026-09-22
- Status: accepted
- Decision: Add `cozmo-scan measure` to compose the tested reconstruction and structural functions and write six diagnostic artifacts: PLY, reconstruction JSON, top-down PNG, structure JSON, floor-plan SVG, and floor-plan PNG.
- Evidence/reasoning: CP04 needs an auditable real-data path before CP05 defines the final product schema/report. Reusing `reconstruct_capture()` avoids a second geometry pipeline, and overwrite protection covers all known files.
- Consequences: CP05 will compose these functions into the final `run` result rather than replace them. `measure` remains useful for low-level diagnosis; it is not yet the full assignment artifact contract.
- Revisit when: CP05 finalizes command naming and reviewer workflow.

### D-031 — Make `run` the primary single-capture product command

- Date: 2026-09-22
- Status: accepted
- Decision: Add `cozmo-scan run` as a thin orchestration path over the existing validator, reconstruction, and structural-analysis functions. Keep `validate`, `reconstruct`, and `measure` as lower-level diagnostic commands.
- Evidence/reasoning: A reviewer needs one command and one stable bundle, while each earlier command remains useful for isolating ingestion, transform, or measurement failures. The real final run completes in a few seconds without duplicating numerical logic.
- Consequences: `pipeline.py` owns composition and public-result construction only. Geometry remains in its existing modules, and CP06 can reuse `run_pipeline()` rather than introduce a second batch code path.
- Revisit when: Final usability testing shows that the diagnostic commands confuse rather than help the reviewer.

### D-032 — Publish a versioned evidence-carrying final result

- Date: 2026-09-22
- Status: accepted
- Decision: Define immutable Pydantic models for input/software provenance, effective configuration, reconstruction evidence, room geometry, quality metrics, timings, capability assessments, warnings, and a seven-file artifact manifest under schema version `1.0.0`.
- Evidence/reasoning: A drawing alone cannot communicate missing ceiling evidence, provisional convex area, processing parameters, or unsupported assignment features. The model round-trips from JSON in tests and preserves every CP02–CP04 warning.
- Consequences: Unsupported capabilities are explicit `not_implemented` or `not_evaluated` records instead of invented empty detections. Missing ceiling values remain `null`, and consumers have a stable machine-readable contract.
- Revisit when: A backward-incompatible field change is necessary; if so, increment the schema version rather than silently changing meaning.

### D-033 — Record reproducible provenance without local absolute paths

- Date: 2026-09-22
- Status: accepted
- Decision: Hash ZIP inputs byte-for-byte and directory inputs through sorted normalized member names, lengths, and contents. Store only the input basename, hash method, byte count, capture inventory, package/dependency versions, and effective parameters.
- Evidence/reasoning: The real run reproduced the known `single_room.zip` SHA-256 exactly. Canonical-directory tests prove creation order does not change the digest and content changes do. Absolute workstation paths add no reproducibility value and can leak local details.
- Consequences: ZIP and extracted-directory hashes intentionally use different definitions and declare `hash_kind`. Final JSON/report contains no local absolute path.
- Revisit when: A standard external manifest format is required for cross-container ZIP/directory equivalence.

### D-034 — Stage the complete artifact set before publication

- Date: 2026-09-22
- Status: accepted
- Decision: Render all seven final artifacts inside a temporary sibling directory, verify that every expected file exists, then move only known files into the requested output directory. Refuse conflicts without `--overwrite` and preserve unrelated destination files.
- Evidence/reasoning: A late SVG/PNG/report failure must not leave a plausible-looking partial product. The injected render-failure test leaves no destination directory; complete/overwrite tests preserve an unrelated reviewer note.
- Consequences: Publication is all-render-before-move and atomic per file, though an operating-system failure during the final sequence could still move only part of the staged set. That residual limitation is acceptable for the local deadline baseline.
- Revisit when: The product needs transactional publication across filesystems or concurrent writers.

### D-035 — Separate deterministic evidence from observed runtime

- Date: 2026-09-22
- Status: accepted
- Decision: Keep observed reconstruction, structure, and total durations in `result.json`, but include no generated timestamp. Require geometry, reports, and renderings to be deterministic; compare final JSON after excluding the timing object.
- Evidence/reasoning: Two real final runs produced byte-identical PLY, top-down PNG, trajectory PNG, floor-plan SVG/PNG, and Markdown report. Their final JSON matched after removing timings, while elapsed seconds naturally differed.
- Consequences: Reviewers retain useful performance evidence without pretending wall-clock duration is deterministic. Result consumers know exactly which field varies between equivalent runs.
- Revisit when: A formal reproducible-build profile chooses to omit timings entirely or stores them outside the result contract.

### D-036 — Reuse the final pipeline sequentially with one frozen configuration

- Date: 2026-09-22
- Status: accepted
- Decision: Make `batch` a thin sequential orchestrator over the unchanged `run_pipeline()` and `write_run_outputs()` contracts. Construct one `PipelineConfig` and pass that same immutable object to every capture. Add no worker pool and no dependency.
- Evidence/reasoning: The three samples complete in tens of seconds with the bounded `fast` profile. Sequential execution keeps peak memory bounded, makes console/report order deterministic, and proves cross-sample behavior without creating a second numerical code path.
- Consequences: Batch speed is the sum of individual runs, but results remain easy to reproduce and audit. A future parallel runner must preserve ordering, failure semantics, and the exact per-capture contract.
- Revisit when: Measured runtime on a materially larger dataset justifies controlled parallelism and memory limits are tested.

### D-037 — Discover only top-level captures and reserve collision-free output names

- Date: 2026-09-22
- Status: accepted
- Decision: Accept one ZIP, one valid capture directory, or the deterministic case-insensitive ordering of top-level ZIP/valid-directory children. Ignore unrelated entries, sanitize output names, reject case-insensitive collisions, and preflight every known batch/per-capture destination before starting work.
- Evidence/reasoning: Recursively interpreting arbitrary folders as a dataset risks duplicate processing and output ambiguity. Tests cover stable ordering, unrelated files, empty inputs, `room`/`ROOM.zip` collisions, known-artifact conflicts, and a per-capture destination that is a file even under `--overwrite`.
- Consequences: Nested collections are deliberately not traversed. Inputs must be organized as direct children, while an extracted capture directory remains accepted directly. Existing unrelated output files are preserved.
- Revisit when: A documented manifest or recursive dataset format provides unambiguous capture identities.

### D-038 — Continue after expected capture failures but expose internal bugs

- Date: 2026-09-22
- Status: accepted
- Decision: Record `PipelineError` and `OutputError` as failed batch items, continue later captures, and return exit code 2 when any item fails. Do not catch unexpected exception types inside the batch loop.
- Evidence/reasoning: One corrupt archive should not erase evidence from other supplied samples, but treating a programming error as ordinary bad data would produce a misleading partial-success report. Injected tests prove both continuation for an expected failure and propagation for an unexpected runtime error.
- Consequences: `batch.json` and `batch-report.md` contain explicit errors for normal per-capture failures. Internal faults reach the CLI safety boundary and return exit code 1 rather than being disguised as data quality.
- Revisit when: New pipeline exception classes are introduced; add only failures that genuinely represent input/output conditions.

### D-039 — Keep cross-sample measurements cautious and evidence-led

- Date: 2026-09-22
- Status: accepted
- Decision: Retain the shared structural thresholds and report all three real convex areas as provisional because occupied support is below 60%. Keep ceiling height `null` for `single_room` and `single_scan_floor_only`; report 2.40 m only for `single_scan_with_ceiling`, where a plane passes the existing support checks.
- Evidence/reasoning: The frozen run produced occupied support of 46.8%, 57.4%, and 48.5%. Manual review of all nine PNGs confirms broad multi-space or incomplete/concave coverage, matching the caution labels. The explicitly named floor-only sample remains nullable, while the with-ceiling sample provides accepted plane evidence without a per-file threshold change.
- Consequences: The batch demonstrates general behavior rather than cosmetically tuned drawings. It does not claim ground-truth accuracy, a concave room boundary, or a ceiling where the evidence is absent.
- Revisit when: Survey dimensions, labelled room boundaries, or a tested concave-outline implementation supplies objective evaluation evidence.

### D-040 — Compare deterministic batch evidence separately from durations

- Date: 2026-09-22
- Status: accepted
- Decision: Record total and per-capture wall-clock durations in batch artifacts, but assess repeatability by comparing every geometric/rendered artifact byte-for-byte and JSON after removing only elapsed-time fields.
- Evidence/reasoning: Two independent three-capture runs produced byte-identical PLY, top-down PNG, trajectory PNG, SVG, floor-plan PNG, and per-capture Markdown files. Per-capture result objects and the aggregate batch object were equal after durations were removed.
- Consequences: Runtime evidence remains useful while deterministic geometry and reporting have a precise audit rule. The aggregate Markdown naturally differs where it displays observed durations.
- Revisit when: Timing moves to a separate benchmark artifact or deterministic-build mode omits it.

### D-041 — Keep the reviewer demo thin, cross-platform, and shell-free

- Date: 2026-09-22
- Status: accepted
- Decision: Add one standard-library `scripts/demo.py` that checks the three supplied filenames, optionally runs tests, validates `single_room`, invokes the existing `batch` CLI, reads `batch.json`, and prints a compact summary. Use `sys.executable` and subprocess argument sequences with no shell.
- Evidence/reasoning: The exact documented command completed successfully on all real samples and printed the same measurements as the validated batch contract. Six focused tests cover defaults, missing inputs, full command flow, partial-batch evidence, missing summary rejection, and refusal to display stale evidence after a failed rerun.
- Consequences: The demonstration adds no second pipeline, geometry logic, dependency, platform-specific shell script, or automatic file opening. Existing overwrite and exit-code behavior remains visible to the reviewer.
- Revisit when: A hosted or packaged demonstration environment replaces repository-local execution.

### D-042 — Make generated contracts the source of truth for submission claims

- Date: 2026-09-22
- Status: accepted
- Decision: State measurements, ceilings, confidence, and limitations in README only when they can be matched to validated `batch.json` and per-capture `result.json`. Keep generated runs ignored rather than committing workstation-specific evidence bundles.
- Evidence/reasoning: The final claims audit parsed every generated contract, verified identical configurations, and matched the three areas, dimensions, and ceiling outcomes to README. The input hashes already identify the assessor-supplied data without duplicating hundreds of megabytes in Git.
- Consequences: The repository stays small and the README remains evidence-led. Reviewers regenerate artifacts locally from their supplied samples rather than trusting opaque committed binaries.
- Revisit when: The submission instructions explicitly require generated artifacts to be uploaded separately.

### D-043 — Verify packaging offline without altering the development environment

- Date: 2026-09-22
- Status: accepted
- Decision: Copy the package inputs to a temporary directory and install them to a separate target with both build isolation and dependency downloads disabled. Verify import location, version, and full CLI help from that target.
- Evidence/reasoning: The temporary build produced and installed a `cozmo_scan-0.1.0` wheel using the declared metadata. Import resolved to the temporary target and the CLI exposed all five commands. This checks packaging without mutating the repository environment or depending on network availability.
- Consequences: The final audit proves the project itself packages cleanly; runtime dependency compatibility remains covered by the real demo and full test suite in the provisioned Python 3.12 environment.
- Revisit when: A release artifact or fully isolated dependency-resolution test is required by the delivery channel.

### D-044 — Keep ground-truth evaluation above the frozen pipeline

- Date: 2026-09-23
- Status: accepted
- Decision: Implement CP08 as `benchmark.py`, which reads published `batch.json` and per-capture `result.json` contracts. Do not modify capture ingestion, reconstruction, floor-plan mathematics, final-result construction, output rendering, or batch execution.
- Evidence/reasoning: The existing three-capture baseline is deterministic and already audited. Accuracy evaluation needs independent reference data and matching logic, not a second geometry path. The final diff leaves every numerical and CP05/CP06 pipeline module unchanged.
- Consequences: CP08 can expose current limitations without moving the baseline. Future wall/opening predictions can enter through a versioned result contract and reuse the evaluator.
- Revisit when: CP09 or CP10 makes a backward-incompatible result-schema change; version and migrate the prediction adapter explicitly.

### D-045 — Encode only thresholds stated by the assignment

- Date: 2026-09-23
- Status: accepted
- Decision: Gate ceiling height at 0.015 m absolute error, openings at 0.02 m and 85% aggregate including misses/phantoms, photo named-wall length at 8%, video named-wall length at 3%, repeated ceiling spread at 0.01 m, and repeated wall spread at 0.01 m or 0.5%. Report floor-area/principal-dimension errors diagnostically, with no invented gate; likewise define no LiDAR wall or interval-coverage threshold.
- Evidence/reasoning: Applying a linear wall percentage to area, treating fit residual as accuracy, or choosing an arbitrary LiDAR/coverage threshold would make an unsupported pass/fail claim. Boundary tests cover every encoded accuracy threshold.
- Consequences: Many current LiDAR comparisons are honestly `not_evaluated` even when an error can be calculated. This is less flattering but auditable.
- Revisit when: The assessor supplies an authoritative additional threshold; record its source and version before changing the gate.

### D-046 — Do not reinterpret anonymous planes as named walls or openings

- Date: 2026-09-23
- Status: accepted
- Decision: Normalize current results to scalar area/dimensions/height but leave the named-wall and named-opening maps empty. Do not match RANSAC plane order or convex polygon edges to physical wall/opening IDs.
- Evidence/reasoning: Current wall planes have no stable physical identity or finite wall-length measurement, and the pipeline does not detect openings. Positional matching would create plausible but false correspondence and corrupt repeatability/phantom accounting.
- Consequences: Real wall/opening truth produces explicit `missing_prediction`; the opening aggregate counts misses and future phantom IDs correctly. CP10 must introduce stable IDs and evidence before these gates can pass.
- Revisit when: A versioned room topology provides persistent wall/opening identities and tested association across repeated captures.

### D-047 — Separate evaluator execution success from product-gate success

- Date: 2026-09-23
- Status: accepted
- Decision: Return CLI exit code 0 when a valid evaluation was produced, even if `evaluation.json` status is `failed_gates` or `incomplete`. Return 2 for invalid/missing/unsafe inputs or output conflicts, and 1 only at the existing unexpected-error boundary.
- Evidence/reasoning: A failed accuracy gate is a valid benchmark result, not a tool crash. Conflating the two would make automated runs discard precisely the evidence the evaluator exists to publish.
- Consequences: CI and reviewers must inspect the product status for quality decisions. The CLI and report state this rule explicitly.
- Revisit when: A separate `--fail-on-gate` automation option is requested; keep the default evidence-first behavior stable.

### D-048 — Bind optional truth entries to input hashes and stage all outputs

- Date: 2026-09-23
- Status: accepted
- Decision: Allow each truth capture to declare the expected input SHA-256 and refuse scoring on mismatch. Constrain result paths to the batch root, validate batch/result names and hashes, reject unknown truth fields, and stage all three evaluation files before publication with explicit overwrite behavior.
- Evidence/reasoning: A correct score against the wrong capture is invalid evidence. Tests cover strict manifests, result/hash mismatch, staged-render failure, collision refusal, and preservation of unrelated files.
- Consequences: Real benchmark manifests should include input hashes. Local real-property manifests use the ignored `benchmark/*.local.json` convention.
- Revisit when: A signed external benchmark manifest or remote artifact store defines stronger identity guarantees.

### D-049 — Report benchmark protocol coverage separately from metric scores

- Date: 2026-09-23
- Status: accepted
- Decision: The compliance matrix separately reports the assignment's at-least-three-room condition, same-room photo/video/LiDAR coverage, repeated captures, staged damage from two classes, declared laser/tape method, photo stitching, drift ablation, competitor comparison, and fix loop. A manifest can declare protocol facts but the evaluator does not certify that the physical procedure occurred.
- Evidence/reasoning: Passing one numerical ceiling or opening check cannot prove that the required benchmark design was followed. The real-artifact smoke report correctly warns about missing tiers and repeats even though all three result files load.
- Consequences: `Declared`, `not met`, `not evaluated`, and implementation statuses remain distinct. Damage and other unbuilt features cannot disappear behind a geometry score.
- Revisit when: New prediction/annotation schemas make the missing protocol rows objectively evaluable.

### D-050 — Accept concavity only through an evidence gate

- Date: 2026-09-23
- Status: accepted
- Decision: Quantize the already accepted floor inliers, close only one-cell gaps, find deterministic four-neighbour components, trace exposed grid-cell edges, simplify the largest outer contour, and use it only if it is simple and improves occupied support. Preserve the CP04 convex hull as the fallback.
- Evidence/reasoning: Dense synthetic L and U rooms recover their exact 12 m² and 16 m² occupancy areas with valid concave polygons. Disconnected support and invalid/overly complex candidates return a reasoned fallback rather than an attractive guess.
- Consequences: CP09 adds no second point-cloud or plane path. Every accepted/fallback result shares the same upstream floor evidence and public measurement function.
- Revisit when: A wall/opening topology supplies a stronger boundary constraint than floor occupancy alone.

### D-051 — Bound concave contours by retention, support, perimeter, and complexity

- Date: 2026-09-23
- Status: accepted
- Decision: Require at least 80% occupied-cell retention, 55% direct boundary support, an 8-percentage-point support improvement over the occupancy convex hull, no more than 36 simplified vertices, perimeter no more than 1.5 times the convex perimeter, and a simple counter-clockwise polygon. Use a separate 0.24 m concave simplification tolerance while retaining the 0.08 m convex tolerance.
- Evidence/reasoning: The first real contour had 80 vertices and an unreadable 34.28 m labelled perimeter despite 97.5% support. The stricter simplification produces a readable 27-vertex plan with 94.9% support; increasing simplification to 0.32 m did not make the other two scans defensible, so their fallbacks remain.
- Consequences: Strong support alone cannot pass a jagged plan. JSON preserves the selected method, component count, retention, discarded cells, support alias, and exact fallback reason.
- Revisit when: Ground-truth boundaries allow these conservative thresholds to be tuned objectively instead of visually.

### D-052 — Do not call occupancy components rooms

- Date: 2026-09-23
- Status: accepted
- Decision: Record connected-component evidence and select one defensible outer contour, but do not label disconnected floor fragments as semantic rooms or claim multi-room segmentation/stitching.
- Evidence/reasoning: The real scans contain 3, 4, and 14 cleaned components, yet the largest `single_room` component retains 95.7% of the original occupied cells. Small components can be noise, disconnected scan support, or another region; floor occupancy alone cannot distinguish them.
- Consequences: CP09 improves one published outline without inventing room identities. CP10 wall/opening adjacency is the next prerequisite for semantic segmentation.
- Revisit when: Stable wall segments, openings, and adjacency produce objective room-enclosure evidence.

### D-053 — Publish additive outline evidence as schema 1.1

- Date: 2026-09-23
- Status: accepted
- Decision: Emit structure, final-result, and batch schema `1.1.0` with additive outline fields while accepting both `1.0.0` and `1.1.0` when reading existing artifacts. Retain `convex_fill_ratio` for compatibility and serialize `boundary_support_ratio` as its clearer method-neutral alias.
- Evidence/reasoning: CP09 changes numerical output meaning and adds method/fallback evidence, so silently calling it the same schema would be misleading. The CP08 loader parsed all three real CP07 `1.0.0` results and all three CP09 `1.1.0` results.
- Consequences: Old artifacts remain evaluable. New consumers should prefer `boundary_support_ratio` and inspect `outline_method` before interpreting area.
- Revisit when: A topology graph or multiple room polygons requires a non-additive 2.0 schema.

### D-054 — Keep detailed edges in JSON but limit drawing labels

- Date: 2026-09-23
- Status: accepted
- Decision: Preserve every polygon edge and length in machine-readable output, but when a plan has more than 12 edges render at most the 14 longest edges of at least 0.50 m as dimension labels.
- Evidence/reasoning: Labelling all 80 edges made the first real CP09 preview unreadable. The final 27-vertex `single_room` drawing remains inspectable while JSON retains every value.
- Consequences: The drawing is a reviewer view rather than the sole measurement record. Short-edge omission from the image is not data loss.
- Revisit when: An interactive layer or collision-aware label placement replaces the static renderer.

### D-055 — Keep mixed accepted/fallback behavior across the supplied scans

- Date: 2026-09-23
- Status: accepted
- Decision: With one frozen configuration, accept the 16.40 m²/94.9%-supported `single_room` contour and retain the existing convex results for floor-only and with-ceiling because their simplified candidates exceed the 36-vertex cap. Do not relax the cap per sample.
- Evidence/reasoning: All three scans complete with shared parameters. The two rejected candidates still contain 63 and 57 vertices at 0.24 m simplification and remain 58 and 47 vertices at 0.32 m; stronger global simplification makes the first plan only marginally smaller and does not rescue the others.
- Consequences: Cross-sample output is intentionally mixed and carries explicit method/fallback evidence. The lower `single_room` area is described as better supported, not ground-truth accurate.
- Revisit when: Independent measured room boundaries show whether a rejected candidate or alternative contour is more accurate.
