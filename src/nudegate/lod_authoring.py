"""Assemble and verify every indexed, skinned LOD in a reviewed COLLADA body.

LOD identity comes from LSLib's explicit LSTools ExportOrder metadata. No
geometry is selected by triangle count or silently omitted during authoring.
"""
from __future__ import annotations

import copy
import math
from pathlib import Path
import re
import tempfile
from typing import Callable, Any
import xml.etree.ElementTree as ET

from .collada import (ColladaMesh, _Source, _canonical, _hash, _indices,
                      _integer, _reference, _tag, validate_smooth_seams)


def _parse(path: Path) -> ET.ElementTree:
    try:
        parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True))
        tree = ET.parse(path, parser=parser)
    except (OSError, ET.ParseError) as exc:
        raise ValueError(f"Cannot read LOD document {path}: {exc}") from exc
    if tree.getroot().tag != _tag("COLLADA"):
        raise ValueError("Expected a standard-namespace COLLADA document")
    return tree


def _metadata(tree: ET.ElementTree, expected_lods: int | None) -> list[dict[str, Any]]:
    if expected_lods is not None and (isinstance(expected_lods, bool)
            or not isinstance(expected_lods, int) or expected_lods < 1):
        raise ValueError("expected_lods must be a positive integer")
    root = tree.getroot()
    geometries = root.findall(f"{_tag('library_geometries')}/{_tag('geometry')}")
    if not geometries:
        raise ValueError("LOD document contains no geometries")
    rows = []
    identifiers = set()
    for geometry in geometries:
        identifier, name = geometry.get("id"), geometry.get("name")
        if not identifier or identifier in identifiers or not name:
            raise ValueError("LOD geometries require unique IDs and explicit mesh names")
        identifiers.add(identifier)
        mesh = geometry.find(_tag("mesh"))
        if mesh is None:
            raise ValueError(f"LOD geometry is not an indexed mesh: {identifier}")
        techniques = mesh.findall(f"{_tag('extra')}/{_tag('technique')}[@profile='LSTools']")
        orders = [item for technique in techniques for item in technique
                  if isinstance(item.tag, str) and item.tag.rsplit("}", 1)[-1] == "ExportOrder"]
        lod_tags = [item for technique in techniques for item in technique
                    if isinstance(item.tag, str) and item.tag.rsplit("}", 1)[-1] == "LOD"]
        if len(orders) != 1 or len(lod_tags) > 1:
            raise ValueError(f"LOD {identifier} requires one unambiguous ExportOrder")
        lod = _integer((orders[0].text or "").strip(), "LOD ExportOrder")
        if lod_tags and _integer((lod_tags[0].text or "").strip(), "LOD number") != lod:
            raise ValueError(f"Conflicting LOD and ExportOrder for {identifier}")
        if lod and not lod_tags:
            raise ValueError(f"Nonzero LOD {identifier} requires explicit LOD metadata")
        suffix = re.search(r"_LOD(\d+)$", name, re.IGNORECASE)
        if (suffix and int(suffix.group(1)) != lod) or (lod and not suffix):
            raise ValueError(f"Mesh name contradicts LOD metadata: {name}")
        rows.append({"geometry_id": identifier, "mesh_name": name, "lod": lod})
    rows.sort(key=lambda row: row["lod"])
    if [row["lod"] for row in rows] != list(range(len(rows))):
        raise ValueError("LOD ExportOrder values must be unique and contiguous starting at zero")
    if expected_lods is not None and len(rows) != expected_lods:
        raise ValueError(f"Expected all {expected_lods} LODs, found {len(rows)}")
    counts = {identifier: 0 for identifier in identifiers}
    for controller in root.findall(f"{_tag('library_controllers')}/{_tag('controller')}"):
        skin = controller.find(_tag("skin"))
        if skin is None:
            raise ValueError("LOD documents may contain only explicit skin controllers")
        identifier = _reference(skin.get("source"), "LOD skin source")
        if identifier not in counts:
            raise ValueError(f"Skin controller targets an unknown LOD: {identifier}")
        counts[identifier] += 1
    if any(count != 1 for count in counts.values()):
        raise ValueError("Every LOD requires exactly one indexed skin controller")
    return rows


