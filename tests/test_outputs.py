"""Tests for CP03 reconstruction artifact writers."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from cozmo_scan.floorplan import analyze_structure
from cozmo_scan.models import (
    FrameSelection,
    ReconstructionConfig,
    ReconstructionProfile,
    ReconstructionStatistics,
    ReconstructionSummary,
    RunResult,
)
from cozmo_scan.outputs import (
    OutputError,
    render_topdown,
    write_measurement_outputs,
    write_ply,
    write_reconstruction_outputs,
    write_run_outputs,
)
from cozmo_scan.reconstruction import ReconstructionResult
from tests.pipeline_factory import make_pipeline_execution
from tests.structure_factory import make_synthetic_room


def make_result() -> ReconstructionResult:
    points = np.asarray(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 0.0, 1.0]],
        dtype=np.float32,
    )
    trajectory = np.asarray([[0.0, 1.0, 0.0], [1.0, 1.0, 1.0]])
    config = ReconstructionConfig(
        profile=ReconstructionProfile.TEST,
        frame_selection=FrameSelection.DISTRIBUTED,
        max_frames=10,
        pixel_stride=8,
        voxel_size_m=0.08,
        minimum_confidence=1,
        minimum_depth_m=0.2,
        maximum_depth_m=5.0,
        calibration_width=1920,
        calibration_height=1440,
        fusion_batch_frames=5,
    )
    statistics = ReconstructionStatistics(
        total_matched_frames=2,
        selected_frame_count=2,
        processed_frame_count=2,
        skipped_frame_count=0,
        sampled_pixel_count=6,
        valid_point_count_before_voxel=3,
        output_point_count=3,
        bounds_min_xyz_m=(0.0, 0.0, 0.0),
        bounds_max_xyz_m=(1.0, 0.0, 1.0),
        trajectory_start_xyz_m=(0.0, 1.0, 0.0),
        trajectory_end_xyz_m=(1.0, 1.0, 1.0),
        trajectory_path_length_m=math_sqrt_two(),
        closure_proxy_m=math_sqrt_two(),
    )
    summary = ReconstructionSummary(
        status="ok",
        source="capture.zip",
        config=config,
        statistics=statistics,
        elapsed_seconds=0.1,
        artifacts={
            "point_cloud": "reconstruction.ply",
            "topdown_preview": "topdown.png",
            "summary": "reconstruction.json",
        },
    )
    return ReconstructionResult(points, trajectory, summary)


def math_sqrt_two() -> float:
    return 2.0**0.5


class ReconstructionOutputTests(unittest.TestCase):
    def test_binary_ply_contains_expected_vertex_count(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "cloud.ply"

            write_ply(destination, make_result().points_xyz_m)

            content = destination.read_bytes()
        header = content.split(b"end_header\n", maxsplit=1)[0]
        self.assertIn(b"format binary_little_endian 1.0", header)
        self.assertIn(b"element vertex 3", header)

    def test_topdown_renderer_writes_a_valid_png(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "topdown.png"
            result = make_result()

            render_topdown(
                destination,
                result.points_xyz_m,
                result.trajectory_xyz_m,
                image_size=128,
            )

            with Image.open(destination) as image:
                self.assertEqual(image.size, (128, 128))
                self.assertEqual(image.format, "PNG")

    def test_complete_output_set_and_overwrite_protection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "run"
            result = make_result()

            paths = write_reconstruction_outputs(result, destination)

            self.assertEqual(set(paths), {"point_cloud", "topdown_preview", "summary"})
            for path in paths.values():
                self.assertTrue(path.is_file())
            summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
            self.assertEqual(summary["units"], "metre")
            self.assertEqual(summary["statistics"]["output_point_count"], 3)
            with self.assertRaisesRegex(OutputError, "--overwrite"):
                write_reconstruction_outputs(result, destination)
            write_reconstruction_outputs(result, destination, overwrite=True)

    def test_measurement_output_set_and_overwrite_protection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "measurement"
            reconstruction = make_synthetic_room()
            structure = analyze_structure(reconstruction)

            paths = write_measurement_outputs(
                reconstruction,
                structure,
                destination,
            )

            self.assertEqual(
                set(paths),
                {
                    "point_cloud",
                    "topdown_preview",
                    "summary",
                    "structure_summary",
                    "floorplan_vector",
                    "floorplan_preview",
                },
            )
            for path in paths.values():
                self.assertTrue(path.is_file())
            with self.assertRaisesRegex(OutputError, "--overwrite"):
                write_measurement_outputs(reconstruction, structure, destination)

    def test_final_bundle_is_complete_valid_and_overwrite_protected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "final"
            execution = make_pipeline_execution(include_ceiling=False)

            paths = write_run_outputs(execution, destination)

            self.assertEqual(len(paths), 7)
            self.assertEqual(
                RunResult.model_validate_json(
                    paths["result"].read_text(encoding="utf-8")
                ),
                execution.result,
            )
            report = paths["report"].read_text(encoding="utf-8")
            self.assertIn("Assignment capability coverage", report)
            self.assertIn("not_implemented", report)
            self.assertIn("not certified drift", report)
            with Image.open(paths["trajectory_preview"]) as image:
                self.assertEqual(image.format, "PNG")
                self.assertEqual(image.size, (1000, 700))
            unrelated = destination / "reviewer-note.txt"
            unrelated.write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(OutputError, "--overwrite"):
                write_run_outputs(execution, destination)
            write_run_outputs(execution, destination, overwrite=True)
            self.assertEqual(unrelated.read_text(encoding="utf-8"), "keep")

    def test_failed_staged_render_publishes_no_partial_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "final"
            execution = make_pipeline_execution()

            with patch(
                "cozmo_scan.outputs.render_floorplan_png",
                side_effect=OutputError("injected render failure"),
            ):
                with self.assertRaisesRegex(OutputError, "injected"):
                    write_run_outputs(execution, destination)

            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
