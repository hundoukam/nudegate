"""Experimental new-character presets using private adult body/root clones.

Original roots, their descendants, character visuals and body resources are never
overridden. Only selected generic CC preset records retain their original UUIDs.
This does not update an existing save or guarantee that CC preserves every choice.
"""

from __future__ import annotations

import copy
from pathlib import Path
import re
import stat
from uuid import UUID, uuid5
import xml.etree.ElementTree as ET

from .core import Database, MINOR_BASES, MINOR_TAGS, MINOR_TEXT, ZERO_UUID, attrs


TAV_NAMESPACE = UUID("fe53e541-3bfd-5949-9040-8146b9e4af7c")
# Exact adult body resources inspected in native/BCB Female and FemaleStrong
# banks. They admit no child/unknown body, and do not infer age from missing tags.
SUPPORTED_BODY_PROFILES = {
    "db6e5918-8514-4dcc-8363-e8fd3c50cce5": ("0", {"HUM_F_NKD_Body_A_Mesh"}),
    "9e43f0e4-d063-d85c-87b4-470d569645db": ("0", {"HUM_F_NKD_Body_A_Mesh"}),
    "ddfaee83-10c4-92bb-dbbc-30c92c506d54": ("0", {"HUM_F_NKD_Body_A_Mesh"}),
    "820ddd41-7946-f026-099f-7034983d50d2": ("0", {"TIF_F_NKD_Body_A_Mesh"}),
    "b7bfa2d3-4dad-d8a3-8639-9e3dddb97a00": ("0", {"GTY_F_NKD_Body_A_Mesh", "HUM_F_NKD_Body_A_Mesh"}),
    "9725b3db-6e40-054b-dc49-b8e479bc0cba": ("1", {"HUM_FS_NKD_Body_A_Mesh"}),
    "edb26736-c3d5-72a7-b69a-16b5720ba664": ("1", {"HUM_FS_NKD_Body_A_Mesh"}),
    "a89dc12f-f2d2-f66b-cb25-eebbaa429a25": ("1", {"TIF_FS_NKD_Body_A_Mesh"}),
    "4997dd39-8210-e1a8-2e5b-bb3a85c2b2cf": ("1", {"TIF_FS_NKD_Body_A_Mesh"}),
    "a1292048-0f09-89e2-2fd6-42d8afe3ef02": ("1", {"TIF_FS_NKD_Body_A_Mesh"}),
    "df1d045b-6c9f-99d0-c1d3-bf8ad9c5148f": ("1", {"TIF_FS_NKD_Body_A_Mesh"}),
}
_PROFILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")


def _uuid(value: object, label: str) -> str:
    try:
        parsed = UUID(value) if isinstance(value, str) else None
    except ValueError as exc:
        raise ValueError(f"Invalid {label}: {value!r}") from exc
    if parsed is None or not parsed.int:
        raise ValueError(f"Invalid {label}: {value!r}")
    return str(parsed)


def _set(node: ET.Element, key: str, value: str, kind: str = "FixedString") -> None:
    matches = node.findall(f'attribute[@id="{key}"]')
    if len(matches) > 1:
        raise ValueError(f"Duplicate {key} attribute")
    if matches:
        matches[0].set("value", value)
    else:
        node.insert(len(node.findall("attribute")), ET.Element(
            "attribute", {"id": key, "type": kind, "value": value}))


def _document(region: str, container: str, nodes: list[ET.Element]) -> bytes:
    root = ET.Element("save")
    ET.SubElement(root, "version", {"major": "4", "minor": "0", "revision": "9", "build": "0",
                                   "lslib_meta": "v1,bswap_guids,lsf_adjacency"})
    inner = ET.SubElement(ET.SubElement(root, "region", {"id": region}), "node", {"id": container})
    ET.SubElement(inner, "children").extend(nodes)
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


