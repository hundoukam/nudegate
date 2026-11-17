"""Compile reviewed adult root templates into private character visuals.

Game data is read from a local LSLib extraction.  Shared game resources are
never modified: each admitted template receives its own cloned visual.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Iterable
from uuid import UUID, uuid5
import xml.etree.ElementTree as ET


ZERO_UUID = "00000000-0000-0000-0000-000000000000"
PRIVATE_NAMESPACE = UUID("cf489c15-992c-5753-8193-7535e902d70e")
MINOR_TAGS = {
    "ee978587-6c68-4186-9bfc-3b3cc719a835",  # KID
    "88730ec2-439e-4172-95f4-b7f1875169fa",  # GOBLIN_KID
}
MINOR_BASES = {"1ccae813-70c3-4be7-843c-0ddf1b6fe5c3"}  # BASE_Children
MINOR_TEXT = re.compile(r"child|kid|teen|young|baby|adolescent", re.IGNORECASE)
CLOTHING_SLOTS = frozenset(
    {"Body", "Underwear", "Gloves", "Footwear", "Cloak", "Headwear"}
)
MODULE_ORDER = ("Shared", "SharedDev", "Gustav", "GustavDev", "GustavX", "Honour")


def attrs(node: ET.Element) -> dict[str, str | None]:
    """Return the node's direct attributes, without reading nested objects."""
    return {item.attrib["id"]: item.get("value") for item in node.findall("attribute")}


