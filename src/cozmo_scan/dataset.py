"""Read and validate Stray Scanner capture archives and directories."""

from __future__ import annotations

import csv
import io
import math
import zipfile
from collections.abc import Iterable, Sequence
from pathlib import Path, PurePosixPath

from PIL import Image, UnidentifiedImageError

from cozmo_scan.models import (
    CameraMatrix,
    CaptureIndex,
    CaptureInventory,
    FrameMatchResult,
    FrameRecord,
    ImageInspection,
    ImuSummary,
    IssueSeverity,
    OdometryRecord,
    ValidationIssue,
    ValidationResult,
)

CAMERA_MATRIX_FILE = "camera_matrix.csv"
ODOMETRY_FILE = "odometry.csv"
IMU_FILE = "imu.csv"
RGB_VIDEO_FILE = "rgb.mp4"
DEPTH_DIRECTORY = "depth"
CONFIDENCE_DIRECTORY = "confidence"
IMAGE_INSPECTION_COUNT = 3

ODOMETRY_REQUIRED_COLUMNS = (
    "timestamp",
    "frame",
    "x",
    "y",
    "z",
    "qx",
    "qy",
    "qz",
    "qw",
    "fx",
    "fy",
    "cx",
    "cy",
)


class CaptureError(ValueError):
    """Base exception for invalid or unreadable capture input."""


class UnsafeArchiveError(CaptureError):
    """Raised when an archive contains unsafe or ambiguous member paths."""


