"""Tests for structural planes and floor-plan measurements."""

from __future__ import annotations

import math
import tempfile
import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path

import numpy as np
from PIL import Image

from cozmo_scan.floorplan import (
    StructureError,
    analyze_structure,
    build_convex_outline,
    build_occupancy_cells,
    classify_plane,
    connected_occupancy_components,
    fit_plane_ransac,
    is_simple_polygon,
    measure_polygon,
    select_floor_outline,
    simplify_polygon,
    trace_occupancy_boundary,
)
from cozmo_scan.models import StructureConfig
from cozmo_scan.outputs import render_floorplan_png, render_floorplan_svg
from cozmo_scan.reconstruction import ReconstructionResult
from tests.structure_factory import make_synthetic_room


class PlaneTests(unittest.TestCase):
    def test_plane_classification(self) -> None:
        self.assertEqual(classify_plane(np.asarray([0.0, 1.0, 0.0])), "horizontal")
        self.assertEqual(classify_plane(np.asarray([1.0, 0.0, 0.0])), "vertical")
        self.assertEqual(classify_plane(np.asarray([1.0, 1.0, 0.0])), "other")

    def test_ransac_fits_noisy_floor_despite_outliers(self) -> None:
        generator = np.random.default_rng(3)
        x, z = np.meshgrid(np.linspace(-2, 2, 20), np.linspace(-1, 1, 12))
        floor = np.column_stack((x.ravel(), generator.normal(0, 0.003, x.size), z.ravel()))
        outliers = generator.uniform(-2, 2, (50, 3))

        fit = fit_plane_ransac(
            np.vstack((floor, outliers)),
            distance_threshold_m=0.02,
            iterations=200,
            expected_orientation="horizontal",
        )

        self.assertGreater(abs(float(fit.normal_xyz[1])), 0.99)
        self.assertLess(fit.rmse_m, 0.01)
        self.assertGreaterEqual(int(fit.inlier_mask.sum()), len(floor))

    def test_ransac_handles_slightly_tilted_floor(self) -> None:
        generator = np.random.default_rng(4)
        x, z = np.meshgrid(np.linspace(-2, 2, 25), np.linspace(-1.5, 1.5, 20))
        y = 0.04 * x + generator.normal(0.0, 0.003, x.shape)
        floor = np.column_stack((x.ravel(), y.ravel(), z.ravel()))

        fit = fit_plane_ransac(
            floor,
            distance_threshold_m=0.02,
            iterations=200,
            expected_orientation="horizontal",
        )

        expected = np.asarray([-0.04, 1.0, 0.0])
        expected /= np.linalg.norm(expected)
        self.assertGreater(abs(float(fit.normal_xyz @ expected)), 0.999)
        self.assertLess(fit.rmse_m, 0.01)


class PolygonTests(unittest.TestCase):
    def test_convex_hull_and_rectangle_measurements(self) -> None:
        rectangle = np.asarray(
            [[-2.0, -1.5], [2.0, -1.5], [2.0, 1.5], [-2.0, 1.5], [0.0, 0.0]]
        )
        angle = math.radians(23)
        rotation = np.asarray(
            [[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]]
        )
        hull = build_convex_outline(rectangle @ rotation.T)
        measured = measure_polygon(hull, supporting_cell_count=len(rectangle))

        self.assertEqual(len(hull), 4)
        self.assertAlmostEqual(measured.area_m2, 12.0, places=6)
        self.assertAlmostEqual(measured.perimeter_m, 14.0, places=6)
        self.assertAlmostEqual(measured.length_m, 4.0, places=6)
        self.assertAlmostEqual(measured.width_m, 3.0, places=6)
        self.assertEqual(measured.convex_fill_ratio, 1.0)

    def test_simplification_removes_nearly_collinear_vertex(self) -> None:
        polygon = np.asarray(
            [[0.0, 0.0], [1.0, 0.01], [2.0, 0.0], [2.0, 1.0], [0.0, 1.0]]
        )
        simplified = simplify_polygon(polygon, 0.02)
        self.assertEqual(len(simplified), 4)

    def test_l_shaped_occupancy_produces_simple_concave_outline(self) -> None:
        cells = {
            (x, y)
            for x in range(4)
            for y in range(4)
            if not (x >= 2 and y >= 2)
        }
        points = np.asarray(
            [(x + 0.5, y + 0.5) for x, y in sorted(cells)], dtype=np.float64
        )
        config = StructureConfig(
            boundary_grid_size_m=1.0,
            boundary_close_radius_cells=0,
            polygon_simplify_tolerance_m=0.0,
            concave_simplify_tolerance_m=0.0,
            minimum_concave_support_ratio=0.9,
            minimum_concave_support_improvement=0.05,
        )

        selected = select_floor_outline(points, config)
        measured = measure_polygon(
            selected.vertices_xy_m,
            supporting_cell_count=selected.supporting_cell_count,
            occupied_cell_area_m2=selected.occupied_cell_area_m2,
            outline_method=selected.method,
        )

        self.assertEqual(selected.method, "occupancy_concave")
        self.assertTrue(is_simple_polygon(selected.vertices_xy_m))
        self.assertEqual(len(selected.vertices_xy_m), 6)
        self.assertAlmostEqual(measured.area_m2, 12.0)
        self.assertAlmostEqual(selected.support_ratio, 1.0)

    def test_u_shaped_occupancy_preserves_deep_recess(self) -> None:
        cells = {
            (x, y)
            for x in range(5)
            for y in range(5)
            if y < 2 or x in (0, 4)
        }
        points = np.asarray(
            [(x + 0.5, y + 0.5) for x, y in sorted(cells)], dtype=np.float64
        )
        config = StructureConfig(
            boundary_grid_size_m=1.0,
            boundary_close_radius_cells=0,
            polygon_simplify_tolerance_m=0.0,
            concave_simplify_tolerance_m=0.0,
            minimum_concave_support_ratio=0.9,
            minimum_concave_support_improvement=0.1,
        )

        selected = select_floor_outline(points, config)
        measured = measure_polygon(
            selected.vertices_xy_m,
            supporting_cell_count=selected.supporting_cell_count,
            occupied_cell_area_m2=selected.occupied_cell_area_m2,
            outline_method=selected.method,
        )

        self.assertEqual(selected.method, "occupancy_concave")
        self.assertTrue(is_simple_polygon(selected.vertices_xy_m))
        self.assertAlmostEqual(measured.area_m2, 16.0)
        self.assertLess(measured.area_m2, 25.0)

    def test_disconnected_support_uses_convex_fallback(self) -> None:
        cells = {
            *((x, y) for x in range(4) for y in range(4)),
            *((x + 8, y) for x in range(3) for y in range(3)),
        }
        points = np.asarray(
            [(x + 0.5, y + 0.5) for x, y in sorted(cells)], dtype=np.float64
        )
        config = StructureConfig(
            boundary_grid_size_m=1.0,
            boundary_close_radius_cells=0,
            polygon_simplify_tolerance_m=0.0,
            minimum_component_cell_ratio=0.8,
        )

        selected = select_floor_outline(points, config)

        self.assertEqual(selected.method, "convex_hull")
        self.assertEqual(selected.connected_component_count, 2)
        self.assertIn("largest component retains", selected.fallback_reason or "")

    def test_components_and_polygon_validity_are_deterministic(self) -> None:
        cells = {(0, 0), (1, 0), (5, 5), (5, 6)}
        first = connected_occupancy_components(cells)
        second = connected_occupancy_components(set(reversed(sorted(cells))))
        outline = trace_occupancy_boundary(set(first[0]), 1.0)

        self.assertEqual(first, second)
        self.assertTrue(is_simple_polygon(outline))
        self.assertFalse(
            is_simple_polygon(
                np.asarray([[0.0, 0.0], [2.0, 2.0], [0.0, 2.0], [2.0, 0.0]])
            )
        )
        self.assertEqual(
            build_occupancy_cells(
                np.asarray([[0.5, 0.5], [1.5, 0.5], [1.5, 0.5]]), 1.0
            ),
            {(0, 0), (1, 0)},
        )


