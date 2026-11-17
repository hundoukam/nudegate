"""Experimental offline scaling of explicitly authored adult-body masks.

This module knows nothing about game characters, age, anatomy, asset paths,
rigs, or physics. Callers supply an already reviewed mesh, topology identifier,
region masks, and seam locks. Only vertex positions are returned; topology and
rig weights must be retained by the external asset-authoring workflow.
"""

from __future__ import annotations

import math
from typing import Any


def _object(value: Any, label: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _name(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")
    return value


def _sequence(value: Any, label: str) -> list | tuple:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{label} must be a list")
    return value


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite number")
    return number


def _vector(value: Any, label: str) -> tuple[float, float, float]:
    values = _sequence(value, label)
    if len(values) != 3:
        raise ValueError(f"{label} must contain exactly three coordinates")
    return tuple(_finite(item, f"{label}[{axis}]") for axis, item in enumerate(values))


def apply_morph(mesh: dict, recipe: dict) -> dict[str, Any]:
    """Apply independent masked scales against the original vertex positions.

    ``mesh`` contains ``positions``, ``regions``, ``locked_vertices``, and
    ``topology_id``. A region contains a three-coordinate ``center`` and one
    ``weights`` value per vertex. ``recipe`` contains ``id``, ``topology_id``,
    and ``region_scales`` mapping known mask names to three scales in [0.5, 2].

    The sum of weights of recipe-selected regions may not exceed one at any
    vertex, including locked vertices. Unselected masks do not contribute to
    that sum. All supplied masks are validated, including unselected ones.

    Returns ``{"positions": [...], "report": {...}}``. The inputs are never
    mutated. Locked and unmasked positions are copied exactly. No file, game,
    topology, skinning, or physics operations are performed.
    """
    _object(mesh, "mesh")
    _object(recipe, "recipe")
    topology = _name(mesh.get("topology_id"), "mesh.topology_id")
    recipe_topology = _name(recipe.get("topology_id"), "recipe.topology_id")
    if topology != recipe_topology:
        raise ValueError("Recipe topology_id does not match mesh topology_id")
    recipe_id = _name(recipe.get("id"), "recipe.id")

    raw_positions = _sequence(mesh.get("positions"), "mesh.positions")
    if not raw_positions:
        raise ValueError("mesh.positions must not be empty")
    positions = [_vector(point, f"mesh.positions[{index}]")
                 for index, point in enumerate(raw_positions)]
    vertex_count = len(positions)

    locked: set[int] = set()
    for index in _sequence(mesh.get("locked_vertices"), "mesh.locked_vertices"):
        if isinstance(index, bool) or not isinstance(index, int):
            raise ValueError("Locked vertex indices must be integers")
        if index < 0 or index >= vertex_count:
            raise ValueError(f"Locked vertex index out of bounds: {index}")
        locked.add(index)

    masks = _object(mesh.get("regions"), "mesh.regions")
    regions: dict[str, tuple[tuple[float, float, float], list[float]]] = {}
    for name, raw_region in masks.items():
        _name(name, "region name")
        region = _object(raw_region, f"mesh.regions[{name!r}]")
        center = _vector(region.get("center"), f"region {name!r} center")
        raw_weights = _sequence(region.get("weights"), f"region {name!r} weights")
        if len(raw_weights) != vertex_count:
            raise ValueError(f"Region {name!r} weights must match vertex count {vertex_count}")
        weights = [_finite(weight, f"region {name!r} weight[{index}]")
                   for index, weight in enumerate(raw_weights)]
        if any(weight < 0.0 or weight > 1.0 for weight in weights):
            raise ValueError(f"Region {name!r} weights must be within [0, 1]")
        regions[name] = (center, weights)

    raw_scales = _object(recipe.get("region_scales"), "recipe.region_scales")
    if not raw_scales:
        raise ValueError("recipe.region_scales must select at least one explicit region mask")
    scales: dict[str, tuple[float, float, float]] = {}
    for name, raw_scale in raw_scales.items():
        _name(name, "recipe region name")
        if name not in regions:
            raise ValueError(f"Unknown region mask in recipe: {name!r}")
        scale = _vector(raw_scale, f"region {name!r} scales")
        if any(axis < 0.5 or axis > 2.0 for axis in scale):
            raise ValueError(f"Region {name!r} scales must be within [0.5, 2.0]")
        scales[name] = scale

    # Stable ordering keeps recipe dictionary insertion order from affecting math.
    active_names = sorted(scales)
    for index in range(vertex_count):
        total = math.fsum(regions[name][1][index] for name in active_names)
        if total > 1.0:
            raise ValueError(f"Selected region weights overlap at vertex {index}: total {total} exceeds 1")

    result = [list(point) for point in raw_positions]
    moved_vertices = 0
    max_displacement = 0.0
    for index, original in enumerate(positions):
        if index in locked:
            continue
        delta_by_axis: list[list[float]] = [[], [], []]
        for name in active_names:
            center, weights = regions[name]
            weight = weights[index]
            if weight == 0.0:
                continue
            for axis in range(3):
                factor = (scales[name][axis] - 1.0) * weight
                if factor != 0.0:
                    delta = (original[axis] - center[axis]) * factor
                    if not math.isfinite(delta):
                        raise ValueError(f"Morph arithmetic is nonfinite at vertex {index}, axis {axis}")
                    delta_by_axis[axis].append(delta)
        try:
            delta = tuple(math.fsum(values) for values in delta_by_axis)
        except OverflowError as exc:
            raise ValueError(f"Morph arithmetic overflow at vertex {index}") from exc
        if any(component != 0.0 for component in delta):
            updated = [original[axis] + delta[axis] for axis in range(3)]
            if not all(math.isfinite(component) for component in updated):
                raise ValueError(f"Morph output is nonfinite at vertex {index}")
            displacement = math.hypot(*(updated[axis] - original[axis] for axis in range(3)))
            if not math.isfinite(displacement):
                raise ValueError(f"Morph displacement is nonfinite at vertex {index}")
            if updated != list(original):
                result[index] = updated
                moved_vertices += 1
                max_displacement = max(max_displacement, displacement)

    return {"positions": result, "report": {
        "recipe_id": recipe_id,
        "topology_id": topology,
        "vertex_count": vertex_count,
        "locked_vertices": len(locked),
        "active_regions": active_names,
        "moved_vertices": moved_vertices,
        "max_displacement": max_displacement,
    }}
