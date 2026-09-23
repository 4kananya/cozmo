"""Tests for the explicitly experimental visual-damage screen."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from cozmo_scan.damage import screen_damage_candidates


class DamageScreenTests(unittest.TestCase):
    def test_thin_dark_local_contrast_is_sent_for_review(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "wall.png"
            image = Image.new("RGB", (800, 600), (210, 210, 210))
            draw = ImageDraw.Draw(image)
            draw.line([(100, 80), (420, 500)], fill=(20, 20, 20), width=3)
            image.save(path)

            result = screen_damage_candidates(path)

            self.assertEqual(result["candidate_count"], 1)
            self.assertEqual(result["images"][0]["status"], "review_required")
            self.assertEqual(result["inspection_scope"]["repair_quantity_status"], "not_estimated")

    def test_blank_surface_does_not_claim_damage_absence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "wall.png"
            Image.new("RGB", (800, 600), (210, 210, 210)).save(path)

            result = screen_damage_candidates(path)

            self.assertEqual(result["candidate_count"], 0)
            self.assertIn("does not prove absence", result["inspection_scope"]["action"])


if __name__ == "__main__":
    unittest.main()
