"""Change placed NPC appearances only when every known consumer is reviewed."""

from __future__ import annotations

from collections import defaultdict
import copy
from pathlib import Path
import xml.etree.ElementTree as ET

from nudegate.core import (
    CLOTHING_SLOTS, MINOR_BASES, MINOR_TAGS, MINOR_TEXT, ZERO_UUID,
    _document, _set_attr, _uuid, attrs,
)


ACTOR_BANK = Path("Public/Nudegate/Content/[PAK]_CharacterVisuals/placed-npcs.lsf")


def _minor_evidence(node):
    values = attrs(node)
    for key in ("Name", "Stats"):
        if MINOR_TEXT.search(values.get(key) or ""):
            return f"minor indication in {key}"
    for tag in node.findall("./children/node[@id='Tags']//attribute"):
        if (tag.get("value") or "").lower() in MINOR_TAGS:
            return "minor tag"
    return None


def _read_actors(db, paths):
    if not paths:
        raise ValueError("Complete native placement inventory is required")
    actors = {}
    inherited = {}
    for path in paths:
        tree = ET.parse(path)
        container = tree.find("./region[@id='Templates']/node[@id='Templates']/children")
        if container is None:
            raise ValueError(f"Missing Templates inventory region in {path}")
        for node in container:
            if node.get("id") != "GameObjects":
                raise ValueError(f"Unknown placed actor record in {path}")
            values = attrs(node)
            if len(values) != len(node.findall("attribute")) or values.get("Type") != "character":
                raise ValueError(f"Ambiguous placed character record in {path}")
            actor_id = _uuid(values.get("MapKey"), "placed actor ID")
            parent = _uuid(values.get("TemplateName"), "placed actor template")
            if actor_id in actors:
                raise ValueError(f"Ambiguous placed actor definition for {actor_id}")
            if parent not in inherited:
                inherited[parent] = db.effective_attr(parent, "CharacterVisualResourceID")
            own = values.get("CharacterVisualResourceID")
            # A zero-valued override is ambiguous. Include inherited consumers
            # conservatively, but do not accept such an actor for an override.
            ambiguous = "CharacterVisualResourceID" in values and own in (None, "", ZERO_UUID)
            visual = inherited[parent] if not own or ambiguous else _uuid(own, "placed character visual")
            actors[actor_id] = {
                "actor_id": actor_id, "name": values.get("Name"), "parent_id": parent,
                "effective_visual": visual, "explicit": bool(own) and not ambiguous,
                "ambiguous": ambiguous, "minor": _minor_evidence(node),
                "source": Path(path).as_posix(),
            }
    return actors


def _template_consumers(db, visual_ids):
    """Find root visuals plus every descendant that inherits them."""
    consumers = defaultdict(set)
    for root_id, node in db.templates.items():
        visual_id = attrs(node).get("CharacterVisualResourceID")
        if visual_id not in visual_ids:
            continue
        pending = [root_id]
        while pending:
            current = pending.pop()
            if current in consumers[visual_id]:
                continue
            consumers[visual_id].add(current)
            pending.extend(child for child in db.direct_children(current)
                           if attrs(db.templates[child]).get("CharacterVisualResourceID") in (None, "", ZERO_UUID))
    return consumers


def _check_catalog_actor(db, actual, entry):
    review = entry.get("review", {})
    if (review.get("adult") is not True or not isinstance(review.get("evidence"), str)
            or not review["evidence"].strip()):
        return "missing explicit adult evidence"
    if actual["ambiguous"] or actual["minor"]:
        return actual["minor"] or "ambiguous explicit visual"
    if (not entry.get("expected_name") or actual["name"] != entry.get("expected_name")
            or actual["parent_id"] != entry.get("template_id")
            or ("expected_visual_id" in entry and actual["effective_visual"] != entry["expected_visual_id"])):
        return "actor name, parent or visual differs from reviewed record"
    parent = actual["parent_id"]
    if db.effective_attr(parent, "Type") != "character":
        return "parent is not a character"
    for ancestor in db.ancestry(parent):
        if ancestor in MINOR_BASES or _minor_evidence(db.templates[ancestor]):
            return "minor evidence in placed actor parent chain"
    if db.inherited_tags(parent) & MINOR_TAGS:
        return "minor tag on placed actor parent chain"
    return None


