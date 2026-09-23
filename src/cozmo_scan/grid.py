"""Deterministic occupancy-cell primitives shared by floor plans and openings.

These helpers live in their own module so `floorplan` and `openings` can both use
one implementation of cell quantisation, gap closing, and component labelling
without importing each other. `floorplan` re-exports them, so the CP09 public
surface is unchanged.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.floating]


def build_occupancy_cells(
    points_xy_m: FloatArray, grid_size_m: float
) -> set[tuple[int, int]]:
    """Quantize finite floor-local points to deterministic integer grid cells."""
    points = np.asarray(points_xy_m, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 2:
        raise ValueError("occupancy points must have shape (N, 2)")
    if grid_size_m <= 0:
        raise ValueError("grid_size_m must be positive")
    finite = points[np.isfinite(points).all(axis=1)]
    cells = np.floor(finite / grid_size_m).astype(np.int64)
    return {(int(cell[0]), int(cell[1])) for cell in cells}


def close_occupancy_cells(
    cells: set[tuple[int, int]], radius_cells: int
) -> set[tuple[int, int]]:
    """Close one-cell-scale gaps with square dilation followed by erosion."""
    if radius_cells < 0:
        raise ValueError("radius_cells must be non-negative")
    if not cells or radius_cells == 0:
        return set(cells)
    offsets = tuple(
        (dx, dy)
        for dx in range(-radius_cells, radius_cells + 1)
        for dy in range(-radius_cells, radius_cells + 1)
    )
    dilated = {
        (cell_x + dx, cell_y + dy)
        for cell_x, cell_y in cells
        for dx, dy in offsets
    }
    return {
        (cell_x, cell_y)
        for cell_x, cell_y in dilated
        if all((cell_x + dx, cell_y + dy) in dilated for dx, dy in offsets)
    }


def connected_occupancy_components(
    cells: set[tuple[int, int]] | frozenset[tuple[int, int]],
) -> tuple[frozenset[tuple[int, int]], ...]:
    """Return deterministic four-neighbour occupancy components, largest first."""
    remaining = set(cells)
    components: list[frozenset[tuple[int, int]]] = []
    while remaining:
        seed = min(remaining)
        remaining.remove(seed)
        component = {seed}
        pending = [seed]
        while pending:
            cell_x, cell_y = pending.pop()
            for neighbour in (
                (cell_x - 1, cell_y),
                (cell_x, cell_y - 1),
                (cell_x, cell_y + 1),
                (cell_x + 1, cell_y),
            ):
                if neighbour in remaining:
                    remaining.remove(neighbour)
                    component.add(neighbour)
                    pending.append(neighbour)
        components.append(frozenset(component))
    components.sort(key=lambda component: (-len(component), min(component)))
    return tuple(components)
