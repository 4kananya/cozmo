# Cozmo Scan Project Handover

## Purpose of this file

This file is the self-contained starting point for a new chat or engineer. Read it before changing the repository, then use `THOUGHT.md` as the authoritative detailed plan and append-only decision record.

The project is a deadline-focused engineering assessment for Cozmo AI. It processes the three supplied Stray Scanner/ARKit LiDAR captures and produces measured, reviewable reconstruction artifacts. The agreed product constraint is to build and test against the supplied sample data, while being explicit about unsupported assignment features.

## Required collaboration workflow

The user requires checkpoint-by-checkpoint approval:

1. Before a new checkpoint, explain in easy language what it will build.
2. Give the exact files, functions, dependencies, risks, tests, and acceptance gates.
3. Wait for explicit approval.
4. Only then implement that checkpoint.
5. Audit it harshly, run the complete test and real-data checks, update `THOUGHT.md`, and commit it.
6. Explain what was built and present the next checkpoint overview for separate approval.

Do not treat completion of one checkpoint, or a generic request such as “continue,” as approval for every remaining checkpoint. If the user explicitly says “approve,” “build CP10,” or equivalent after seeing the CP10 overview, implementation may start.

Communication should be point-by-point, easy to understand, evidence-led, and thorough without overcomplicating the codebase.

## Current approval boundary

- CP01 through CP09 are complete and audited.
- CP09 implementation commit: `cbb88b3 feat: add guarded concave floor outlines`.
- CP10 has been presented to the user, but it has **not** been approved yet.
- CP11 has not received its separate checkpoint overview or approval.
- The current request was only to create this handover file.

Therefore, a new chat must not begin CP10 code merely because this file exists. If the user says only “continue,” first restate the CP10 build contract and ask for approval. If the user clearly approves CP10, proceed with that exact bounded scope.

## Product in one paragraph

`cozmo-scan` is a local, CPU-only Python CLI. It validates a capture ZIP or extracted directory, reconstructs a metric point cloud from depth/confidence images and ARKit camera poses, detects structural planes, builds a guarded floor outline, measures the room, and publishes deterministic JSON/PLY/SVG/PNG/Markdown artifacts. The same pipeline runs one capture or all three supplied samples. A separate evaluator compares published results with independently supplied ground truth. The project does not invent measurements, openings, rooms, damage, or accuracy when evidence is absent.

## Repository state and history

Expected branch: `main`.

Recent implementation commits before this handover:

```text
cbb88b3 feat: add guarded concave floor outlines
571bffe feat: add ground-truth benchmark evaluator
6d4de23 feat: add reviewer demo and finalize submission
5726230 feat: validate all sample captures
fa29c0c feat: add final artifact pipeline
89f0e54 feat: measure structural room geometry
8027c48 feat: reconstruct metric point clouds
9e34e29 feat: validate Stray Scanner captures
2a33321 docs: record CP01 completion
021253a chore: initialize Cozmo Scan assessment
```

At the start of handover creation, `git status --short` was empty. Always run these before work:

```powershell
git status --short
git log -5 --oneline
```

Preserve unrelated user changes. Never discard them with `git reset --hard` or `git checkout --`.

## Important files

- `Applied AI.docx` — the original assignment document.
- `README.md` — reviewer-facing setup, commands, architecture, results, limitations, and evaluator usage.
- `THOUGHT.md` — full audit, checkpoint table, completion evidence, risks, and append-only decisions D-001 onward.
- `pyproject.toml` — Python package metadata and the complete dependency list.
- `scripts/demo.py` — one-command reviewer demonstration.
- `benchmark/README.md` — ground-truth manifest and evaluator instructions.
- `src/cozmo_scan/models.py` — immutable/versioned public contracts and configuration.
- `src/cozmo_scan/dataset.py` — capture discovery, safe ZIP access, parsing, validation, and frame selection.
- `src/cozmo_scan/reconstruction.py` — depth back-projection, poses, voxel fusion, PLY and reconstruction evidence.
- `src/cozmo_scan/floorplan.py` — plane fitting, floor coordinates, convex/concave outline selection, measurements, and quality evidence.
- `src/cozmo_scan/pipeline.py` — final single-capture orchestration; it should not contain geometry algorithms.
- `src/cozmo_scan/outputs.py` — staged artifact publication and renderers.
- `src/cozmo_scan/batch.py` — deterministic sequential reuse of the final pipeline.
- `src/cozmo_scan/benchmark.py` — truth/result matching, assignment gates, repeatability, and compliance outputs.
- `src/cozmo_scan/cli.py` — argument parsing and user-facing orchestration only.
- `tests/` — 101 tests at the CP09 baseline.

