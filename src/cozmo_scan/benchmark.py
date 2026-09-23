"""Ground-truth benchmark evaluation for completed Cozmo Scan batch runs.

This module deliberately sits above the reconstruction pipeline.  It reads the
published ``result.json`` contracts and never changes geometry or derives truth
from the predictions it is evaluating.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cozmo_scan.batch import BATCH_JSON_FILENAME
from cozmo_scan.models import BatchSummary, RunResult

EVALUATION_SCHEMA_VERSION = "1.1.0"
GROUND_TRUTH_SCHEMA_VERSION = "1.0.0"
EVALUATION_JSON_FILENAME = "evaluation.json"
EVALUATION_REPORT_FILENAME = "evaluation-report.md"
COMPLIANCE_MATRIX_FILENAME = "compliance-matrix.md"
EVALUATION_FILENAMES = (
    EVALUATION_JSON_FILENAME,
    EVALUATION_REPORT_FILENAME,
    COMPLIANCE_MATRIX_FILENAME,
)


class EvaluationError(ValueError):
    """Raised when benchmark inputs or outputs are invalid or unsafe."""


class StrictModel(BaseModel):
    """Immutable benchmark model that rejects misspelled/unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class InputTier(StrEnum):
    """Capture-input tier used by the benchmark."""

    PHOTO = "photo"
    VIDEO = "video"
    LIDAR = "lidar"


class EvaluationStatus(StrEnum):
    """Outcome of one metric or benchmark check."""

    PASSED = "passed"
    FAILED = "failed"
    MISSING_PREDICTION = "missing_prediction"
    NOT_EVALUATED = "not_evaluated"


class GroundTruthWall(StrictModel):
    """One independently measured wall length."""

    wall_id: str = Field(min_length=1)
    length_m: float = Field(gt=0)


class GroundTruthOpening(StrictModel):
    """One independently measured door/window/open-transition width."""

    opening_id: str = Field(min_length=1)
    width_m: float = Field(gt=0)
    wall_id: str | None = Field(default=None, min_length=1)


class GroundTruthRoom(StrictModel):
    """Independent survey/tape/laser measurements for one physical room."""

    room_id: str = Field(min_length=1)
    floor_area_m2: float | None = Field(default=None, gt=0)
    principal_length_m: float | None = Field(default=None, gt=0)
    principal_width_m: float | None = Field(default=None, gt=0)
    ceiling_height_m: float | None = Field(default=None, gt=0)
    walls: tuple[GroundTruthWall, ...] = ()
    openings: tuple[GroundTruthOpening, ...] = ()
    notes: str | None = None

    @model_validator(mode="after")
    def validate_measurements(self) -> GroundTruthRoom:
        scalar_values = (
            self.floor_area_m2,
            self.principal_length_m,
            self.principal_width_m,
            self.ceiling_height_m,
        )
        if not any(value is not None for value in scalar_values) and not (
            self.walls or self.openings
        ):
            raise ValueError("ground-truth room must contain at least one measurement")

        wall_ids = [wall.wall_id for wall in self.walls]
        if len(wall_ids) != len(set(wall_ids)):
            raise ValueError(f"duplicate wall_id in room {self.room_id}")
        opening_ids = [opening.opening_id for opening in self.openings]
        if len(opening_ids) != len(set(opening_ids)):
            raise ValueError(f"duplicate opening_id in room {self.room_id}")
        known_walls = set(wall_ids)
        unknown_references = sorted(
            {
                opening.wall_id
                for opening in self.openings
                if opening.wall_id is not None and opening.wall_id not in known_walls
            }
        )
        if unknown_references:
            raise ValueError(
                f"openings in room {self.room_id} reference unknown walls: "
                + ", ".join(unknown_references)
            )
        return self


class GroundTruthCapture(StrictModel):
    """Mapping from one batch capture to a physical room and input tier."""

    capture_name: str = Field(min_length=1)
    room_id: str = Field(min_length=1)
    tier: InputTier
    repeatability_group: str | None = Field(default=None, min_length=1)
    expected_input_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    notes: str | None = None


class GroundTruthManifest(StrictModel):
    """Versioned benchmark truth supplied independently of Cozmo Scan."""

    schema_version: Literal["1.0.0"] = GROUND_TRUTH_SCHEMA_VERSION
    property_id: str = Field(min_length=1)
    measurement_method: str = Field(min_length=1)
    rooms: tuple[GroundTruthRoom, ...] = Field(min_length=1)
    captures: tuple[GroundTruthCapture, ...] = Field(min_length=1)
    notes: str | None = None

    @model_validator(mode="after")
    def validate_references(self) -> GroundTruthManifest:
        room_ids = [room.room_id for room in self.rooms]
        if len(room_ids) != len(set(room_ids)):
            raise ValueError("ground-truth room_id values must be unique")
        capture_names = [capture.capture_name for capture in self.captures]
        if len(capture_names) != len(set(capture_names)):
            raise ValueError("ground-truth capture_name values must be unique")
        known_rooms = set(room_ids)
        unknown_rooms = sorted(
            {
                capture.room_id
                for capture in self.captures
                if capture.room_id not in known_rooms
            }
        )
        if unknown_rooms:
            raise ValueError(
                "captures reference unknown room_id values: "
                + ", ".join(unknown_rooms)
            )
        return self


class MeasurementEvaluation(StrictModel):
    """One prediction/truth comparison and its exact evaluation gate."""

    capture_name: str
    room_id: str
    metric: str
    target_id: str | None = None
    unit: Literal["metre", "square_metre"]
    truth_value: float | None = None
    predicted_value: float | None = None
    absolute_error: float | None = Field(default=None, ge=0)
    percentage_error: float | None = Field(default=None, ge=0)
    threshold_value: float | None = Field(default=None, ge=0)
    threshold_unit: Literal["metre", "percent"] | None = None
    gate_applicable: bool
    status: EvaluationStatus
    reason: str


class CaptureEvaluation(StrictModel):
    """All benchmark comparisons for one declared capture."""

    capture_name: str
    room_id: str
    tier: InputTier
    result_available: bool
    input_sha256_matches: bool | None = None
    measurements: tuple[MeasurementEvaluation, ...]
    passed_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    missing_prediction_count: int = Field(ge=0)
    not_evaluated_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> CaptureEvaluation:
        expected = {
            EvaluationStatus.PASSED: self.passed_count,
            EvaluationStatus.FAILED: self.failed_count,
            EvaluationStatus.MISSING_PREDICTION: self.missing_prediction_count,
            EvaluationStatus.NOT_EVALUATED: self.not_evaluated_count,
        }
        for status, declared in expected.items():
            actual = sum(item.status == status for item in self.measurements)
            if actual != declared:
                raise ValueError(
                    f"capture {status.value} count does not match measurements"
                )
        return self


class RepeatabilityEvaluation(StrictModel):
    """Spread of one prediction across repeated captures of the same room."""

    repeatability_group: str
    room_id: str
    metric: str
    target_id: str | None = None
    capture_names: tuple[str, ...]
    predicted_values: tuple[float, ...] = ()
    spread_m: float | None = Field(default=None, ge=0)
    relative_spread_percent: float | None = Field(default=None, ge=0)
    threshold_description: str
    accuracy_status: EvaluationStatus
    status: EvaluationStatus
    classification: Literal[
        "accurate_and_repeatable",
        "accurate_not_repeatable",
        "biased_but_repeatable",
        "biased_and_not_repeatable",
        "incomplete",
        "not_evaluated",
    ]
    reason: str


