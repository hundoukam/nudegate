"""Build private native skin virtual textures for new body variants.

SOFT edits low-frequency normal slopes in a mesh-projected front abdomen mask
and sets existing vein/roughness scalar defaults. DEFINED retains the native
normal DDS and scalar defaults. Both preserve the
native CLEA/Normal/HMVY layer order and leave existing materials untouched.
NumPy and Pillow are authoring dependencies, never game dependencies.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
from uuid import UUID, uuid5
import xml.etree.ElementTree as ET

from .collada import ColladaMesh


NAMESPACE = UUID("fb582366-55bd-5306-8bd5-6df05a62f50a")
NS = {"c": "http://www.collada.org/2005/11/COLLADASchema"}
STYLE_VERSION = "front-abdomen-agb-v1"
MATERIAL_PRESENTATION_VERSION = "soft-vein-roughness-v1"
SOFT_SCALARS = {"VeinAmount": "0.15", "TMP_BODY_ROUGH": "0.62"}
LAYERS = ("Albedo", "Normal", "Physical")


def _deps():
    try:
        import numpy as np
        from PIL import Image, ImageFilter
    except ImportError as exc:
        raise RuntimeError("Skin authoring requires NumPy and Pillow") from exc
    return np, Image, ImageFilter


def _attrs(node):
    result = {}
    for item in node.findall("attribute"):
        name = item.get("id")
        if not name or name in result:
            raise ValueError("Material bank contains missing or duplicate attribute IDs")
        result[name] = item
    return result


def _value(node, name):
    item = _attrs(node).get(name)
    return item.get("value") if item is not None else None


def _uuid(value):
    try:
        identifier = str(UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"Expected a nonzero UUID, found {value!r}") from exc
    if UUID(identifier).int == 0:
        raise ValueError("Zero resource UUID is prohibited")
    return identifier


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _material_uuid(original_id, private_vt_id, style):
    key = "material:" + original_id + ":" + private_vt_id
    if style == "soft":
        key += ":" + MATERIAL_PRESENTATION_VERSION + ":" + json.dumps(SOFT_SCALARS, sort_keys=True)
    elif style != "defined":
        raise ValueError(f"Unsupported skin material style {style}")
    return str(uuid5(NAMESPACE, key))


def _styled_material(original, style, private_id, private_vt_id):
    """Clone without source mutation; SOFT edits only two existing scalars.

    BaseValue, parameter metadata, skin colours, tattoos and texture references
    are preserved. Missing or ambiguous supported scalar records fail closed.
    DEFINED retains every native scalar field exactly.
    """
    if style not in {"soft", "defined"}:
        raise ValueError(f"Unsupported skin material style {style}")
    material = copy.deepcopy(original)
    changes = {}
    if style == "soft":
        scalars = material.findall('./children/node[@id="ScalarParameters"]')
        for name,value in SOFT_SCALARS.items():
            matches = [node for node in scalars if _value(node,"ParameterName") == name]
            if len(matches) != 1:
                raise ValueError(f"SOFT material requires exactly one existing scalar {name}")
            attrs = _attrs(matches[0])
            enabled,scalar = attrs.get("Enabled"),attrs.get("Value")
            if (enabled is None or scalar is None or enabled.get("type") != "bool"
                    or scalar.get("type") != "float"):
                raise ValueError(f"SOFT scalar {name} requires existing bool Enabled and float Value")
            try:
                source_value = float(scalar.get("value"))
            except (TypeError,ValueError) as exc:
                raise ValueError(f"SOFT scalar {name} has an invalid native Value") from exc
            if not math.isfinite(source_value) or enabled.get("value") not in {"True","False","true","false","0","1"}:
                raise ValueError(f"SOFT scalar {name} has invalid native defaults")
            changes[name] = {"before":{"Enabled":enabled.get("value"),"Value":scalar.get("value")},
                             "after":{"Enabled":"True","Value":value}}
            enabled.set("value","True")
            scalar.set("value",value)
    _attrs(material)["ID"].set("value",private_id)
    parameters = [node for node in material.findall('./children/node[@id="VirtualTextureParameters"]')
                  if _value(node,"ParameterName") == "virtualtexture"]
    if len(parameters) != 1:
        raise ValueError("Skin material requires one existing virtualtexture parameter")
    _attrs(parameters[0])["ID"].set("value",private_vt_id)
    return material,changes


def verify_agb_packing(rgba):
    """Validate the native A=X/G=Y/B=Z convention before editing data.

    The native CHAR_Skin_Body DX11 pixel shader samples Cache1.yzwx then
    reverses its xyz components before 2*x-1 (GBA -> ABG, followed by its
    tangent-basis reordering).  R is unused.  The checks below additionally
    reject maps whose decoded A/G/B vectors are inconsistent with normals.
    """
    np, _, _ = _deps()
    image = np.asarray(rgba)
    if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 4:
        raise ValueError("Expected an 8-bit RGBA packed normal map")
    if np.any(image[:, :, 0] != 0):
        raise ValueError("Unsupported normal packing: native skin maps require unused R=0")
    vectors = image[:, :, [3, 1, 2]].astype(np.float32) / 127.5 - 1.0
    length = np.linalg.norm(vectors, axis=2)
    mean_error = float(np.mean(np.abs(length - 1.0)))
    p99_error = float(np.quantile(np.abs(length - 1.0), 0.99))
    if mean_error > 0.04 or p99_error > 0.15:
        raise ValueError("A/G/B channels do not pass native unit-normal validation")
    return {"packing": "X=A,Y=G,Z=B;R=unused", "mean_unit_error": mean_error,
            "p99_unit_error": p99_error}


def _smoothstep(low, high, value):
    np, _, _ = _deps()
    t = np.clip((value - low) / (high - low), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _abdomen_weight(x, y, z):
    # Canonical smaller-frame metres. Exact support stays within the reviewed
    # central front abdomen, avoiding back, clavicle, groin, hands and tail.
    return (_smoothstep(1.02, 1.055, y) * (1.0 - _smoothstep(1.225, 1.26, y))
            * (1.0 - _smoothstep(0.095, 0.13, abs(x)))
            * (1.0 - _smoothstep(-0.035, -0.015, z)))


def rasterize_abdomen_mask(dae, geometry_id, size, frame=(1.0, 1.0, 1.0)):
    """Project the reviewed anatomical mask through actual indexed mesh UVs."""
    np, _, _ = _deps()
    if len(frame) != 3 or any(not math.isfinite(float(v)) or float(v) <= 0 for v in frame):
        raise ValueError("Frame must contain three positive finite scales")
    width, height = map(int, size)
    if min(width, height) < 1:
        raise ValueError("Invalid normal texture dimensions")
    model = ColladaMesh.load(dae, geometry_id=geometry_id)
    positions = np.asarray(model.positions, dtype=np.float64) / np.asarray(frame)
    root = ET.parse(dae).getroot()
    identifiers = {node.get("id"): node for node in root.iter() if node.get("id")}
    mesh = identifiers[model.geometry_id].find("c:mesh", NS)
    mask = np.zeros((height, width), dtype=np.float32)
    candidates = 0
    for primitive in mesh.findall("c:triangles", NS):
        inputs = primitive.findall("c:input", NS)
        vertex = [v for v in inputs if v.get("semantic") == "VERTEX"]
        uv = [v for v in inputs if v.get("semantic") == "TEXCOORD" and v.get("set", "0") == "0"]
        if len(vertex) != 1 or len(uv) != 1:
            raise ValueError("Abdomen projection requires unambiguous POSITION and UV0 inputs")
        stride = max(int(v.get("offset", "0")) for v in inputs) + 1
        pos_offset, uv_offset = int(vertex[0].get("offset", "0")), int(uv[0].get("offset", "0"))
        source = identifiers[uv[0].get("source")[1:]]
        accessor = source.find("c:technique_common/c:accessor", NS)
        array = identifiers[accessor.get("source")[1:]]
        values = np.asarray([float(v) for v in array.text.split()])
        uv_stride, uv_start, count = (int(accessor.get("stride", "1")),
                                      int(accessor.get("offset", "0")), int(accessor.get("count")))
        names = [v.get("name") for v in accessor.findall("c:param", NS)]
        if "S" in names and "T" in names:
            components = (names.index("S"), names.index("T"))
        elif "U" in names and "V" in names:
            components = (names.index("U"), names.index("V"))
        elif uv_stride == 2 and not any(names):
            components = (0, 1)
        else:
            raise ValueError("Unsupported UV accessor component names")
        coords = np.asarray([[values[uv_start + i * uv_stride + c] for c in components]
                             for i in range(count)])
        if np.any(~np.isfinite(coords)):
            raise ValueError("Body UV0 contains nonfinite coordinates")
        indices = [int(v) for v in primitive.find("c:p", NS).text.split()]
        for start in range(0, len(indices), stride * 3):
            p = positions[[indices[start + corner * stride + pos_offset] for corner in range(3)]]
            if (p[:, 1].max() <= 1.02 or p[:, 1].min() >= 1.26 or p[:, 0].min() >= 0.13
                    or p[:, 0].max() <= -0.13 or p[:, 2].min() >= -0.015):
                continue
            t = coords[[indices[start + corner * stride + uv_offset] for corner in range(3)]].copy()
            # Native skin UVs include a second integer U tile.
            # CHAR_Skin_Body samples frac(UV); keep the source UVs intact and
            # remove only the triangle's common integer tile for mask projection.
            t -= np.floor(np.mean(t, axis=0))
            if np.any(t < -0.00001) or np.any(t > 1.00001):
                raise ValueError("Reviewed abdomen triangle crosses a wrapped UV boundary")
            t[:, 0] *= width
            # Divine's DAE exporter flips the native DirectX V coordinate.
            t[:, 1] = (1.0 - t[:, 1]) * height
            x0, y0 = np.floor(t.min(axis=0)).astype(int)
            x1, y1 = np.ceil(t.max(axis=0)).astype(int)
            x0, x1, y0, y1 = max(0, x0), min(width, x1), max(0, y0), min(height, y1)
            if x0 >= x1 or y0 >= y1:
                continue
            a, b, c = t
            denominator = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
            if abs(denominator) < 1e-10:
                continue
            yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float64) + 0.5
            wa = ((b[1] - c[1]) * (xx - c[0]) + (c[0] - b[0]) * (yy - c[1])) / denominator
            wb = ((c[1] - a[1]) * (xx - c[0]) + (a[0] - c[0]) * (yy - c[1])) / denominator
            wc = 1.0 - wa - wb
            inside = (wa >= -1e-7) & (wb >= -1e-7) & (wc >= -1e-7)
            point = wa[:, :, None] * p[0] + wb[:, :, None] * p[1] + wc[:, :, None] * p[2]
            weights = np.where(inside, _abdomen_weight(point[:, :, 0], point[:, :, 1], point[:, :, 2]), 0)
            np.maximum(mask[y0:y1, x0:x1], weights, out=mask[y0:y1, x0:x1])
            candidates += 1
    if not np.any(mask > 0):
        raise ValueError("Reviewed front abdomen mask does not intersect this geometry's UV0")
    return mask, {"geometry_id": model.geometry_id, "source_dae": str(Path(dae).resolve()),
                  "source_dae_sha256": _hash(dae), "frame": list(frame), "candidate_triangles": candidates,
                  "masked_pixels": int(np.count_nonzero(mask)), "total_pixels": width * height,
                  "canonical_region_metres": {"y": [1.02, 1.26], "abs_x_below": 0.13, "z_below": -0.015}}


def soften_packed_normal(rgba, mask, strength=0.85, blur_radius=12.0, preserve_ridges=True):
    """Attenuate broad slopes, retaining fine normal detail and protected pixels."""
    np, Image, ImageFilter = _deps()
    packing = verify_agb_packing(rgba)
    source = np.asarray(rgba)
    weights = np.asarray(mask, dtype=np.float32)
    if weights.shape != source.shape[:2] or np.any(~np.isfinite(weights)) or np.any((weights < 0) | (weights > 1)):
        raise ValueError("Normal mask must be finite, match the texture, and stay within 0..1")
    if not 0 < strength <= 1 or not math.isfinite(blur_radius) or blur_radius <= 0:
        raise ValueError("Invalid normal softening strength or blur radius")
    xy = source[:, :, [3, 1]].astype(np.float32) / 127.5 - 1.0
    low = np.stack([np.asarray(Image.fromarray(source[:, :, channel]).filter(
        ImageFilter.GaussianBlur(blur_radius)), dtype=np.float32) / 127.5 - 1.0 for channel in (3, 1)], axis=2)
    detail = np.linalg.norm(xy - low, axis=2)
    ridge_guard = _smoothstep(0.08, 0.20, detail) if preserve_ridges else np.zeros_like(weights)
    effective = weights * (1.0 - ridge_guard)
    edited_xy = xy - (strength * effective[:, :, None]) * low
    radius = np.linalg.norm(edited_xy, axis=2)
    edited_xy /= np.maximum(1.0, radius / 0.999)[:, :, None]
    z = np.sqrt(np.maximum(0.0, 1.0 - np.sum(edited_xy * edited_xy, axis=2)))
    result = source.copy()
    changed = effective > 0.000001
    for channel, value in ((3, edited_xy[:, :, 0]), (1, edited_xy[:, :, 1]), (2, z)):
        encoded = np.clip(np.rint((value + 1.0) * 127.5), 0, 255).astype(np.uint8)
        result[:, :, channel] = np.where(changed, encoded, source[:, :, channel])
    changed_pixels = np.any(result != source, axis=2)
    selected = weights > 0.05
    before = float(np.sqrt(np.mean(np.sum(xy[selected] ** 2, axis=1)))) if np.any(selected) else 0.0
    after = float(np.sqrt(np.mean(np.sum(edited_xy[selected] ** 2, axis=1)))) if np.any(selected) else 0.0
    return result, {"packing_validation": packing, "strength": strength, "blur_radius_pixels": blur_radius,
                    "ridge_guard": preserve_ridges, "changed_pixels": int(np.count_nonzero(changed_pixels)),
                    "protected_pixels_unchanged": bool(np.array_equal(result[weights == 0], source[weights == 0])),
                    "unused_red_unchanged": bool(np.array_equal(result[:, :, 0], source[:, :, 0])),
                    "masked_xy_rms_before": before, "masked_xy_rms_after": after}


def _dds_layout(data):
    if len(data) < 128 or data[:4] != b"DDS ":
        raise ValueError("Expected a DDS file")
    height, width = struct.unpack_from("<II", data, 12)
    mip_count = max(1, struct.unpack_from("<I", data, 28)[0])
    fourcc = data[84:88]
    if fourcc == b"DXT5":
        offset = 128
    elif fourcc == b"DX10" and len(data) >= 148 and struct.unpack_from("<I", data, 128)[0] in {77, 78}:
        offset = 148
    else:
        raise ValueError("Native skin VT inputs require BC3/DXT5 DDS")
    levels = []
    for level in range(mip_count):
        size = ((width + 3) // 4) * ((height + 3) // 4) * 16
        if offset + size > len(data):
            raise ValueError("DDS mip payload is truncated")
        levels.append((offset, size, width, height))
        offset += size
        width, height = max(1, width // 2), max(1, height // 2)
    return levels


def splice_changed_bc3_blocks(original, recompressed, changed_pixels):
    """Keep original compressed blocks outside the edited UV footprint, all mips."""
    np, _, _ = _deps()
    source, edited = bytes(original), bytes(recompressed)
    a, b = _dds_layout(source), _dds_layout(edited)
    if [(v[2], v[3]) for v in a] != [(v[2], v[3]) for v in b]:
        raise ValueError("Recompressed DDS dimensions or mip count changed")
    mask = np.asarray(changed_pixels, dtype=bool)
    if mask.shape != (a[0][3], a[0][2]):
        raise ValueError("Changed-pixel mask does not match the DDS")
    output = bytearray(source)
    counts = []
    for level, ((start, size, width, height), (other_start, _, _, _)) in enumerate(zip(a, b)):
        block_rows, block_columns = (height + 3) // 4, (width + 3) // 4
        padded = np.zeros((block_rows * 4, block_columns * 4), dtype=bool)
        padded[:height, :width] = mask
        blocks = padded.reshape(block_rows, 4, block_columns, 4).any(axis=(1, 3))
        for block in np.flatnonzero(blocks):
            target = start + int(block) * 16
            origin = other_start + int(block) * 16
            output[target:target + 16] = edited[origin:origin + 16]
        counts.append({"mip": level, "changed_blocks": int(blocks.sum()), "total_blocks": int(blocks.size)})
        if width > 1 or height > 1:
            next_width, next_height = max(1, width // 2), max(1, height // 2)
            next_mask = np.zeros((next_height, next_width), dtype=bool)
            for yy in range(2 if height > 1 else 1):
                for xx in range(2 if width > 1 else 1):
                    next_mask |= mask[yy:next_height * 2:2 if height > 1 else 1,
                                      xx:next_width * 2:2 if width > 1 else 1][:next_height, :next_width]
            mask = next_mask
    return bytes(output), {"mips": counts, "outside_changed_blocks_byte_exact": True,
                            "source_header_byte_exact": output[:a[0][0]] == source[:a[0][0]]}


def _run(arguments):
    result = subprocess.run([str(value) for value in arguments], capture_output=True, text=True)
    log = result.stdout + result.stderr
    if result.returncode or "[ERROR]" in log or "[FATAL]" in log:
        raise RuntimeError(log.strip() or f"Tool returned {result.returncode}")
    return log


def _bank_document(regions):
    root = ET.Element("save")
    ET.SubElement(root, "version", {"major": "4", "minor": "0", "revision": "9", "build": "0",
                                   "lslib_meta": "v1,bswap_guids,lsf_adjacency"})
    for name, resources in regions.items():
        region = ET.SubElement(root, "region", {"id": name})
        parent = ET.SubElement(region, "node", {"id": name})
        ET.SubElement(parent, "children").extend(resources)
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _read_banks(paths):
    result = {"MaterialBank": {}, "VirtualTextureBank": {}}
    for path in paths:
        root = ET.parse(path).getroot()
        for region, entries in result.items():
            for resource in root.findall(f'./region[@id="{region}"]/node[@id="{region}"]/children/node[@id="Resource"]'):
                identifier = _uuid(_value(resource, "ID"))
                if identifier in entries:
                    # Different source definitions cannot silently establish priority.
                    old = copy.deepcopy(entries[identifier])
                    new = copy.deepcopy(resource)
                    for node in list(old.iter()) + list(new.iter()):
                        node.text, node.tail = None, None
                    if ET.tostring(old) != ET.tostring(new):
                        raise ValueError(f"Conflicting {region} resource {identifier}")
                entries[identifier] = resource
    return result


def create_skin_styles(source_banks, families, output, *, divine, texconv, module_folder="Nudegate"):
    """Build SOFT/DEFINED private skin resources and their Script Extender mapping.

    Families contain id, material_id, dae, geometry_id, frame and textures.
    Native skin layers MUST be Albedo=CLEA, Normal=NM, Physical=HMVY.  ``output``
    is a dedicated new authoring directory; package/ is ready to merge into the
    combined mod.  Legacy body assets and original resource UUIDs are not edited.
    """
    np, Image, _ = _deps()
    if (not families or not source_banks or not module_folder or module_folder in {".", ".."}
            or Path(module_folder).name != module_folder):
        raise ValueError("Families, source banks and a plain module folder are required")
    bank = _read_banks(source_banks)
    output = Path(output).resolve()
    package, authoring = output / "package", output / "authoring"
    authoring.mkdir(parents=True, exist_ok=True)
    texture_root = authoring / "textures"
    texture_root.mkdir(exist_ok=True)
    resources = {"MaterialBank": [], "VirtualTextureBank": []}
    mappings, reports, material_map, descriptors = [], [], {}, []
    family_ids = set()
    for family in families:
        family_id = family["id"]
        if (not isinstance(family_id, str) or not family_id or family_id in {".", ".."}
                or Path(family_id).name != family_id or family_id in family_ids):
            raise ValueError("Family IDs must be unique plain names")
        family_ids.add(family_id)
        material_id = _uuid(family["material_id"])
        if material_id in material_map:
            raise ValueError("Each original material can appear in only one skin family")
        original_material = bank["MaterialBank"].get(material_id)
        if original_material is None or _value(original_material, "SourceFile") != "Public/Shared/Assets/Materials/Characters/CHAR_Skin_Body.lsf":
            raise ValueError(f"Unsupported or missing native CHAR_Skin_Body material {material_id}")
        parameters = [node for node in original_material.findall('./children/node[@id="VirtualTextureParameters"]')
                      if _value(node, "ParameterName") == "virtualtexture"]
        if len(parameters) != 1 or _value(parameters[0], "Enabled") != "True":
            raise ValueError("Native body material requires one enabled virtualtexture parameter")
        original_vt_id = _uuid(_value(parameters[0], "ID"))
        original_vt = bank["VirtualTextureBank"].get(original_vt_id)
        if original_vt is None:
            raise ValueError(f"Missing referenced VirtualTextureBank resource {original_vt_id}")
        textures = {name: Path(family["textures"][name]).resolve() for name in LAYERS}
        for path in textures.values():
            levels = _dds_layout(path.read_bytes())
            width, height = levels[0][2:]
            if (min(width, height) < 128 or width & (width - 1) or height & (height - 1)
                    or len(levels) != int(math.log2(max(width, height))) + 1):
                raise ValueError("Skin VT source DDS files require complete power-of-two mip chains and at least 128px")
        rgba = np.asarray(Image.open(textures["Normal"]).convert("RGBA"))
        packing = verify_agb_packing(rgba)
        mask, mask_report = rasterize_abdomen_mask(family["dae"], family["geometry_id"],
                                                  (rgba.shape[1], rgba.shape[0]), family.get("frame", (1, 1, 1)))
        Image.fromarray(np.rint(mask * 255).astype(np.uint8)).save(authoring / f"{family_id}-abdomen-mask.png")
        material_map[material_id] = {}
        for style in ("soft", "defined"):
            normal_path = authoring / f"{family_id}-{style}-NM.dds"
            normal_report = {"packing_validation": packing, "normal_map_changed": False}
            if style == "soft":
                softened, normal_report = soften_packed_normal(rgba, mask)
                png = authoring / f"{family_id}-{style}-NM.png"
                Image.fromarray(softened).save(png)
                with tempfile.TemporaryDirectory(prefix="bc3-", dir=authoring) as temp:
                    _run([texconv, "-nologo", "-f", "DXT5", "-m", "0", "-sepalpha", "-if", "BOX",
                          "--ignore-srgb", "-y", "-o", temp, png])
                    recompressed = (Path(temp) / (png.stem + ".dds")).read_bytes()
                changed = np.any(softened != rgba, axis=2)
                normal_bytes, block_report = splice_changed_bc3_blocks(textures["Normal"].read_bytes(), recompressed, changed)
                normal_path.write_bytes(normal_bytes)
                normal_report.update({"normal_map_changed": True, "compressed_block_preservation": block_report})
            else:
                shutil.copyfile(textures["Normal"], normal_path)
            signature = json.dumps({"version": STYLE_VERSION, "style": style,
                                    "source": {name: _hash(path) for name, path in textures.items()},
                                    "normal": _hash(normal_path)}, sort_keys=True)
            private_vt_id = str(uuid5(NAMESPACE, "vt:" + original_vt_id + ":" + signature))
            private_material_id = _material_uuid(material_id, private_vt_id, style)
            gtex = uuid5(NAMESPACE, "gtex:" + private_vt_id).hex
            for identifier, region in ((private_vt_id, "VirtualTextureBank"), (private_material_id, "MaterialBank")):
                if identifier in bank[region]:
                    raise ValueError(f"Private {region} UUID collides with a source resource")
            vt = copy.deepcopy(original_vt)
            _attrs(vt)["ID"].set("value", private_vt_id)
            _attrs(vt)["GTexFileName"].set("value", gtex)
            material,scalar_changes = _styled_material(original_material,style,private_material_id,private_vt_id)
            resources["MaterialBank"].append(material)
            resources["VirtualTextureBank"].append(vt)
            for index, name in enumerate(LAYERS):
                shutil.copyfile(normal_path if name == "Normal" else textures[name], texture_root / f"{gtex}_{index}.dds")
            descriptors.append(gtex)
            material_map[material_id][style] = private_material_id
            reports.append({"family": family_id, "style": style, "original_material_id": material_id,
                            "private_material_id": private_material_id, "private_virtual_texture_id": private_vt_id,
                            "gtex_name": gtex, "normal": normal_report, "uv_mask": mask_report,
                            "material_presentation_version": MATERIAL_PRESENTATION_VERSION if style == "soft" else "native",
                            "material_scalar_changes": scalar_changes,
                            "layer_order": {"Albedo": "CLEA", "Normal": "NM", "Physical": "HMVY"},
                            "texture_provenance": family.get("texture_provenance"),
                            "source_textures": {name: {"path": str(path), "sha256": _hash(path)} for name, path in textures.items()}})

    texture_set = "NudegateSkinStyles"
    vt_relative = f"Public/{module_folder}/Assets/VirtualTextures"
    config = ET.Element("TileSet", {"Version": "2", "Name": texture_set})
    paths = ET.SubElement(config, "Paths")
    # LSLib resolves an absolute SourceTextures path without changing package roots.
    ET.SubElement(paths, "SourceTextures").text = str(texture_root)
    ET.SubElement(paths, "VirtualTextures").text = vt_relative
    textures_node = ET.SubElement(config, "Textures")
    for gtex in descriptors:
        texture = ET.SubElement(textures_node, "Texture", {"Name": gtex})
        for index, name in enumerate(LAYERS):
            ET.SubElement(texture, "Layer", {"Name": name, "Source": f"{gtex}_{index}.dds"})
    layers = ET.SubElement(config, "Layers")
    for name, kind in (("Albedo", "R8G8B8A8_SRGB"), ("Normal", "X8Y8Z8W8"), ("Physical", "X8Y8Z8W8")):
        ET.SubElement(layers, "Layer", {"Name": name, "Type": kind})
    settings = ET.SubElement(config, "TileSetConfig")
    for name, value in (("Compression", "Best"), ("OneFilePerGTex", "false"), ("BackfillPages", "true"), ("DeduplicateTiles", "true")):
        ET.SubElement(settings, name).text = value
    config_path = authoring / "VTexConfig.xml"
    ET.indent(config, space="  ")
    ET.ElementTree(config).write(config_path, encoding="utf-8", xml_declaration=True)
    package.mkdir(exist_ok=True)
    (package / vt_relative).mkdir(parents=True, exist_ok=True)
    build_log = _run([divine, "-g", "bg3", "-a", "build-vt", "-s", config_path,
                      "--vt-root", package, "--vt-validate"])
    (authoring / "build-vt.log").write_text(build_log, encoding="utf-8")
    gts = package / vt_relative / f"{texture_set}.gts"
    if not gts.is_file() or not list(gts.parent.glob("*.gtp")):
        raise RuntimeError("VT build did not produce the required GTS and GTP assets")
    bank_path = package / f"Public/{module_folder}/Content/[PAK]_SkinStyles/_merged.lsx"
    bank_path.parent.mkdir(parents=True, exist_ok=True)
    bank_path.write_bytes(_bank_document(resources))
    lsf = bank_path.with_suffix(".lsf")
    _run([divine, "-g", "bg3", "-a", "convert-resource", "-s", bank_path, "-d", lsf])
    verified = authoring / "skin-resources-verified.lsx"
    _run([divine, "-g", "bg3", "-a", "convert-resource", "-s", lsf, "-d", verified])
    # LSX is an authoring artifact; only the engine-readable LSF enters package/.
    shutil.copyfile(bank_path, authoring / "skin-resources.lsx")
    bank_path.unlink()
    se_root = package / f"Mods/{module_folder}/ScriptExtender"
    se_root.mkdir(parents=True, exist_ok=True)
    for gtex in descriptors:
        mappings.append({"GTexName": gtex, "GTS": f"{vt_relative}/{texture_set}.gts"})
    (se_root / "VirtualTextures.json").write_text(json.dumps({"Mappings": mappings}, indent=2) + "\n", encoding="utf-8")
    (se_root / "Config.json").write_text(json.dumps({"RequiredVersion": 12, "ModTable": module_folder,
                                                    "FeatureFlags": []}, indent=2) + "\n", encoding="utf-8")
    files = [{"path": path.relative_to(package).as_posix(), "bytes": path.stat().st_size, "sha256": _hash(path)}
             for path in sorted(package.rglob("*")) if path.is_file()]
    report = {"schema_version": 1, "style_version": STYLE_VERSION,
              "material_presentation_version": MATERIAL_PRESENTATION_VERSION,"material_map": material_map,
              "package_root": str(package), "gts": str(gts), "resources": str(lsf), "styles": reports,
              "source_banks": [{"path": str(Path(path).resolve()), "sha256": _hash(path)} for path in source_banks],
              "files": files, "validation": {"lslib_vt_validation": "passed", "resource_lsf_roundtrip": "passed", "in_game": "not tested"},
              "script_extender_required": 12, "scope": "New private resources only; legacy materials are not repointed"}
    (output / "skin-styles.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