def _load(path: Path, expected_lods: int | None):
    tree = _parse(path)
    rows = _metadata(tree, expected_lods)
    meshes = {}
    for row in rows:
        mesh = ColladaMesh.load(path, row["geometry_id"])
        if len(mesh._controllers) != 1 or not mesh._weighted_vertices:
            raise ValueError(f"LOD is not an indexed, weighted skin: {row['geometry_id']}")
        snapshot = mesh.snapshot()
        row.update(vertex_count=snapshot["vertex_count"], triangle_count=snapshot["triangle_count"], snapshot=snapshot)
        meshes[row["geometry_id"]] = mesh
    return tree, rows, meshes


def enumerate_lods(path: str | Path, expected_lods: int | None = None) -> list[dict[str, Any]]:
    """Return every LOD's explicit identity and validated geometry/skin snapshot.

    Pass expected_lods=5 for the reviewed strong-body sources. Smaller complete
    chains are permitted when expected_lods is omitted or specified otherwise.
    """
    return _load(Path(path), expected_lods)[1]


def _outside_geometries(root: ET.Element) -> str:
    copied = copy.deepcopy(root)
    for library in copied.findall(_tag("library_geometries")):
        for geometry in list(library):
            if geometry.tag == _tag("geometry"):
                library.remove(geometry)
    return _hash(_canonical(copied))


def bake_lods(source: str | Path, output: str | Path,
              transform: Callable[[ColladaMesh, int], list[list[float]]],
              expected_lods: int | None = None) -> dict[str, Any]:
    """Transform every LOD, preserving all original non-geometry XML exactly.

    The callback is invoked once for each LOD and must return its complete
    position array. Output is published atomically only after every LOD passes.
    This function does not invoke GR2 conversion or install game assets.
    """
    source, output = Path(source), Path(output)
    if not callable(transform):
        raise ValueError("transform must be callable")
    tree, rows, meshes = _load(source, expected_lods)
    root = tree.getroot()
    protected = _outside_geometries(root)
    geometry_parent = root.find(_tag("library_geometries"))
    reports = []
    for row in rows:
        identifier, lod = row["geometry_id"], row["lod"]
        mesh = meshes[identifier]
        original_positions = mesh.positions
        positions = transform(mesh, lod)
        normals = mesh.set_positions(positions, recalculate_normals=True)
        after = mesh.snapshot()
        for key in ("topology_id", "controller_sha256", "uv_sha256", "tangent_sha256", "material_sha256"):
            if row["snapshot"][key] != after[key]:
                raise ValueError(f"LOD {lod} authoring changed protected data: {key}")
        shading = validate_smooth_seams(mesh, mesh)
        old = next(geometry for geometry in geometry_parent if geometry.get("id") == identifier)
        index = list(geometry_parent).index(old)
        geometry_parent.remove(old)
        geometry_parent.insert(index, copy.deepcopy(mesh._geometry))
        distances = [math.dist(a, b) for a, b in zip(original_positions, mesh.positions)]
        reports.append({**row, "authored_snapshot": after, "normal_report": normals,
                        "smooth_seams": shading, "moved_vertices": sum(value > 0 for value in distances),
                        "max_displacement": max(distances, default=0.0)})
    if _outside_geometries(root) != protected:
        raise ValueError("LOD assembly changed original controllers, joints, or other protected XML")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix=output.name + ".", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
        tree.write(temporary, encoding="utf-8", xml_declaration=True)
        temporary.replace(output)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return {"schema_version": 1, "source": str(source.resolve()), "output": str(output.resolve()),
            "lod_count": len(reports), "all_lods_processed": True,
            "controllers_preserved": True, "other_xml_preserved": True,
            "protected_xml_sha256": protected, "lods": reports}


