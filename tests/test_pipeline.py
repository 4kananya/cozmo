"""Tests for the final result contract and pipeline orchestration."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cozmo_scan.models import CapabilityStatus, RunResult
from cozmo_scan.pipeline import (
    CaptureHash,
    get_pipeline_config,
    hash_capture_input,
    run_pipeline,
)
from tests.pipeline_factory import make_pipeline_execution, make_validation


class ProvenanceTests(unittest.TestCase):
    def test_file_hash_matches_sha256_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            capture = Path(temporary) / "capture.zip"
            content = b"deterministic-capture-bytes"
            capture.write_bytes(content)

            result = hash_capture_input(capture)

        self.assertEqual(result.sha256, hashlib.sha256(content).hexdigest())
        self.assertEqual(result.hash_kind, "file_bytes")
        self.assertEqual(result.byte_count, len(content))

    def test_directory_hash_is_content_and_name_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "first"
            second = Path(temporary) / "second"
            first.mkdir()
            second.mkdir()
            (first / "b.txt").write_bytes(b"two")
            (first / "a.txt").write_bytes(b"one")
            (second / "a.txt").write_bytes(b"one")
            (second / "b.txt").write_bytes(b"two")

            first_hash = hash_capture_input(first)
            second_hash = hash_capture_input(second)
            (second / "b.txt").write_bytes(b"changed")
            changed_hash = hash_capture_input(second)

        self.assertEqual(first_hash.sha256, second_hash.sha256)
        self.assertNotEqual(first_hash.sha256, changed_hash.sha256)
        self.assertEqual(first_hash.hash_kind, "canonical_directory")
        self.assertEqual(first_hash.byte_count, 6)


class FinalResultTests(unittest.TestCase):
    def test_result_round_trips_and_has_truthful_capabilities(self) -> None:
        execution = make_pipeline_execution(include_ceiling=False)

        decoded = RunResult.model_validate_json(execution.result.model_dump_json())
        capabilities = {
            item.capability: item.status for item in decoded.capabilities
        }

        self.assertEqual(decoded.schema_version, "1.4.0")
        self.assertIsNone(decoded.room.ceiling)
        self.assertIsNone(decoded.room.ceiling_height_m)
        self.assertIn(
            capabilities["opening_detection"],
            (
                CapabilityStatus.SUPPORTED_WITH_LIMITATIONS,
                CapabilityStatus.NOT_EVALUATED,
            ),
        )
        self.assertEqual(
            capabilities["metric_reconstruction"], CapabilityStatus.SUPPORTED
        )
        self.assertEqual(
            capabilities["damage_detection"], CapabilityStatus.NOT_IMPLEMENTED
        )
        self.assertEqual(
            capabilities["ground_truth_accuracy"], CapabilityStatus.NOT_EVALUATED
        )
        self.assertEqual(len(decoded.artifacts.artifacts), 7)
        for version in ("1.0.0", "1.1.0", "1.2.0", "1.3.0"):
            legacy = execution.result.model_copy(
                update={"schema_version": version}
            )
            self.assertEqual(
                RunResult.model_validate_json(legacy.model_dump_json()).schema_version,
                version,
            )

    def test_run_pipeline_composes_existing_stage_implementations(self) -> None:
        expected = make_pipeline_execution()
        config = get_pipeline_config("test")
        with (
            patch("cozmo_scan.pipeline.validate_capture", return_value=make_validation()),
            patch(
                "cozmo_scan.pipeline.hash_capture_input",
                return_value=CaptureHash("b" * 64, "file_bytes", 99),
            ),
            patch(
                "cozmo_scan.pipeline.reconstruct_capture",
                return_value=expected.reconstruction,
            ) as reconstruct,
            patch(
                "cozmo_scan.pipeline.analyze_structure",
                return_value=expected.structure,
            ) as analyze,
        ):
            actual = run_pipeline("synthetic-room.zip", config)

        reconstruct.assert_called_once_with("synthetic-room.zip", config.reconstruction)
        analyze.assert_called_once_with(expected.reconstruction, config.structure)
        self.assertEqual(actual.result.input.sha256, "b" * 64)
        self.assertNotIn("synthetic-room.zip\\", actual.result.input.name)


if __name__ == "__main__":
    unittest.main()
