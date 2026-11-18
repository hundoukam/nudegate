"""Reuse selected original-v0.2 body shapes with their original game materials."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid5
import xml.etree.ElementTree as ET

from build import run
from build_donor_probe import NAMESPACE, semantic, set_attr, sha
from npc_donor_resources import BANK_CONTAINER, ROOT, publish_resources
from nudegate.core import attrs


DEFAULT_NATIVE_MANIFEST = ROOT / "build/collections/original-v0.2/body-build.json"
MANIFEST_SHA256 = "de9bb6445c14b608b7cf99a3d8d9cc1c380681126343beb7949a6c36d97c9f71"
ARCHIVE_SHA256 = "483b2ad2d5229bdd8a2d00da023aa5d76c8341ecaace0d47ff41977a7c27b0d2"
REPORT_SHA256 = "f78b91f82e5c5aae0d8e09b7d97e1f2b61e33683f58a18928e28c6014b7aa3cb"
ORIGINAL_BANK = Path("Public/Nudegate/Content/[PAK]_BodyVisuals/_merged.lsf")
NATIVE_BANK = ORIGINAL_BANK.with_name("native.lsf")


def _restore_materials(resource, entry, native_to_private):
    """Restore the exact native material reference on every selected render LOD."""
    objects = resource.findall("./children/node[@id='Objects']")
    expected = entry.get("lods")
    if expected is None:
        if len(entry["original_material_ids"]) != 1:
            raise ValueError("Ambiguous original single-LOD material")
        expected = [{"lod": 0, "original_material_id": entry["original_material_ids"][0],
                     "object_id": f"{entry['variant_id']}.{entry['mesh_name']}.0"}]
    by_lod = {row["lod"]: row for row in expected}
    if sorted(int(attrs(obj)["LOD"]) for obj in objects) != sorted(by_lod):
        raise ValueError("LOD set differs from the validated native profile")
    for obj in objects:
        values = attrs(obj)
        row = by_lod[int(values["LOD"])]
        original = row["original_material_id"]
        if (values["MaterialID"] != native_to_private[original]
                or values["ObjectID"] != row["object_id"]):
            raise ValueError("Object or material differs from the reviewed LOD")
        set_attr(obj, "MaterialID", original)
    return len(objects)


def stage_native_resources(requested, stage, divine, manifest_path=DEFAULT_NATIVE_MANIFEST):
    """Stage exactly the requested {original body UUID: set of profile IDs} pairs."""
    wanted = {(body_id, profile) for body_id, profiles in requested.items() for profile in profiles}
    result = {"resource_map": {}, "variants": [], "bank_relative": None, "bank_sha256": None,
              "counts": {"resources": 0, "meshes": 0}}
    if not wanted:
        return result
    manifest_path = Path(manifest_path)
    snapshot = manifest_path.parent / "snapshot/dist"
    archive = snapshot / "Nudegate-0.2.0-plush-tav-study.pak"
    report_path = snapshot / "body-study-report.json"
    if any(sha(path) != expected for path, expected in (
            (manifest_path, MANIFEST_SHA256), (archive, ARCHIVE_SHA256), (report_path, REPORT_SHA256))):
        raise ValueError("The frozen original-v0.2 manifest, package or report changed")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    models = {
        (body_id, variant["id"]): (family["id"], variant["gr2_sha256"])
        for family in manifest["families"]
        for body_id in family["original_visual_ids"]
        for variant in family["variants"]
    }
    accepted = {(row["original_visual_id"], row["variant_id"]): row
                for row in report["body_resources"]["variants"]}
    if not wanted.issubset(models.keys() & accepted.keys()):
        raise ValueError("A requested native body/profile pair is outside the validated collection")
    stage = Path(stage).resolve()
    stage.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="npc-native-resources-", dir=stage.parent) as temporary:
        work = Path(temporary)
        extracted = work / "original"
        run(divine, "-a", "extract-package", "-s", archive, "-d", extracted)
        decoded = work / "original.lsx"
        run(divine, "-a", "convert-resource", "-s", extracted / ORIGINAL_BANK, "-d", decoded)
        tree = ET.parse(decoded)
        container = tree.find(BANK_CONTAINER)
        by_id = {attrs(node)["ID"]: node for node in container}
        material_map = report["skin_materials"]["material_map"]
        files = {}
        selected = []
        for key in sorted(wanted):
            body_id, profile = key
            row = accepted[key]
            family, digest = models[key]
            model = extracted / row["sourcefile"]
            if row["family_id"] != family or digest != row["source_gr2_sha256"] or sha(model) != digest:
                raise ValueError(f"The model differs from the frozen native shape for {key}")
            resource = by_id[row["private_visual_id"]]
            old = attrs(resource)
            model_prefix = row["sourcefile"].rsplit(".", 1)[0]
            if old["SourceFile"] != row["sourcefile"] or old["Template"] != model_prefix + "." + row["model_name"] + ".0":
                raise ValueError(f"Unexpected model path in native body {key}")
            lod_count = _restore_materials(resource, row, material_map)
            relative = Path("Generated/Public/Nudegate/Assets/NpcNative") / family / model.name
            private_id = str(uuid5(NAMESPACE, "npc-native:" + row["private_visual_id"]))
            set_attr(resource, "ID", private_id)
            set_attr(resource, "Name", f"Nudegate NPC native body / {family} / {profile} / {body_id}")
            set_attr(resource, "SourceFile", relative.as_posix())
            set_attr(resource, "Template", relative.with_suffix("").as_posix() + "." + row["model_name"] + ".0")
            selected.append(resource)
            files[relative] = model
            entry = {
                "family_id": family, "variant_id": profile, "label": row["variant_label"],
                "original_visual_id": body_id, "private_visual_id": private_id,
                "sourcefile": relative.as_posix(), "model_relative": relative.as_posix(),
                "mesh_name": row["mesh_name"], "model_sha256": digest,
                "lod_count": lod_count, "material_ids": row["original_material_ids"],
                "physics": "static skinned body",
            }
            result["variants"].append(entry)
            result["resource_map"].setdefault(body_id, []).append(entry)
        container[:] = selected
        source = work / "native.lsx"
        compiled = work / "native.lsf"
        verified = work / "verified.lsx"
        tree.write(source, encoding="utf-8", xml_declaration=True)
        run(divine, "-a", "convert-resource", "-s", source, "-d", compiled)
        run(divine, "-a", "convert-resource", "-s", compiled, "-d", verified)
        readback = ET.parse(verified).find(BANK_CONTAINER)
        if readback is None or semantic(readback) != semantic(container):
            raise ValueError("Native body set changed during LSF conversion")
        result.update(bank_relative=NATIVE_BANK.as_posix(), bank_sha256=sha(compiled),
                      counts={"resources": len(selected), "meshes": len(files)})
        files[NATIVE_BANK] = compiled
        publish_resources(stage, files)
    return result