class OpeningDetectionSummary(StrictModel):
    """Aggregate opening pass rate including misses and phantom predictions."""

    expected_count: int = Field(ge=0)
    matched_count: int = Field(ge=0)
    passed_count: int = Field(ge=0)
    missed_count: int = Field(ge=0)
    phantom_count: int = Field(ge=0)
    denominator_count: int = Field(ge=0)
    pass_rate: float | None = Field(default=None, ge=0, le=1)
    required_pass_rate: float = Field(default=0.85, ge=0, le=1)
    status: EvaluationStatus
    reason: str

    @model_validator(mode="after")
    def validate_counts(self) -> OpeningDetectionSummary:
        if self.matched_count + self.missed_count != self.expected_count:
            raise ValueError("opening matched/missed counts do not match expected count")
        if self.passed_count > self.matched_count:
            raise ValueError("opening passed count cannot exceed matched count")
        if self.denominator_count != self.expected_count + self.phantom_count:
            raise ValueError("opening denominator must include expected and phantom counts")
        if self.denominator_count == 0 and self.pass_rate is not None:
            raise ValueError("empty opening benchmark cannot have a pass rate")
        if self.denominator_count > 0:
            expected_rate = self.passed_count / self.denominator_count
            if self.pass_rate is None or abs(self.pass_rate - expected_rate) > 1e-12:
                raise ValueError("opening pass rate does not match counts")
        return self


class CalibrationSummary(StrictModel):
    """Empirical coverage for numerical confidence intervals, when published."""

    interval_count: int = Field(ge=0)
    covered_count: int = Field(ge=0)
    coverage_rate: float | None = Field(default=None, ge=0, le=1)
    status: EvaluationStatus
    reason: str


class BenchmarkEvaluation(StrictModel):
    """Complete machine-readable benchmark result."""

    schema_version: Literal["1.0.0", "1.1.0"] = EVALUATION_SCHEMA_VERSION
    product: Literal["cozmo-scan-evaluation"] = "cozmo-scan-evaluation"
    status: Literal["passed", "failed_gates", "incomplete"]
    property_id: str
    measurement_method: str
    batch_input_name: str
    ground_truth_schema_version: str
    room_count: int = Field(gt=0)
    capture_count: int = Field(ge=0)
    matched_result_count: int = Field(ge=0)
    tiers_present: tuple[InputTier, ...]
    repeatability_group_count: int = Field(ge=0)
    predicted_wall_count_across_captures: int = Field(default=0, ge=0)
    predicted_opening_count_across_captures: int = Field(default=0, ge=0)
    passed_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    missing_prediction_count: int = Field(ge=0)
    not_evaluated_count: int = Field(ge=0)
    captures: tuple[CaptureEvaluation, ...]
    repeatability: tuple[RepeatabilityEvaluation, ...]
    openings: OpeningDetectionSummary
    interval_calibration: CalibrationSummary
    warnings: tuple[str, ...] = ()
    artifacts: dict[str, str]

    @model_validator(mode="after")
    def validate_counts(self) -> BenchmarkEvaluation:
        if self.capture_count != len(self.captures):
            raise ValueError("benchmark capture count does not match captures")
        if self.matched_result_count != sum(
            capture.result_available for capture in self.captures
        ):
            raise ValueError("matched result count does not match captures")
        measurements = tuple(
            item for capture in self.captures for item in capture.measurements
        )
        expected = {
            EvaluationStatus.PASSED: self.passed_count,
            EvaluationStatus.FAILED: self.failed_count,
            EvaluationStatus.MISSING_PREDICTION: self.missing_prediction_count,
            EvaluationStatus.NOT_EVALUATED: self.not_evaluated_count,
        }
        for status, declared in expected.items():
            actual = sum(item.status == status for item in measurements)
            if actual != declared:
                raise ValueError(
                    f"benchmark {status.value} count does not match measurements"
                )
        return self


class _PredictedRoom(StrictModel):
    """Normalized prediction view; named walls/openings are intentionally empty."""

    floor_area_m2: float | None = None
    principal_length_m: float | None = None
    principal_width_m: float | None = None
    ceiling_height_m: float | None = None
    walls_m: dict[str, float] = Field(default_factory=dict)
    openings_m: dict[str, float] = Field(default_factory=dict)


