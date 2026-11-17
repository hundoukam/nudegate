"""Build private, local body VisualBank resources from single-mesh prototypes.

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


def create_body_resources(body_manifest: dict, source_visual_bank: Path, output: Path) -> dict:
    """Clone explicit original body UUIDs for each local GR2/DAE variant.

    families contain id, label, original_visual_ids and variants. Each variant
    requires id, label, absolute gr2/dae paths and mesh_name; model_name defaults
    to Dummy_Root. Output contains an LSX VisualBank and private GR2 copies.
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
            mesh = ColladaMesh.load(dae)
            dae_root = ET.parse(dae).getroot()
            geometries = dae_root.findall(f'{{{NS}}}library_geometries/{{{NS}}}geometry')
            if len(geometries) != 1 or geometries[0].get("name") != mesh_name:
                raise ValueError(f"mesh_name does not identify the single exported mesh: {mesh_name}")
            if len(dae_root.findall(f'{{{NS}}}library_controllers/{{{NS}}}controller/{{{NS}}}skin')) != 1:
                raise ValueError("Body prototype requires one skin controller")
            if any(n.tag.split("}")[-1] == "DivModelType" and (n.text or "").strip() in {"Cloth", "ClothPhysics"} for n in dae_root.iter()):
                raise ValueError("Cloth prototypes require a matched physics builder")
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
                if values.get("Slot") != "NakedBody":
                    raise ValueError(f"Source is not a NakedBody visual: {identifier}")
                if original.findall('.//node[@id="ClothParams"]') or original.findall('.//attribute[@id="ClosestVertices"]'):
                    raise ValueError("Source has cloth physics requiring a matched physics builder")
                objects = original.findall('./children/node[@id="Objects"]')
                materials = {_values(obj).get("MaterialID") for obj in objects}
                if not objects or None in materials or len(materials) != 1:
                    raise ValueError(f"Expected one consistent source skin material: {identifier}")
                material = next(iter(materials))
                _uuid(material)
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
                obj = ET.SubElement(nested, "node", {"id": "Objects"})
                _set(obj, "ObjectID", f"{variant_id}.{mesh_name}.0")
                _set(obj, "MaterialID", material)
                _set(obj, "LOD", "0", "uint8")
                children.append(cloned)
                entry = {"family_id": family_id, "variant_id": variant_id,
                         "family_label": family_label, "variant_label": variant_label,
                         "original_visual_id": identifier, "private_visual_id": private_id,
                         "sourcefile": sourcefile, "mesh_name": mesh_name, "model_name": model_name,
                         "material_ids": [material], "skeleton_resource": values.get("SkeletonResource", ""),
                         "source_gr2_sha256": digest, "physics": "not included",
                         "position_vertices": len(positions), "triangles": len(mesh.triangles)}
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
