"""Stage the six reviewed donor bodies and their fitted cloth for an NPC package."""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
from tempfile import TemporaryDirectory
from uuid import uuid5
import xml.etree.ElementTree as ET

from build import run
from build_donor_probe import (
    MESH, MODULE as PROBE_MODULE, NAMESPACE, SOURCE_BODY, private_resource,
    semantic, set_attr, sha, verify_source_bank,
)
from bundle_donor_probes import ROOT, collect
from nudegate.core import attrs


DEFAULT_INDEX = ROOT / "build/donors/accepted-six-donor-validation-index.json"
BANK_CONTAINER = "./region[@id='VisualBank']/node/children"
PROBE_BANK = Path("Public") / PROBE_MODULE / "Content/[PAK]_BodyVisuals/donor.lsf"


def _relocate(resource, model_path, module, profile):
    """Change only ownership and file references on a verified probe resource."""
    values = attrs(resource)
    old_prefix = model_path.with_suffix("").as_posix()
    if (values["SourceFile"] != model_path.as_posix()
            or not values["Template"].startswith(old_prefix + ".")):
        raise ValueError(f"Unexpected model or template reference for {profile}")
    relative = Path("Public") / module / "Assets/NpcDonors" / profile / model_path.name
    private_id = str(uuid5(NAMESPACE, f"npc-body:{module}:{SOURCE_BODY}:{profile}"))
    for key, value in {
        "ID": private_id, "Name": f"Nudegate NPC body / {profile}",
        "SourceFile": relative.as_posix(),
        "Template": relative.with_suffix("").as_posix() + values["Template"][len(old_prefix):],
    }.items():
        set_attr(resource, key, value)
    return relative, private_id


def _read_probe(package, work, divine, module):
    profile = package["profile"]
    report = json.loads(Path(package["report"]).read_text(encoding="utf-8"))
    model_hash = package["model_sha256"]
    mapping_pin = report["mapping_report"]
    mapping_file = Path(mapping_pin["path"])
    if sha(mapping_file) != mapping_pin["sha256"]:
        raise ValueError(f"Cloth mapping report changed for {profile}")
    mapping = json.loads(mapping_file.read_text(encoding="utf-8"))
    if mapping.get("validation_status") != "passed" or mapping["source_sha256"] != model_hash:
        raise ValueError(f"Cloth mapping targets a different model for {profile}")
    source_bank = Path(report["source_bank"]["path"])
    verify_source_bank(source_bank)
    _, expected, model_relative, probe_id = private_resource(source_bank, mapping, profile)
    if probe_id != package["private_body_id"]:
        raise ValueError(f"Unexpected probe resource ID for {profile}")

    # Extract to temporary storage. Only the audited model and body VisualBank
    # are eligible to enter the NPC package.
    extracted = work / profile
    run(divine, "-a", "extract-package", "-s", package["package"], "-d", extracted)
    model = extracted / model_relative
    bank = extracted / PROBE_BANK
    if (sha(model) != model_hash or sha(bank) != report["files"][PROBE_BANK.as_posix()]):
        raise ValueError(f"Packaged model or physics resource changed for {profile}")
    decoded = work / f"{profile}.lsx"
    run(divine, "-a", "convert-resource", "-s", bank, "-d", decoded)
    tree = ET.parse(decoded)
    records = tree.findall(BANK_CONTAINER + "/node")
    if len(records) != 1 or semantic(records[0]) != semantic(expected):
        raise ValueError(f"Decoded resource does not contain the reviewed cloth and rig for {profile}")
    resource = records[0]
    relative, npc_id = _relocate(resource, model_relative, module, profile)
    entry = {
        "family_id": "human_elf_f", "variant_id": profile, "label": package["label"],
        "original_visual_id": SOURCE_BODY, "private_visual_id": npc_id,
        "model_relative": relative.as_posix(), "sourcefile": relative.as_posix(),
        "model_sha256": model_hash,
        "mesh_name": MESH, "physics": "fitted native breast cloth, offline verified",
        "mapping_sha256": mapping["mapping"]["sha256_raw"],
        "source_probe_id": probe_id, "source_package_sha256": package["package_sha256"],
    }
    return tree, resource, model, entry


def publish_resources(stage, files):
    """Copy verified inputs without overwriting existing staged resources."""
    created = []
    try:
        for relative, path in files.items():
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            with path.open("rb") as src, destination.open("xb") as dst:
                created.append(destination)
                shutil.copyfileobj(src, dst)
    except BaseException:
        for destination in created:
            destination.unlink(missing_ok=True)
        raise


def stage_donor_resources(index_path, stage, divine, module="Nudegate"):
    """Write six GR2 files and one verified LSF. Return the compatible body palette."""
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,60}", module) or module == PROBE_MODULE:
        raise ValueError("Expected a distinct NPC module folder")
    stage = Path(stage).resolve()
    stage.mkdir(parents=True, exist_ok=True)
    manifest, _ = collect(Path(index_path))
    bank_relative = Path("Public") / module / "Content/[PAK]_BodyVisuals/_merged.lsf"
    with TemporaryDirectory(prefix="npc-donor-resources-", dir=stage.parent) as temporary:
        work = Path(temporary)
        resources = []
        entries = []
        files = {}
        for package in manifest["packages"]:
            tree, resource, model, entry = _read_probe(package, work, divine, module)
            entries.append(entry)
            resources.append(resource)
            files[Path(entry["model_relative"])] = model
        npc_ids = {entry["private_visual_id"] for entry in entries}
        probe_ids = {entry["source_probe_id"] for entry in entries}
        if len(npc_ids) != 6 or len(files) != 6 or npc_ids & (probe_ids | {SOURCE_BODY}):
            raise ValueError("Six distinct private NPC body resources and models are required")
        container = tree.find(BANK_CONTAINER)
        container[:] = resources
        source = work / "npc-donors.lsx"
        compiled = work / "npc-donors.lsf"
        decoded = work / "verified.lsx"
        tree.write(source, encoding="utf-8", xml_declaration=True)
        run(divine, "-a", "convert-resource", "-s", source, "-d", compiled)
        run(divine, "-a", "convert-resource", "-s", compiled, "-d", decoded)
        readback = ET.parse(decoded).find(BANK_CONTAINER)
        if readback is None or semantic(readback) != semantic(container):
            raise ValueError("NPC body resources changed during LSF conversion")
        files[bank_relative] = compiled

        # Publish only after every model/mapping has passed. Preserve any file
        # already in the caller's stage, including on a concurrent retry.
        publish_resources(stage, files)
    return {
        "resource_map": {SOURCE_BODY: entries}, "variants": entries,
        "bank_relative": bank_relative.as_posix(), "bank_sha256": sha(stage / bank_relative),
        "validation_index_sha256": manifest["validation_index_sha256"],
        "native_cloth_resource_round_trip": "passed",
    }
