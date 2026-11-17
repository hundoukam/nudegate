"""Build private, local body VisualBank resources with explicit mesh/LOD maps.

This BCB-derived prototype path includes no authored jiggle. It never assigns a
body to a character: callers may use resource_map only after compatibility and
adult admission checks. Third-party input assets are not repository contents.
"""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import re
import stat
from uuid import UUID, uuid5
import xml.etree.ElementTree as ET

from .collada import ColladaMesh, NS


BODY_NAMESPACE = UUID("7ce3c27e-6ada-5be4-b176-412569a06838")
_SLUG = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_MODEL_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{0,127}\Z")
_BANK_PATH = Path("Public/Nudegate/Content/[PAK]_BodyVisuals/_merged.lsx")
_BG3_GR2_MAGIC = bytes.fromhex("e59b495e6f631f141e13eba990beedc4")
# These exact native body resources were inspected in Shared's FemaleStrong
# banks. Unassigned is a real native slot for HUM_FS/ELF_FS, not a general pass.
STRONG_UNASSIGNED_VISUALS = frozenset({
    "9725b3db-6e40-054b-dc49-b8e479bc0cba",  # HUM_FS_NKD_Body_A
    "edb26736-c3d5-72a7-b69a-16b5720ba664",  # ELF_FS_NKD_Body_A
    "a89dc12f-f2d2-f66b-cb25-eebbaa429a25",  # TIF_FS_NKD_Body_A
})
STRONG_BODY_VISUALS = STRONG_UNASSIGNED_VISUALS | {
    "4997dd39-8210-e1a8-2e5b-bb3a85c2b2cf",  # Karlach
    "a1292048-0f09-89e2-2fd6-42d8afe3ef02",  # Karlach glow
    "df1d045b-6c9f-99d0-c1d3-bf8ad9c5148f",  # Karlach glow 02
}


def _values(node: ET.Element) -> dict[str, str]:
    result = {}
    for item in node.findall("attribute"):
        key = item.get("id")
        if not key or key in result or item.get("value") is None:
            raise ValueError(f"Missing/duplicate attribute in {node.get('id')}")
        result[key] = item.get("value")
    return result


def _set(node: ET.Element, name: str, value: str, kind: str = "FixedString") -> None:
    found = node.findall(f'attribute[@id="{name}"]')
    if len(found) > 1:
        raise ValueError(f"Duplicate attribute: {name}")
    if found:
        found[0].set("value", value)
    else:
        node.insert(len(node.findall("attribute")), ET.Element(
            "attribute", {"id": name, "type": kind, "value": value}))


def _name(value: object, label: str, *, model: bool = False) -> str:
    if not isinstance(value, str) or not (_MODEL_NAME if model else _SLUG).fullmatch(value):
        raise ValueError(f"Unsafe {label}: {value!r}")
    if value.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                         *(f"LPT{i}" for i in range(1, 10))}:
        raise ValueError(f"Reserved {label}: {value!r}")
    return value


def _uuid(value: object) -> str:
    try:
        result = UUID(value) if isinstance(value, str) else None
    except ValueError as exc:
        raise ValueError(f"Invalid visual UUID: {value!r}") from exc
    if result is None or result.int == 0:
        raise ValueError(f"Invalid visual UUID: {value!r}")
    return str(result)