def _uuid(value: str, label: str) -> str:
    try:
        result = str(UUID(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError(f"{label} must be a UUID: {value!r}") from exc
    if result == ZERO_UUID:
        raise ValueError(f"{label} must not be the zero UUID")
    return result


def _set_attr(node: ET.Element, key: str, value: str, kind: str = "FixedString") -> None:
    matches = node.findall(f'attribute[@id="{key}"]')
    if len(matches) > 1:
        raise ValueError(f"Duplicate {key} attribute in {node.get('id')}")
    if matches:
        matches[0].set("value", value)
    else:
        node.insert(len(node.findall("attribute")), ET.Element(
            "attribute", {"id": key, "type": kind, "value": value}
        ))


def _fingerprint(node: ET.Element) -> bytes:
    """Ignore XML indentation when checking duplicate resource definitions."""
    clean = copy.deepcopy(node)
    for item in clean.iter():
        if not (item.text or "").strip():
            item.text = None
        if not (item.tail or "").strip():
            item.tail = None
    return ET.tostring(clean, encoding="utf-8")


@dataclass
class Database:
    templates: dict[str, ET.Element] = field(default_factory=dict)
    visuals: dict[str, ET.Element] = field(default_factory=dict)
    template_sources: dict[str, dict[str, str]] = field(default_factory=dict)
    visual_sources: dict[str, dict[str, str]] = field(default_factory=dict)
    package_order: list[str] = field(default_factory=list)
    _children: dict[str, set[str]] | None = field(default=None, init=False, repr=False)
    _children_count: int = field(default=-1, init=False, repr=False)

    @classmethod
    def load(cls, source_root: Path, package_order: list[str]) -> "Database":
        """Read package directories in priority order (the last package wins).

        Each package directory contains Public/<module>/RootTemplates/*.lsx
        and/or Public/<module>/Content/[PAK]_CharacterVisuals/*.lsx.  Files
        ending .lsf.lsx are also accepted as ordinary .lsx files.
        """
        source_root = Path(source_root)
        if not source_root.is_dir():
            raise ValueError(f"Game source directory does not exist: {source_root}")
        if not package_order or len(package_order) != len(set(package_order)):
            raise ValueError("package_order must be a nonempty list without duplicates")
        db = cls(package_order=list(package_order))
        for package in package_order:
            if Path(package).name != package or package in {".", ".."}:
                raise ValueError(f"Invalid package directory name: {package!r}")
            package_path = source_root / package
            if not package_path.is_dir():
                raise ValueError(f"Missing extracted package directory: {package_path}")
            seen: dict[tuple[str, str, str], ET.Element] = {}
            def source_order(path: Path) -> tuple[int, str, str]:
                relative_parts = path.relative_to(package_path).parts
                module = relative_parts[1] if len(relative_parts) > 1 and relative_parts[0] == "Public" else ""
                priority = MODULE_ORDER.index(module) if module in MODULE_ORDER else len(MODULE_ORDER)
                return priority, module, path.as_posix()

            for path in sorted(package_path.rglob("*.lsx"), key=source_order):
                parts = path.relative_to(package_path).parts
                if len(parts) < 3 or parts[0] != "Public":
                    continue
                module = parts[1]
                if "RootTemplates" in parts:
                    kind, id_key, index, sources = (
                        "template", "MapKey", db.templates, db.template_sources
                    )
                    xpath = './region[@id="Templates"]/node[@id="Templates"]/children/node[@id="GameObjects"]'
                elif "[PAK]_CharacterVisuals" in parts:
                    kind, id_key, index, sources = (
                        "visual", "ID", db.visuals, db.visual_sources
                    )
                    xpath = './region[@id="CharacterVisualBank"]/node[@id="CharacterVisualBank"]/children/node[@id="Resource"]'
                else:
                    continue
                try:
                    document = ET.parse(path)
                except (ET.ParseError, OSError) as exc:
                    raise ValueError(f"Cannot parse game source {path}: {exc}") from exc
                for node in document.findall(xpath):
                    identifier = _uuid(attrs(node).get(id_key), f"{kind} {id_key} in {path}")
                    key = (module, kind, identifier)
                    if key in seen and _fingerprint(seen[key]) != _fingerprint(node):
                        raise ValueError(f"Conflicting {kind} {identifier} within package {package}, module {module}")
                    seen[key] = node
                    index[identifier] = node
                    sources[identifier] = {
                        "package": package,
                        "module": module,
                        "path": path.relative_to(source_root).as_posix(),
                    }
        if not db.templates or not db.visuals:
            raise ValueError("Game source must contain root templates and character visuals")
        return db

    def ancestry(self, template_id: str) -> tuple[str, ...]:
        """Resolve the complete chain, refusing missing parents and cycles."""
        current = _uuid(template_id, "template_id")
        chain: list[str] = []
        while current:
            if current in chain:
                raise ValueError(f"Template inheritance cycle: {' -> '.join(chain + [current])}")
            if current not in self.templates:
                raise ValueError(f"Missing template in inheritance chain: {current}")
            chain.append(current)
            parent = attrs(self.templates[current]).get("ParentTemplateId")
            if not parent or parent == ZERO_UUID:
                break
            current = _uuid(parent, f"ParentTemplateId of {current}")
        return tuple(chain)

    def effective_attr(self, template_id: str, key: str) -> str | None:
        chain = self.ancestry(template_id)
        for identifier in chain:
            values = attrs(self.templates[identifier])
            if key in values:
                return values[key]
        return None

    def inherited_tags(self, template_id: str) -> set[str]:
        """Union tags across the chain so a local override cannot hide a veto."""
        tags: set[str] = set()
        for identifier in self.ancestry(template_id):
            for node in self.templates[identifier].findall('./children/node[@id="Tags"]'):
                for attribute in node.iter("attribute"):
                    value = attribute.get("value", "")
                    try:
                        tags.add(str(UUID(value)))
                    except ValueError:
                        continue
        return tags

    def _child_index(self) -> dict[str, set[str]]:
        if self._children is None or self._children_count != len(self.templates):
            children: dict[str, set[str]] = {}
            for identifier, node in self.templates.items():
                parent = attrs(node).get("ParentTemplateId")
                if parent:
                    children.setdefault(parent.lower(), set()).add(identifier)
            self._children = children
            self._children_count = len(self.templates)
        return self._children

    def direct_children(self, template_id: str) -> set[str]:
        """Return immediate children, used to verify inheritance barriers."""
        template_id = _uuid(template_id, "template_id")
        if template_id not in self.templates:
            raise ValueError(f"Unknown template: {template_id}")
        return set(self._child_index().get(template_id, set()))

    def descendants(self, template_id: str) -> set[str]:
        """Find all transitive children, including malformed cycles."""
        template_id = _uuid(template_id, "template_id")
        if template_id not in self.templates:
            raise ValueError(f"Unknown template: {template_id}")
        children = self._child_index()
        found: set[str] = set()
        pending = list(children.get(template_id, set()))
        while pending:
            identifier = pending.pop()
            if identifier not in found:
                found.add(identifier)
                pending.extend(children.get(identifier, set()))
        return found


def _document(region: str, nodes: Iterable[ET.Element]) -> ET.ElementTree:
    root = ET.Element("save")
    ET.SubElement(root, "version", {
        "major": "4", "minor": "0", "revision": "9", "build": "0",
        "lslib_meta": "v1,bswap_guids,lsf_adjacency",
    })
    container = ET.SubElement(ET.SubElement(root, "region", {"id": region}), "node", {"id": region})
    children = ET.SubElement(container, "children")
    children.extend(nodes)
    ET.indent(root, space="  ")
    return ET.ElementTree(root)


def compile(db: Database, catalog: dict[str, Any], output: Path) -> dict[str, Any]:
    """Validate every enabled entry, then emit appearance-only merged LSX files.

    Review is an exact adult allowlist; an absent child tag is never treated as
    positive evidence.  BASE_Children, minor tags/names/stats, missing ancestry,
    are unconditional vetoes. Descendants require an explicit existing visual
    on every immediate child, so the changed visual cannot be inherited.
    """
    if not isinstance(catalog, dict) or catalog.get("schema_version") != 1:
        raise ValueError("Catalog schema_version must be 1")
    adults = catalog.get("adults")
    if not isinstance(adults, list):
        raise ValueError("Catalog adults must be a list")
    templates: list[ET.Element] = []
    visuals: list[ET.Element] = []
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in adults:
        if not isinstance(entry, dict):
            raise ValueError("Each adult catalog entry must be an object")
        enabled = entry.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError("Catalog enabled must be a boolean")
        if not enabled:
            continue
        identifier = _uuid(entry.get("template_id"), "catalog template_id")
        if identifier in seen:
            raise ValueError(f"Duplicate adult catalog template: {identifier}")
        seen.add(identifier)
        review = entry.get("review")
        if (not isinstance(review, dict) or review.get("adult") is not True
                or not isinstance(review.get("evidence"), str)
                or not review["evidence"].strip()):
            raise ValueError(f"Template {identifier} requires explicit adult review and evidence")
        chain = db.ancestry(identifier)
        original = db.templates[identifier]
        values = attrs(original)
        expected_name = entry.get("expected_name")
        if not isinstance(expected_name, str) or not expected_name or values.get("Name") != expected_name:
            raise ValueError(f"Template name mismatch for {identifier}: expected {expected_name!r}, found {values.get('Name')!r}")
        if db.effective_attr(identifier, "Type") != "character":
            raise ValueError(f"Catalog template is not a character: {identifier}")
        for ancestor_id in chain:
            ancestor = attrs(db.templates[ancestor_id])
            if ancestor_id in MINOR_BASES:
                raise ValueError(f"Template {identifier} inherits BASE_Children")
            for key in ("Name", "Stats"):
                if MINOR_TEXT.search(ancestor.get(key) or ""):
                    raise ValueError(f"Minor evidence in {key} of {ancestor_id}: {ancestor.get(key)}")
        blocked_tags = db.inherited_tags(identifier) & MINOR_TAGS
        if blocked_tags:
            raise ValueError(f"Minor tag veto for {identifier}: {sorted(blocked_tags)}")
        descendants = db.descendants(identifier)
        if descendants:
            for child_id in sorted(db.direct_children(identifier)):
                child_visual = attrs(db.templates[child_id]).get("CharacterVisualResourceID")
                try:
                    child_visual_id = _uuid(child_visual, f"CharacterVisualResourceID of child {child_id}")
                except ValueError as exc:
                    raise ValueError(f"Template {identifier} has descendants without an explicit valid visual barrier on child {child_id}") from exc
                if child_visual_id not in db.visuals:
                    raise ValueError(f"Template {identifier} has descendants with unresolved visual barrier {child_visual_id} on child {child_id}")
        visual_id = _uuid(db.effective_attr(identifier, "CharacterVisualResourceID"), f"CharacterVisualResourceID of {identifier}")
        if visual_id not in db.visuals:
            raise ValueError(f"Missing character visual {visual_id} for {identifier}")
        original_visual = db.visuals[visual_id]
        visual_values = attrs(original_visual)
        for key in ("BaseVisual", "BodySetVisual"):
            _uuid(visual_values.get(key), f"{key} of character visual {visual_id}")
        if MINOR_TEXT.search(visual_values.get("Name") or ""):
            raise ValueError(f"Minor evidence in character visual name: {visual_values.get('Name')}")
        slots = original_visual.findall('./children/node[@id="Slots"]')
        if not any(attrs(slot).get("Slot") == "Head" and attrs(slot).get("VisualResource") for slot in slots):
            raise ValueError(f"Character visual {visual_id} has no explicit head slot")
        private_id = str(uuid5(PRIVATE_NAMESPACE, f"template:{identifier}:visual:{visual_id}"))
        if private_id in db.visuals:
            raise ValueError(f"Private visual UUID collides with existing resource: {private_id}")
        template = copy.deepcopy(original)
        visual = copy.deepcopy(original_visual)
        _set_attr(template, "CharacterVisualResourceID", private_id)
        _set_attr(visual, "ID", private_id)
        _set_attr(visual, "Name", "Nudegate_" + (visual_values.get("Name") or expected_name), "LSString")
        _set_attr(visual, "ShowEquipmentVisuals", "False", "bool")
        removed: list[dict[str, str | None]] = []
        visual_children = visual.find("children")
        if visual_children is not None:
            for child in list(visual_children):
                if child.get("id") == "Slots" and attrs(child).get("Slot") in CLOTHING_SLOTS:
                    removed.append(attrs(child))
                    visual_children.remove(child)
        templates.append(template)
        visuals.append(visual)
        entries.append({
            "template_id": identifier,
            "name": expected_name,
            "original_visual_id": visual_id,
            "private_visual_id": private_id,
            "body_set_visual": visual_values["BodySetVisual"],
            "base_visual": visual_values["BaseVisual"],
            "removed_slots": removed,
            "insulated_descendants": sorted(descendants),
            "template_source": db.template_sources.get(identifier),
            "visual_source": db.visual_sources.get(visual_id),
            "review_evidence": review["evidence"],
        })
    if not templates:
        raise ValueError("Catalog has no enabled, reviewed adult templates")
    output = Path(output)
    template_path = output / "Public/Nudegate/RootTemplates/_merged.lsx"
    visual_path = output / "Public/Nudegate/Content/[PAK]_CharacterVisuals/_merged.lsx"
    documents = ((_document("Templates", templates), template_path),
                 (_document("CharacterVisualBank", visuals), visual_path))
    # All admission checks and serialization occur before creating output files.
    serialized = [(ET.tostring(document.getroot(), encoding="utf-8", xml_declaration=True), path)
                  for document, path in documents]
    for content, path in serialized:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_bytes(content)
        temporary.replace(path)
    return {
        "schema_version": 1,
        "counts": {"templates": len(templates), "private_visuals": len(visuals),
                   "clothing_slots_removed": sum(len(entry["removed_slots"]) for entry in entries)},
        "package_order": list(db.package_order),
        "templates": entries,
        "outputs": {"templates": str(template_path), "visuals": str(visual_path)},
    }
