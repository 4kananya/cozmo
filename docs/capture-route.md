# LiDAR capture route

Use this checklist to record one room for Cozmo Scan with the stock iOS app Stray Scanner. The pipeline has no custom iPhone application. It expects Stray Scanner depth, confidence, camera-pose, and calibration files and runs locally without a cloud account.

## Before recording

- Use a LiDAR-equipped Pro-class iPhone, iPhone 12 Pro or later.
- Install Stray Scanner. Record its version, the iPhone model, and the iOS version with the capture.
- Free several gigabytes of storage. A four-minute capture can be roughly 570 MB.
- Turn on the room lights and open blinds. ARKit camera tracking degrades in poor light even though LiDAR itself does not require visible light.
- Clear a continuous walking path around the room. Ask other people to remain still and do not move furniture during recording.
- Clean the rear camera and LiDAR window. Note the locations of mirrors, glass, glossy, wet-looking, and very dark surfaces.
- Choose a visible start point. Finish at the same point facing the same direction.

## Record one room

1. Stand at the start point, 1.5 to 2 metres from a wall, holding the phone upright at chest height. Start recording and remain still for three seconds.
2. Walk the perimeter slowly in one direction, keeping the wall on the same side. Point the phone roughly square to the wall, not along it, and keep the wall-floor junction visible. Stay within about two metres of the surface.
3. Turn corners by walking around them. Do not spin, swing the phone, or make abrupt direction changes.
4. Complete a second perimeter pass with the phone tilted upward so the top of each wall and the wall-ceiling junction are visible. Without this pass, wall heights may be coverage-limited and ceiling height may remain unavailable.
5. At each open doorway, stop about 1.5 metres away and point straight through it for five seconds. Capture the threshold floor and at least one metre of space beyond it. Do not walk into the next room. Record closed doors as closed.
6. At each window, hold square to it for five seconds and tilt slowly from below the sill to above the head. Capture the surrounding wall and frame, not only the glass.
7. Return to the start point, face the original direction, remain still for three seconds, and stop. Aim for three to four minutes total.

Record a separate file for every room. Multi-room stitching is not implemented, so walking through several rooms does not create a whole-property plan.

## Difficult surfaces

- Pass mirrors at an angle and record their position. Reflections can place false points behind a wall.
- Capture glass together with its frame and surrounding wall. Transparent surfaces may look like pass-through space.
- Pass glossy, wet-looking, or dark surfaces twice from different angles. Sparse returns suppress openings rather than creating a confident measurement.
- If tracking becomes unstable, stop and hold the phone on a well-lit textured surface until it recovers.

## Export and verify

Export the capture from the installed Stray Scanner version and compress the capture folder as one ZIP. The ZIP should contain one top-level folder with:

```text
camera_matrix.csv
odometry.csv
depth/
confidence/
imu.csv       optional
rgb.mp4       optional
```

Do not rename or rearrange files inside the capture. Use a lower-case filename without spaces, copy it to the repository's ignored `sample/` directory, then run:

```powershell
python -m cozmo_scan validate sample\defense_room.zip
python -m cozmo_scan run sample\defense_room.zip `
  --output runs\defense-room `
  --profile fast
```

Validation exit code `0` means the capture is structurally usable. Exit code `2` identifies a capture or layout error. Read `runs\defense-room\report.md` first, then inspect the PNG/SVG plan and `result.json`.

The LiDAR output is a measured coverage extent with evidence and warnings. Separate photo/video inputs publish validated manifests through `cozmo-scan ingest`; the LiDAR tier publishes metric reconstruction. Multi-room stitching, damage detection, concealed-condition flags, repair scope, calibrated accuracy, and guaranteed opening detection are outside the current scope. An empty opening list means no candidate passed the evidence gates; it does not prove that the room has no openings.