class StructurePipelineTests(unittest.TestCase):
    def test_synthetic_room_yields_floor_ceiling_walls_and_measurements(self) -> None:
        result = analyze_structure(make_synthetic_room())

        self.assertLess(result.summary.floor.rmse_m, 0.02)
        self.assertIsNotNone(result.summary.ceiling)
        self.assertAlmostEqual(result.summary.ceiling_height_m or 0.0, 2.5, delta=0.03)
        self.assertGreaterEqual(len(result.summary.walls), 4)
        self.assertAlmostEqual(result.summary.floor_plan.area_m2, 12.0, delta=1.0)
        self.assertAlmostEqual(result.summary.floor_plan.length_m, 4.0, delta=0.2)
        self.assertAlmostEqual(result.summary.floor_plan.width_m, 3.0, delta=0.2)
        self.assertIn(
            result.summary.floor_plan.outline_method,
            {"convex_hull", "occupancy_concave"},
        )
        self.assertEqual(
            result.summary.floor_plan.boundary_support_ratio,
            result.summary.floor_plan.convex_fill_ratio,
        )
        self.assertIn(
            "boundary_support_ratio", result.summary.floor_plan.model_dump()
        )

    def test_missing_ceiling_remains_null_with_warning(self) -> None:
        result = analyze_structure(make_synthetic_room(include_ceiling=False))

        self.assertIsNone(result.summary.ceiling)
        self.assertIsNone(result.summary.ceiling_height_m)
        self.assertTrue(any("No ceiling" in warning for warning in result.summary.warnings))

    def test_geometry_is_deterministic(self) -> None:
        reconstruction = make_synthetic_room()
        first = analyze_structure(reconstruction, StructureConfig(random_seed=12))
        second = analyze_structure(reconstruction, StructureConfig(random_seed=12))

        self.assertEqual(first.summary.floor_plan, second.summary.floor_plan)
        self.assertEqual(first.summary.floor, second.summary.floor)
        self.assertEqual(first.summary.ceiling, second.summary.ceiling)
        self.assertEqual(first.summary.walls, second.summary.walls)

    def test_floorplan_renderers_write_valid_files(self) -> None:
        result = analyze_structure(make_synthetic_room())
        with tempfile.TemporaryDirectory() as temporary:
            svg_path = Path(temporary) / "floorplan.svg"
            png_path = Path(temporary) / "floorplan.png"

            render_floorplan_svg(svg_path, result.summary)
            render_floorplan_png(png_path, result.summary)

            svg = svg_path.read_text(encoding="utf-8")
            self.assertIn("Measured floor plan", svg)
            self.assertIn("Convex safety fallback", svg)
            ElementTree.parse(svg_path)
            with Image.open(png_path) as image:
                self.assertEqual(image.format, "PNG")
                self.assertEqual(image.size, (1200, 800))

    def test_too_small_cloud_is_rejected(self) -> None:
        reconstruction = make_synthetic_room()
        too_small = ReconstructionResult(
            reconstruction.points_xyz_m[:5],
            reconstruction.trajectory_xyz_m,
            reconstruction.summary,
        )

        with self.assertRaisesRegex(StructureError, "too small"):
            analyze_structure(too_small)


if __name__ == "__main__":
    unittest.main()