def _corner_uvs(mesh: ColladaMesh) -> dict[tuple[int, int], list[tuple[float, float]]]:
    result = {}
    for primitive_index, primitive in enumerate(mesh._primitives):
        inputs = primitive.findall(_tag("input"))
        stride = max(_integer(item.get("offset", "0"), "UV input offset") for item in inputs) + 1
        values = _indices(primitive.find(_tag("p")), "UV corner indices")
        bindings = []
        for item in inputs:
            offset = _integer(item.get("offset", "0"), "UV input offset")
            if item.get("semantic") == "TEXCOORD":
                bindings.append((item, offset))
            elif item.get("semantic") == "VERTEX":
                target = mesh._ids[_reference(item.get("source"), "UV vertex source")]
                if target.tag == _tag("vertices"):
                    bindings.extend((child, offset) for child in target.findall(_tag("input"))
                                    if child.get("semantic") == "TEXCOORD")
        if not bindings:
            raise ValueError("Every reviewed LOD primitive requires explicit corner UVs")
        for item, offset in bindings:
            layer = _integer(item.get("set", "0"), "UV layer")
            key = (primitive_index, layer)
            if key in result:
                raise ValueError("Ambiguous duplicate UV layer in a primitive")
            _, source = mesh._source(item.get("source"), "UV source")
            if not source.numeric or source.stride < 2:
                raise ValueError("UV source must contain numeric coordinate pairs")
            accessor = source.element.find(f"{_tag('technique_common')}/{_tag('accessor')}")
            names = [param.get("name") for param in accessor.findall(_tag("param"))]
            components = next(((names.index(a), names.index(b)) for a, b in
                               (("S", "T"), ("U", "V"), ("X", "Y"))
                               if names.count(a) == 1 and names.count(b) == 1), None)
            if components is None:
                if source.stride != 2 or any(names):
                    raise ValueError("UV accessor requires explicit coordinate components")
                components = (0, 1)
            coordinates = []
            for corner in range(0, len(values), stride):
                start = source.offset + values[corner + offset] * source.stride
                coordinates.append(tuple(source.values[start + component] for component in components))
            result[key] = coordinates
    return result


def _uv_drift(reference: ColladaMesh, current: ColladaMesh, tolerance: float) -> float:
    before, after = _corner_uvs(reference), _corner_uvs(current)
    if before.keys() != after.keys():
        raise ValueError("Export changed LOD primitive or UV-set layout")
    maximum = 0.0
    for key in before:
        if len(before[key]) != len(after[key]):
            raise ValueError("Export changed LOD corner UV count")
        maximum = max(maximum, max((abs(a - b) for old, new in zip(before[key], after[key])
                                    for a, b in zip(old, new)), default=0.0))
    if maximum > tolerance:
        raise ValueError(f"Export changed LOD corner UVs beyond tolerance: {maximum}")
    return maximum


def _source_records(source: _Source, width: int) -> list:
    if source.stride < width or (source.count and source.offset + (source.count - 1) * source.stride + width > len(source.values)):
        raise ValueError("Skin accessor is too short for the expected record width")
    return [source.values[source.offset + index * source.stride:source.offset + index * source.stride + width]
            for index in range(source.count)]


def _skin_data(mesh: ColladaMesh) -> dict[str, Any]:
    controller = mesh._controllers[0]
    skin = controller.find(_tag("skin"))
    sources = {element.get("id"): _Source.read(element) for element in skin.findall(_tag("source"))}
    joint_inputs = skin.findall(f"{_tag('joints')}/{_tag('input')}")
    if sorted(item.get("semantic") for item in joint_inputs) != ["INV_BIND_MATRIX", "JOINT"]:
        raise ValueError("LOD skin requires JOINT and INV_BIND_MATRIX inputs")
    joint_sources = {item.get("semantic"): sources[_reference(item.get("source"), "skin joint input")]
                     for item in joint_inputs}
    names = _source_records(joint_sources["JOINT"], 1)
    inverse = _source_records(joint_sources["INV_BIND_MATRIX"], 16)
    if len(names) != len(inverse) or joint_sources["JOINT"].numeric or not joint_sources["INV_BIND_MATRIX"].numeric:
        raise ValueError("LOD joint names and inverse bind matrices must have matching valid counts")
    weights = skin.find(_tag("vertex_weights"))
    inputs = weights.findall(_tag("input"))
    influence = []
    weight_values = None
    for item in sorted(inputs, key=lambda value: _integer(value.get("offset", "0"), "skin input offset")):
        semantic = item.get("semantic")
        source = sources[_reference(item.get("source"), "skin weight input")]
        influence.append((semantic, _integer(item.get("offset", "0"), "skin input offset")))
        if semantic == "JOINT" and _source_records(source, 1) != names:
            raise ValueError("Vertex influences reference a different joint-name order")
        if semantic == "WEIGHT":
            weight_values = [record[0] for record in _source_records(source, 1)]
    bind_shape = skin.find(_tag("bind_shape_matrix"))
    shape = ([float(value) for value in (bind_shape.text or "").split()] if bind_shape is not None
             else [1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.])
    if len(shape) != 16 or not all(math.isfinite(value) for value in shape):
        raise ValueError("Invalid LOD bind-shape matrix")
    return {"controller_id": controller.get("id"), "joint_order": names, "inverse_bind": inverse,
            "influence_inputs": influence, "vcount": _indices(weights.find(_tag("vcount")), "skin vcount"),
            "v": _indices(weights.find(_tag("v")), "skin v"), "weights": weight_values, "bind_shape": shape}


