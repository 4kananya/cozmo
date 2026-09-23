# Project capability matrix

This matrix maps each material project capability to the implementation and evidence present in this repository. `Implemented with limitations` is not an accuracy claim. `Not evaluated` is not a pass. No physical ground truth was supplied with the three captures, so the matrix does not convert internal fit statistics or synthetic tests into real-world accuracy.

| Requirement | File path | Review artifact | Status | Evidence and limitation |
|---|---|---|---|---|
| Stock capture route | `docs/capture-route.md` | Capture checklist | Implemented | Route 2 protocol for Stray Scanner and a LiDAR-equipped iPhone. No custom iOS application. |
| Device and tier matrix | `docs/device-matrix.md` | Device matrix | Implemented | All three ingestion paths and the LiDAR-only geometry boundary are mapped to hardware and commands. |
| Photo input tier | `src/cozmo_scan/media.py` | `media-input.json`, `contact-sheet.jpg` | Implemented with limitations | Images are decoded, hashed, checked for resolution, exposure, sharpness, clipping and perceptual duplicates. Thresholds screen capture quality; metric geometry is produced by the LiDAR tier. |
| Video input tier | `src/cozmo_scan/media.py` | `media-input.json`, sampled frames, `contact-sheet.jpg` | Implemented with limitations | FFprobe validates the stream and FFmpeg extracts evenly distributed frames. Frames are hashed and quality-screened. This is not video-only metric geometry. |
| Known-pose media reconstruction | `src/cozmo_scan/photogrammetry.py` | `media-reconstruction.json`, `media-reconstruction.ply` | Prototype | Multi-view DLT produces sparse metric points from calibrated observations and metre-scale camera poses, with positive-depth and reprojection gates. Automatic matching and dense stereo are absent. |
| LiDAR input tier | `src/cozmo_scan/dataset.py`, `reconstruction.py` | `reconstruction.ply`, `result.json` | Implemented with limitations | Three supplied Stray Scanner captures validate and run locally. |
| One command per capture | `src/cozmo_scan/cli.py` | Seven-file `run` bundle | Implemented | `python -m cozmo_scan run ...` validates, reconstructs, measures, and publishes. |
| All-sample execution | `src/cozmo_scan/batch.py`, `scripts/demo.py` | `batch.json`, `batch-report.md` | Implemented | One frozen configuration processes all three captures sequentially. |
| Per-room floor plan | `src/cozmo_scan/floorplan.py` | `floorplan.svg`, `floorplan.png`, `result.json` | Implemented with limitations | Occupancy-supported measured extent with explicit sprawl and coverage warnings; not a stitched homeowner plan. |
| Walls and dimensions | `src/cozmo_scan/floorplan.py`, `openings.py` | `result.json` | Implemented with limitations | Per-capture deterministic wall IDs and measured spans; no cross-capture physical identity. |
| Ceiling height | `src/cozmo_scan/floorplan.py` | `result.json`, `report.md` | Implemented with limitations | Published only when an evidence-supported ceiling plane exists. Real accuracy is unmeasured. |
| Openings and widths | `src/cozmo_scan/openings.py` | `result.json`, rendered plans | Implemented with limitations | Conservative pass-through/far-floor evidence gates. Synthetic door and window widths are within 2 cm; physical accuracy is unmeasured. |
| Room adjacency | `src/cozmo_scan/openings.py` | `result.json` | Partial | Near/far scanned areas can support an adjacency observation. No global room identity or stitched graph. |
| Multi-room stitching | `src/cozmo_scan/stitching.py` | Prototype stitching JSON | Prototype | Manual anchors or automatic wall hypotheses estimate a rigid transform; consensus wall matches refine it. Repeated layouts, loop closure and physical validation remain unresolved. |
| Damage regions and classes | `src/cozmo_scan/damage.py` | Experimental screening JSON | Prototype; not evaluated | Multi-scale local-contrast segmentation reports connected crack-like visual candidates. It is not a structural diagnosis and has no labelled-data validation. |
| Concealed-condition flags | Not present | None | Not implemented | Not inferred from the supplied evidence. |
| Repair-scope line items | `src/cozmo_scan/damage.py` | Draft scope JSON | Prototype; reviewer required | Scaled candidate geometry plus explicit reviewer confirmations/actions produce draft quantities and optional costs. The artifact requires engineering approval and does not infer repairs. |
| Interval on every measurement | `src/cozmo_scan/intervals.py` | `result.json` | Implemented with limitations | Bootstrap precision intervals cover area, perimeter, principal dimensions, available ceiling height, and opening widths that reappear in enough point resamples. Precision is not accuracy. |
| Calibrated interval coverage | `src/cozmo_scan/benchmark.py` | `evaluation.json`, evaluation report | Not evaluated | Coverage can be reported when truth is supplied; no physical truth is present and no pass threshold is invented. |
| Drift accountability | `src/cozmo_scan/drift.py` | `drift-ablation.json`, `drift-ablation.md` | Implemented with limitations | Both arms are rebuilt and compared; all supplied captures roll back to recorded poses. Horizontal drift and yaw are untouched. |
| Versioned JSON contract | `src/cozmo_scan/models.py` | Schema `1.4.0` results | Implemented | Readers accept result schemas `1.0.0` through `1.4.0`; missing legacy evidence is not fabricated. |
| Ground-truth evaluator | `src/cozmo_scan/benchmark.py` | Three-file evaluation bundle | Implemented; data required | Strict manifest, capture binding, gates, misses, phantoms, repeatability, and descriptive interval coverage. |
| Three-room physical benchmark | Not present | None | Not met | Supplied data is three independent archives without verified physical-room identities. |
| Same rooms at all three tiers | `src/cozmo_scan/media.py` | Media manifests plus LiDAR results | Not met | Ingestion paths exist, but no matched three-tier room captures or media-derived geometry results are present. |
| Repeated capture benchmark | Not present | None | Not met | No independently identified repeated room pair with truth. |
| Laser or tape ground truth | Not present | None | Not met | Accuracy remains unestablished. |
| Opening width gate | `src/cozmo_scan/benchmark.py` | Evaluation report | Not evaluated on real data | The 2 cm on 85% gate is encoded; no physical opening truth is supplied. |
| Ceiling gate | `src/cozmo_scan/benchmark.py` | Evaluation report | Not evaluated on real data | The 1.5 cm gate is encoded; the 2.40 m estimate has no physical reference. |
| Repeatability gates | `src/cozmo_scan/benchmark.py` | Evaluation report | Not evaluated | Requires repeated captures with named-wall and ceiling truth. |
| Photo and video wall gates | `src/cozmo_scan/benchmark.py` | Evaluation report | Not evaluated | The 8% and 3% gates are encoded; ingestion does not produce wall predictions. |
| Head-to-head consumer-app comparison | Not present | None | Not evaluated | No identical-room app export and common truth. |
| Fix declaration | `docs/fix-loop-declaration.md` | Declaration | Implemented | Written before the boundary-support change and records the failing gate and prediction. |
| Fix result and before/after regeneration | `docs/fix-loop-result.md` | Result plus commands | Implemented with limitations | Before/after runs are reproducible from the local samples; generated outputs remain intentionally untracked. |
| Technical report | `docs/technical-report.md` | Technical report | Implemented | Covers architecture, tiers, drift, error budget, calibration, fix loop, and failure modes. |
| Test evidence | `tests/` | Automated test suite | Implemented | Unit, contract, media-evidence, stitching, anomaly-screening, synthetic-geometry, failure-path, rendering, determinism, and audit regressions. |
| Offline local runtime | `pyproject.toml` | CLI and artifacts | Implemented | NumPy, Pillow, and Pydantic; local FFmpeg/FFprobe for video evidence. No account, API key, GPU, database, or hosted service. |
## Scope interpretation

The implemented product has three deterministic input paths and an offline LiDAR geometry pipeline with conservative evidence handling. Photo and video produce validated media manifests; LiDAR additionally produces measured geometry. The remaining scope boundaries are documented per capability rather than hidden behind a single tier-level label.