def load_ground_truth(path: str | Path) -> GroundTruthManifest:
    """Load and strictly validate a ground-truth JSON manifest."""
    source = Path(path)
    if not source.is_file():
        raise EvaluationError(f"Ground-truth file does not exist: {source}")
    try:
        return GroundTruthManifest.model_validate_json(
            source.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise EvaluationError(f"Invalid ground-truth manifest: {source}: {exc}") from exc


def load_run_results(
    batch_directory: str | Path,
) -> tuple[BatchSummary, dict[str, RunResult], tuple[str, ...]]:
    """Load successful run contracts named by one validated batch summary."""
    root = Path(batch_directory)
    batch_path = root / BATCH_JSON_FILENAME
    if not batch_path.is_file():
        raise EvaluationError(f"Batch summary does not exist: {batch_path}")
    try:
        summary = BatchSummary.model_validate_json(batch_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EvaluationError(f"Invalid batch summary: {batch_path}: {exc}") from exc

    results: dict[str, RunResult] = {}
    warnings: list[str] = []
    root_resolved = root.resolve()
    seen_names: set[str] = set()
    for item in summary.items:
        if item.input_name in seen_names:
            raise EvaluationError(f"Duplicate batch input_name: {item.input_name}")
        seen_names.add(item.input_name)
        if item.status == "failed":
            warnings.append(
                f"Batch capture {item.input_name} failed and has no result: {item.error}"
            )
            continue
        result_path = (root / item.output_directory / "result.json").resolve()
        if root_resolved not in result_path.parents:
            raise EvaluationError(
                f"Unsafe result path in batch summary for {item.input_name}"
            )
        if not result_path.is_file():
            raise EvaluationError(f"Run result does not exist: {result_path}")
        try:
            result = RunResult.model_validate_json(
                result_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise EvaluationError(f"Invalid run result: {result_path}: {exc}") from exc
        if result.input.name != item.input_name:
            raise EvaluationError(
                f"Result input name {result.input.name!r} does not match "
                f"batch item {item.input_name!r}"
            )
        if item.input_sha256 != result.input.sha256:
            raise EvaluationError(
                f"Result hash does not match batch summary for {item.input_name}"
            )
        results[item.input_name] = result
    return summary, results, tuple(warnings)


def calculate_absolute_error(predicted: float, truth: float) -> float:
    """Return absolute error in the measurement's native unit."""
    return abs(float(predicted) - float(truth))


def calculate_percentage_error(predicted: float, truth: float) -> float:
    """Return absolute percentage error; ground truth must be positive."""
    if truth <= 0:
        raise ValueError("percentage error requires positive ground truth")
    return calculate_absolute_error(predicted, truth) / float(truth) * 100.0


def evaluate_interval_coverage(
    intervals: tuple[tuple[float, float, float], ...],
) -> CalibrationSummary:
    """Evaluate ``(lower, upper, truth)`` interval coverage."""
    if not intervals:
        return CalibrationSummary(
            interval_count=0,
            covered_count=0,
            coverage_rate=None,
            status=EvaluationStatus.NOT_EVALUATED,
            reason=(
                "No published precision interval could be paired with a supplied "
                "ground-truth value."
            ),
        )
    covered = 0
    for lower, upper, truth in intervals:
        if lower > upper:
            raise ValueError("confidence interval lower bound exceeds upper bound")
        covered += lower <= truth <= upper
    rate = covered / len(intervals)
    return CalibrationSummary(
        interval_count=len(intervals),
        covered_count=covered,
        coverage_rate=rate,
        status=EvaluationStatus.NOT_EVALUATED,
        reason=(
            "Coverage is reported descriptively; the benchmark does not specify "
            "a numerical interval-coverage pass threshold."
        ),
    )


def evaluate_benchmark(
    manifest: GroundTruthManifest,
    summary: BatchSummary,
    results: dict[str, RunResult],
    *,
    loader_warnings: tuple[str, ...] = (),
) -> BenchmarkEvaluation:
    """Compare batch predictions with independent truth and evaluation gates."""
    rooms = {room.room_id: room for room in manifest.rooms}
    truth_names = {capture.capture_name for capture in manifest.captures}
    warnings = list(loader_warnings)
    referenced_rooms = {capture.room_id for capture in manifest.captures}
    unreferenced_rooms = sorted(set(rooms) - referenced_rooms)
    if unreferenced_rooms:
        warnings.append(
            "Ground-truth rooms have no declared capture: "
            + ", ".join(unreferenced_rooms)
        )
    if len(manifest.rooms) < 3:
        warnings.append(
            "Benchmark protocol is incomplete: at least three rooms are required."
        )
    tiers_present = tuple(sorted({capture.tier for capture in manifest.captures}, key=str))
    missing_tiers = [tier.value for tier in InputTier if tier not in tiers_present]
    if missing_tiers:
        warnings.append(
            "Benchmark protocol is missing input tiers: " + ", ".join(missing_tiers)
        )
    tiers_by_room: dict[str, set[InputTier]] = {}
    for capture in manifest.captures:
        tiers_by_room.setdefault(capture.room_id, set()).add(capture.tier)
    if any(room_tiers != set(InputTier) for room_tiers in tiers_by_room.values()):
        warnings.append(
            "Benchmark protocol is incomplete: each room must be captured at photo, video, and LiDAR tiers."
        )
    repeatability_groups = {
        capture.repeatability_group
        for capture in manifest.captures
        if capture.repeatability_group is not None
    }
    if not repeatability_groups:
        warnings.append(
            "Benchmark protocol is incomplete: no repeated-capture group is declared."
        )
    for result_name in sorted(set(results) - truth_names):
        warnings.append(f"Batch result has no ground-truth entry: {result_name}")

    capture_evaluations: list[CaptureEvaluation] = []
    predictions: dict[str, _PredictedRoom] = {}
    for capture in manifest.captures:
        result = results.get(capture.capture_name)
        room = rooms[capture.room_id]
        if result is None:
            warnings.append(
                f"Ground-truth capture has no successful batch result: {capture.capture_name}"
            )
        prediction = _prediction_from_result(result) if result is not None else _PredictedRoom()
        predictions[capture.capture_name] = prediction
        measurements = _evaluate_capture_measurements(capture, room, prediction)
        hash_matches = None
        if result is not None and capture.expected_input_sha256 is not None:
            hash_matches = result.input.sha256 == capture.expected_input_sha256
            if not hash_matches:
                raise EvaluationError(
                    "Input SHA-256 does not match truth manifest for "
                    f"{capture.capture_name}; refusing to score the wrong capture"
                )
        capture_evaluations.append(
            CaptureEvaluation(
                capture_name=capture.capture_name,
                room_id=capture.room_id,
                tier=capture.tier,
                result_available=result is not None,
                input_sha256_matches=hash_matches,
                measurements=measurements,
                passed_count=_count_status(measurements, EvaluationStatus.PASSED),
                failed_count=_count_status(measurements, EvaluationStatus.FAILED),
                missing_prediction_count=_count_status(
                    measurements, EvaluationStatus.MISSING_PREDICTION
                ),
                not_evaluated_count=_count_status(
                    measurements, EvaluationStatus.NOT_EVALUATED
                ),
            )
        )

    all_measurements = tuple(
        measurement
        for capture in capture_evaluations
        for measurement in capture.measurements
    )
    repeatability = _evaluate_repeatability(
        manifest, rooms, predictions, tuple(capture_evaluations)
    )
    openings = _summarize_openings(all_measurements)
    intervals = evaluate_interval_coverage(
        _published_interval_coverage(manifest, rooms, results)
    )

    gate_failure = any(
        measurement.status == EvaluationStatus.FAILED
        or (
            measurement.status == EvaluationStatus.MISSING_PREDICTION
            and measurement.gate_applicable
        )
        for measurement in all_measurements
    ) or any(check.status == EvaluationStatus.FAILED for check in repeatability)
    incomplete = any(
        measurement.status
        in (EvaluationStatus.MISSING_PREDICTION, EvaluationStatus.NOT_EVALUATED)
        for measurement in all_measurements
    ) or any(
        check.status
        in (EvaluationStatus.MISSING_PREDICTION, EvaluationStatus.NOT_EVALUATED)
        for check in repeatability
    )
    status: Literal["passed", "failed_gates", "incomplete"] = (
        "failed_gates" if gate_failure else "incomplete" if incomplete else "passed"
    )
    return BenchmarkEvaluation(
        status=status,
        property_id=manifest.property_id,
        measurement_method=manifest.measurement_method,
        batch_input_name=summary.input_name,
        ground_truth_schema_version=manifest.schema_version,
        room_count=len(manifest.rooms),
        capture_count=len(manifest.captures),
        matched_result_count=sum(
            capture.result_available for capture in capture_evaluations
        ),
        tiers_present=tiers_present,
        repeatability_group_count=len(repeatability_groups),
        predicted_wall_count_across_captures=sum(
            len(prediction.walls_m) for prediction in predictions.values()
        ),
        predicted_opening_count_across_captures=sum(
            len(prediction.openings_m) for prediction in predictions.values()
        ),
        passed_count=_count_status(all_measurements, EvaluationStatus.PASSED),
        failed_count=_count_status(all_measurements, EvaluationStatus.FAILED),
        missing_prediction_count=_count_status(
            all_measurements, EvaluationStatus.MISSING_PREDICTION
        ),
        not_evaluated_count=_count_status(
            all_measurements, EvaluationStatus.NOT_EVALUATED
        ),
        captures=tuple(capture_evaluations),
        repeatability=repeatability,
        openings=openings,
        interval_calibration=intervals,
        warnings=tuple(warnings),
        artifacts={
            "evaluation": EVALUATION_JSON_FILENAME,
            "report": EVALUATION_REPORT_FILENAME,
            "compliance_matrix": COMPLIANCE_MATRIX_FILENAME,
        },
    )


def run_evaluation(
    batch_directory: str | Path,
    ground_truth_path: str | Path,
) -> BenchmarkEvaluation:
    """Load benchmark inputs and return a validated evaluation contract."""
    manifest = load_ground_truth(ground_truth_path)
    summary, results, warnings = load_run_results(batch_directory)
    return evaluate_benchmark(
        manifest, summary, results, loader_warnings=warnings
    )


def write_evaluation_outputs(
    evaluation: BenchmarkEvaluation,
    output_directory: str | Path,
    *,
    overwrite: bool = False,
) -> dict[str, Path]:
    """Stage and publish the three evaluation artifacts."""
    directory = Path(output_directory)
    if directory.exists() and not directory.is_dir():
        raise EvaluationError(f"Output path is not a directory: {directory}")
    conflicts = [directory / name for name in EVALUATION_FILENAMES if (directory / name).exists()]
    if conflicts and not overwrite:
        names = ", ".join(path.name for path in conflicts)
        raise EvaluationError(
            f"Evaluation artifacts already exist ({names}); pass --overwrite to replace them"
        )
    try:
        directory.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise EvaluationError(
            f"Cannot create output parent directory: {directory.parent}"
        ) from exc

    with TemporaryDirectory(prefix=".cozmo-evaluation-stage-", dir=directory.parent) as temporary:
        staging = Path(temporary)
        try:
            (staging / EVALUATION_JSON_FILENAME).write_text(
                evaluation.model_dump_json(indent=2) + "\n", encoding="utf-8"
            )
            (staging / EVALUATION_REPORT_FILENAME).write_text(
                render_evaluation_report(evaluation), encoding="utf-8"
            )
            (staging / COMPLIANCE_MATRIX_FILENAME).write_text(
                render_compliance_matrix(evaluation), encoding="utf-8"
            )
            directory.mkdir(parents=True, exist_ok=True)
            for name in EVALUATION_FILENAMES:
                (staging / name).replace(directory / name)
        except OSError as exc:
            raise EvaluationError(
                f"Cannot publish evaluation artifacts to: {directory}"
            ) from exc
    return {
        "evaluation": directory / EVALUATION_JSON_FILENAME,
        "report": directory / EVALUATION_REPORT_FILENAME,
        "compliance_matrix": directory / COMPLIANCE_MATRIX_FILENAME,
    }


def render_evaluation_report(evaluation: BenchmarkEvaluation) -> str:
    """Render a readable benchmark report without overstating results."""
    lines = [
        "# Cozmo Scan ground-truth evaluation",
        "",
        f"- Status: **{evaluation.status.upper()}**",
        f"- Property: `{_markdown(evaluation.property_id)}`",
        f"- Ground-truth method: {_markdown(evaluation.measurement_method)}",
        f"- Batch input: `{_markdown(evaluation.batch_input_name)}`",
        f"- Declared rooms: {evaluation.room_count}",
        f"- Declared captures: {evaluation.capture_count}",
        f"- Matched results: {evaluation.matched_result_count}",
        "- Input tiers present: "
        + (", ".join(tier.value for tier in evaluation.tiers_present) or "none"),
        f"- Repeatability groups: {evaluation.repeatability_group_count}",
        f"- Passed comparisons: {evaluation.passed_count}",
        f"- Failed comparisons: {evaluation.failed_count}",
        f"- Missing predictions: {evaluation.missing_prediction_count}",
        f"- Not evaluated: {evaluation.not_evaluated_count}",
        "",
        "A successful command means the evidence was evaluated and written. It does not mean the product passed every gate.",
        "",
        "## Capture measurements",
        "",
        "| Capture | Tier | Metric | Target | Truth | Prediction | Error | Gate | Status |",
        "|---|---|---|---|---:|---:|---:|---|---|",
    ]
    for capture in evaluation.captures:
        for measurement in capture.measurements:
            error = _format_error(measurement)
            gate = _format_gate(measurement)
            lines.append(
                "| "
                + " | ".join(
                    (
                        _markdown(capture.capture_name),
                        capture.tier.value,
                        _markdown(measurement.metric),
                        _markdown(measurement.target_id or "—"),
                        _format_value(measurement.truth_value, measurement.unit),
                        _format_value(measurement.predicted_value, measurement.unit),
                        error,
                        gate,
                        measurement.status.value,
                    )
                )
                + " |"
            )

    lines.extend(["", "## Repeatability", ""])
    if not evaluation.repeatability:
        lines.append("No repeatability group contains at least two declared captures.")
    else:
        lines.extend(
            [
                "| Group | Room | Metric | Captures | Spread | Accuracy | Repeatability | Classification |",
                "|---|---|---|---:|---:|---|---|---|",
            ]
        )
        for check in evaluation.repeatability:
            spread = "not available" if check.spread_m is None else f"{check.spread_m:.4f} m"
            lines.append(
                "| "
                + " | ".join(
                    (
                        _markdown(check.repeatability_group),
                        _markdown(check.room_id),
                        _markdown(
                            check.metric
                            + (f":{check.target_id}" if check.target_id else "")
                        ),
                        str(len(check.capture_names)),
                        spread,
                        check.accuracy_status.value,
                        check.status.value,
                        check.classification,
                    )
                )
                + " |"
            )

    lines.extend(
        [
            "",
            "## Opening gate",
            "",
            f"- Status: **{evaluation.openings.status.value.upper()}**",
            f"- Expected: {evaluation.openings.expected_count}",
            f"- Matched: {evaluation.openings.matched_count}",
            f"- Passed within 0.02 m: {evaluation.openings.passed_count}",
            f"- Missed: {evaluation.openings.missed_count}",
            f"- Phantom: {evaluation.openings.phantom_count}",
            "- Pass rate: "
            + (
                "not available"
                if evaluation.openings.pass_rate is None
                else f"{evaluation.openings.pass_rate:.1%}"
            ),
            f"- Required: {evaluation.openings.required_pass_rate:.0%}",
            "",
            "## Confidence-interval calibration",
            "",
            evaluation.interval_calibration.reason,
            "",
            "## Interpretation rules",
            "",
            "- Ceiling gate: absolute error no more than 0.015 m.",
            "- Opening gate: width error no more than 0.02 m on at least 85%, with misses and phantoms counted.",
            "- Wall accuracy gate: no more than 8% for photo and 3% for video. The benchmark defines no equivalent LiDAR wall threshold.",
            "- Repeatability gate: ceiling spread no more than 0.01 m; wall spread no more than 0.01 m or 0.5%.",
            "- Floor area and principal dimensions are diagnostic because the benchmark does not define a direct pass threshold for those derived values.",
            f"- Results published {evaluation.predicted_wall_count_across_captures} identified wall segment(s) and {evaluation.predicted_opening_count_across_captures} opening prediction(s). Opening identifiers are deterministic per capture and configuration; a truth manifest must adopt them before a width can match.",
            (
                "- Published precision intervals were checked descriptively against "
                "the supplied truth; no pass threshold is invented."
                if evaluation.interval_calibration.interval_count
                else "- No published precision interval could be paired with supplied "
                "ground truth, so coverage remains not evaluated."
            ),
        ]
    )
    if evaluation.warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {_markdown(warning)}" for warning in evaluation.warnings)
    lines.append("")
    return "\n".join(lines)


def render_compliance_matrix(evaluation: BenchmarkEvaluation) -> str:
    """Render project capabilities against code, artifacts, and status.

    The file path names where the behaviour lives or would have to live, and the
    artifact names the published file that demonstrates the claim, so every row
    is traceable rather than asserted.
    """
    openings = evaluation.openings
    rows: tuple[tuple[str, str, str, str, str], ...] = (
        # requirement, file path, artifact, status, evidence / limitation
        (
            "Guided capture route",
            "`docs/capture-route.md`",
            "`docs/capture-route.md`",
            "Implemented as a stock-capture protocol",
            "Route 2. Stock Stray Scanner protocol written for a non-engineer. No iOS application and no TestFlight or dev build.",
        ),
        (
            "Device / input-tier matrix",
            "`docs/device-matrix.md`",
            "`docs/device-matrix.md`",
            "Implemented",
            "All three input paths are mapped to hardware and commands; metric geometry is the LiDAR-tier product.",
        ),
        (
            "Photo input tier",
            "`src/cozmo_scan/media.py`",
            "`media-input.json`, `contact-sheet.jpg`",
            "Implemented with limitations",
            "Images are decoded, hashed, screened for resolution, exposure, sharpness and clipping, and checked for perceptual duplicates. Metric geometry is the LiDAR-tier product.",
        ),
        (
            "Video input tier",
            "`src/cozmo_scan/media.py`",
            "`media-input.json`, sampled frames, `contact-sheet.jpg`",
            "Implemented with limitations",
            "FFprobe validates streams and FFmpeg extracts evenly distributed, hashed, quality-screened frames. This is not video-only metric geometry.",
        ),
        (
            "LiDAR tier",
            "`src/cozmo_scan/dataset.py`, `reconstruction.py`",
            "`reconstruction.ply`, `result.json`",
            "Implemented with limitations",
            "`run` and `batch` process supplied Stray Scanner depth, confidence, intrinsics and recorded poses.",
        ),
        (
            "Known-pose media reconstruction",
            "`src/cozmo_scan/photogrammetry.py`",
            "`media-reconstruction.json`, `media-reconstruction.ply`",
            "Prototype",
            "Sparse multi-view DLT uses calibrated observations and metre-scale poses with positive-depth and reprojection gates. Automatic matching and dense stereo are absent.",
        ),
        (
            "Per-room floor / wall / ceiling plan",
            "`src/cozmo_scan/floorplan.py`",
            "`result.json`, `floorplan.svg`, `floorplan.png`",
            "Implemented with limitations",
            "Floor outline, wall planes and optional ceiling are published. A sprawling outline is disclosed as a coverage extent rather than a room.",
        ),
        (
            "Openings with widths",
            "`src/cozmo_scan/openings.py`",
            "`result.json`, `floorplan.svg`",
            _opening_implementation_status(evaluation),
            f"Results published {evaluation.predicted_opening_count_across_captures} opening prediction(s); missing predictions: {openings.missed_count}; phantoms: {openings.phantom_count}. A void is published only when space is observed behind it.",
        ),
        (
            "Named wall identities",
            "`src/cozmo_scan/openings.py`",
            "`result.json`",
            _wall_identity_status(evaluation),
            f"Results published {evaluation.predicted_wall_count_across_captures} identified wall segment(s). Identifiers are per-capture deterministic, so a truth manifest must adopt them before a width can match.",
        ),
        (
            "Rendered plan",
            "`src/cozmo_scan/outputs.py`",
            "`floorplan.svg`, `floorplan.png`",
            "Implemented with limitations",
            "Vector and raster plan with dimensions, scale bar, wall direction and openings. Drawn dimension labels are capped for readability while JSON retains every edge.",
        ),
        (
            "Versioned machine-readable JSON",
            "`src/cozmo_scan/models.py`",
            "`result.json`, `batch.json`, `evaluation.json`",
            "Implemented",
            "Strict versioned Pydantic contracts at schema 1.4.0, with 1.0.0 through 1.3.0 still readable.",
        ),
        (
            "One command per capture",
            "`src/cozmo_scan/cli.py`",
            "seven-file run bundle",
            "Implemented",
            "`run`, `batch`, and `scripts/demo.py` publish validated artifacts with staged writes and overwrite protection.",
        ),
        (
            "Offline, no cloud dependency",
            "`pyproject.toml`",
            "n/a",
            "Implemented",
            "NumPy, Pillow and Pydantic only. No account, API key, service, GPU or network. Verified by an offline packaging audit.",
        ),
        (
            "Confidence interval on every measurement",
            "`src/cozmo_scan/intervals.py`",
            "`result.json`",
            _interval_implementation_status(evaluation),
            "Bootstrap **precision** intervals on floor area, perimeter, principal "
            "dimensions, ceiling height, and sufficiently reproducible opening widths: "
            "the observed points are resampled and the same estimator re-run. Explicitly "
            "not accuracy, since a systematic error would move every resample identically. "
            + _markdown_plain(evaluation.interval_calibration.reason),
        ),
        (
            "Multi-room stitching",
            "`src/cozmo_scan/stitching.py`",
            "prototype stitching JSON",
            "Prototype",
            "Manual anchors or automatic wall hypotheses initialize rigid 2D alignment; matched-wall consensus refines it. Repeated layouts, loop closure and physical validation remain unresolved.",
        ),
        (
            "Damage regions with class and metric extent",
            "`src/cozmo_scan/damage.py`",
            "experimental screening JSON",
            "Prototype; not evaluated",
            "Multi-scale local-contrast segmentation flags connected crack-like candidates for review. Optional scale produces image-plane geometry, not structural diagnosis; labelled-data validation is absent.",
        ),
        (
            "Concealed-damage flags with the rule that fired",
            "not present",
            "none",
            "Not implemented",
            "Not reliably observable from the supplied LiDAR samples.",
        ),
        (
            "Scope line items keyed to surfaces",
            "`src/cozmo_scan/damage.py`",
            "draft scope JSON",
            "Prototype; reviewer required",
            "Scaled candidates plus explicit reviewer confirmations and actions create draft quantities and optional costs. Engineering approval remains mandatory.",
        ),
        (
            "Drift accountability and on/off ablation",
            "`src/cozmo_scan/drift.py`",
            "`drift-ablation.json`, `drift-ablation.md`",
            "Implemented with limitations",
            "`ablate` always estimates a bounded plane-anchored correction and rebuilds both arms. Poses are not used as-is. Acceptance checks point count and inlier support first, then a trimmed residual. Vertical drift only.",
        ),
        (
            "Ground-truth benchmark and evaluator",
            "`src/cozmo_scan/benchmark.py`",
            "`evaluation.json`, `evaluation-report.md`",
            "Implemented; data required",
            f"Matched {evaluation.matched_result_count}/{evaluation.capture_count} declared captures. No real ground truth has been supplied, so no manifest is tracked.",
        ),
        (
            "Compliance matrix",
            "`src/cozmo_scan/benchmark.py`",
            "`compliance-matrix.md`",
            "Implemented",
            "This file. Generated from the evaluation rather than maintained by hand.",
        ),
        (
            "Fix loop: declaration, fix, before/after",
            "`docs/fix-loop-declaration.md`, `docs/fix-loop-result.md`",
            "`docs/fix-loop-result.md`",
            "Implemented",
            "Declared gate was boundary support failing at 48.5%. Declaration written before implementation; prediction exact to 0.01 percentage points; gate moved to 3 of 3 passing.",
        ),
        (
            "Technical report within 6 pages",
            "`docs/technical-report.md`",
            "`docs/technical-report.md`",
            "Implemented",
            "Architecture, tier design, drift handling, error budget, calibration analysis, fix loop and known failure modes.",
        ),
        (
            "Benchmark uses at least 3 rooms",
            "`benchmark/README.md`",
            "ground-truth manifest",
            "Declared" if evaluation.room_count >= 3 else "Not met",
            f"Manifest declares {evaluation.room_count} room(s). The physical setup must be verified independently; the evaluator cannot certify it.",
        ),
        (
            "Same rooms captured at photo, video and LiDAR tiers",
            "`benchmark/README.md`",
            "ground-truth manifest",
            _same_rooms_all_tiers(evaluation),
            "Every benchmark room must declare all three input tiers.",
        ),
        (
            "Repeated capture protocol",
            "`benchmark/README.md`",
            "ground-truth manifest",
            "Declared" if evaluation.repeatability_group_count else "Not met",
            f"Manifest declares {evaluation.repeatability_group_count} repeatability group(s).",
        ),
        (
            "Staged damage in at least 2 classes",
            "not present",
            "none",
            "Not evaluated",
            "Neither the product nor the benchmark schema predicts or scores damage classes.",
        ),
        (
            "Laser or tape ground truth",
            "`benchmark/README.md`",
            "ground-truth manifest",
            "Declared; verify independently",
            f"Manifest method: {_markdown_plain(evaluation.measurement_method)}",
        ),
        (
            "Opening widths within 2 cm on at least 85%",
            "`src/cozmo_scan/benchmark.py`",
            "`evaluation.json`",
            openings.status.value,
            _markdown_plain(openings.reason),
        ),
        (
            "Ceiling height within 1.5 cm",
            "`src/cozmo_scan/benchmark.py`",
            "`evaluation.json`",
            _metric_gate_summary(evaluation, "ceiling_height"),
            "Per-capture measurements are listed in `evaluation.json`.",
        ),
        (
            "Repeated ceiling spread within 1 cm",
            "`src/cozmo_scan/benchmark.py`",
            "`evaluation.json`",
            _repeatability_summary(evaluation, "ceiling_height"),
            "Requires at least two captures in a repeatability group.",
        ),
        (
            "Repeated walls within 1 cm or 0.5%",
            "`src/cozmo_scan/benchmark.py`",
            "`evaluation.json`",
            _repeatability_summary(evaluation, "wall_length"),
            "Requires named wall predictions across repeated captures. Identifiers are per-capture, so cross-capture matching needs a registration step that does not exist.",
        ),
        (
            "Photo wall accuracy within 8%",
            "`src/cozmo_scan/benchmark.py`",
            "`evaluation.json`",
            _tier_wall_summary(evaluation, InputTier.PHOTO),
            "Requires same-room photo results with named walls.",
        ),
        (
            "Video wall accuracy within 3%",
            "`src/cozmo_scan/benchmark.py`",
            "`evaluation.json`",
            _tier_wall_summary(evaluation, InputTier.VIDEO),
            "Requires same-room video results with named walls.",
        ),
        (
            "Photo-tier whole-property stitch within 8%",
            "not present",
            "none",
            "Not evaluated",
            "No photo-only or stitched multi-room prediction exists.",
        ),
        (
            "Head-to-head against a consumer app",
            "not present",
            "none",
            "Not evaluated",
            "No licensed identical-input competitor run and no common ground truth.",
        ),
    )
    lines = [
        "# Project capability matrix",
        "",
        "Requirement, where it lives, the artifact that evidences it, and its status. "
        "`Not evaluated` is not a pass, and `Implemented with limitations` is not a claim "
        "that an accuracy gate has been met.",
        "",
        "Paths are relative to the repository root. Artifact names without a directory are "
        "published inside a run output directory.",
        "",
        "| Requirement | File path | Artifact | Status | Evidence / limitation |",
        "|---|---|---|---|---|",
    ]
    lines.extend(
        f"| {_markdown(requirement)} | {path} | {artifact} | {_markdown(status)} | {_markdown(evidence)} |"
        for requirement, path, artifact, status, evidence in rows
    )
    lines.extend(
        [
            "",
            f"Rows: {len(rows)}. Implemented rows name the module that produces the "
            "behaviour; unbuilt rows say `not present` rather than pointing at a file "
            "that does not implement them.",
            "",
        ]
    )
    return "\n".join(lines)


def _markdown_plain(value: str) -> str:
    """Collapse a sentence for table use without wrapping it in code ticks."""
    return " ".join(str(value).split())


def _opening_implementation_status(evaluation: BenchmarkEvaluation) -> str:
    if evaluation.predicted_opening_count_across_captures:
        return "Implemented with limitations"
    if evaluation.openings.expected_count:
        return "Implemented; no candidate passed the evidence gates"
    return "Implemented; not evaluated"


def _interval_implementation_status(evaluation: BenchmarkEvaluation) -> str:
    if evaluation.interval_calibration.interval_count:
        return "Implemented with limitations; coverage measured"
    return "Implemented with limitations; no truth to measure coverage against"


def _wall_identity_status(evaluation: BenchmarkEvaluation) -> str:
    if evaluation.predicted_wall_count_across_captures:
        return "Implemented with limitations"
    return "Implemented; not evaluated"


#: Interval metric name in `result.json` mapped to the ground-truth room field
#: that it should be checked against.
_INTERVAL_TRUTH_FIELDS: dict[str, str] = {
    "floor_area_m2": "floor_area_m2",
    "principal_length_m": "principal_length_m",
    "principal_width_m": "principal_width_m",
    "ceiling_height_m": "ceiling_height_m",
}


def _published_interval_coverage(
    manifest: GroundTruthManifest,
    rooms: dict[str, GroundTruthRoom],
    results: dict[str, RunResult],
) -> tuple[tuple[float, float, float], ...]:
    """Pair every published interval with its ground-truth value, when one exists.

    Coverage is only computable where truth is supplied. A capture with intervals
    but no truth contributes nothing, which is why an empty result reports
    `not_evaluated` rather than a coverage of zero.
    """
    triples: list[tuple[float, float, float]] = []
    for capture in manifest.captures:
        result = results.get(capture.capture_name)
        if result is None:
            continue
        room = rooms.get(capture.room_id)
        if room is None:
            continue
        for interval in result.intervals:
            field = _INTERVAL_TRUTH_FIELDS.get(interval.metric)
            if field is None:
                continue
            truth = getattr(room, field, None)
            if truth is None:
                continue
            low, high = sorted((interval.low, interval.high))
            triples.append((low, high, float(truth)))
    return tuple(triples)


def _prediction_from_result(result: RunResult) -> _PredictedRoom:
    plan = result.room.floor_plan
    analysis = result.room.openings
    # Current results publish deterministic wall identifiers and measured opening
    # widths. Older results, and captures whose opening analysis is unavailable,
    # keep empty maps so truth becomes an explicit miss
    # rather than a silently absent comparison.
    walls_m: dict[str, float] = {}
    openings_m: dict[str, float] = {}
    if analysis is not None and analysis.status == "available":
        walls_m = {wall.wall_id: wall.length_m for wall in analysis.walls}
        openings_m = {
            opening.opening_id: opening.width_m for opening in analysis.openings
        }
    return _PredictedRoom(
        floor_area_m2=plan.area_m2,
        principal_length_m=plan.length_m,
        principal_width_m=plan.width_m,
        ceiling_height_m=result.room.ceiling_height_m,
        walls_m=walls_m,
        openings_m=openings_m,
    )


def _evaluate_capture_measurements(
    capture: GroundTruthCapture,
    room: GroundTruthRoom,
    prediction: _PredictedRoom,
) -> tuple[MeasurementEvaluation, ...]:
    measurements: list[MeasurementEvaluation] = []
    scalars = (
        ("floor_area", room.floor_area_m2, prediction.floor_area_m2, "square_metre"),
        ("principal_length", room.principal_length_m, prediction.principal_length_m, "metre"),
        ("principal_width", room.principal_width_m, prediction.principal_width_m, "metre"),
        ("ceiling_height", room.ceiling_height_m, prediction.ceiling_height_m, "metre"),
    )
    for metric, truth, predicted, unit in scalars:
        if truth is not None:
            measurements.append(
                evaluate_measurement(
                    capture=capture,
                    metric=metric,
                    target_id=None,
                    unit=unit,
                    truth=truth,
                    predicted=predicted,
                )
            )
    for wall in room.walls:
        measurements.append(
            evaluate_measurement(
                capture=capture,
                metric="wall_length",
                target_id=wall.wall_id,
                unit="metre",
                truth=wall.length_m,
                predicted=prediction.walls_m.get(wall.wall_id),
            )
        )
    for opening in room.openings:
        measurements.append(
            evaluate_measurement(
                capture=capture,
                metric="opening_width",
                target_id=opening.opening_id,
                unit="metre",
                truth=opening.width_m,
                predicted=prediction.openings_m.get(opening.opening_id),
            )
        )
    for opening_id, predicted in sorted(prediction.openings_m.items()):
        if opening_id not in {opening.opening_id for opening in room.openings}:
            measurements.append(
                MeasurementEvaluation(
                    capture_name=capture.capture_name,
                    room_id=capture.room_id,
                    metric="opening_width",
                    target_id=opening_id,
                    unit="metre",
                    truth_value=None,
                    predicted_value=predicted,
                    threshold_value=0.02,
                    threshold_unit="metre",
                    gate_applicable=True,
                    status=EvaluationStatus.FAILED,
                    reason="Phantom opening: prediction has no matching ground-truth opening.",
                )
            )
    return tuple(measurements)


def evaluate_measurement(
    *,
    capture: GroundTruthCapture,
    metric: str,
    target_id: str | None,
    unit: Literal["metre", "square_metre"],
    truth: float,
    predicted: float | None,
) -> MeasurementEvaluation:
    threshold_value, threshold_unit, gate_reason = _evaluation_gate(metric, capture.tier)
    gate_applicable = threshold_value is not None
    if predicted is None:
        return MeasurementEvaluation(
            capture_name=capture.capture_name,
            room_id=capture.room_id,
            metric=metric,
            target_id=target_id,
            unit=unit,
            truth_value=truth,
            threshold_value=threshold_value,
            threshold_unit=threshold_unit,
            gate_applicable=gate_applicable,
            status=EvaluationStatus.MISSING_PREDICTION,
            reason="The ground-truth measurement exists but the result has no corresponding prediction.",
        )
    absolute = calculate_absolute_error(predicted, truth)
    percentage = calculate_percentage_error(predicted, truth)
    if not gate_applicable:
        return MeasurementEvaluation(
            capture_name=capture.capture_name,
            room_id=capture.room_id,
            metric=metric,
            target_id=target_id,
            unit=unit,
            truth_value=truth,
            predicted_value=predicted,
            absolute_error=absolute,
            percentage_error=percentage,
            gate_applicable=False,
            status=EvaluationStatus.NOT_EVALUATED,
            reason=gate_reason,
        )
    compared_error = absolute if threshold_unit == "metre" else percentage
    passed = compared_error <= float(threshold_value) + 1e-12
    return MeasurementEvaluation(
        capture_name=capture.capture_name,
        room_id=capture.room_id,
        metric=metric,
        target_id=target_id,
        unit=unit,
        truth_value=truth,
        predicted_value=predicted,
        absolute_error=absolute,
        percentage_error=percentage,
        threshold_value=threshold_value,
        threshold_unit=threshold_unit,
        gate_applicable=True,
        status=EvaluationStatus.PASSED if passed else EvaluationStatus.FAILED,
        reason=(
            f"Error is {'within' if passed else 'outside'} the evaluation threshold."
        ),
    )


def _evaluation_gate(
    metric: str, tier: InputTier
) -> tuple[float | None, Literal["metre", "percent"] | None, str]:
    if metric == "ceiling_height":
        return 0.015, "metre", "Ceiling-height evaluation gate."
    if metric == "opening_width":
        return 0.02, "metre", "Opening-width evaluation gate."
    if metric == "wall_length" and tier == InputTier.PHOTO:
        return 8.0, "percent", "Photo-derived wall evaluation gate."
    if metric == "wall_length" and tier == InputTier.VIDEO:
        return 3.0, "percent", "Video-derived wall evaluation gate."
    if metric == "wall_length":
        return None, None, "The benchmark defines no direct LiDAR wall-accuracy threshold."
    return (
        None,
        None,
        "The benchmark defines no direct pass threshold for this derived metric; error is diagnostic only.",
    )


def _evaluate_repeatability(
    manifest: GroundTruthManifest,
    rooms: dict[str, GroundTruthRoom],
    predictions: dict[str, _PredictedRoom],
    captures: tuple[CaptureEvaluation, ...],
) -> tuple[RepeatabilityEvaluation, ...]:
    groups: dict[str, list[GroundTruthCapture]] = {}
    for capture in manifest.captures:
        if capture.repeatability_group is not None:
            groups.setdefault(capture.repeatability_group, []).append(capture)
    capture_evaluations = {capture.capture_name: capture for capture in captures}
    checks: list[RepeatabilityEvaluation] = []
    for group_name in sorted(groups):
        group = groups[group_name]
        if len(group) < 2:
            continue
        room_ids = {capture.room_id for capture in group}
        if len(room_ids) != 1:
            raise EvaluationError(
                f"Repeatability group {group_name} contains multiple room_id values"
            )
        room_id = group[0].room_id
        room = rooms[room_id]
        capture_names = tuple(capture.capture_name for capture in group)
        if room.ceiling_height_m is not None:
            values = tuple(
                value
                for capture in group
                if (value := predictions[capture.capture_name].ceiling_height_m)
                is not None
            )
            accuracy = _repeat_accuracy_status(
                capture_names, capture_evaluations, "ceiling_height", None
            )
            checks.append(
                _make_repeatability_check(
                    group_name=group_name,
                    room_id=room_id,
                    metric="ceiling_height",
                    target_id=None,
                    capture_names=capture_names,
                    values=values,
                    truth=room.ceiling_height_m,
                    accuracy_status=accuracy,
                    absolute_threshold_m=0.01,
                    relative_threshold_percent=None,
                )
            )
        for wall in room.walls:
            values = tuple(
                predictions[capture.capture_name].walls_m[wall.wall_id]
                for capture in group
                if wall.wall_id in predictions[capture.capture_name].walls_m
            )
            accuracy = _repeat_accuracy_status(
                capture_names, capture_evaluations, "wall_length", wall.wall_id
            )
            checks.append(
                _make_repeatability_check(
                    group_name=group_name,
                    room_id=room_id,
                    metric="wall_length",
                    target_id=wall.wall_id,
                    capture_names=capture_names,
                    values=values,
                    truth=wall.length_m,
                    accuracy_status=accuracy,
                    absolute_threshold_m=0.01,
                    relative_threshold_percent=0.5,
                )
            )
    return tuple(checks)


def _make_repeatability_check(
    *,
    group_name: str,
    room_id: str,
    metric: str,
    target_id: str | None,
    capture_names: tuple[str, ...],
    values: tuple[float, ...],
    truth: float,
    accuracy_status: EvaluationStatus,
    absolute_threshold_m: float,
    relative_threshold_percent: float | None,
) -> RepeatabilityEvaluation:
    threshold_description = f"spread <= {absolute_threshold_m:.3f} m"
    if relative_threshold_percent is not None:
        threshold_description += f" OR <= {relative_threshold_percent:.1f}% of truth"
    if len(values) != len(capture_names):
        return RepeatabilityEvaluation(
            repeatability_group=group_name,
            room_id=room_id,
            metric=metric,
            target_id=target_id,
            capture_names=capture_names,
            predicted_values=values,
            threshold_description=threshold_description,
            accuracy_status=accuracy_status,
            status=EvaluationStatus.MISSING_PREDICTION,
            classification="incomplete",
            reason="Not every repeated capture has this prediction.",
        )
    spread = max(values) - min(values)
    relative = spread / truth * 100.0
    repeatable = spread <= absolute_threshold_m + 1e-12 or (
        relative_threshold_percent is not None
        and relative <= relative_threshold_percent + 1e-12
    )
    status = EvaluationStatus.PASSED if repeatable else EvaluationStatus.FAILED
    if accuracy_status == EvaluationStatus.PASSED:
        classification = (
            "accurate_and_repeatable" if repeatable else "accurate_not_repeatable"
        )
    elif accuracy_status == EvaluationStatus.FAILED:
        classification = (
            "biased_but_repeatable" if repeatable else "biased_and_not_repeatable"
        )
    else:
        classification = "not_evaluated"
    return RepeatabilityEvaluation(
        repeatability_group=group_name,
        room_id=room_id,
        metric=metric,
        target_id=target_id,
        capture_names=capture_names,
        predicted_values=values,
        spread_m=spread,
        relative_spread_percent=relative,
        threshold_description=threshold_description,
        accuracy_status=accuracy_status,
        status=status,
        classification=classification,
        reason=f"Prediction spread is {'within' if repeatable else 'outside'} the repeatability gate.",
    )


def _repeat_accuracy_status(
    capture_names: tuple[str, ...],
    captures: dict[str, CaptureEvaluation],
    metric: str,
    target_id: str | None,
) -> EvaluationStatus:
    statuses: list[EvaluationStatus] = []
    for name in capture_names:
        match = next(
            (
                measurement
                for measurement in captures[name].measurements
                if measurement.metric == metric and measurement.target_id == target_id
            ),
            None,
        )
        if match is None:
            return EvaluationStatus.NOT_EVALUATED
        statuses.append(match.status)
    if any(status == EvaluationStatus.MISSING_PREDICTION for status in statuses):
        return EvaluationStatus.MISSING_PREDICTION
    if any(status == EvaluationStatus.FAILED for status in statuses):
        return EvaluationStatus.FAILED
    if all(status == EvaluationStatus.PASSED for status in statuses):
        return EvaluationStatus.PASSED
    return EvaluationStatus.NOT_EVALUATED


def _summarize_openings(
    measurements: tuple[MeasurementEvaluation, ...]
) -> OpeningDetectionSummary:
    openings = [measurement for measurement in measurements if measurement.metric == "opening_width"]
    expected = [measurement for measurement in openings if measurement.truth_value is not None]
    phantoms = [measurement for measurement in openings if measurement.truth_value is None]
    matched = [measurement for measurement in expected if measurement.predicted_value is not None]
    passed = [measurement for measurement in expected if measurement.status == EvaluationStatus.PASSED]
    missed = [measurement for measurement in expected if measurement.status == EvaluationStatus.MISSING_PREDICTION]
    denominator = len(expected) + len(phantoms)
    if denominator == 0:
        return OpeningDetectionSummary(
            expected_count=0,
            matched_count=0,
            passed_count=0,
            missed_count=0,
            phantom_count=0,
            denominator_count=0,
            pass_rate=None,
            status=EvaluationStatus.NOT_EVALUATED,
            reason="No ground-truth or predicted openings are available.",
        )
    rate = len(passed) / denominator
    status = EvaluationStatus.PASSED if rate >= 0.85 else EvaluationStatus.FAILED
    return OpeningDetectionSummary(
        expected_count=len(expected),
        matched_count=len(matched),
        passed_count=len(passed),
        missed_count=len(missed),
        phantom_count=len(phantoms),
        denominator_count=denominator,
        pass_rate=rate,
        status=status,
        reason=(
            f"{rate:.1%} passed the 0.02 m width gate after counting misses and phantoms; 85% is required."
        ),
    )


def _count_status(
    measurements: tuple[MeasurementEvaluation, ...], status: EvaluationStatus
) -> int:
    return sum(measurement.status == status for measurement in measurements)


def _metric_gate_summary(evaluation: BenchmarkEvaluation, metric: str) -> str:
    values = [
        measurement.status
        for capture in evaluation.captures
        for measurement in capture.measurements
        if measurement.metric == metric
    ]
    return _statuses_summary(values)


def _same_rooms_all_tiers(evaluation: BenchmarkEvaluation) -> str:
    tiers_by_room: dict[str, set[InputTier]] = {}
    for capture in evaluation.captures:
        tiers_by_room.setdefault(capture.room_id, set()).add(capture.tier)
    required = set(InputTier)
    if evaluation.room_count < 1 or len(tiers_by_room) != evaluation.room_count:
        return "Not met"
    return (
        "Declared"
        if all(room_tiers == required for room_tiers in tiers_by_room.values())
        else "Not met"
    )


def _tier_wall_summary(
    evaluation: BenchmarkEvaluation, tier: InputTier
) -> str:
    values = [
        measurement.status
        for capture in evaluation.captures
        if capture.tier == tier
        for measurement in capture.measurements
        if measurement.metric == "wall_length"
    ]
    return _statuses_summary(values)


def _repeatability_summary(evaluation: BenchmarkEvaluation, metric: str) -> str:
    values = [check.status for check in evaluation.repeatability if check.metric == metric]
    return _statuses_summary(values)


def _statuses_summary(values: list[EvaluationStatus]) -> str:
    if not values:
        return "Not evaluated"
    if any(value == EvaluationStatus.FAILED for value in values):
        return "Failed"
    if any(value == EvaluationStatus.MISSING_PREDICTION for value in values):
        return "Missing predictions"
    if any(value == EvaluationStatus.NOT_EVALUATED for value in values):
        return "Not evaluated"
    return "Passed"


def _format_value(value: float | None, unit: str) -> str:
    if value is None:
        return "not available"
    suffix = "m²" if unit == "square_metre" else "m"
    return f"{value:.4f} {suffix}"


def _format_error(measurement: MeasurementEvaluation) -> str:
    if measurement.absolute_error is None:
        return "not available"
    suffix = "m²" if measurement.unit == "square_metre" else "m"
    return f"{measurement.absolute_error:.4f} {suffix} / {measurement.percentage_error:.2f}%"


def _format_gate(measurement: MeasurementEvaluation) -> str:
    if not measurement.gate_applicable:
        return "not specified"
    suffix = "m" if measurement.threshold_unit == "metre" else "%"
    return f"<= {measurement.threshold_value:g} {suffix}"


def _markdown(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