def _skin_drift(reference: ColladaMesh, current: ColladaMesh, *, matrices: float, weights: float) -> dict[str, float]:
    before, after = _skin_data(reference), _skin_data(current)
    for key in ("controller_id", "joint_order", "influence_inputs", "vcount", "v"):
        if before[key] != after[key]:
            raise ValueError(f"LOD export changed skin {key}")
    result = {}
    for key, tolerance in (("weights", weights), ("inverse_bind", matrices), ("bind_shape", matrices)):
        old, new = before[key], after[key]
        if key == "inverse_bind":
            if len(old) != len(new):
                raise ValueError("LOD export changed inverse-bind count")
            old = [value for record in old for value in record]
            new = [value for record in new for value in record]
        if old is None or new is None or len(old) != len(new):
            raise ValueError(f"LOD export changed skin {key} array size")
        error = max((abs(a - b) for a, b in zip(old, new)), default=0.0)
        if error > tolerance:
            raise ValueError(f"LOD export changed skin {key} beyond tolerance: {error}")
        result[key] = error
    return result


def _vertex_bijection(reference: ColladaMesh, current: ColladaMesh) -> dict[int, int]:
    """Prove a complete bijection from corresponding ordered face corners.

    A source vertex cannot split across export vertices, export vertices cannot
    weld distinct source vertices, and unused/unproved vertices are refused.
    Positions are compared separately under this proven map.
    """
    count = len(reference.positions)
    before, after = reference.triangles, current.triangles
    if count != len(current.positions) or len(before) != len(after):
        raise ValueError("LOD export changed vertex or triangle count")
    mapping, reverse = {}, {}
    for old_triangle, new_triangle in zip(before, after):
        if len(old_triangle) != 3 or len(new_triangle) != 3:
            raise ValueError("LOD topology requires triangle triplets")
        for old, new in zip(old_triangle, new_triangle):
            if old in mapping and mapping[old] != new:
                raise ValueError("LOD export split a vertex or changed face connectivity")
            if new in reverse and reverse[new] != old:
                raise ValueError("LOD export welded vertices or changed face connectivity")
            mapping[old], reverse[new] = new, old
    if set(mapping) != set(range(count)) or set(reverse) != set(range(count)):
        raise ValueError("LOD vertex bijection must prove every source and export vertex is used")
    return mapping


def _vertex_influences(data: dict[str, Any]) -> list[list[tuple[int, float]]]:
    inputs = data["influence_inputs"]
    if len(inputs) != 2 or {semantic for semantic, _ in inputs} != {"JOINT", "WEIGHT"}:
        raise ValueError("Mapped skin comparison supports explicit JOINT and WEIGHT influences")
    offsets = dict(inputs)
    stride = max(offsets.values()) + 1
    result = []
    cursor = 0
    for count in data["vcount"]:
        influences = []
        for _ in range(count):
            joint = data["v"][cursor + offsets["JOINT"]]
            weight_index = data["v"][cursor + offsets["WEIGHT"]]
            influences.append((joint, data["weights"][weight_index]))
            cursor += stride
        result.append(sorted(influences))
    return result


