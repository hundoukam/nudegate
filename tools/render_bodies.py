"""Render generated body geometry with Blender; never import or export a rig.

Usage:
  blender --background --python tools/render_bodies.py -- \
      --manifest build/bodies/body-build.json --output build/bodies/body-comparison.png

The first family and up to six profiles are shown.  The saved .blend is a
render-only scene, built from positions and triangles in the actual DAE files.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import bpy
from mathutils import Vector


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from nudegate.collada import ColladaMesh  # noqa: E402


BODY_COLOR = (0.62, 0.67, 0.72, 1.0)
TEXT_COLOR = (0.86, 0.90, 0.94, 1.0)
MUTED_COLOR = (0.49, 0.57, 0.64, 1.0)
PANEL_COLOR = (0.065, 0.079, 0.095, 1.0)
COLLADA_NS = {"c": "http://www.collada.org/2005/11/COLLADASchema"}


def split_normals(path: Path, geometry_id: str) -> list[tuple[float, float, float]]:
    """Read the actual DAE corner normals, including accessor and index offsets.

    ColladaMesh has already validated this document.  Reading the separate
    NORMAL index stream here preserves authored shading across duplicated UV
    vertices instead of asking Blender to infer smoothing from connectivity.
    """
    root = ET.parse(path).getroot()
    identifiers = {node.get("id"): node for node in root.iter() if node.get("id")}
    geometry = identifiers[geometry_id]
    mesh = geometry.find("c:mesh", COLLADA_NS)
    result: list[tuple[float, float, float]] = []
    source_cache: dict[str, tuple[list[float], int, int, tuple[int, int, int]]] = {}
    for primitive in mesh.findall("c:triangles", COLLADA_NS):
        inputs = primitive.findall("c:input", COLLADA_NS)
        stride = max(int(item.get("offset", "0")) for item in inputs) + 1
        binding = None
        for item in inputs:
            if item.get("semantic") == "NORMAL":
                binding = (item.get("source")[1:], int(item.get("offset", "0")))
            elif item.get("semantic") == "VERTEX":
                vertices = identifiers[item.get("source")[1:]]
                normal_input = vertices.find('c:input[@semantic="NORMAL"]', COLLADA_NS)
                if normal_input is not None:
                    binding = (normal_input.get("source")[1:], int(item.get("offset", "0")))
        if binding is None:
            raise ValueError(f"Body geometry has no explicit corner normals: {path}")
        source_id, normal_offset = binding
        if source_id not in source_cache:
            source = identifiers[source_id]
            accessor = source.find("c:technique_common/c:accessor", COLLADA_NS)
            array = identifiers[accessor.get("source")[1:]]
            values = [float(value) for value in (array.text or "").split()]
            names = [param.get("name") for param in accessor.findall("c:param", COLLADA_NS)]
            if all(axis in names for axis in ("X", "Y", "Z")):
                components = tuple(names.index(axis) for axis in ("X", "Y", "Z"))
            elif int(accessor.get("stride", "1")) == 3 and not any(names):
                components = (0, 1, 2)
            else:
                raise ValueError(f"Unsupported normal accessor in {path}: {source_id}")
            source_cache[source_id] = (values, int(accessor.get("offset", "0")),
                                       int(accessor.get("stride", "1")), components)
        values, offset, source_stride, components = source_cache[source_id]
        indices = [int(value) for value in primitive.find("c:p", COLLADA_NS).text.split()]
        for triangle_start in range(0, len(indices), stride * 3):
            # Match the reflected geometry's reversed [a, c, b] face order.
            for corner in (0, 2, 1):
                index = indices[triangle_start + corner * stride + normal_offset]
                start = offset + index * source_stride
                nx, ny, nz = (values[start + component] for component in components)
                result.append((nx, nz, ny))
    return result


def label(text: str, x: float, z: float, size: float,
          color: tuple[float, float, float, float] = TEXT_COLOR) -> None:
    curve = bpy.data.curves.new("Label", "FONT")
    curve.body = text
    curve.align_x = "CENTER"
    curve.align_y = "CENTER"
    curve.size = size
    curve.space_character = 1.05
    curve.resolution_u = 4
    obj = bpy.data.objects.new(text, curve)
    bpy.context.scene.collection.objects.link(obj)
    # Text's local +Z normal faces the camera at world -Y; local +Y is up.
    obj.rotation_euler = (math.pi / 2, 0.0, 0.0)
    obj.location = (x, -0.40, z)
    obj.color = color


def panel(x: float, floor: float, width: float, height: float) -> None:
    mesh = bpy.data.meshes.new("Panel")
    left, right = x - width / 2, x + width / 2
    bottom, top = floor - 0.12, floor + height - 0.08
    mesh.from_pydata([(left, 0.65, bottom), (right, 0.65, bottom),
                      (right, 0.65, top), (left, 0.65, top)], [], [(0, 1, 2, 3)])
    obj = bpy.data.objects.new("Panel", mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.color = PANEL_COLOR


def load_profiles(manifest_path: Path) -> tuple[dict, list[dict]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    families = manifest.get("families")
    if not isinstance(families, list) or not families or not isinstance(families[0], dict):
        raise ValueError("Manifest must contain at least one body family")
    family = families[0]
    variants = family.get("variants")
    if not isinstance(variants, list) or not variants:
        raise ValueError("The first body family has no generated variants")
    profiles = []
    for variant in variants[:6]:
        if not isinstance(variant, dict) or not isinstance(variant.get("dae"), str):
            raise ValueError("Each body profile must name its generated DAE file")
        path = Path(variant["dae"])
        if not path.is_absolute():
            path = manifest_path.parent / path
        collada = ColladaMesh.load(path, geometry_id=variant.get("geometry_id"))
        # Swapping Y and Z gives the requested front at -Y.  It is a reflection,
        # so triangle winding is reversed below to keep outward-facing normals.
        vertices = [(x, z, y) for x, y, z in collada.positions]
        triangles = [(a, c, b) for a, b, c in collada.triangles]
        if not vertices or not triangles:
            raise ValueError(f"Body profile has no renderable geometry: {path}")
        profiles.append({"variant": variant, "path": path.resolve(),
                         "vertices": vertices, "triangles": triangles,
                         "normals": split_normals(path, collada.geometry_id)})
    return family, profiles


def main() -> None:
    args_start = sys.argv.index("--") + 1 if "--" in sys.argv else len(sys.argv)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(sys.argv[args_start:])
    family, profiles = load_profiles(args.manifest.resolve())
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 2000
    scene.render.resolution_y = 1500
    scene.render.resolution_percentage = 100
    scene.render.pixel_aspect_x = 1.0
    scene.render.pixel_aspect_y = 1.0
    scene.render.use_border = False
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    shading = scene.display.shading
    shading.light = "STUDIO"
    shading.color_type = "OBJECT"
    # A comparison sheet needs local form shading without cast shadows from
    # neighboring profiles or the label geometry crossing other cells.
    shading.show_shadows = False
    shading.show_cavity = True
    shading.cavity_type = "WORLD"
    shading.cavity_ridge_factor = 0.6
    shading.cavity_valley_factor = 0.6
    shading.show_specular_highlight = False
    shading.show_object_outline = False
    shading.background_type = "WORLD"
    if scene.world is None:
        scene.world = bpy.data.worlds.new("Preview background")
    scene.world.color = (0.040, 0.049, 0.061)
    scene.view_settings.view_transform = "Standard"

    columns = min(3, len(profiles))
    rows = math.ceil(len(profiles) / columns)
    cell_width, cell_height = 2.40, 2.13
    max_height = max(max(v[2] for v in p["vertices"]) - min(v[2] for v in p["vertices"])
                     for p in profiles)
    # A common display scale preserves the relative size of all profiles.
    scale = min(1.0, 1.62 / max_height) if max_height > 0 else 1.0
    summaries = []
    for index, profile in enumerate(profiles):
        row, column = divmod(index, columns)
        x = (column - (columns - 1) / 2) * cell_width
        floor = (rows - row - 1) * cell_height
        panel(x, floor, cell_width - 0.10, cell_height)
        vertices = [(vx * scale, vy * scale, vz * scale)
                    for vx, vy, vz in profile["vertices"]]
        mesh = bpy.data.meshes.new(str(profile["variant"].get("id", index)))
        mesh.from_pydata(vertices, [], profile["triangles"])
        mesh.update()
        for polygon in mesh.polygons:
            polygon.use_smooth = True
        if len(mesh.loops) != len(profile["normals"]):
            raise ValueError(f"Corner normal count mismatch in {profile['path']}")
        mesh.normals_split_custom_set(profile["normals"])
        min_z = min(v[2] for v in vertices)
        for view, position_x, angle in [("front", x - 0.27, 0.0),
                                         ("side", x + 0.88, math.pi / 2)]:
            obj = bpy.data.objects.new(f"{mesh.name}_{view}", mesh)
            scene.collection.objects.link(obj)
            obj.location = (position_x, 0.0, floor - min_z)
            obj.rotation_euler.z = angle
            obj.color = BODY_COLOR
        name = str(profile["variant"].get("label") or profile["variant"].get("id") or f"Profile {index + 1}")
        label(name, x, floor + 1.88, min(0.135, 2.5 / max(1, len(name))))
        label("FRONT", x - 0.27, floor - 0.035, 0.052, MUTED_COLOR)
        label("SIDE", x + 0.88, floor - 0.035, 0.052, MUTED_COLOR)
        summaries.append({"id": profile["variant"].get("id"), "dae": str(profile["path"]),
                          "vertices": len(vertices), "triangles": len(profile["triangles"]),
                          "custom_split_normals": len(profile["normals"])})

    upper = (rows - 1) * cell_height + 2.17
    label("Nudegate  /  Body profiles", 0.0, upper + 0.30, 0.17)
    label(str(family.get("label") or family.get("id") or "Generated body family"),
          0.0, upper + 0.075, 0.10, MUTED_COLOR)
    label("Actual generated geometry  /  Front + side", 0.0, -0.35, 0.085, MUTED_COLOR)
    label("Geometry preview / physics untested", 0.0, -0.52, 0.085, MUTED_COLOR)

    camera_data = bpy.data.cameras.new("Comparison camera")
    camera = bpy.data.objects.new("Comparison camera", camera_data)
    scene.collection.objects.link(camera)
    center_z = (upper + 0.48 - 0.68) / 2
    target = Vector((0.0, 0.0, center_z))
    camera.location = (0.0, -10.0, center_z)
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera_data.type = "ORTHO"
    aspect = scene.render.resolution_x / scene.render.resolution_y
    # With AUTO sensor fit and a landscape frame, ortho_scale is the width.
    camera_data.ortho_scale = max((upper + 1.60) * aspect,
                                  columns * cell_width + 0.28)
    scene.camera = camera
    scene.render.filepath = str(output)
    blend = output.with_suffix(".blend")
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    bpy.ops.render.render(write_still=True)
    print("NUDEGATE_BODY_RENDER " + json.dumps({"render_only": True,
          "rig_imported": False, "rig_exported": False, "display_scale": scale,
          "image": str(output), "blend": str(blend), "profiles": summaries}))


if __name__ == "__main__":
    main()