def filter_root_catalog(db, actor_paths, root_catalog, actor_catalog):
    """Exclude a root if its patch could reach even one unreviewed placement."""
    paths = list(actor_paths)
    actors = _read_actors(db, paths)
    known = {}
    for kind in ("actors", "root_inheritors"):
        for entry in actor_catalog.get(kind, []):
            actor_id = _uuid(entry.get("actor_id"), "reviewed actor ID")
            if actor_id in known:
                raise ValueError(f"Duplicate actor review for {actor_id}")
            known[actor_id] = entry
    roots = {row["template_id"] for row in root_catalog["adults"] if row.get("enabled", True)}
    inherited = defaultdict(list)
    blocked = defaultdict(list)
    for actor in actors.values():
        if actor["explicit"]:
            continue
        parent = actor["parent_id"]
        impacted = []
        for ancestor in db.ancestry(parent):
            if ancestor in roots:
                impacted.append(ancestor)
            explicit_visual = attrs(db.templates[ancestor]).get("CharacterVisualResourceID")
            if explicit_visual not in (None, "", ZERO_UUID):
                break
        if not impacted:
            continue
        review = known.get(actor["actor_id"])
        reason = "unreviewed inheriting placement"
        if review is not None:
            reason = _check_catalog_actor(db, actor, review)
            visual = db.visuals.get(actor["effective_visual"])
            if reason is None and "expected_body_set_visual" in review:
                if visual is None or attrs(visual).get("BodySetVisual") != review["expected_body_set_visual"]:
                    reason = "inherited body set changed from placed visual review"
        for root in impacted:
            if reason is not None:
                blocked[root].append({"actor_id": actor["actor_id"], "name": actor["name"], "reason": reason})
            else:
                inherited[root].append({**actor, "review_evidence": review["review"]["evidence"]})
    filtered = dict(root_catalog, adults=[entry for entry in root_catalog["adults"]
                                         if entry["template_id"] not in blocked])
    return filtered, {
        "placed_characters_scanned": len(actors), "placement_sources": len(paths),
        "inheriting_actors_by_root": {root: rows for root, rows in inherited.items() if root not in blocked},
        "skipped_roots": [{"template_id": root, "blocked_by": blocked[root]} for root in sorted(blocked)],
    }


