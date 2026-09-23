# Device matrix

Which input tier runs on which hardware, and what each tier honestly delivers. All three tiers can be ingested, while metric geometry is implemented only for LiDAR. Capture uses a stock iOS app, Stray Scanner, as set out in [capture-route.md](capture-route.md). There is no Cozmo iOS application.

## Input tiers

| Tier | Status | Capture hardware | Processing hardware | What it produces | Accuracy |
|---|---|---|---|---|---|
| LiDAR depth plus ARKit pose, captured with Stray Scanner | Implemented | LiDAR equipped Pro class iPhone, iPhone 12 Pro or later | Any Windows, Linux or macOS laptop with Python 3.12. CPU only | Dimensioned floor outline with area, perimeter, principal dimensions and per edge lengths; wall planes with deterministic identifiers; ceiling height when an evidence supported ceiling plane exists; conservatively gated door and window openings with measured widths; plan as SVG and PNG; point cloud as PLY; machine readable `result.json` and a Markdown report | Not established, no ground truth supplied |
| Video | Implemented with limitations | Any camera producing MP4, MOV, or M4V | Laptop with Python 3.12, FFmpeg and FFprobe | Stream manifest; evenly sampled, hashed and quality-screened frames; contact sheet | Capture-quality evidence only; metric geometry is the LiDAR product |
| Photo | Implemented with limitations | Any camera producing JPEG, PNG, TIFF, BMP, or WebP | Any Windows, Linux, or macOS laptop with Python 3.12 | Manifest, hashes, resolution/exposure/sharpness/clipping checks, duplicate detection and contact sheet | Capture-quality evidence only; metric geometry is the LiDAR product |

An iPhone without LiDAR can feed the media-ingestion tiers, but those tiers do not produce metric geometry or a floor plan.

## Capture device requirements

| Requirement | Value |
|---|---|
| Sensor | LiDAR, required. Present on Pro class iPhones from iPhone 12 Pro onward |
| App | Stray Scanner, iOS |
| App version | **TO BE CONFIRMED:** record the exact Stray Scanner version and build on the day of capture. No version can be verified from this repository |
| Device model and iOS version | **TO BE CONFIRMED:** record the iPhone model and iOS version used on the day |
| Recorded resolution | Depth and confidence at 256 x 192, RGB at 1920 x 1440 HEVC |
| Storage | About 2.4 MB per second of recording, measured across the three supplied captures |
| Network during capture | None |

## Processing environment

| Requirement | Value |
|---|---|
| Runtime | Python 3.12 |
| Runtime dependencies | NumPy, Pillow, Pydantic; FFmpeg and FFprobe for video evidence |
| Compute | CPU only. No GPU |
| Network | None. Fully offline. No cloud account, no API key |
| Command | `python -m cozmo_scan ingest <media> --tier photo|video --output <dir> --evidence`; `python -m cozmo_scan run <capture.zip> --output <dir> --profile fast` for LiDAR geometry |
| Observed runtime | All three supplied captures process in about 10 seconds in total on an Apple silicon laptop under the `fast` profile |

## Accuracy

No accuracy figure is published for any tier. No survey, tape or laser ground truth was supplied with the three captures, so absolute accuracy has not been established for any measurement, any opening width or any drift correction arm. The evaluator exists and scores against an independently supplied ground truth manifest, but no such manifest has been supplied. Numbers in the reports are internal geometric estimates with their supporting evidence attached, not accuracy claims.

Two coverage facts are worth reading alongside any measurement:

- a wall whose top was never scanned is flagged `height_is_coverage_limited`, and on two of the three supplied captures every wall carries that flag;
- an empty opening list means no candidate passed the evidence gates, not that the room has no doors or windows.

## Current scope boundaries

- metric reconstruction and measured plans use LiDAR input;
- manually anchored rigid stitching is a prototype; there is no automatic property-wide registration or loop closure;
- visual damage screening is experimental and not validated as structural diagnosis;
- no concealed condition flags;
- no repair quantity generation; the prototype produces an inspection scope only;
- no calibrated interval coverage. Bootstrap *precision* intervals include opening widths only when enough resamples reproduce the same opening;
- no established accuracy figure.

## Facts to confirm on the day

| Fact | How to confirm |
|---|---|
| Stray Scanner version and build | Read it from the App Store listing or from inside the app before capturing, and record it with the capture |
| iPhone model and iOS version | Settings, General, About. The model must be a LiDAR equipped Pro class iPhone, iPhone 12 Pro or later |
| Ground truth for any room measured at the defense | Measure the room independently with a tape or laser and record the numbers, otherwise accuracy stays unestablished |
