"""Register donor models on the matching elf body with its own skin and cloth settings."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid5
import xml.etree.ElementTree as ET

from build import run
from build_donor_probe import NAMESPACE, semantic, set_attr, sha
from npc_donor_resources import BANK_CONTAINER, SOURCE_BODY, publish_resources
from nudegate.core import attrs


ELF_BODY = "9e43f0e4-d063-d85c-87b4-470d569645db"
JIGGLE_MODULE = "The_Jiggle_Is_Up_7c842b2b-874a-0d28-aafc-1b55c106856d"
SOURCE_ROOT = Path.home() / ".cache/nudegate/bcb-analysis/jiggle"
SOURCE_HASHES = {
    SOURCE_BODY: "301b79e3215173032f0e7e8f2c4660a7a3768847a50c3829e75230c097d3882c",
    ELF_BODY: "62b2f4eaf804b906e443c04a6de86156fbf2fc7a85484876a23aec505f0cee2c",
}
SOURCE_MODEL_HASH = "9b96b5b2b16598cf694d5a2178e51f6d7edfdd97201e3127bcf7efc161535b92"


def _child(resource, kind):
    matches = resource.findall(f"./children/node[@id='{kind}']")
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one native {kind} on the donor body")
    return matches[0]


def _elf_fields(resource, human, elf):
    for kind, key in (("Objects", "MaterialID"), ("ClothParams", "AnimDriveSpringForce")):
        target = _child(resource, kind)
        if attrs(target)[key] != attrs(_child(human, kind))[key]:
            raise ValueError(f"Donor field differs from its native human source: {key}")
        set_attr(target, key, attrs(_child(elf, kind))[key])


def _read_sources():
    base = SOURCE_ROOT / "Public" / JIGGLE_MODULE / "Content/Assets/Characters"
    natives = []
    for family, body_id in (("Humans", SOURCE_BODY), ("Elves", ELF_BODY)):
        path = base / family / "[PAK]_Female_Body" / f"{body_id}.lsx"
        if sha(path) != SOURCE_HASHES[body_id]:
            raise ValueError(f"Original {family} body resource changed")
        records = ET.parse(path).findall(BANK_CONTAINER + "/node")
        if len(records) != 1 or attrs(records[0])["ID"] != body_id:
            raise ValueError("Original body bank must contain its single reviewed body ID")
        record = records[0]
        if sha(SOURCE_ROOT / attrs(record)["SourceFile"]) != SOURCE_MODEL_HASH:
            raise ValueError(f"Original {family} GR2 differs from the reviewed donor rig")
        natives.append(record)
    human, elf = natives
    adapted = deepcopy(human)
    for key in ("ID", "Name"):
        set_attr(adapted, key, attrs(elf)[key])
    _elf_fields(adapted, human, elf)
    if semantic(adapted) != semantic(elf):
        raise ValueError("Original elf and human body resources have additional differences")
    return human, elf


def stage_elf_donors(stage, divine, donors, requested_profiles):
    """Write elf body resources referencing the existing audited donor GR2 files."""
    result = {"resource_map": {}, "variants": [], "bank_relative": None, "bank_sha256": None,
              "counts": {"resources": 0, "meshes": 0}}
    profiles = sorted(set(requested_profiles))
    if not profiles:
        return result

    stage = Path(stage).resolve()
    bank_relative = Path(donors["bank_relative"])
    staged = stage / bank_relative
    if sha(staged) != donors["bank_sha256"]:
        raise ValueError("Staged donor resource bank changed")
    base_entries = {entry["variant_id"]: entry for entry in donors["variants"]}
    if not set(profiles).issubset(base_entries):
        raise ValueError("Requested elf donor profile is absent from the verified donor bank")
    human, elf = _read_sources()
    with TemporaryDirectory(prefix="npc-elf-donors-", dir=stage.parent) as temporary:
        work = Path(temporary)
        original = work / "donors.lsx"
        run(divine, "-a", "convert-resource", "-s", staged, "-d", original)
        tree = ET.parse(original)
        container = tree.find(BANK_CONTAINER)
        by_id = {attrs(record)["ID"]: record for record in container}
        if len(by_id) != len(container):
            raise ValueError("Staged donor bank contains duplicate IDs")
        aliases = []
        entries = []
        for profile in profiles:
            entry = base_entries[profile]
            record = deepcopy(by_id[entry["private_visual_id"]])
            values = attrs(record)
            if (entry["original_visual_id"] != SOURCE_BODY or values["SourceFile"] != entry["sourcefile"]
                    or sha(stage / values["SourceFile"]) != entry["model_sha256"]):
                raise ValueError(f"Staged geometry for {profile} differs from its verified donor")
            alias_id = str(uuid5(NAMESPACE, "npc-elf-body:" + entry["private_visual_id"]))
            if alias_id in by_id or alias_id in (SOURCE_BODY, ELF_BODY):
                raise ValueError("Private elf visual collides with an existing body")
            set_attr(record, "ID", alias_id)
            set_attr(record, "Name", f"Nudegate NPC elf body / {profile}")
            _elf_fields(record, human, elf)
            aliases.append(record)
            entries.append(dict(entry, original_visual_id=ELF_BODY, private_visual_id=alias_id,
                                material_ids=[attrs(_child(elf, "Objects"))["MaterialID"]],
                                native_elf_bank_sha256=SOURCE_HASHES[ELF_BODY]))
        container[:] = aliases
        source = work / "elf.lsx"
        compiled = work / "elf.lsf"
        readback = work / "verified.lsx"
        tree.write(source, encoding="utf-8", xml_declaration=True)
        run(divine, "-a", "convert-resource", "-s", source, "-d", compiled)
        run(divine, "-a", "convert-resource", "-s", compiled, "-d", readback)
        if semantic(ET.parse(readback).find(BANK_CONTAINER)) != semantic(container):
            raise ValueError("Elf material, physics or model references changed during LSF conversion")
        relative = bank_relative.with_name("elf-donors.lsf")
        publish_resources(stage, {relative: compiled})
        result.update(resource_map={ELF_BODY: entries}, variants=entries,
                      bank_relative=relative.as_posix(), bank_sha256=sha(compiled),
                      counts={"resources": len(entries), "meshes": 0},
                      shared_source_model_sha256=SOURCE_MODEL_HASH,
                      native_cloth_resource_round_trip="passed")
    return result