def _body_choices(body_resources: dict, profile_id: str, occupied: set[str]) -> tuple[dict, set[str]]:
    if not isinstance(body_resources, dict) or not isinstance(body_resources.get("resource_map"), dict) or not isinstance(body_resources.get("variants"), list):
        raise ValueError("body_resources requires resource_map and variants from the private body builder")
    variants = {}
    private_ids = set()
    for entry in body_resources["variants"]:
        if not isinstance(entry, dict):
            raise ValueError("Invalid body variant record")
        if any(not isinstance(entry.get(key), str) or not _PROFILE.fullmatch(entry[key])
               for key in ("family_id", "variant_id")):
            raise ValueError("Invalid body family/profile identifier")
        original = _uuid(entry.get("original_visual_id"), "original body UUID")
        private = _uuid(entry.get("private_visual_id"), "private body UUID")
        if private == original or private in occupied:
            raise ValueError("Private body UUID collides with an existing original resource")
        if private in private_ids:
            raise ValueError("Duplicate private body UUID")
        private_ids.add(private)
        key = (original, entry.get("family_id"), entry.get("variant_id"), private)
        if key in variants:
            raise ValueError("Duplicate body variant record")
        variants[key] = entry
    choices, seen = {}, set()
    for raw_original, mappings in body_resources["resource_map"].items():
        original = _uuid(raw_original, "resource_map original UUID")
        if original in seen or not isinstance(mappings, list):
            raise ValueError("Invalid or duplicate resource_map body entry")
        seen.add(original)
        if original not in SUPPORTED_BODY_PROFILES:
            continue
        selected = []
        for mapping in mappings:
            if not isinstance(mapping, dict):
                raise ValueError("Invalid body resource mapping")
            if mapping.get("variant_id") != profile_id:
                continue
            private = _uuid(mapping.get("private_visual_id"), "mapped private body UUID")
            key = (original, mapping.get("family_id"), profile_id, private)
            if key not in variants:
                raise ValueError("Body resource mapping has no matching built variant record")
            entry = variants[key]
            if entry.get("mesh_name") not in SUPPORTED_BODY_PROFILES[original][1]:
                raise ValueError("Built body mesh family disagrees with the reviewed normal/strong source UUID")
            selected.append(entry)
        if len(selected) > 1:
            raise ValueError(f"Ambiguous body profile {profile_id!r} for {original}")
        if selected:
            choices[original] = selected[0]
    return choices, private_ids


def _output_paths(output: Path) -> dict[str, Path]:
    root = Path(output).absolute()
    if root == Path(root.anchor) or (root.exists() and not root.is_dir()):
        raise ValueError("Output must be a non-root directory")
    paths = {
        "templates": root / "Public/Nudegate/RootTemplates/tav.lsx",
        "visuals": root / "Public/Nudegate/Content/[PAK]_CharacterVisuals/tav.lsx",
        "presets": root / "Public/Nudegate/CharacterCreationPresets/CharacterCreationPresets.lsx",
    }
    for path in paths.values():
        for candidate in (path, *path.parents):
            try:
                info = candidate.lstat()
            except FileNotFoundError:
                continue
            if candidate.is_symlink() or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
                raise ValueError(f"Output contains a link/reparse point: {candidate}")
    return paths


