"""Regression tests for admission boundaries and appearance-only output."""

from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from nudegate.core import Database, MINOR_BASES, MINOR_TAGS, attrs, compile


ADULT = "11111111-1111-4111-8111-111111111111"
BASE = "22222222-2222-4222-8222-222222222222"
VISUAL = "33333333-3333-4333-8333-333333333333"
BODY = "44444444-4444-4444-8444-444444444444"
SKELETON = "55555555-5555-4555-8555-555555555555"
CHILD = "66666666-6666-4666-8666-666666666666"
MISSING = "77777777-7777-4777-8777-777777777777"


def node(identifier: str, **values: str) -> ET.Element:
    result = ET.Element("node", {"id": identifier})
    for key, value in values.items():
        ET.SubElement(result, "attribute", {"id": key, "type": "FixedString", "value": value})
    return result


def add_tag(template: ET.Element, tag: str) -> None:
    children = template.find("children")
    if children is None:
        children = ET.SubElement(template, "children")
    tags = ET.SubElement(children, "node", {"id": "Tags"})
    ET.SubElement(tags, "children").append(node("Tag", Object=tag))


def fixture() -> Database:
    adult = node("GameObjects", MapKey=ADULT, Name="S_DEN_Dammon", ParentTemplateId=BASE,
                 Equipment="EQP_Dammon", Stats="Tiefling_Smith", Type="character")
    gameplay = ET.SubElement(adult, "children")
    gameplay.append(node("OnDeathActions", Action="QuestStatePreserved"))
    base = node("GameObjects", MapKey=BASE, Name="BASE_Humanoid_Adult",
                Type="character", CharacterVisualResourceID=VISUAL)
    visual = node("Resource", ID=VISUAL, Name="Dammon_Visual", BaseVisual=SKELETON,
                  BodySetVisual=BODY, ShowEquipmentVisuals="True")
    children = ET.SubElement(visual, "children")
    for slot in ("Head", "Hair", "Horns", "Body", "Underwear", "Gloves", "Footwear",
                 "Cloak", "Headwear", "NakedBody", "Private Parts", "ModestyLeaf",
                 "Beard", "Tail", "SpecialIdentitySlot"):
        children.append(node("Slots", Slot=slot, VisualResource=BODY, Bone=""))
    children.append(node("MaterialOverrides", MaterialResource="skin-material"))
    children.append(node("LocatorAttachments", LocatorId="identity-locator", VisualResource=BODY))
    return Database(templates={ADULT: adult, BASE: base}, visuals={VISUAL: visual},
                    template_sources={ADULT: {"package": "Gustav", "module": "Gustav", "path": "source-root.lsx"}},
                    visual_sources={VISUAL: {"package": "Gustav", "module": "Gustav", "path": "source-visual.lsx"}},
                    package_order=["Shared", "Gustav"])


def catalog() -> dict:
    return {"schema_version": 1, "adults": [{"template_id": ADULT,
            "expected_name": "S_DEN_Dammon", "enabled": True,
            "review": {"adult": True, "evidence": "Reviewed named adult smith in source data."}}]}


class AdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "output"
        self.db = fixture()

    def assert_refused(self, pattern: str, review: dict | None = None) -> None:
        with self.assertRaisesRegex(ValueError, pattern):
            compile(self.db, review if review is not None else catalog(), self.output)
        self.assertFalse(self.output.exists(), "Invalid build must not write any output")

    def test_preserves_gameplay_and_identity_and_does_not_mutate_sources(self) -> None:
        template_before = ET.tostring(self.db.templates[ADULT])
        visual_before = ET.tostring(self.db.visuals[VISUAL])
        report = compile(self.db, catalog(), self.output)
        generated_template = ET.parse(report["outputs"]["templates"]).find('.//node[@id="GameObjects"]')
        generated_visual = ET.parse(report["outputs"]["visuals"]).find('.//node[@id="Resource"]')
        self.assertIsNotNone(generated_template)
        self.assertIsNotNone(generated_visual)
        original_attrs = attrs(self.db.templates[ADULT])
        changed_attrs = attrs(generated_template)
        self.assertEqual({k: v for k, v in changed_attrs.items() if k != "CharacterVisualResourceID"}, original_attrs)
        self.assertEqual(attrs(generated_template.find('./children/node[@id="OnDeathActions"]')),
                         {"Action": "QuestStatePreserved"})
        self.assertNotEqual(changed_attrs["CharacterVisualResourceID"], VISUAL)
        self.assertEqual(changed_attrs["CharacterVisualResourceID"], attrs(generated_visual)["ID"])
        self.assertEqual(attrs(generated_visual)["BodySetVisual"], BODY)
        self.assertEqual(attrs(generated_visual)["BaseVisual"], SKELETON)
        self.assertEqual(attrs(generated_visual)["ShowEquipmentVisuals"], "False")
        kept = {attrs(x)["Slot"] for x in generated_visual.findall('./children/node[@id="Slots"]')}
        self.assertEqual(kept, {"Head", "Hair", "Horns", "NakedBody", "Private Parts", "ModestyLeaf",
                                "Beard", "Tail", "SpecialIdentitySlot"})
        self.assertEqual(attrs(generated_visual.find('./children/node[@id="MaterialOverrides"]')),
                         {"MaterialResource": "skin-material"})
        self.assertEqual(attrs(generated_visual.find('./children/node[@id="LocatorAttachments"]')),
                         {"LocatorId": "identity-locator", "VisualResource": BODY})
        self.assertEqual(report["counts"]["clothing_slots_removed"], 6)
        self.assertEqual(ET.tostring(self.db.templates[ADULT]), template_before)
        self.assertEqual(ET.tostring(self.db.visuals[VISUAL]), visual_before)

    def test_private_id_is_deterministic_and_distinct_for_different_targets(self) -> None:
        first = compile(self.db, catalog(), self.output)
        second = compile(self.db, catalog(), self.output)
        self.assertEqual(first["templates"][0]["private_visual_id"], second["templates"][0]["private_visual_id"])
        another = copy.deepcopy(self.db.templates[ADULT])
        another.find('attribute[@id="MapKey"]').set("value", CHILD)
        another.find('attribute[@id="Name"]').set("value", "S_DEN_AnotherAdult")
        self.db.templates[CHILD] = another
        review = catalog()
        review["adults"].append({**review["adults"][0], "template_id": CHILD,
                                  "expected_name": "S_DEN_AnotherAdult"})
        report = compile(self.db, review, self.output)
        self.assertEqual(len({x["private_visual_id"] for x in report["templates"]}), 2)

    def test_inherited_child_tags_veto_even_reviewed_entry(self) -> None:
        for tag in MINOR_TAGS:
            with self.subTest(tag=tag):
                self.db = fixture()
                add_tag(self.db.templates[BASE], tag)
                self.assert_refused("Minor tag veto")

    def test_base_children_ancestry_veto(self) -> None:
        forbidden = next(iter(MINOR_BASES))
        self.db.templates[forbidden] = node("GameObjects", MapKey=forbidden,
                                           Name="BASE_Humanoid", Type="character")
        self.db.templates[BASE].append(ET.Element("attribute", {"id": "ParentTemplateId", "value": forbidden}))
        self.assert_refused("BASE_Children")

    def test_ancestor_minor_name_and_child_stats_veto(self) -> None:
        for key, text in (("Name", "BASE_Children"), ("Stats", "Human_Child"),
                          ("Name", "Goblin_Kid"), ("Name", "Unknown_Adolescent")):
            with self.subTest(key=key):
                self.db = fixture()
                existing = self.db.templates[BASE].find(f'attribute[@id="{key}"]')
                if existing is None:
                    self.db.templates[BASE].append(ET.Element("attribute", {"id": key, "value": text}))
                else:
                    existing.set("value", text)
                self.assert_refused("Minor evidence")

    def test_leaf_requirement_prevents_child_inheriting_override(self) -> None:
        self.db.templates[CHILD] = node("GameObjects", MapKey=CHILD,
                                       Name="Unverified", ParentTemplateId=ADULT)
        self.assert_refused("has descendants")

    def test_explicit_child_visual_insulates_child_and_grandchild(self) -> None:
        self.db.templates[CHILD] = node("GameObjects", MapKey=CHILD,
                                       Name="Child_Shadowheart_Memory", ParentTemplateId=ADULT,
                                       CharacterVisualResourceID=VISUAL)
        self.db.templates[MISSING] = node("GameObjects", MapKey=MISSING,
                                         Name="Grandchild_Memory", ParentTemplateId=CHILD)
        child_before = ET.tostring(self.db.templates[CHILD])
        report = compile(self.db, catalog(), self.output)
        self.assertEqual(report["templates"][0]["insulated_descendants"], sorted([CHILD, MISSING]))
        generated = ET.parse(report["outputs"]["templates"]).findall('.//node[@id="GameObjects"]')
        self.assertEqual([attrs(n)["MapKey"] for n in generated], [ADULT])
        self.assertEqual(ET.tostring(self.db.templates[CHILD]), child_before)
        self.assertEqual(self.db.effective_attr(MISSING, "CharacterVisualResourceID"), VISUAL)

    def test_explicit_grandchild_does_not_insulate_inheriting_child(self) -> None:
        self.db.templates[CHILD] = node("GameObjects", MapKey=CHILD,
                                       Name="Unverified", ParentTemplateId=ADULT)
        self.db.templates[MISSING] = node("GameObjects", MapKey=MISSING,
                                         Name="Another", ParentTemplateId=CHILD,
                                         CharacterVisualResourceID=VISUAL)
        self.assert_refused("without an explicit valid visual barrier")

    def test_invalid_child_visual_barriers_veto(self) -> None:
        for child_visual in ("", "00000000-0000-0000-0000-000000000000", "invalid", MISSING):
            with self.subTest(visual=child_visual):
                self.db = fixture()
                self.db.templates[CHILD] = node("GameObjects", MapKey=CHILD,
                    Name="Unverified", ParentTemplateId=ADULT, CharacterVisualResourceID=child_visual)
                self.assert_refused("has descendants")

    def test_missing_and_cyclic_ancestry_veto(self) -> None:
        self.db.templates[BASE].append(ET.Element("attribute", {"id": "ParentTemplateId", "value": MISSING}))
        self.assert_refused("Missing template in inheritance")
        self.db.templates[BASE].find('attribute[@id="ParentTemplateId"]').set("value", ADULT)
        self.assert_refused("inheritance cycle")

    def test_missing_unknown_or_name_drift_veto(self) -> None:
        review = catalog()
        review["adults"][0]["template_id"] = MISSING
        self.assert_refused("Missing template", review)
        review = catalog()
        review["adults"][0]["expected_name"] = "Changed_by_patch"
        self.assert_refused("name mismatch", review)

    def test_positive_adult_evidence_required(self) -> None:
        for review_value in ({}, {"adult": False, "evidence": "No"},
                             {"adult": "true", "evidence": "Wrong type"},
                             {"adult": True, "evidence": "  "}):
            with self.subTest(review=review_value):
                review = catalog()
                review["adults"][0]["review"] = review_value
                self.assert_refused("explicit adult review", review)

    def test_missing_body_and_head_veto(self) -> None:
        self.db.visuals[VISUAL].find('attribute[@id="BodySetVisual"]').set("value", "")
        self.assert_refused("BodySetVisual")
        self.db = fixture()
        children = self.db.visuals[VISUAL].find("children")
        children.remove(children.find('node[@id="Slots"]/attribute[@value="Head"]/..'))
        self.assert_refused("no explicit head")

    def test_all_entries_validate_before_any_file_write(self) -> None:
        review = catalog()
        review["adults"].append({**review["adults"][0], "template_id": MISSING})
        self.assert_refused("Missing template", review)


class SourceLoadingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name)

    def write(self, package: str, module: str, kind: str, nodes: list[ET.Element], filename: str = "_merged.lsf.lsx") -> None:
        region = "Templates" if kind == "RootTemplates" else "CharacterVisualBank"
        directory = self.source / package / "Public" / module
        directory = directory / "RootTemplates" if kind == "RootTemplates" else directory / "Content/[PAK]_CharacterVisuals"
        directory.mkdir(parents=True, exist_ok=True)
        root = ET.Element("save")
        children = ET.SubElement(ET.SubElement(ET.SubElement(root, "region", {"id": region}), "node", {"id": region}), "children")
        children.extend(copy.deepcopy(nodes))
        ET.ElementTree(root).write(directory / filename, encoding="utf-8")

    def seed(self) -> None:
        db = fixture()
        self.write("Shared", "Shared", "RootTemplates", list(db.templates.values()))
        self.write("Shared", "Shared", "Visuals", list(db.visuals.values()))

    def test_module_then_package_priority(self) -> None:
        self.seed()
        replacement = copy.deepcopy(fixture().templates[ADULT])
        replacement.find('attribute[@id="Name"]').set("value", "SharedDev_Adult")
        self.write("Shared", "SharedDev", "RootTemplates", [replacement])
        db = Database.load(self.source, ["Shared"])
        self.assertEqual(attrs(db.templates[ADULT])["Name"], "SharedDev_Adult")
        self.assertEqual(db.template_sources[ADULT]["module"], "SharedDev")
        replacement.find('attribute[@id="Name"]').set("value", "Patched_Adult")
        self.write("Patch", "Shared", "RootTemplates", [replacement])
        db = Database.load(self.source, ["Shared", "Patch"])
        self.assertEqual(attrs(db.templates[ADULT])["Name"], "Patched_Adult")
        self.assertEqual(db.template_sources[ADULT]["package"], "Patch")

    def test_conflicting_duplicates_inside_one_module_veto(self) -> None:
        self.seed()
        replacement = copy.deepcopy(fixture().templates[ADULT])
        replacement.find('attribute[@id="Name"]').set("value", "Conflicting_Adult")
        self.write("Shared", "Shared", "RootTemplates", [replacement], "other.lsx")
        with self.assertRaisesRegex(ValueError, "Conflicting template"):
            Database.load(self.source, ["Shared"])

    def test_no_recursive_resource_confusion(self) -> None:
        self.seed()
        visual = copy.deepcopy(fixture().visuals[VISUAL])
        visual.find("children").append(node("Resource", ID=MISSING))
        self.write("Shared", "Shared", "Visuals", [visual])
        db = Database.load(self.source, ["Shared"])
        self.assertEqual(set(db.visuals), {VISUAL})


if __name__ == "__main__":
    unittest.main()
