"""Create private skin materials with softer vein and specular presentation.

This optional patch changes existing material scalar defaults only.  It does
not edit muscle normal maps, virtual textures, skin colours, or tattoo data.
"""
from __future__ import annotations

import copy
import hashlib
import math
from pathlib import Path
from uuid import UUID, uuid5
import xml.etree.ElementTree as ET


SKIN_NAMESPACE = UUID("33f9772c-a2fc-5c41-a737-f11e0a3d3ba9")
SOFT_SCALARS = {"VeinAmount": "0.15", "TMP_BODY_ROUGH": "0.62"}
RESOURCE_XPATH = './region[@id="MaterialBank"]/node[@id="MaterialBank"]/children/node[@id="Resource"]'


def _uuid(value: str | None, label: str) -> str:
    try:
        result = str(UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"{label} must be a UUID: {value!r}") from exc
    if UUID(result).int == 0:
        raise ValueError(f"{label} must not be the zero UUID")
    return result


def _attributes(node: ET.Element) -> dict[str, ET.Element]:
    attributes = {}
    for attribute in node.findall("attribute"):
        identifier = attribute.get("id")
        if not identifier or identifier in attributes:
            raise ValueError(f"Missing or duplicate attribute ID in {node.get('id')}")
        attributes[identifier] = attribute
    return attributes


def _fingerprint(node: ET.Element) -> bytes:
    clean = copy.deepcopy(node)
    for element in clean.iter():
        if not (element.text or "").strip():
            element.text = None
        if not (element.tail or "").strip():
            element.tail = None
    return ET.tostring(clean, encoding="utf-8")


def _document(resources: list[ET.Element]) -> ET.Element:
    root = ET.Element("save")
    ET.SubElement(root, "version", {"major": "4", "minor": "0", "revision": "9", "build": "0",
                                   "lslib_meta": "v1,bswap_guids,lsf_adjacency"})
    region = ET.SubElement(root, "region", {"id": "MaterialBank"})
    parent = ET.SubElement(region, "node", {"id": "MaterialBank"})
    ET.SubElement(parent, "children").extend(resources)
    ET.indent(root, space="  ")
    return root


def create_soft_materials(source_banks: list[Path], material_ids: list[str],
                          output: Path) -> dict:
    """Clone exact materials, rejecting unsupported or ambiguous definitions.

    ``output`` is the generated package root.  Every requested material must
    contain exactly one existing ScalarParameters entry for each supported
    scalar, with existing Enabled and Value attributes.  All checks finish
    before an output file is created; sources are always read without edits.
    """
    if not source_banks or not material_ids:
        raise ValueError("Source banks and requested material IDs must be nonempty")
    requested = [_uuid(identifier, "Material ID") for identifier in material_ids]
    if len(requested) != len(set(requested)):
        raise ValueError("Requested material IDs contain duplicates")
    output_path = Path(output) / "Public/Nudegate/Content/[PAK]_SkinMaterials/_merged.lsx"
    sources = [Path(path).resolve() for path in source_banks]
    if output_path.resolve() in sources:
        raise ValueError("Material output must not overwrite a source bank")
    index: dict[str, ET.Element] = {}
    provenance: dict[str, str] = {}
    bank_reports = []
    for path in sources:
        try:
            data = path.read_bytes()
            parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
            document = ET.fromstring(data, parser=parser)
        except (OSError, ET.ParseError) as exc:
            raise ValueError(f"Cannot read material source bank {path}: {exc}") from exc
        bank_reports.append({"path": str(path), "sha256": hashlib.sha256(data).hexdigest()})
        for resource in document.findall(RESOURCE_XPATH):
            attributes = _attributes(resource)
            identifier = _uuid(attributes.get("ID").get("value") if "ID" in attributes else None,
                               f"Material ID in {path}")
            if identifier in index and _fingerprint(resource) != _fingerprint(index[identifier]):
                raise ValueError(f"Conflicting material definitions for {identifier}; select an unambiguous source bank")
            index[identifier] = resource
            provenance[identifier] = str(path)

    resources = []
    material_map = {}
    material_reports = []
    for identifier in requested:
        if identifier not in index:
            raise ValueError(f"Requested material not found: {identifier}")
        original = index[identifier]
        clone = copy.deepcopy(original)
        private_id = str(uuid5(SKIN_NAMESPACE,
                              f"soft-skin-v1:{identifier}:VeinAmount=0.15:TMP_BODY_ROUGH=0.62"))
        if private_id in index:
            raise ValueError(f"Private material UUID collides with a source material: {private_id}")
        scalar_nodes = clone.findall('./children/node[@id="ScalarParameters"]')
        changes = {}
        for parameter, value in SOFT_SCALARS.items():
            matches = [node for node in scalar_nodes
                       if _attributes(node).get("ParameterName") is not None
                       and _attributes(node)["ParameterName"].get("value") == parameter]
            if len(matches) != 1:
                raise ValueError(f"Material {identifier} requires exactly one existing scalar {parameter}")
            attributes = _attributes(matches[0])
            if "Enabled" not in attributes or "Value" not in attributes:
                raise ValueError(f"Material {identifier} scalar {parameter} requires existing Enabled and Value attributes")
            enabled, scalar = attributes["Enabled"], attributes["Value"]
            if enabled.get("type") != "bool" or scalar.get("type") != "float":
                raise ValueError(f"Material {identifier} scalar {parameter} has unsupported attribute types")
            try:
                source_value = float(scalar.get("value"))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Material {identifier} scalar {parameter} has an invalid Value") from exc
            if not math.isfinite(source_value) or enabled.get("value") not in {"True", "False", "true", "false", "0", "1"}:
                raise ValueError(f"Material {identifier} scalar {parameter} has invalid defaults")
            changes[parameter] = {"before": {"Enabled": enabled.get("value"), "Value": scalar.get("value")},
                                  "after": {"Enabled": "True", "Value": value}}
            enabled.set("value", "True")
            scalar.set("value", value)
        _attributes(clone)["ID"].set("value", private_id)
        resources.append(clone)
        material_map[identifier] = private_id
        material_reports.append({"original_material_id": identifier, "private_material_id": private_id,
                                 "source": provenance[identifier], "changes": changes})

    serialized = ET.tostring(_document(resources), encoding="utf-8", xml_declaration=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(output_path.name + ".tmp")
    temporary.write_bytes(serialized)
    temporary.replace(output_path)
    return {"schema_version": 1, "material_map": material_map, "counts": {"materials": len(resources)},
            "output": str(output_path), "outputs": {"materials": str(output_path)},
            "materials": material_reports, "source_banks": bank_reports,
            "muscle_normal_maps_changed": False,
            "presentation": "Existing vein and roughness scalar defaults only; textures and colour parameters preserved"}
