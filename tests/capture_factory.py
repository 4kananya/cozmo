"""Tiny on-disk capture factory shared by integration-style unit tests."""

from __future__ import annotations

import zipfile
from pathlib import Path

from PIL import Image

ODOMETRY_HEADER = (
    "timestamp, frame, x, y, z, qx, qy, qz, qw, fx, fy, cx, cy, "
    "distortion_center_x, distortion_center_y\n"
)


def create_test_capture(
    container: Path,
    *,
    root_name: str = "capture123",
    frame_ids: tuple[str, ...] = ("000000", "000001", "000002"),
    confidence_value: int | None = None,
) -> Path:
    """Create a tiny valid Stray-like capture for one test."""
    root = container / root_name
    (root / "depth").mkdir(parents=True)
    (root / "confidence").mkdir()
    (root / "camera_matrix.csv").write_text(
        "100.0,0.0,2.0\n0.0,100.0,1.5\n0.0,0.0,1.0\n",
        encoding="utf-8",
    )

    rows = [ODOMETRY_HEADER]
    for index, frame_id in enumerate(frame_ids):
        rows.append(
            f"{10.0 + index}, {frame_id}, {index}.0, 0.0, 0.0, "
            "0.0, 0.0, 0.0, 1.0, 100.0, 100.0, 2.0, 1.5, , \n"
        )
        Image.new("I;16", (4, 3), color=1000 + index).save(
            root / "depth" / f"{frame_id}.png"
        )
        confidence = index % 3 if confidence_value is None else confidence_value
        Image.new("L", (4, 3), color=confidence).save(
            root / "confidence" / f"{frame_id}.png"
        )

    (root / "odometry.csv").write_text("".join(rows), encoding="utf-8")
    (root / "imu.csv").write_text(
        "timestamp,a_x,a_y,a_z,alpha_x,alpha_y,alpha_z\n"
        "10.0,0,0,-1,0,0,0\n"
        "11.0,0,0,-1,0,0,0\n",
        encoding="utf-8",
    )
    (root / "rgb.mp4").write_bytes(b"test-video-placeholder")
    return root


def create_zip(source_directory: Path, destination: Path) -> None:
    """Store a generated capture directory in a ZIP with its root intact."""
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_STORED) as archive:
        for path in sorted(source_directory.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source_directory.parent).as_posix())