## Architecture and non-negotiable principles

```text
capture ZIP/directory
        |
        v
dataset.py          validation and typed capture loading
        |
        v
reconstruction.py   metric XYZ reconstruction from depth + poses
        |
        v
floorplan.py        structural planes and guarded floor outline
        |
        v
pipeline.py         provenance, quality, warnings, capabilities
        |
        v
outputs.py          seven-file reviewer artifact bundle
        ^
        |
batch.py            same pipeline across all captures
        |
        v
benchmark.py        independent truth comparison and exact gates
```

Keep these principles:

- One numerical pipeline; diagnostic, single-run, batch, demo, and evaluation paths must reuse it.
- Internal geometry is in metres and units should be explicit in field names.
- Missing data is `null`/unavailable, never silently `0`.
- Prefer pure, deterministic NumPy functions and fixed seeds.
- Keep I/O at module boundaries.
- Do not add a framework, service, database, GPU requirement, cloud service, or model-training stack.
- Do not add a dependency unless there is a demonstrated need. Current runtime dependencies are only NumPy, Pillow, and Pydantic.
- Do not hard-code coordinates or thresholds per supplied sample.
- Do not confuse fit residual/support with ground-truth accuracy.
- Stage complete output bundles before publishing them and preserve overwrite protection.
- Do not store local absolute paths in result artifacts or tracked documentation.

## Completed checkpoints

| Checkpoint | Delivered result | Audit status |
|---|---|---|
| CP01 | Safe, small, installable repository and CLI skeleton | Complete |
| CP02 | ZIP/directory ingestion, capture validation, frame matching | Complete |
| CP03 | Deterministic metric point-cloud reconstruction | Complete |
| CP04 | Floors, optional ceilings, wall planes, measurements, convex outline | Complete |
| CP05 | One-command seven-file result bundle with provenance and quality | Complete |
| CP06 | Frozen-configuration batch execution over all three samples | Complete |
| CP07 | Reviewer demo, documentation, packaging and submission audits | Complete |
| CP08 | Independent ground-truth/compliance evaluator | Complete |
| CP09 | Guarded occupancy-supported concave outline with convex fallback | Complete |
| CP10 | Wall IDs, openings and adjacency | Proposed; approval required |
| CP11 | Optional bounded drift correction and ablation | Proposed; approval required |

The exact checklists, gates, and completion evidence are in `THOUGHT.md`; do not duplicate or replace that append-only record casually.

## CP09 state that must be preserved

CP09 uses only already accepted floor inliers. It builds occupancy cells, closes one-cell gaps, identifies deterministic four-neighbour components, traces the largest exterior contour, simplifies it, validates topology, and selects it only when all evidence gates pass. Otherwise it preserves the previous convex hull and records why.

Current acceptance gates:

- at least 80% occupied-cell retention;
- at least 55% direct boundary support;
- at least 8 percentage points more support than the occupancy convex hull;
- at most 36 simplified vertices;
- perimeter no greater than 1.5 times the convex perimeter;
- simple, counter-clockwise polygon;
- concave candidate area cannot exceed the convex area.

Important interpretation: occupancy components are evidence fragments, not semantic rooms. CP09 deliberately did **not** claim room segmentation or multi-room stitching.

CP09 introduced additive schema `1.1.0`. Readers accept both `1.0.0` and `1.1.0`. The legacy field `convex_fill_ratio` remains for compatibility, and `boundary_support_ratio` is the clearer method-neutral serialized alias.

## Verified real-data baseline

All three supplied archives use one frozen `fast` profile with no per-file threshold changes:

| Capture | Output points | Outline | Area | Principal dimensions | Ceiling | Boundary support |
|---|---:|---|---:|---:|---:|---:|
| `single_room.zip` | 70,928 | occupancy concave | 16.40 m² | 8.07 × 4.55 m | unavailable | 94.9% |
| `single_scan_floor_only.zip` | 171,537 | convex safety fallback | 78.23 m² provisional | 10.88 × 9.44 m | unavailable | 57.4% |
| `single_scan_with_ceiling.zip` | 242,402 | convex safety fallback | 85.80 m² provisional | 12.40 × 9.28 m | 2.40 m | 48.5% |

Why the mixed behavior is correct:

- `single_room` produced a supported 27-vertex contour with 95.7% retained-component evidence.
- The floor-only candidate still had 63 vertices after simplification, so it was rejected.
- The with-ceiling candidate still had 57 vertices, so it was rejected.
- The global limit was not weakened for individual samples.
- These are internal geometric estimates, not ground-truth accuracy claims.

Two independent CP09 batches produced byte-identical PLY, SVG, PNG, and Markdown artifacts. JSON matched after removing only observed timing fields. All floor plans were manually inspected. Old `1.0.0` artifacts still load through the CP08 evaluator.

Generated audit directories such as `runs/cp09-final`, `runs/cp09-final-repeat`, and `runs/cp09-demo` are intentionally ignored by Git.

## Commands that were verified