class CaptureSource:
    """Read-only access to either a ZIP archive or capture directory."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.kind: str
        self._archive: zipfile.ZipFile | None = None
        self._files: dict[str, Path | zipfile.ZipInfo] = {}

    def __enter__(self) -> CaptureSource:
        if not self.path.exists():
            raise CaptureError(f"Capture does not exist: {self.path}")

        if self.path.is_dir():
            self.kind = "directory"
            self._open_directory()
        elif self.path.is_file() and self.path.suffix.lower() == ".zip":
            self.kind = "zip"
            self._open_zip()
        else:
            raise CaptureError(
                f"Capture must be a .zip file or directory: {self.path}"
            )
        return self

    def __exit__(self, *_: object) -> None:
        if self._archive is not None:
            self._archive.close()
            self._archive = None

    @property
    def members(self) -> tuple[str, ...]:
        """Return normalized file member names in deterministic order."""
        return tuple(sorted(self._files))

    def size(self, member: str) -> int:
        """Return the uncompressed size of a member in bytes."""
        entry = self._entry(member)
        if isinstance(entry, zipfile.ZipInfo):
            return entry.file_size
        return entry.stat().st_size

    def read_bytes(self, member: str) -> bytes:
        """Read one member without extracting the complete capture."""
        entry = self._entry(member)
        try:
            if isinstance(entry, zipfile.ZipInfo):
                if self._archive is None:
                    raise RuntimeError("Capture archive is not open")
                return self._archive.read(entry)
            return entry.read_bytes()
        except (EOFError, KeyError, OSError, RuntimeError, zipfile.BadZipFile) as exc:
            raise CaptureError(f"Cannot read capture member: {member}") from exc

    def read_text(self, member: str) -> str:
        """Read one UTF-8 text member, accepting an optional BOM."""
        try:
            return self.read_bytes(member).decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise CaptureError(f"{member} is not valid UTF-8 text") from exc

    def _entry(self, member: str) -> Path | zipfile.ZipInfo:
        try:
            return self._files[member]
        except KeyError as exc:
            raise CaptureError(f"Capture member does not exist: {member}") from exc

    def _open_zip(self) -> None:
        try:
            archive = zipfile.ZipFile(self.path)
        except (OSError, zipfile.BadZipFile) as exc:
            raise CaptureError(f"Cannot open ZIP capture: {self.path}") from exc

        try:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                normalized = _normalize_archive_member(info.filename)
                if normalized in self._files:
                    raise UnsafeArchiveError(
                        f"ZIP contains duplicate member path: {normalized}"
                    )
                self._files[normalized] = info
        except Exception:
            archive.close()
            self._files.clear()
            raise

        if not self._files:
            archive.close()
            raise CaptureError(f"ZIP capture contains no files: {self.path}")
        self._archive = archive

    def _open_directory(self) -> None:
        root = self.path.resolve()
        for candidate in self.path.rglob("*"):
            if not candidate.is_file():
                continue
            resolved = candidate.resolve()
            if not resolved.is_relative_to(root):
                raise UnsafeArchiveError(
                    f"Capture contains a file outside its root: {candidate}"
                )
            relative = candidate.relative_to(self.path).as_posix()
            normalized = _normalize_archive_member(relative)
            if normalized in self._files:
                raise UnsafeArchiveError(
                    f"Capture contains duplicate member path: {normalized}"
                )
            self._files[normalized] = candidate

        if not self._files:
            raise CaptureError(f"Capture directory contains no files: {self.path}")


def open_capture(path: str | Path) -> CaptureSource:
    """Create a read-only capture source context manager."""
    return CaptureSource(path)


def discover_capture_root(members: Iterable[str]) -> str:
    """Find the single directory containing the required capture CSV files."""
    member_set = set(members)
    roots: set[str] = set()

    for member in member_set:
        pure_path = PurePosixPath(member)
        if pure_path.name not in {CAMERA_MATRIX_FILE, ODOMETRY_FILE}:
            continue
        parent = pure_path.parent.as_posix()
        roots.add("" if parent == "." else parent)

    complete_roots = [
        root
        for root in sorted(roots)
        if _join_member(root, CAMERA_MATRIX_FILE) in member_set
        and _join_member(root, ODOMETRY_FILE) in member_set
    ]

    if len(complete_roots) == 1:
        return complete_roots[0]
    if len(complete_roots) > 1:
        joined = ", ".join(root or "<capture root>" for root in complete_roots)
        raise CaptureError(f"Multiple capture roots found: {joined}")
    if len(roots) == 1:
        return next(iter(roots))
    if not roots:
        raise CaptureError(
            "Could not find camera_matrix.csv or odometry.csv in the capture"
        )
    joined = ", ".join(root or "<capture root>" for root in sorted(roots))
    raise CaptureError(f"Multiple incomplete capture roots found: {joined}")


def read_camera_matrix(source: CaptureSource, member: str) -> CameraMatrix:
    """Parse and validate a 3 x 3 camera calibration matrix."""
    rows = [
        row
        for row in csv.reader(io.StringIO(source.read_text(member)))
        if any(value.strip() for value in row)
    ]
    if len(rows) != 3 or any(len(row) != 3 for row in rows):
        raise CaptureError(f"{member} must contain exactly three rows of three values")

    parsed: list[tuple[float, float, float]] = []
    for row_index, row in enumerate(rows, start=1):
        values = tuple(
            _parse_finite(value, f"{member} row {row_index}") for value in row
        )
        parsed.append(values)  # type: ignore[arg-type]

    matrix = CameraMatrix(rows=(parsed[0], parsed[1], parsed[2]))
    if matrix.fx <= 0 or matrix.fy <= 0:
        raise CaptureError(f"{member} must contain positive fx and fy values")
    if not (
        math.isclose(matrix.rows[2][0], 0.0, abs_tol=1e-6)
        and math.isclose(matrix.rows[2][1], 0.0, abs_tol=1e-6)
        and math.isclose(matrix.rows[2][2], 1.0, abs_tol=1e-6)
    ):
        raise CaptureError(f"{member} has an invalid final calibration row")
    return matrix


def read_odometry(source: CaptureSource, member: str) -> tuple[OdometryRecord, ...]:
    """Parse the observed Stray Scanner odometry CSV format by header name."""
    reader = csv.reader(io.StringIO(source.read_text(member)), skipinitialspace=True)
    try:
        raw_header = next(reader)
    except StopIteration as exc:
        raise CaptureError(f"{member} is empty") from exc

    header = [column.strip() for column in raw_header]
    missing_columns = [
        column for column in ODOMETRY_REQUIRED_COLUMNS if column not in header
    ]
    if missing_columns:
        raise CaptureError(
            f"{member} is missing columns: {', '.join(missing_columns)}"
        )

    index = {column: position for position, column in enumerate(header)}
    records: list[OdometryRecord] = []
    seen_frames: set[str] = set()

    for row_number, row in enumerate(reader, start=2):
        if not any(value.strip() for value in row):
            continue
        if len(row) < len(header):
            row.extend([""] * (len(header) - len(row)))

        def value(column: str) -> str:
            return row[index[column]].strip()

        frame_id = _canonical_frame_id(value("frame"), f"{member} row {row_number}")
        if frame_id in seen_frames:
            raise CaptureError(
                f"{member} contains duplicate frame ID {frame_id} at row {row_number}"
            )
        seen_frames.add(frame_id)

        distortion_x = _optional_value(row, index, "distortion_center_x")
        distortion_y = _optional_value(row, index, "distortion_center_y")
        if (distortion_x is None) != (distortion_y is None):
            raise CaptureError(
                f"{member} row {row_number} has only one distortion-centre value"
            )
        distortion = (
            None
            if distortion_x is None
            else (
                _parse_finite(distortion_x, f"{member} row {row_number}"),
                _parse_finite(distortion_y or "", f"{member} row {row_number}"),
            )
        )

        intrinsics = tuple(
            _parse_finite(value(column), f"{member} row {row_number}")
            for column in ("fx", "fy", "cx", "cy")
        )
        if intrinsics[0] <= 0 or intrinsics[1] <= 0:
            raise CaptureError(
                f"{member} row {row_number} must contain positive fx and fy"
            )

        quaternion = tuple(
            _parse_finite(value(column), f"{member} row {row_number}")
            for column in ("qx", "qy", "qz", "qw")
        )
        if math.sqrt(sum(component * component for component in quaternion)) < 1e-8:
            raise CaptureError(f"{member} row {row_number} has a zero quaternion")

        records.append(
            OdometryRecord(
                timestamp=_parse_finite(
                    value("timestamp"), f"{member} row {row_number}"
                ),
                frame_id=frame_id,
                position_xyz_m=tuple(
                    _parse_finite(value(column), f"{member} row {row_number}")
                    for column in ("x", "y", "z")
                ),
                quaternion_xyzw=quaternion,
                intrinsics_fx_fy_cx_cy=intrinsics,
                distortion_center_xy=distortion,
            )
        )

    if not records:
        raise CaptureError(f"{member} contains no odometry records")
    return tuple(records)


def read_imu_summary(source: CaptureSource, member: str) -> ImuSummary:
    """Validate the optional IMU header and summarize its timestamps."""
    reader = csv.reader(io.StringIO(source.read_text(member)), skipinitialspace=True)
    try:
        header = [column.strip() for column in next(reader)]
    except StopIteration as exc:
        raise CaptureError(f"{member} is empty") from exc
    if "timestamp" not in header:
        raise CaptureError(f"{member} is missing the timestamp column")

    timestamp_index = header.index("timestamp")
    timestamps: list[float] = []
    for row_number, row in enumerate(reader, start=2):
        if not any(value.strip() for value in row):
            continue
        if timestamp_index >= len(row):
            raise CaptureError(f"{member} row {row_number} has no timestamp")
        timestamps.append(
            _parse_finite(row[timestamp_index], f"{member} row {row_number}")
        )

    return ImuSummary(
        record_count=len(timestamps),
        first_timestamp=min(timestamps) if timestamps else None,
        last_timestamp=max(timestamps) if timestamps else None,
    )


def inspect_image(source: CaptureSource, member: str) -> ImageInspection:
    """Decode one image and return the properties needed for validation."""
    try:
        with Image.open(io.BytesIO(source.read_bytes(member))) as image:
            image.load()
            if image.format != "PNG":
                raise CaptureError(f"{member} is not a PNG image")
            extrema = image.getextrema()
            if isinstance(extrema[0], tuple):
                flattened = [value for pair in extrema for value in pair]
                minimum, maximum = min(flattened), max(flattened)
            else:
                minimum, maximum = extrema
            return ImageInspection(
                member=member,
                width=image.width,
                height=image.height,
                mode=image.mode,
                minimum=minimum,
                maximum=maximum,
            )
    except (OSError, UnidentifiedImageError) as exc:
        raise CaptureError(f"Cannot decode PNG image: {member}") from exc


def match_frames(
    depth_paths: dict[str, str],
    confidence_paths: dict[str, str],
    odometry: Sequence[OdometryRecord],
) -> FrameMatchResult:
    """Match depth, confidence, and odometry records by canonical frame ID."""
    poses = {record.frame_id: record for record in odometry}
    all_ids = set(depth_paths) | set(confidence_paths) | set(poses)
    common_ids = set(depth_paths) & set(confidence_paths) & set(poses)

    frames = tuple(
        FrameRecord(
            frame_id=frame_id,
            depth_path=depth_paths[frame_id],
            confidence_path=confidence_paths[frame_id],
            odometry=poses[frame_id],
        )
        for frame_id in sorted(common_ids, key=int)
    )
    return FrameMatchResult(
        frames=frames,
        missing_depth_ids=tuple(sorted(all_ids - set(depth_paths), key=int)),
        missing_confidence_ids=tuple(
            sorted(all_ids - set(confidence_paths), key=int)
        ),
        missing_odometry_ids=tuple(sorted(all_ids - set(poses), key=int)),
    )


def select_keyframes(
    frames: Sequence[FrameRecord],
    *,
    stride: int = 1,
    max_frames: int | None = None,
) -> tuple[FrameRecord, ...]:
    """Select deterministic, capture-spanning keyframes."""
    if stride < 1:
        raise ValueError("stride must be at least 1")
    if max_frames is not None and max_frames < 1:
        raise ValueError("max_frames must be at least 1")

    ordered = tuple(sorted(frames, key=lambda frame: int(frame.frame_id)))
    candidates = ordered[::stride]
    if max_frames is None or len(candidates) <= max_frames:
        return candidates
    if max_frames == 1:
        return (candidates[0],)

    final_index = len(candidates) - 1
    selected_indices = tuple(
        round(position * final_index / (max_frames - 1))
        for position in range(max_frames)
    )
    return tuple(candidates[index] for index in selected_indices)


def build_capture_index(source: CaptureSource) -> CaptureIndex:
    """Build the validated calibration/frame index used by reconstruction."""
    capture_root = discover_capture_root(source.members)
    members = set(source.members)
    camera_member = _join_member(capture_root, CAMERA_MATRIX_FILE)
    odometry_member = _join_member(capture_root, ODOMETRY_FILE)
    missing = [
        member
        for member in (camera_member, odometry_member)
        if member not in members
    ]
    if missing:
        raise CaptureError(f"Missing required files: {', '.join(missing)}")

    camera_matrix = read_camera_matrix(source, camera_member)
    odometry = read_odometry(source, odometry_member)
    issues: list[ValidationIssue] = []
    depth_paths = _index_frame_members(
        source, capture_root, DEPTH_DIRECTORY, issues
    )
    confidence_paths = _index_frame_members(
        source, capture_root, CONFIDENCE_DIRECTORY, issues
    )
    errors = [
        issue.message
        for issue in issues
        if issue.severity is IssueSeverity.ERROR
    ]
    if errors:
        raise CaptureError("; ".join(errors))

    matches = match_frames(depth_paths, confidence_paths, odometry)
    if not matches.frames:
        raise CaptureError("No frame has depth, confidence, and odometry together")
    return CaptureIndex(
        capture_root=capture_root,
        camera_matrix=camera_matrix,
        frames=matches.frames,
    )


def inventory_capture(
    *,
    source: CaptureSource,
    capture_root: str,
    depth_paths: dict[str, str],
    confidence_paths: dict[str, str],
    odometry: Sequence[OdometryRecord],
    matches: FrameMatchResult,
    imu_summary: ImuSummary | None,
    depth_inspections: Sequence[ImageInspection],
    confidence_inspections: Sequence[ImageInspection],
) -> CaptureInventory:
    """Build a compact capture inventory from parsed components."""
    members = set(source.members)
    rgb_member = _join_member(capture_root, RGB_VIDEO_FILE)
    timestamps = [record.timestamp for record in odometry]
    first_timestamp = min(timestamps) if timestamps else None
    last_timestamp = max(timestamps) if timestamps else None
    duration = (
        last_timestamp - first_timestamp
        if first_timestamp is not None and last_timestamp is not None
        else None
    )

    return CaptureInventory(
        source_name=source.path.name,
        source_kind=source.kind,  # type: ignore[arg-type]
        capture_root=capture_root,
        camera_matrix_present=_join_member(capture_root, CAMERA_MATRIX_FILE)
        in members,
        odometry_present=_join_member(capture_root, ODOMETRY_FILE) in members,
        imu_present=_join_member(capture_root, IMU_FILE) in members,
        rgb_video_present=rgb_member in members,
        rgb_video_bytes=source.size(rgb_member) if rgb_member in members else None,
        depth_frame_count=len(depth_paths),
        confidence_frame_count=len(confidence_paths),
        odometry_record_count=len(odometry),
        matched_frame_count=len(matches.frames),
        missing_depth_count=len(matches.missing_depth_ids),
        missing_confidence_count=len(matches.missing_confidence_ids),
        missing_odometry_count=len(matches.missing_odometry_ids),
        imu_record_count=imu_summary.record_count if imu_summary else None,
        first_timestamp=first_timestamp,
        last_timestamp=last_timestamp,
        duration_seconds=duration,
        image_pairs_inspected=min(
            len(depth_inspections), len(confidence_inspections)
        ),
        depth_image_size=_common_size(depth_inspections),
        confidence_image_size=_common_size(confidence_inspections),
        depth_modes=tuple(sorted({item.mode for item in depth_inspections})),
        confidence_modes=tuple(
            sorted({item.mode for item in confidence_inspections})
        ),
    )


def validate_capture(path: str | Path) -> ValidationResult:
    """Validate a capture and return structured evidence without extracting it."""
    source_path = Path(path)
    issues: list[ValidationIssue] = []

    try:
        with open_capture(source_path) as source:
            capture_root = discover_capture_root(source.members)
            members = set(source.members)
            camera_member = _join_member(capture_root, CAMERA_MATRIX_FILE)
            odometry_member = _join_member(capture_root, ODOMETRY_FILE)
            imu_member = _join_member(capture_root, IMU_FILE)
            rgb_member = _join_member(capture_root, RGB_VIDEO_FILE)

            for required_member in (camera_member, odometry_member):
                if required_member not in members:
                    _add_issue(
                        issues,
                        IssueSeverity.ERROR,
                        "missing_required_file",
                        f"Missing required file: {required_member}",
                    )
                elif source.size(required_member) == 0:
                    _add_issue(
                        issues,
                        IssueSeverity.ERROR,
                        "empty_required_file",
                        f"Required file is empty: {required_member}",
                    )

            camera_matrix: CameraMatrix | None = None
            odometry: tuple[OdometryRecord, ...] = ()
            if camera_member in members and source.size(camera_member) > 0:
                try:
                    camera_matrix = read_camera_matrix(source, camera_member)
                except CaptureError as exc:
                    _add_issue(
                        issues,
                        IssueSeverity.ERROR,
                        "invalid_camera_matrix",
                        str(exc),
                    )
            if odometry_member in members and source.size(odometry_member) > 0:
                try:
                    odometry = read_odometry(source, odometry_member)
                except CaptureError as exc:
                    _add_issue(
                        issues,
                        IssueSeverity.ERROR,
                        "invalid_odometry",
                        str(exc),
                    )

            depth_paths = _index_frame_members(
                source, capture_root, DEPTH_DIRECTORY, issues
            )
            confidence_paths = _index_frame_members(
                source, capture_root, CONFIDENCE_DIRECTORY, issues
            )
            if not depth_paths:
                _add_issue(
                    issues,
                    IssueSeverity.ERROR,
                    "missing_depth_frames",
                    "Capture contains no valid depth PNG frames",
                )
            if not confidence_paths:
                _add_issue(
                    issues,
                    IssueSeverity.ERROR,
                    "missing_confidence_frames",
                    "Capture contains no valid confidence PNG frames",
                )

            matches = match_frames(depth_paths, confidence_paths, odometry)
            _add_match_issues(issues, matches)
            if not matches.frames:
                _add_issue(
                    issues,
                    IssueSeverity.ERROR,
                    "no_matched_frames",
                    "No frame has depth, confidence, and odometry together",
                )

            _add_odometry_quality_issues(issues, odometry)

            imu_summary: ImuSummary | None = None
            if imu_member not in members:
                _add_issue(
                    issues,
                    IssueSeverity.WARNING,
                    "imu_missing",
                    "Optional imu.csv is missing",
                )
            else:
                try:
                    imu_summary = read_imu_summary(source, imu_member)
                except CaptureError as exc:
                    _add_issue(
                        issues,
                        IssueSeverity.WARNING,
                        "invalid_imu",
                        str(exc),
                    )

            if rgb_member not in members:
                _add_issue(
                    issues,
                    IssueSeverity.WARNING,
                    "rgb_video_missing",
                    "Optional rgb.mp4 is missing",
                )
            elif source.size(rgb_member) == 0:
                _add_issue(
                    issues,
                    IssueSeverity.WARNING,
                    "rgb_video_empty",
                    "Optional rgb.mp4 is empty",
                )

            depth_inspections: list[ImageInspection] = []
            confidence_inspections: list[ImageInspection] = []
            for frame in _representative_frames(matches.frames):
                try:
                    depth = inspect_image(source, frame.depth_path)
                    confidence = inspect_image(source, frame.confidence_path)
                except CaptureError as exc:
                    _add_issue(
                        issues,
                        IssueSeverity.ERROR,
                        "invalid_frame_image",
                        str(exc),
                    )
                    continue
                depth_inspections.append(depth)
                confidence_inspections.append(confidence)

            _add_image_quality_issues(
                issues, depth_inspections, confidence_inspections
            )

            inventory = inventory_capture(
                source=source,
                capture_root=capture_root,
                depth_paths=depth_paths,
                confidence_paths=confidence_paths,
                odometry=odometry,
                matches=matches,
                imu_summary=imu_summary,
                depth_inspections=depth_inspections,
                confidence_inspections=confidence_inspections,
            )
            valid = not any(
                issue.severity is IssueSeverity.ERROR for issue in issues
            )
            return ValidationResult(
                source=str(source_path),
                valid=valid,
                inventory=inventory,
                camera_matrix=camera_matrix,
                issues=tuple(issues),
            )
    except CaptureError as exc:
        _add_issue(
            issues,
            IssueSeverity.ERROR,
            "capture_open_failed",
            str(exc),
        )
        return ValidationResult(
            source=str(source_path),
            valid=False,
            issues=tuple(issues),
        )


def _normalize_archive_member(name: str) -> str:
    normalized_slashes = name.replace("\\", "/")
    if normalized_slashes.startswith("/"):
        raise UnsafeArchiveError(f"ZIP contains an absolute member path: {name}")

    path = PurePosixPath(normalized_slashes)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise UnsafeArchiveError(f"ZIP contains an unsafe member path: {name}")
    if path.parts and ":" in path.parts[0]:
        raise UnsafeArchiveError(f"ZIP contains a drive-qualified member path: {name}")
    return path.as_posix()


def _join_member(root: str, relative: str) -> str:
    return f"{root}/{relative}" if root else relative


def _canonical_frame_id(value: str, context: str) -> str:
    stripped = value.strip()
    if not stripped.isdigit():
        raise CaptureError(f"{context} contains invalid frame ID: {value!r}")
    return f"{int(stripped):06d}"


def _parse_finite(value: str, context: str) -> float:
    try:
        number = float(value.strip())
    except ValueError as exc:
        raise CaptureError(f"{context} contains a non-numeric value: {value!r}") from exc
    if not math.isfinite(number):
        raise CaptureError(f"{context} contains a non-finite value: {value!r}")
    return number


def _optional_value(row: Sequence[str], index: dict[str, int], column: str) -> str | None:
    position = index.get(column)
    if position is None or position >= len(row):
        return None
    value = row[position].strip()
    return value or None


def _index_frame_members(
    source: CaptureSource,
    capture_root: str,
    directory: str,
    issues: list[ValidationIssue],
) -> dict[str, str]:
    prefix = _join_member(capture_root, f"{directory}/")
    indexed: dict[str, str] = {}
    for member in source.members:
        if not member.startswith(prefix):
            continue
        remainder = member[len(prefix) :]
        if "/" in remainder or not remainder.lower().endswith(".png"):
            continue
        try:
            frame_id = _canonical_frame_id(
                PurePosixPath(remainder).stem, f"capture member {member}"
            )
        except CaptureError as exc:
            _add_issue(
                issues,
                IssueSeverity.WARNING,
                "invalid_frame_filename",
                str(exc),
            )
            continue
        if frame_id in indexed:
            _add_issue(
                issues,
                IssueSeverity.ERROR,
                "duplicate_frame_file",
                f"Duplicate {directory} frame ID {frame_id}",
            )
            continue
        if source.size(member) == 0:
            _add_issue(
                issues,
                IssueSeverity.ERROR,
                "empty_frame_file",
                f"Frame image is empty: {member}",
            )
            continue
        indexed[frame_id] = member
    return indexed


def _representative_frames(frames: Sequence[FrameRecord]) -> tuple[FrameRecord, ...]:
    if len(frames) <= IMAGE_INSPECTION_COUNT:
        return tuple(frames)
    indices = (0, len(frames) // 2, len(frames) - 1)
    return tuple(frames[index] for index in indices)


def _common_size(
    inspections: Sequence[ImageInspection],
) -> tuple[int, int] | None:
    sizes = {(item.width, item.height) for item in inspections}
    return next(iter(sizes)) if len(sizes) == 1 else None


def _add_issue(
    issues: list[ValidationIssue],
    severity: IssueSeverity,
    code: str,
    message: str,
) -> None:
    issues.append(ValidationIssue(severity=severity, code=code, message=message))


def _add_match_issues(
    issues: list[ValidationIssue], matches: FrameMatchResult
) -> None:
    categories = (
        ("depth", matches.missing_depth_ids),
        ("confidence", matches.missing_confidence_ids),
        ("odometry", matches.missing_odometry_ids),
    )
    for category, frame_ids in categories:
        if not frame_ids:
            continue
        _add_issue(
            issues,
            IssueSeverity.WARNING,
            f"frames_missing_{category}",
            f"{len(frame_ids)} frame IDs are missing {category}: "
            f"{_format_bounded_ids(frame_ids)}",
        )


def _add_odometry_quality_issues(
    issues: list[ValidationIssue], odometry: Sequence[OdometryRecord]
) -> None:
    if not odometry:
        return
    decreasing = sum(
        current.timestamp < previous.timestamp
        for previous, current in zip(odometry, odometry[1:], strict=False)
    )
    if decreasing:
        _add_issue(
            issues,
            IssueSeverity.WARNING,
            "odometry_timestamp_order",
            f"Odometry timestamps decrease {decreasing} times",
        )

    non_unit = 0
    for record in odometry:
        norm = math.sqrt(sum(value * value for value in record.quaternion_xyzw))
        if not math.isclose(norm, 1.0, abs_tol=0.05):
            non_unit += 1
    if non_unit:
        _add_issue(
            issues,
            IssueSeverity.WARNING,
            "odometry_quaternion_norm",
            f"{non_unit} odometry quaternions differ from unit length by more than 0.05",
        )


def _add_image_quality_issues(
    issues: list[ValidationIssue],
    depth: Sequence[ImageInspection],
    confidence: Sequence[ImageInspection],
) -> None:
    depth_sizes = {(item.width, item.height) for item in depth}
    confidence_sizes = {(item.width, item.height) for item in confidence}
    if len(depth_sizes) > 1:
        _add_issue(
            issues,
            IssueSeverity.ERROR,
            "inconsistent_depth_size",
            f"Inspected depth images have inconsistent sizes: {sorted(depth_sizes)}",
        )
    if len(confidence_sizes) > 1:
        _add_issue(
            issues,
            IssueSeverity.ERROR,
            "inconsistent_confidence_size",
            "Inspected confidence images have inconsistent sizes: "
            f"{sorted(confidence_sizes)}",
        )
    if depth_sizes and confidence_sizes and depth_sizes != confidence_sizes:
        _add_issue(
            issues,
            IssueSeverity.ERROR,
            "depth_confidence_size_mismatch",
            "Inspected depth and confidence images do not share one size",
        )

    invalid_depth_modes = sorted({item.mode for item in depth if not item.mode.startswith("I")})
    if invalid_depth_modes:
        _add_issue(
            issues,
            IssueSeverity.ERROR,
            "invalid_depth_mode",
            f"Depth PNGs must be integer images; observed modes: {invalid_depth_modes}",
        )
    invalid_confidence_modes = sorted(
        {item.mode for item in confidence if item.mode != "L"}
    )
    if invalid_confidence_modes:
        _add_issue(
            issues,
            IssueSeverity.ERROR,
            "invalid_confidence_mode",
            "Confidence PNGs must be 8-bit grayscale; observed modes: "
            f"{invalid_confidence_modes}",
        )
    confidence_out_of_range = [
        item for item in confidence if item.minimum < 0 or item.maximum > 2
    ]
    if confidence_out_of_range:
        _add_issue(
            issues,
            IssueSeverity.ERROR,
            "invalid_confidence_values",
            "Inspected confidence images contain values outside 0..2",
        )


def _format_bounded_ids(frame_ids: Sequence[str], limit: int = 10) -> str:
    visible = ", ".join(frame_ids[:limit])
    if len(frame_ids) > limit:
        return f"{visible}, ..."
    return visible