def _mapped_skin_drift(reference: ColladaMesh, current: ColladaMesh,
                       vertex_map: dict[int, int], *, matrices: float, weights: float) -> dict[str, float]:
    """Compare actual joint/weight influences rather than incidental table order."""
    before, after = _skin_data(reference), _skin_data(current)
    for key in ("controller_id", "joint_order"):
        if before[key] != after[key]:
            raise ValueError(f"LOD export changed skin {key}")
    old_influences, new_influences = _vertex_influences(before), _vertex_influences(after)
    if len(old_influences) != len(vertex_map) or len(new_influences) != len(vertex_map):
        raise ValueError("LOD export changed skin vertex count")
    maximum = 0.0
    for old, new in vertex_map.items():
        source_weights, exported_weights = old_influences[old], new_influences[new]
        if (len(source_weights) != len(exported_weights)
                or [joint for joint, _ in source_weights] != [joint for joint, _ in exported_weights]):
            raise ValueError(f"LOD export changed mapped joint influences at source vertex {old}")
        maximum = max(maximum, max((abs(a - b) for (_, a), (_, b) in zip(source_weights, exported_weights)), default=0.0))
    if maximum > weights:
        raise ValueError(f"LOD export changed mapped skin weights beyond tolerance: {maximum}")
    result = {"weights": maximum}
    for key in ("inverse_bind", "bind_shape"):
        old, new = before[key], after[key]
        if key == "inverse_bind":
            if len(old) != len(new):
                raise ValueError("LOD export changed inverse-bind count")
            old = [value for record in old for value in record]
            new = [value for record in new for value in record]
        if len(old) != len(new):
            raise ValueError(f"LOD export changed skin {key} array size")
        drift = max((abs(a - b) for a, b in zip(old, new)), default=0.0)
        if drift > matrices:
            raise ValueError(f"LOD export changed skin {key} beyond tolerance: {drift}")
        result[key] = drift
    return result


def validate_lod_roundtrip(reference: str | Path, authored: str | Path, roundtrip: str | Path,
                           expected_lods: int | None = None) -> dict[str, Any]:
    """Verify all LODs after GR2 export, including corner UVs and skin bindings."""
    _, source_rows, sources = _load(Path(reference), expected_lods)
    _, authored_rows, authored_meshes = _load(Path(authored), expected_lods)
    _, exported_rows, exported_meshes = _load(Path(roundtrip), expected_lods)
    identities = lambda rows: [(row["geometry_id"], row["mesh_name"], row["lod"]) for row in rows]
    if identities(source_rows) != identities(authored_rows) or identities(source_rows) != identities(exported_rows):
        raise ValueError("LOD export changed or omitted explicit LOD identities")
    results = []
    for row in source_rows:
        identifier = row["geometry_id"]
        original, baked, exported = sources[identifier], authored_meshes[identifier], exported_meshes[identifier]
        if original.triangles != baked.triangles or len(original.positions) != len(baked.positions):
            raise ValueError(f"LOD {row['lod']} authoring changed indexed topology")
        vertex_map = _vertex_bijection(baked, exported)
        _uv_drift(original, baked, 0.0)
        _skin_drift(original, baked, matrices=0.0, weights=0.0)
        expected_positions, exported_positions = baked.positions, exported.positions
        delta = max((math.dist(expected_positions[old], exported_positions[new])
                     for old, new in vertex_map.items()), default=0.0)
        if delta > 3e-6:
            raise ValueError(f"LOD {row['lod']} position drift exceeds tolerance: {delta}")
        uv = _uv_drift(original, exported, 1e-6)
        skin = _mapped_skin_drift(original, exported, vertex_map, matrices=5e-5, weights=1e-6)
        shading = validate_smooth_seams(original, exported, tolerance_degrees=1.0, vertex_map=vertex_map)
        results.append({"geometry_id": identifier, "mesh_name": row["mesh_name"], "lod": row["lod"],
                        "vertex_count": row["vertex_count"], "triangle_count": row["triangle_count"],
                        "topology": "passed", "skin_arrays": "passed", "corner_uvs": "passed",
                        "bind_shape": "passed", "max_position_drift": delta,
                        "vertex_bijection": {"status": "passed", "vertex_count": len(vertex_map),
                                              "all_vertices_used": True,
                                              "reindexed_vertices": sum(old != new for old, new in vertex_map.items()),
                                              "sha256": _hash(sorted(vertex_map.items()))},
                        "max_corner_uv_drift": uv, "max_inverse_bind_drift": skin["inverse_bind"],
                        "max_bind_shape_drift": skin["bind_shape"], "max_skin_weight_drift": skin["weights"],
                        "smooth_seams": shading})
    return {"status": "passed", "lod_count": len(results), "all_lods_validated": True,
            "lods": results, "max_position_drift": max(row["max_position_drift"] for row in results),
            "max_corner_uv_drift": max(row["max_corner_uv_drift"] for row in results)}