From the repository root, with the package installed or `src` on `PYTHONPATH`:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -q
```

CP09 result: `Ran 101 tests ... OK`.

Reviewer demo:

```powershell
python scripts/demo.py --sample-dir sample --output runs/demo --profile fast
```

Use `--overwrite` only when deliberately replacing known artifacts. Use `--skip-tests` only when the full suite was just run separately.

Useful direct commands:

```powershell
python -m cozmo_scan validate sample/single_room.zip
python -m cozmo_scan reconstruct sample/single_room.zip --output runs/reconstruction --profile fast
python -m cozmo_scan measure sample/single_room.zip --output runs/measurement --profile fast
python -m cozmo_scan run sample/single_room.zip --output runs/final --profile fast
python -m cozmo_scan batch sample --output runs/all-samples --profile fast
python -m cozmo_scan evaluate runs/all-samples --ground-truth path/to/real-ground-truth.json --output runs/evaluation
```

Check current CLI help if evaluator argument order or naming is in question rather than guessing:

```powershell
python -m cozmo_scan --help
python -m cozmo_scan evaluate --help
```

The no-network package smoke test previously succeeded using `pip install --no-deps --no-build-isolation --target <temporary-directory> .`. Do not install dependencies or change the environment unnecessarily.

## Output contracts

`run` publishes exactly seven artifacts:

1. `result.json`
2. `reconstruction.ply`
3. `topdown.png`
4. `trajectory.png`
5. `floorplan.svg`
6. `floorplan.png`
7. `report.md`

`batch` adds `batch.json` and `batch-report.md` at the output root and one seven-file directory per capture.

`evaluate` publishes:

1. `evaluation.json`
2. `evaluation-report.md`
3. `compliance-matrix.md`

Evaluation success and product accuracy are deliberately separate: the evaluator returns a valid result even when gates fail or evidence is incomplete. Missing and phantom openings are counted rather than hidden. No genuine sample ground truth is currently tracked.

## Proposed CP10 build contract

CP10 is about detecting and representing doors, windows, and open wall transitions conservatively enough for CP08 to score them. It must not infer semantic rooms or adjacency without physical evidence.

### Proposed files

- Add `src/cozmo_scan/openings.py` so opening logic does not further overload `floorplan.py`.
- Extend `src/cozmo_scan/models.py` with versioned wall/opening/adjacency evidence models.
- Extend `src/cozmo_scan/pipeline.py` to call the new analysis without embedding its algorithms.
- Extend `src/cozmo_scan/outputs.py` for plan/report representation.
- Extend `src/cozmo_scan/benchmark.py` only as required to adapt the new named predictions to existing miss/phantom scoring.
- Extend `src/cozmo_scan/cli.py` only if an exposed, justified configuration option is required; do not put detection logic there.
- Add `tests/test_openings.py` and focused integration/renderer/schema tests.
- Update `README.md` and append CP10 decisions/evidence to `THOUGHT.md`.

### Proposed functions/components

Names may be refined after inspecting the existing contracts, but responsibilities should remain narrow:

- associate finite boundary edges with supported vertical wall planes;
- assign stable deterministic wall IDs;
- create a wall-local coordinate system;
- project suitable non-floor points into distance-along-wall and height coordinates;
- construct occupancy/support profiles along each wall;
- propose bounded gaps;
- reject gaps caused by scan limits, weak support, furniture occlusion, or missing coverage;
- classify strong evidence as `door_like`, `window_like`, or `unclassified_gap` rather than overstating semantics;
- measure supported opening width and optional height;
- attach every opening to a supported wall with stable IDs, confidence, and evidence;
- represent the unknown other side explicitly when a second room is not supported;
- create room adjacency only when two independently supported enclosed regions share the opening;
- render openings and expose them through the existing result/report/evaluator contracts.

### CP10 risks

- Missing scan coverage can look like an opening.
- Furniture and occlusion can create phantom wall gaps.
- Reflective or transparent windows may have sparse LiDAR returns.
- Existing wall planes are anonymous and effectively infinite; they must first be associated with finite boundary edges.
- A floor occupancy boundary is not automatically a physical wall.
- The supplied samples have no trusted opening ground truth, so real-data accuracy cannot be claimed.

### CP10 safety posture

- Prefer no prediction over a plausible false opening.
- Require support on the wall and around the proposed gap.
- Record the rejection/unavailable reason.
- Keep classification conservative.
- Do not claim room-to-room adjacency when only one region is supported.
- Add no dependency unless the tested NumPy implementation cannot meet a specific requirement.

### CP10 tests and acceptance gate

- Synthetic solid wall produces no opening.
- Synthetic door-like and window-like gaps receive stable IDs and measured widths within the configured profile resolution/assignment tolerance.
- Partial, scan-edge, fragmented, and occluded walls are rejected or marked unavailable.
- Results remain deterministic across repeated runs.
- Old schema artifacts remain readable or receive an explicit, tested version migration.
- CP08 consumes named opening predictions and continues counting misses and phantoms.
- JSON, report, SVG, and PNG clearly distinguish predictions from unavailable evidence.
- All existing tests continue to pass.
- All three samples complete with one shared configuration.
- Real-sample reporting publishes only supported candidates and makes no accuracy claim without real ground truth.

Before implementation, inspect existing model shapes and benchmark adapters and present the final exact function signatures/configuration thresholds to the user. Then wait for approval unless it was already explicitly given in that new conversation.

## CP11 is later and independent

CP11 proposes optional, bounded drift correction plus an on/off ablation. It is not part of CP10 and must not be smuggled into it. It needs its own detailed overview and approval. A lower first-to-last camera distance alone is not proof of better geometry; any correction must improve broader supported evidence and automatically roll back when worse.

## Known limitations that must remain honest

- No supplied survey/tape/laser ground truth, so absolute accuracy is not established.
- No semantic multi-room stitching yet.
- No supported opening detector yet; that is CP10.
- No photo-only or video-only reconstruction pipeline.
- No damage detection or damage annotations.
- No concealed-condition prediction.
- No automated repair scope.
- No production API, mobile app, cloud deployment, database, or live walk-in experience.
- Recorded-pose reconstruction is used as-is; drift correction is only a proposed CP11 experiment.
- Start-to-end camera distance is a closure proxy, not certified drift.

Never hide these limitations behind an attractive drawing or an empty result array.

## How to resume safely in a new chat

1. Read this entire file.
2. Read the checkpoint table, CP09/CP10 sections, and decisions D-044 through D-055 in `THOUGHT.md`.
3. Run `git status --short` and inspect the latest commits.
4. Run the 101-test baseline before numerical changes.
5. If the user has not explicitly approved CP10, present its exact overview and wait.
6. After approval, implement CP10 only; do not start CP11.
7. Use one frozen configuration and synthetic evidence first.
8. Run the complete suite, all three samples, determinism/backward-compatibility checks, visual artifact inspection, claim/path/secret/package audits, and `git diff --check`.
9. Update the checkpoint status, completion evidence, and append-only decisions in `THOUGHT.md`.
10. Commit CP10, explain the result in easy language, then present CP11 separately for approval.