def compile_actor_visuals(db, actor_paths, actor_catalog, core_report, generated, *, publish_roots=True):
    paths = list(actor_paths)
    actors = _read_actors(db, paths)
    if actor_catalog.get("schema_version") != 1 or not isinstance(actor_catalog.get("actors"), list):
        raise ValueError("Expected schema version 1 placed adult catalog")
    catalog = {}
    candidates = defaultdict(list)
    for entry in actor_catalog["actors"]:
        identifier = _uuid(entry["actor_id"], "reviewed placed actor ID")
        visual = _uuid(entry["expected_visual_id"], "reviewed placed character visual")
        if identifier in catalog:
            raise ValueError(f"Repeated actor ID in catalog: {identifier}")
        catalog[identifier] = entry
        candidates[visual].append(identifier)

    core_ids = {r["template_id"] for r in core_report["templates"] if r.get("review_evidence")}
    root_consumers = _template_consumers(db, set(candidates))
    actor_consumers = defaultdict(set)
    for actual in actors.values():
        if actual["effective_visual"] in candidates:
            actor_consumers[actual["effective_visual"]].add(actual["actor_id"])
    reports, covered_actors, skipped, output_nodes = [], [], [], []
    for visual, group in sorted(candidates.items()):
        group = sorted(group)
        reason = None
        unknown_roots = root_consumers[visual] - core_ids
        unknown_actors = actor_consumers[visual] - set(group)
        if unknown_roots or unknown_actors:
            reason = "character visual has additional unreviewed consumers"
        elif set(group) != actor_consumers[visual]:
            reason = "reviewed actor or its visual no longer matches the placement inventory"
        else:
            for identifier in group:
                reason = _check_catalog_actor(db, actors[identifier], catalog[identifier])
                if reason:
                    break
        expected_bodies = {catalog[i]["expected_body_set_visual"] for i in group}
        original = db.visuals.get(visual)
        if reason is None:
            if original is None:
                reason = "missing character visual resource"
            else:
                values = attrs(original)
                slots = original.findall("./children/node[@id='Slots']")
                if (expected_bodies != {values.get("BodySetVisual")}
                        or not values.get("BaseVisual") or values["BaseVisual"] == ZERO_UUID
                        or _minor_evidence(original)
                        or not any(attrs(slot).get("Slot") == "Head" and attrs(slot).get("VisualResource")
                                   for slot in slots)):
                    reason = "changed body set, missing head/base, or minor visual evidence"
        seeds = {(catalog[i].get("body_seed", i), catalog[i].get("donor_profile")) for i in group}
        if reason is None and len(seeds) != 1:
            reason = "one visual has conflicting reviewed body assignments"
        if reason:
            skipped.append({"visual_id": visual, "actors": group, "reason": reason,
                            "unreviewed_template_ids": sorted(unknown_roots),
                            "unreviewed_actor_ids": sorted(unknown_actors)})
            continue
        needs_patch = [i for i in group if not publish_roots or actors[i]["explicit"] or actors[i]["parent_id"] not in core_ids]
        for i in group:
            covered_actors.append({**actors[i], "review_evidence": catalog[i]["review"]["evidence"],
                                   "coverage": "placed_visual" if i in needs_patch else "inherited_root"})
        if not needs_patch:
            continue
        first = needs_patch[0]
        clone = copy.deepcopy(original)
        _set_attr(clone, "ShowEquipmentVisuals", "False", "bool")
        removed = []
        children = clone.find("children")
        for slot in list(children):
            if slot.get("id") == "Slots" and attrs(slot).get("Slot") in CLOTHING_SLOTS:
                removed.append(attrs(slot))
                children.remove(slot)
        output_nodes.append(clone)
        reports.append({"template_id": first, "name": actors[first]["name"],
                        "original_visual_id": visual, "private_visual_id": visual,
                        "body_set_visual": attrs(original)["BodySetVisual"],
                        "base_visual": attrs(original)["BaseVisual"], "removed_slots": removed,
                        "actor_ids": needs_patch, "reviewed_template_consumers": sorted(root_consumers[visual])})
    source = Path(generated) / ACTOR_BANK.with_suffix(".lsx")
    source.parent.mkdir(parents=True, exist_ok=True)
    content = ET.tostring(_document("CharacterVisualBank", output_nodes).getroot(),
                          encoding="utf-8", xml_declaration=True)
    with source.open("xb") as stream:
        stream.write(content)
    return {"templates": reports, "actors": covered_actors, "skipped": skipped,
            "outputs": {"visuals": str(source)},
            "counts": {"placement_sources": len(paths), "placed_characters_scanned": len(actors),
                       "visual_overrides": len(output_nodes), "reviewed_actors": len(covered_actors)},
            "scope": "Current native template and placed-character visual references. Dynamic script or save overrides require game testing."}


def verify_actor_visuals(verified_dir, report):
    path = Path(verified_dir) / ACTOR_BANK.with_suffix(".verified.lsx")
    tree = ET.parse(path)
    nodes = tree.findall("./region[@id='CharacterVisualBank']/node/children/node[@id='Resource']")
    indexed = {attrs(node)["ID"]: node for node in nodes}
    if len(indexed) != len(nodes) or set(indexed) != {row["original_visual_id"] for row in report["templates"]}:
        raise ValueError("Compiled placed visual IDs differ from the admitted roster")
    for row in report["templates"]:
        node = indexed[row["original_visual_id"]]
        values = attrs(node)
        if (values.get("ShowEquipmentVisuals", "").lower() != "false"
                or values.get("BaseVisual") != row["base_visual"] or values.get("BodySetVisual") != row["body_set_visual"]
                or any(attrs(slot).get("Slot") in CLOTHING_SLOTS for slot in node.findall("./children/node[@id='Slots']"))):
            raise ValueError(f"Compiled placed appearance changed for {row['name']}")
