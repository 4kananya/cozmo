# Ground-truth benchmark

CP08 evaluates already-published batch results against measurements collected independently with a laser distance meter, tape, or survey process. It does not infer “truth” from the Cozmo Scan output.

Do not copy the example numbers below into a submission as if they describe the supplied scans. Measure the physical rooms, replace every fictional value, and record the method used. The repository intentionally contains no `ground-truth.json` for the three samples because no reference measurements were supplied with them.

## Manifest format

Save a JSON file such as `benchmark/ground-truth.local.json`. The repository ignores `benchmark/*.local.json`; still check Git status before committing any real property data under another name.

```json
{
  "schema_version": "1.0.0",
  "property_id": "fictional-demo-property",
  "measurement_method": "Fictional example only; replace with the real laser/tape procedure",
  "rooms": [
    {
      "room_id": "room-1",
      "floor_area_m2": 12.0,
      "principal_length_m": 4.0,
      "principal_width_m": 3.0,
      "ceiling_height_m": 2.5,
      "walls": [
        {"wall_id": "north", "length_m": 4.0},
        {"wall_id": "east", "length_m": 3.0}
      ],
      "openings": [
        {"opening_id": "door-1", "wall_id": "north", "width_m": 0.9}
      ],
      "notes": "All values in this example are fictional."
    }
  ],
  "captures": [
    {
      "capture_name": "single_room.zip",
      "room_id": "room-1",
      "tier": "lidar",
      "repeatability_group": "room-1-repeat",
      "expected_input_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    }
  ],
  "notes": "Fictional schema example, not benchmark evidence."
}
```

Rules:

- `capture_name` must exactly match `input_name` in `batch.json`, including the `.zip` suffix when present.
- `room_id`, `wall_id`, `opening_id`, and `capture_name` values must be unique in their scope.
- An opening may reference a declared wall, or set `wall_id` to `null` when the measurement protocol does not assign it to a wall.
- `expected_input_sha256` is optional but recommended. A mismatch stops evaluation so the wrong scan cannot receive a score.
- Put two or more captures of the same physical room in the same `repeatability_group`. A group containing different `room_id` values is rejected.
- Use `tier` values `photo`, `video`, or `lidar`. Do not label a LiDAR-derived result as photo/video merely to obtain a threshold.
- Omit measurements that were not independently collected. Never encode “unknown” as zero.

## Run the evaluator

First create the normal batch artifacts, then evaluate them:

```powershell
python -m cozmo_scan batch `
  "sample" `
  --output "runs\demo" `
  --profile fast

python -m cozmo_scan evaluate `
  "runs\demo" `
  --ground-truth "benchmark\ground-truth.local.json" `
  --output "runs\evaluation"
```

The evaluator writes:

- `evaluation.json`: strict machine-readable comparisons, counts, repeatability checks, warnings, and statuses;
- `evaluation-report.md`: per-capture truth/prediction/error/gate table and interpretation rules;
- `compliance-matrix.md`: the wider assignment requirements mapped to implemented, partial, missing, or unevaluated evidence.

The assignment's benchmark protocol also calls for at least three physical rooms, the same rooms captured at photo/video/LiDAR tiers, repeated captures, staged damage from at least two classes, and laser/tape reference measurements. The compliance matrix reports each condition separately. Current supplied data meets neither the all-tier nor damage-evaluation requirements; the evaluator does not hide that limitation.

Existing known files require `--overwrite`. Unrelated files in the output directory are preserved. Exit code `0` means the evaluation artifacts were created successfully, even if their product status is `failed_gates` or `incomplete`. Invalid input, a mismatched bound hash, or unsafe/missing result artifacts return exit code `2`.

## Gates encoded exactly

- ceiling-height absolute error: at most `0.015 m`;
- opening-width absolute error: at most `0.02 m` on at least `85%`, counting misses and phantom predictions;
- photo-derived named wall length: at most `8%` error;
- video-derived named wall length: at most `3%` error;
- repeated ceiling prediction spread: at most `0.01 m`;
- repeated named-wall spread: at most `0.01 m` **or** `0.5%` of independent truth.

The evaluator calculates floor-area and principal-dimension errors but marks their gates `not_evaluated`, because the assignment does not state a direct threshold for those derived values. It likewise does not invent a LiDAR wall threshold or a confidence-interval coverage threshold.

The current CP05 result schema has no stable physical wall IDs, finite wall lengths, opening predictions, or numerical confidence intervals. Ground-truth entries for those capabilities therefore expose honest `missing_prediction`/`not_evaluated` results. CP10 is the planned checkpoint that can supply named opening predictions; CP08 is ready to count matched, missed, and phantom openings when they exist.
