"""Tests for the explicitly experimental visual-damage screen."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from cozmo_scan.damage import build_repair_scope, screen_damage_candidates, write_damage_screen


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

    def test_scaled_candidate_can_feed_reviewer_approved_draft_scope(self) -> None:
        import json

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image_path = root / "wall.png"
            image = Image.new("RGB", (800, 600), (210, 210, 210))
            draw = ImageDraw.Draw(image)
            draw.line([(100, 80), (420, 500)], fill=(20, 20, 20), width=3)
            image.save(image_path)
            screen = screen_damage_candidates(image_path, metres_per_pixel=0.001)
            screen_path = write_damage_screen(screen, root / "screen.json")
            decisions_path = root / "decisions.json"
            decisions_path.write_text(
                json.dumps(
                    {
                        "reviewer": "Example reviewer",
                        "decisions": [
                            {
                                "relative_path": "wall.png",
                                "confirmed": True,
                                "action": "route and seal after engineering approval",
                                "quantity_basis": "maximum_candidate_extent_m",
                                "unit_rate": 10.0,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            scope = build_repair_scope(screen_path, decisions_path)

            self.assertEqual(scope["line_item_count"], 1)
            self.assertGreater(scope["line_items"][0]["quantity"], 0)
            self.assertEqual(scope["status"], "draft_requires_engineer_approval")


if __name__ == "__main__":
    unittest.main()