def create_tav_presets(db: Database, preset_files: list[Path], body_resources: dict,
                       output: Path, profile_id: str = "plush") -> dict:
    """Build private adult female BT1/BT3 roots for generic new-character presets.

    Later preset_files win UUID collisions. Absent/zero OriginUUID denotes a
    generic preset; named origins are skipped. Original roots may have children,
    because only entirely new MapKeys/CVIDs are emitted. Visual visibility, slots,
    materials and all root gameplay state are preserved. No save editing occurs.
    """
    if not isinstance(profile_id, str) or not _PROFILE.fullmatch(profile_id):
        raise ValueError("profile_id must be a safe nonempty identifier")
    if not isinstance(preset_files, list) or not preset_files:
        raise ValueError("preset_files must be a nonempty ordered list")
    paths = _output_paths(output)
    occupied = set(db.templates) | set(db.visuals)
    choices, body_private_ids = _body_choices(body_resources, profile_id, occupied)
    report = {"schema_version": 1, "profile_id": profile_id, "experimental": True,
              "scope": "new character creation only", "existing_saves": "not supported",
              "in_game": "not tested", "templates": [], "presets": [], "skipped": [],
              "counts": {}, "outputs": {}}
    presets, priority_replacements = {}, 0
    for filename in preset_files:
        path = Path(filename)
        if not path.is_file() or path.suffix.lower() != ".lsx":
            raise ValueError(f"Missing preset LSX file: {path}")
        if path.resolve() in {target.resolve() for target in paths.values()}:
            raise ValueError("Preset input collides with a generated output path")
        try:
            tree = ET.parse(path)
        except (OSError, ET.ParseError) as exc:
            raise ValueError(f"Cannot read CC presets: {path}") from exc
        nodes = tree.findall('./region[@id="CharacterCreationPresets"]/node[@id="root"]/children/node[@id="CharacterCreationPreset"]')
        if not nodes:
            raise ValueError(f"File contains no CharacterCreationPresets: {path}")
        local_ids = set()
        for node in nodes:
            attribute_keys = [item.get("id") for item in node.findall("attribute")]
            if None in attribute_keys or len(attribute_keys) != len(set(attribute_keys)):
                raise ValueError("Preset has missing or duplicate attribute IDs")
            try:
                identifier = _uuid(attrs(node).get("UUID"), "CC preset UUID")
            except ValueError:
                report["skipped"].append({"preset_id": None, "source": str(path), "reason": "missing or invalid preset UUID"})
                continue
            if identifier in local_ids:
                raise ValueError(f"Duplicate CC preset UUID within one file: {identifier}")
            local_ids.add(identifier)
            priority_replacements += identifier in presets
            presets[identifier] = (node, str(path))

    occupied |= body_private_ids | set(presets)
    cloned_roots, root_nodes, visual_nodes, preset_nodes = {}, [], [], []
    generated_ids = set()
    for preset_id in sorted(presets):
        preset, source_path = presets[preset_id]
        fields = attrs(preset)
        def skip(reason: str) -> None:
            report["skipped"].append({"preset_id": preset_id, "source": source_path, "reason": reason})
        if fields.get("BodyType") != "1" or fields.get("BodyShape") not in {"0", "1"}:
            skip("unsupported or non-female CC body profile")
            continue
        origin = fields.get("OriginUUID")
        if origin not in {None, "", ZERO_UUID}:
            skip("named origin preset")
            continue
        try:
            template_id = _uuid(fields.get("RootTemplate"), "CC RootTemplate")
            chain = db.ancestry(template_id)
        except ValueError as exc:
            skip(f"missing root or unresolved ancestry: {exc}")
            continue
        if db.effective_attr(template_id, "Type") != "character":
            skip("CC root is not a character")
            continue
        veto = None
        for ancestor_id in chain:
            ancestor = attrs(db.templates[ancestor_id])
            if ancestor_id in MINOR_BASES:
                veto = "minor ancestry veto: BASE_Children"
                break
            if any(MINOR_TEXT.search(ancestor.get(key) or "") for key in ("Name", "Stats")):
                veto = "minor name or stats veto"
                break
        if db.inherited_tags(template_id) & MINOR_TAGS:
            veto = "minor tag veto"
        if veto:
            skip(veto)
            continue
        try:
            visual_id = _uuid(db.effective_attr(template_id, "CharacterVisualResourceID"), "CC character visual")
            original_visual = db.visuals[visual_id]
            visual_fields = attrs(original_visual)
            body_id = _uuid(visual_fields.get("BodySetVisual"), "CC BodySetVisual")
            _uuid(visual_fields.get("BaseVisual"), "CC BaseVisual")
        except (ValueError, KeyError):
            skip("unresolved character visual or body/skeleton reference")
            continue
        if MINOR_TEXT.search(visual_fields.get("Name") or ""):
            skip("minor character visual name veto")
            continue
        if body_id not in choices:
            skip("unsupported adult body source or requested profile unavailable")
            continue
        body_shape = fields["BodyShape"]
        if SUPPORTED_BODY_PROFILES[body_id][0] != body_shape:
            skip("CC BodyShape disagrees with the reviewed normal/strong body source")
            continue
        selected = choices[body_id]
        body_private_id = _uuid(selected["private_visual_id"], "selected private body UUID")
        if template_id not in cloned_roots:
            root_id = str(uuid5(TAV_NAMESPACE, f"tav-root:{template_id}:{profile_id}:{body_private_id}"))
            new_visual_id = str(uuid5(TAV_NAMESPACE, f"tav-visual:{template_id}:{visual_id}:{profile_id}:{body_private_id}"))
            if root_id == new_visual_id or any(guid in occupied or guid in generated_ids for guid in (root_id, new_visual_id)):
                raise ValueError("Private Tav root/visual UUID collides with an existing resource")
            generated_ids.update((root_id, new_visual_id))
            root = copy.deepcopy(db.templates[template_id])
            visual = copy.deepcopy(original_visual)
            _set(root, "MapKey", root_id)
            _set(root, "Name", f"Nudegate_Tav_{profile_id}_{attrs(root).get('Name') or template_id}", "LSString")
            _set(root, "CharacterVisualResourceID", new_visual_id)
            _set(visual, "ID", new_visual_id)
            _set(visual, "Name", f"Nudegate_Tav_{profile_id}_{visual_fields.get('Name') or visual_id}", "LSString")
            _set(visual, "BodySetVisual", body_private_id)
            root_nodes.append(root)
            visual_nodes.append(visual)
            evidence = (f"Generic adult CC female BodyType=1, BodyShape={body_shape}; exact reviewed adult "
                        f"body source {body_id}; built compatible mesh {selected['mesh_name']}; complete ancestry "
                        "and inherited minor tags/names/stats checked. Only a new private root is emitted.")
            entry = {"original_template_id": template_id, "private_template_id": root_id,
                     "original_visual_id": visual_id, "private_visual_id": new_visual_id,
                     "original_body_set_visual": body_id, "private_body_set_visual": body_private_id,
                     "body_type": "1", "body_shape": body_shape, "profile_id": profile_id,
                     "family_id": selected["family_id"], "preset_ids": [],
                     "review": {"adult": True, "evidence": evidence}}
            report["templates"].append(entry)
            cloned_roots[template_id] = entry
        entry = cloned_roots[template_id]
        entry["preset_ids"].append(preset_id)
        modified_preset = copy.deepcopy(preset)
        _set(modified_preset, "RootTemplate", entry["private_template_id"], "guid")
        preset_nodes.append(modified_preset)
        report["presets"].append({"preset_id": preset_id, "original_template_id": template_id,
                                  "private_template_id": entry["private_template_id"],
                                  "body_type": "1", "body_shape": body_shape, "source": source_path,
                                  "review": entry["review"]})

    report["counts"] = {"source_presets": len(presets), "presets": len(preset_nodes),
                        "templates": len(root_nodes), "private_visuals": len(visual_nodes),
                        "skipped": len(report["skipped"]), "priority_replacements": priority_replacements}
    if not preset_nodes:
        return report
    documents = {
        "templates": _document("Templates", "Templates", root_nodes),
        "visuals": _document("CharacterVisualBank", "CharacterVisualBank", visual_nodes),
        "presets": _document("CharacterCreationPresets", "root", preset_nodes),
    }
    for key, data in documents.items():
        path = paths[key]
        if path.exists() and (not path.is_file() or path.read_bytes() != data):
            raise ValueError(f"Output collision with a different Tav artifact: {path}")
    for key, data in documents.items():
        path = paths[key]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    report["outputs"] = {key: str(path) for key, path in paths.items()}
    return report