def _label(value: object, kind: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200 or any(ord(c) < 32 for c in value):
        raise ValueError(f"Invalid {kind} label")
    return value


def _file(value: object, suffix: str) -> Path:
    if not isinstance(value, (str, Path)):
        raise ValueError(f"Expected absolute {suffix} source path")
    path = Path(value)
    if not path.is_absolute() or path.suffix.lower() != suffix or not path.is_file():
        raise ValueError(f"Missing or invalid absolute {suffix} file: {path}")
    if path.stat().st_size == 0:
        raise ValueError(f"Empty source file: {path}")
    return path.resolve()


def _destination(root: Path, relative: Path) -> Path:
    target = root / relative
    if not target.resolve().is_relative_to(root):
        raise ValueError(f"Output path escapes destination: {target}")
    for item in (target, *target.parents):
        if item.exists():
            info = item.lstat()
            if item.is_symlink() or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
                raise ValueError(f"Output path contains a link/reparse point: {item}")
        if item == root:
            break
    return target


def _lod_meshes(variant: dict, dae: Path, mesh_name: str) -> tuple[list[dict], bool]:
    """Validate every declared LOD against the actual exported COLLADA meshes."""
    try:
        root = ET.parse(dae).getroot()
    except (ET.ParseError, OSError) as exc:
        raise ValueError(f"Cannot read body COLLADA: {exc}") from exc
    geometries = root.findall(f'{{{NS}}}library_geometries/{{{NS}}}geometry')
    explicit = "lods" in variant
    if explicit:
        raw = variant["lods"]
        if not isinstance(raw, list) or len(raw) != 5 or any(not isinstance(d, dict) for d in raw):
            raise ValueError("Explicit lods requires all five LODs 0 through 4")
        descriptors = []
        for item in raw:
            level = item.get("lod")
            if type(level) is not int or level not in range(5):
                raise ValueError("LOD must be an integer from 0 through 4")
            descriptors.append({"lod": level,
                                "geometry_id": _name(item.get("geometry_id"), "geometry_id", model=True),
                                "mesh_name": _name(item.get("mesh_name"), "LOD mesh_name", model=True)})
        if {d["lod"] for d in descriptors} != set(range(5)):
            raise ValueError("Explicit lods requires unique entries for all five LODs 0 through 4")
        descriptors.sort(key=lambda d: d["lod"])
        if len({d["geometry_id"] for d in descriptors}) != 5 or len({d["mesh_name"] for d in descriptors}) != 5:
            raise ValueError("LOD geometry IDs and mesh names must be unique")
        if len(geometries) != 5 or {g.get("id") for g in geometries} != {d["geometry_id"] for d in descriptors}:
            raise ValueError("Declared LOD geometry IDs must match exactly the five exported geometries")
        if descriptors[0]["mesh_name"] != mesh_name:
            raise ValueError("Primary mesh_name must match LOD 0")
    else:
        if len(geometries) != 1 or geometries[0].get("name") != mesh_name:
            raise ValueError(f"mesh_name does not identify the single exported mesh: {mesh_name}")
        if not geometries[0].get("id"):
            raise ValueError("Exported geometry requires an XML ID")
        descriptors = [{"lod": 0, "geometry_id": geometries[0].get("id"), "mesh_name": mesh_name}]
    skins = root.findall(f'{{{NS}}}library_controllers/{{{NS}}}controller/{{{NS}}}skin')
    if len(skins) != len(descriptors):
        raise ValueError("Body prototype requires one skin controller per LOD geometry")
    if any(n.tag.split("}")[-1] == "DivModelType" and (n.text or "").strip() in {"Cloth", "ClothPhysics"} for n in root.iter()):
        raise ValueError("Cloth prototypes require a matched physics builder")
    indexed = {g.get("id"): g for g in geometries}
    for descriptor in descriptors:
        geometry = indexed[descriptor["geometry_id"]]
        if geometry.get("name") != descriptor["mesh_name"]:
            raise ValueError(f"LOD mesh_name does not match exported geometry: {descriptor['mesh_name']}")
        if sum(s.get("source") == "#" + descriptor["geometry_id"] for s in skins) != 1:
            raise ValueError("Body prototype requires one skin controller per LOD geometry")
        if explicit:
            order = [(n.text or "").strip() for n in geometry.iter() if n.tag.split("}")[-1] == "ExportOrder"]
            if order != [str(descriptor["lod"])]:
                raise ValueError(f"LOD {descriptor['lod']} must match the actual LSTools ExportOrder")
        mesh = ColladaMesh.load(dae, descriptor["geometry_id"])
        descriptor["mesh"] = mesh
    return descriptors, explicit


def _lod_materials(original: ET.Element, descriptors: list[dict], explicit: bool) -> dict[int, str]:
    objects = original.findall('./children/node[@id="Objects"]')
    if not explicit:
        materials = {_values(obj).get("MaterialID") for obj in objects}
        if not objects or None in materials or len(materials) != 1:
            raise ValueError("Expected one consistent source skin material")
        return {0: _uuid(next(iter(materials)))}
    result = {}
    for obj in objects:
        fields = _values(obj)
        raw_lod = fields.get("LOD", "")
        if raw_lod not in {"0", "1", "2", "3", "4"} or int(raw_lod) in result:
            raise ValueError("Source Objects must have one material mapping for each LOD 0 through 4")
        result[int(raw_lod)] = _uuid(fields.get("MaterialID"))
    if set(result) != {d["lod"] for d in descriptors}:
        raise ValueError("Source Objects must have one material mapping for each LOD 0 through 4")
    return result


def create_body_resources(body_manifest: dict, source_visual_bank: Path, output: Path) -> dict:
    """Clone explicit original body UUIDs for each local GR2/DAE variant.

    families contain id, label, original_visual_ids and variants. Each variant
    requires id, label, absolute gr2/dae paths and mesh_name; model_name defaults
    to Dummy_Root. Optional lods explicitly lists geometry_id, mesh_name and lod
    for all five levels 0..4; registered strong bodies require this complete map.
    Output contains an LSX VisualBank and private GR2 copies.
    Report variants are flat original-UUID/variant pairs. resource_map maps each
    original UUID to compatible family/variant/private-UUID references; it does
    not itself assert race/rig compatibility or grant character eligibility.
    """
    if not isinstance(body_manifest, dict) or not isinstance(body_manifest.get("families"), list) or not body_manifest["families"]:
        raise ValueError("body_manifest requires a nonempty families list")
    if body_manifest.get("schema_version", 1) != 1:
        raise ValueError("Unsupported body_manifest schema_version")
    bank_path = _file(source_visual_bank, ".lsx")
    raw_output = Path(output).absolute()
    if raw_output == Path(raw_output.anchor) or (raw_output.exists() and not raw_output.is_dir()):
        raise ValueError("Output must be a non-root directory")
    # Validate the unresolved output too, before resolve can conceal a junction.
    for parent in (raw_output, *raw_output.parents):
        if parent.exists():
            info = parent.lstat()
            if parent.is_symlink() or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
                raise ValueError(f"Output path contains a link/reparse point: {parent}")
    root = raw_output.resolve()
    try:
        source = ET.parse(bank_path)
    except (ET.ParseError, OSError) as exc:
        raise ValueError(f"Cannot read source VisualBank: {exc}") from exc
    originals: dict[str, list[ET.Element]] = {}
    ignored_records = 0
    for node in source.findall('./region[@id="VisualBank"]/node[@id="VisualBank"]/children/node[@id="Resource"]'):
        # The supplied BCB bank includes unrelated clothing drafts with malformed
        # IDs. They are never candidates; selected body IDs must be unique/valid.
        ids = node.findall('attribute[@id="ID"]')
        try:
            identifier = _uuid(ids[0].get("value")) if len(ids) == 1 else _uuid(None)
        except ValueError:
            ignored_records += 1
            continue
        originals.setdefault(identifier, []).append(node)
    if not originals:
        raise ValueError("Source contains no VisualBank resources")

    document = ET.Element("save")
    version = source.find("version")
    if version is not None:
        document.append(copy.deepcopy(version))
    region = ET.SubElement(document, "region", {"id": "VisualBank"})
    children = ET.SubElement(ET.SubElement(region, "node", {"id": "VisualBank"}), "children")
    report = {"schema_version": 1, "physics": "not included", "in_game": "not tested",
              "variants": [], "resource_map": {}, "outputs": {}, "counts": {},
              "ignored_unrelated_malformed_source_records": ignored_records}
    files: dict[Path, bytes] = {}
    family_names, claimed_originals, private_ids = set(), set(), set()
    for family in body_manifest["families"]:
        if not isinstance(family, dict):
            raise ValueError("Each family must be an object")
        family_id = _name(family.get("id"), "family id")
        family_label = _label(family.get("label"), "family")
        if family_id.casefold() in family_names:
            raise ValueError(f"Duplicate family id: {family_id}")
        family_names.add(family_id.casefold())
        ids, variants = family.get("original_visual_ids"), family.get("variants")
        if not isinstance(ids, list) or not ids or not isinstance(variants, list) or not variants:
            raise ValueError(f"Family {family_id} needs original_visual_ids and variants")
        ids = [_uuid(value) for value in ids]
        if len(ids) != len(set(ids)) or claimed_originals.intersection(ids):
            raise ValueError("An original visual UUID may belong to only one family")
        claimed_originals.update(ids)
        for identifier in ids:
            if identifier not in originals:
                raise ValueError(f"Unknown original visual UUID: {identifier}")
            if len(originals[identifier]) != 1:
                raise ValueError(f"Duplicate selected source visual UUID: {identifier}")
        variant_names = set()
        for variant in variants:
            if not isinstance(variant, dict):
                raise ValueError("Each variant must be an object")
            variant_id = _name(variant.get("id"), "variant id")
            variant_label = _label(variant.get("label"), "variant")
            if variant_id.casefold() in variant_names:
                raise ValueError(f"Duplicate variant id: {variant_id}")
            variant_names.add(variant_id.casefold())
            mesh_name = _name(variant.get("mesh_name"), "mesh_name", model=True)
            model_name = _name(variant.get("model_name", "Dummy_Root"), "model_name", model=True)
            gr2, dae = _file(variant.get("gr2"), ".gr2"), _file(variant.get("dae"), ".dae")
            if gr2.is_relative_to(root) or dae.is_relative_to(root) or bank_path.is_relative_to(root):
                raise ValueError("Input sources must be outside output")
            descriptors, explicit_lods = _lod_meshes(variant, dae, mesh_name)
            if STRONG_BODY_VISUALS.intersection(ids) and not explicit_lods:
                raise ValueError("Registered strong body resources require all five explicit LODs")
            mesh = descriptors[0]["mesh"]
            positions = mesh.positions
            bounds = [[min(p[axis] for p in positions) for axis in range(3)],
                      [max(p[axis] for p in positions) for axis in range(3)]]
            data = gr2.read_bytes()
            if len(data) < 32 or data[:16] != _BG3_GR2_MAGIC:
                raise ValueError(f"Invalid or unsupported BG3 GR2 header: {gr2}")
            digest = hashlib.sha256(data).hexdigest()
            sourcefile = f"Generated/Public/Nudegate/Assets/Bodies/{family_id}/{variant_id}.GR2"
            destination = _destination(root, Path(sourcefile))
            files[destination] = data
            for identifier in ids:
                original = originals[identifier][0]
                values = _values(original)
                if values.get("Slot") != "NakedBody" and not (
                    values.get("Slot") == "Unassigned" and identifier in STRONG_UNASSIGNED_VISUALS
                ):
                    raise ValueError(f"Source is not a NakedBody visual: {identifier}")
                if original.findall('.//node[@id="ClothParams"]') or original.findall('.//attribute[@id="ClosestVertices"]'):
                    raise ValueError("Source has cloth physics requiring a matched physics builder")
                material_by_lod = _lod_materials(original, descriptors, explicit_lods)
                private_id = str(uuid5(BODY_NAMESPACE, f"{identifier}|{family_id}|{variant_id}|{digest}"))
                if private_id in originals or private_id in private_ids:
                    raise ValueError(f"Private visual UUID collision: {private_id}")
                private_ids.add(private_id)
                cloned = copy.deepcopy(original)
                _set(cloned, "ID", private_id)
                _set(cloned, "Name", f"Nudegate_{family_id}_{variant_id}_{identifier}", "LSString")
                _set(cloned, "SourceFile", sourcefile, "LSString")
                _set(cloned, "Template", f"{sourcefile[:-4]}.{model_name}.0")
                for key, bound in zip(("BoundsMin", "BoundsMax"), bounds):
                    _set(cloned, key, " ".join(format(v, ".9g") for v in bound), "fvec3")
                nested = cloned.find("children")
                for obj in list(nested):
                    if obj.get("id") in {"Objects", "ClothProxyMapping"}:
                        nested.remove(obj)
                lod_report = []
                for descriptor in descriptors:
                    level, name = descriptor["lod"], descriptor["mesh_name"]
                    object_id = f"{variant_id}.{name}.{level}"
                    obj = ET.SubElement(nested, "node", {"id": "Objects"})
                    _set(obj, "ObjectID", object_id)
                    _set(obj, "MaterialID", material_by_lod[level])
                    _set(obj, "LOD", str(level), "uint8")
                    lod_report.append({"lod": level, "geometry_id": descriptor["geometry_id"],
                                       "mesh_name": name, "object_id": object_id,
                                       "material_id": material_by_lod[level],
                                       "position_vertices": len(descriptor["mesh"].positions),
                                       "triangles": len(descriptor["mesh"].triangles)})
                children.append(cloned)
                entry = {"family_id": family_id, "variant_id": variant_id,
                         "family_label": family_label, "variant_label": variant_label,
                         "original_visual_id": identifier, "private_visual_id": private_id,
                         "sourcefile": sourcefile, "mesh_name": mesh_name, "model_name": model_name,
                         "material_ids": sorted(set(material_by_lod.values())),
                         "skeleton_resource": values.get("SkeletonResource", ""),
                         "source_gr2_sha256": digest, "physics": "not included",
                         "position_vertices": len(positions), "triangles": len(mesh.triangles)}
                if explicit_lods:
                    entry["lods"] = lod_report
                report["variants"].append(entry)
                report["resource_map"].setdefault(identifier, []).append(
                    {key: entry[key] for key in ("family_id", "variant_id", "private_visual_id")})

    visual_path = _destination(root, _BANK_PATH)
    ET.indent(document, space="  ")
    files[visual_path] = ET.tostring(document, encoding="utf-8", xml_declaration=True) + b"\n"
    # Refuse conflicting existing artifacts before creating anything.
    for path, data in files.items():
        if path.exists() and (not path.is_file() or path.read_bytes() != data):
            raise ValueError(f"Output collision with a different artifact: {path}")
    for path, data in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    report["outputs"] = {"visuals": str(visual_path), "meshes": [str(p) for p in files if p != visual_path]}
    report["counts"] = {"families": len(family_names), "resources": len(report["variants"]),
                        "meshes": len(files) - 1}
    return report
