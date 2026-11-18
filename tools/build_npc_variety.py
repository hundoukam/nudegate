"""Build and read back the adult NPC nudity and body-variety package."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET

from build import (REPO, Database, attrs, compile_patch, find_divine, package_order, prepare,
                   run, select_body_candidate, read_back_package)
from nudegate.core import CLOTHING_SLOTS
from npc_donor_resources import DEFAULT_INDEX, SOURCE_BODY, stage_donor_resources
from npc_native_resources import DEFAULT_NATIVE_MANIFEST, stage_native_resources
from npc_actor_sources import actor_sources
from npc_actor_visuals import compile_actor_visuals, filter_root_catalog, verify_actor_visuals
from npc_elf_donors import ELF_BODY, stage_elf_donors
from npc_mod_sources import overlay_active_mods


MODULE = "Nudegate"
PAK_NAME = "Nudegate-0.4.0-Body-Replacer.pak"
DEFAULT_DATA = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Baldurs Gate 3\Data")
DEFAULT_OUTPUT = REPO / "dist/Nudegate-Body-Replacer-0.4.0"
VERSION = str(4 * (1 << 47))


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plan_assignments(rows, catalog, donors, native_families):
    """Assign by reviewed identity and original body UUID, including alternate forms."""
    catalog_by_id = {row["template_id"]: row for row in catalog["adults"] if row.get("enabled", True)}
    native_choices = {
        original: [dict(variant_id=v["id"]) for v in family["variants"]]
        for family in native_families for original in family["original_visual_ids"]
    }
    pins = {}
    for row in catalog_by_id.values():
        if "donor_profile" in row:
            seed = row.get("body_seed", row["template_id"])
            profile = row["donor_profile"]
            if profile not in donors or pins.setdefault(seed, profile) != profile:
                raise ValueError(f"Invalid or conflicting reviewed donor for {seed}")
    planned = {}
    native_requests = defaultdict(set)
    for record in rows:
        identifier = record["template_id"]
        entry = catalog_by_id[identifier]
        source = record["body_set_visual"]
        seed = entry.get("body_seed", identifier)
        if source != entry.get("expected_body_set_visual", source):
            raise ValueError(f"Reviewed body set changed for {entry['expected_name']}")
        if "donor_profile" in entry and source not in (SOURCE_BODY, ELF_BODY):
            raise ValueError(f"Reviewed donor needs a matching body set for {entry['expected_name']}")
        if source in (SOURCE_BODY, ELF_BODY):
            if seed in pins:
                chosen = pins[seed]
            else:
                # Rendezvous hashing keeps a character's selection independent of other NPCs.
                chosen = max(sorted(donors), key=lambda p: hashlib.sha256(f"{seed}/{p}".encode()).digest())
        elif source in native_choices:
            chosen = select_body_candidate(native_choices[source], seed)[0]["variant_id"]
            native_requests[source].add(chosen)
        else:
            continue
        planned[identifier] = (source, chosen)
    return planned, native_requests


def apply_assignments(report, plan, resources):
    by_key = {(r["original_visual_id"], r["variant_id"]): r for r in resources}
    if len(by_key) != len(resources):
        raise ValueError("Duplicate source body and profile in package")
    path = Path(report["outputs"]["visuals"])
    doc = ET.parse(path)
    visuals = {attrs(n)["ID"]: n for n in doc.findall("./region/node/children/node")}
    for entry in report["templates"]:
        assignment = plan.get(entry["template_id"])
        if assignment is None:
            raise ValueError(f"Clothing may only change with a replacement body: {entry['name']}")
        selected = by_key[assignment]
        attribute = visuals[entry["private_visual_id"]].find('attribute[@id="BodySetVisual"]')
        if attribute is None or attribute.get("value") != selected["original_visual_id"]:
            raise ValueError(f"Source body mismatch for {entry['name']}")
        entry["original_body_set_visual"] = attribute.get("value")
        attribute.set("value", selected["private_visual_id"])
        entry["body_set_visual"] = selected["private_visual_id"]
        entry["profile"] = selected["variant_id"]
        entry["profile_label"] = selected["label"]
    doc.write(path, encoding="utf-8", xml_declaration=True)


def write_module(stage):
    tree = ET.parse(REPO / "mod/Mods/Nudegate/meta.lsx")
    info = tree.find('.//node[@id="ModuleInfo"]')
    values = {"Name": "Nudegate Body Replacer",
              "Description": "Body shape variety for existing adult NPCs using compatible standard bodies.",
              "Version64": VERSION}
    for key, value in values.items():
        info.find(f'attribute[@id="{key}"]').set("value", value)
    destination = stage / "Mods/Nudegate/meta.lsx"
    destination.parent.mkdir(parents=True, exist_ok=True)
    tree.write(destination, encoding="utf-8", xml_declaration=True)
    return attrs(info)


def verify_palette(verified, banks, templates):
    """Follow compiled NPC -> private body -> model links in the extracted PAK."""
    ids = set()
    for bank in banks:
        if not bank["variants"]:
            continue
        compiled = verified / bank["bank_relative"]
        if sha(compiled) != bank["bank_sha256"]:
            raise ValueError("Published VisualBank differs from the checked bank")
        nodes = ET.parse(compiled.with_suffix(".verified.lsx")).findall("./region/node/children/node")
        indexed = {attrs(n)["ID"]: attrs(n)["SourceFile"] for n in nodes}
        if len(indexed) != len(nodes) or set(indexed) != {v["private_visual_id"] for v in bank["variants"]}:
            raise ValueError("Unexpected body resource in published VisualBank")
        for row in bank["variants"]:
            key = row["private_visual_id"]
            path = indexed[key]
            if key in ids or path != row["sourcefile"] or sha(verified / path) != row["model_sha256"]:
                raise ValueError("A compiled resource points to the wrong body model")
            ids.add(key)
    assigned = {entry["body_set_visual"] for entry in templates if "profile" in entry}
    if not assigned.issubset(ids):
        raise ValueError("NPC references a missing private body")
    for path in verified.rglob("*"):
        if {"RootTemplates", "CharacterCreationPresets", "Levels", "Globals"}.intersection(path.parts):
            raise ValueError(f"Unexpected character or world record in body replacer: {path}")


def verify_retained_slots(db, rows, path):
    nodes = {attrs(n)["ID"]: n for n in ET.parse(path).findall("./region/node/children/node")}
    def retained(node):
        return sorted(tuple(sorted(attrs(slot).items())) for slot in node.findall("./children/node[@id='Slots']")
                      if attrs(slot).get("Slot") not in CLOTHING_SLOTS)
    for row in rows:
        if retained(db.visuals[row["original_visual_id"]]) != retained(nodes[row["private_visual_id"]]):
            raise ValueError(f"Head, hair or another retained slot changed on {row['name']}")


def write_roster(delivery, report, actor_catalog):
    catalog = {r["actor_id"]: r for r in actor_catalog["actors"]}
    placed = report["placed_npcs"]
    rows = {}
    for picture in placed["templates"]:
        for actor_id in picture["actor_ids"]:
            rows[actor_id] = (catalog[actor_id]["display_name"], picture)
    lines = ["Nudegate Body Replacer", "",
             f"{len(rows)} identified adult character placements in this game and mod profile.",
             "Some characters have multiple appearances. Each row describes one placed appearance.",
             "The package hides embedded clothing and equipment visuals on these records.",
             "The table is verified against the PAK. In-game appearance and physics still need testing.",
             "", "NPC | Body | Placement UUID"]
    for actor_id, (name, appearance) in sorted(rows.items(), key=lambda item: (item[1][0].casefold(), item[0])):
        lines.append(f"{name} | {appearance.get('profile_label', 'Original body')} | {actor_id}")
    (delivery / "NPC-roster.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    report["placed_coverage"] = {
        "distinct_actor_ids": len(rows),
        "with_blender_profile": sum(row.get("profile", "").startswith("donor_") for _, row in rows.values()),
        "with_native_profile": sum("profile" in row and not row["profile"].startswith("donor_")
                                   for _, row in rows.values()),
        "with_original_body": sum("profile" not in row for _, row in rows.values()),
    }


def build_package(args):
    output = args.output.resolve()
    if output.exists():
        raise ValueError(f"Output already exists. Choose a fresh --output directory: {output}")
    if not args.divine or not args.divine.is_file():
        raise ValueError("Pass --divine pointing to Divine.exe")
    packages = package_order(args.game_data)
    sources = prepare(args.game_data, args.divine, args.cache, packages)
    catalog = {"schema_version": 1, "adults": []}
    for path in (REPO / "config/adults.json", REPO / "config/npc_donor_adults.json"):
        part = read_json(path)
        if part["schema_version"] != 1:
            raise ValueError(f"Unsupported adult catalog {path}")
        catalog["adults"].extend(part["adults"])
    db = Database.load(sources, packages)
    actor_paths, source_report = actor_sources(args.game_data, packages, args.cache.parent / "npc-actors", args.divine)
    active_paths, overlay = overlay_active_mods(db, args.profile.parent.parent.parent / "Mods",
                                               args.profile, args.cache.parent / "npc-active-mods", args.divine)
    actor_paths.extend(active_paths)
    actor_catalog = read_json(REPO / "config/npc_actor_adults.json")
    actor_catalog["actors"].extend(read_json(REPO / "config/npc_replacer_placements.json")["actors"])
    native_families = read_json(DEFAULT_NATIVE_MANIFEST)["families"] if args.include_earlier_shapes else []
    compatible = {SOURCE_BODY, ELF_BODY} | {body for family in native_families for body in family["original_visual_ids"]}
    actor_catalog["actors"] = [entry for entry in actor_catalog["actors"]
                               if entry["expected_body_set_visual"] in compatible]
    catalog, inheritance = filter_root_catalog(db, actor_paths, catalog, actor_catalog)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="npc-variety-", dir=output.parent) as tmp:
        work = Path(tmp)
        generated, stage, delivery = work / "generated", work / "stage", work / "delivery"
        # Validate any template that also uses a selected appearance. Template
        # clones are review inputs in this mode and never enter the package.
        reviewed = compile_patch(db, catalog, work / "template-review")
        actors = compile_actor_visuals(db, actor_paths, actor_catalog, reviewed, generated, publish_roots=False)
        report = {"schema_version": 1, "character_templates_shipped": 0}
        donors = stage_donor_resources(args.index, stage, args.divine)
        donor_ids = {r["variant_id"] for r in donors["variants"]}
        assignment_rules = list(catalog["adults"])
        assignment_rules.extend(dict(entry, template_id=entry["actor_id"]) for entry in actor_catalog["actors"])
        appearance_rows = actors["templates"]
        plan, requested = plan_assignments(appearance_rows, {"adults": assignment_rules},
                                           donor_ids, native_families)
        if not appearance_rows or any(r["body_set_visual"] not in compatible for r in appearance_rows):
            raise ValueError("Expected existing characters with a reviewed standard body")
        elf_profiles = {profile for source, profile in plan.values() if source == ELF_BODY and profile in donor_ids}
        elves = stage_elf_donors(stage, args.divine, donors, elf_profiles)
        native = stage_native_resources(requested, stage, args.divine, manifest_path=DEFAULT_NATIVE_MANIFEST)
        palettes = (donors, elves, native)
        variants = [variant for bank in palettes for variant in bank["variants"]]
        apply_assignments(actors, plan, variants)
        for source in generated.rglob("*.lsx"):
            destination = stage / source.relative_to(generated).with_suffix(".lsf")
            destination.parent.mkdir(parents=True, exist_ok=True)
            run(args.divine, "-a", "convert-resource", "-s", source, "-d", destination)
        delivery.mkdir()
        report["module"] = write_module(stage)
        pak = delivery / PAK_NAME
        run(args.divine, "-a", "create-package", "-s", stage, "-d", pak)
        verified = work / "verify"
        read_back_package(args.divine, pak, stage, verified)
        verify_actor_visuals(verified, actors)
        verify_palette(verified, palettes, appearance_rows)
        visual_dir = verified / "Public/Nudegate/Content/[PAK]_CharacterVisuals"
        verify_retained_slots(db, actors["templates"], visual_dir / "placed-npcs.verified.lsx")
        report["package_sha256"] = sha(pak)
        actors["outputs"]["visuals"] = "Public/Nudegate/Content/[PAK]_CharacterVisuals/placed-npcs.lsf"
        report["placed_npcs"] = actors
        report["game_actor_sources"] = source_report
        report["active_mod_inputs"] = overlay
        report["source_root_reviews_skipped"] = inheritance["skipped_roots"]
        report["resources"] = {"blender_donors": donors, "elf_donors": elves, "native_profiles": native}
        report["placed_profile_counts"] = dict(Counter(e.get("profile", "original_body")
                                                      for e in actors["templates"] for _ in e["actor_ids"]))
        report["validation"] = {"package_round_trip": "passed", "outfit_slots_and_equipment_flags": "passed",
                                "body_resource_and_model_hashes": "passed", "effective_head_and_other_retained_slots": "passed",
                                "in_game": "not tested"}
        report["outputs"] = {"package": PAK_NAME}
        write_roster(delivery, report, actor_catalog)
        (delivery / "npc-variety-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        delivery.rename(output)
    print(output / PAK_NAME)
    print(json.dumps({"roots": 0, "placed": actors["counts"],
                      "placed_profiles": report["placed_profile_counts"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--cache", type=Path, default=Path.home() / ".cache/nudegate/sources")
    parser.add_argument("--profile", type=Path, default=Path(os.environ.get("LOCALAPPDATA", ""))
                        / "Larian Studios/Baldur's Gate 3/PlayerProfiles/Public/modsettings.lsx")
    parser.add_argument("--divine", type=Path, default=find_divine())
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--include-earlier-shapes", action="store_true")
    build_package(parser.parse_args())
