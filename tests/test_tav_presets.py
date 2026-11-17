"""CC clones must not override NPC roots, strip gear, or cross adult rig profiles."""

from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import UUID
import xml.etree.ElementTree as ET

from nudegate.core import Database, MINOR_BASES, MINOR_TAGS, ZERO_UUID, attrs
from nudegate.tav_presets import create_tav_presets


NORMAL_ROOT = "11111111-1111-4111-8111-111111111111"
STRONG_ROOT = "22222222-2222-4222-8222-222222222222"
BASE = "33333333-3333-4333-8333-333333333333"
NORMAL_VISUAL = "44444444-4444-4444-8444-444444444444"
STRONG_VISUAL = "55555555-5555-4555-8555-555555555555"
SKELETON = "66666666-6666-4666-8666-666666666666"
DESCENDANT = "77777777-7777-4777-8777-777777777777"
NORMAL_PRIVATE_BODY = "88888888-8888-4888-8888-888888888888"
STRONG_PRIVATE_BODY = "99999999-9999-4999-8999-999999999999"
NORMAL_PRESET = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
STRONG_PRESET = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
NORMAL_BODY = "db6e5918-8514-4dcc-8363-e8fd3c50cce5"
STRONG_BODY = "9725b3db-6e40-054b-dc49-b8e479bc0cba"


def node(identifier: str, **values: str) -> ET.Element:
    result = ET.Element("node", {"id": identifier})
    for key, value in values.items():
        ET.SubElement(result, "attribute", {"id": key, "type": "FixedString", "value": value})
    return result


def canonical(element: ET.Element) -> list:
    return [element.tag, sorted(element.attrib.items()), " ".join((element.text or "").split()),
            [canonical(child) for child in element]]


def visual(identifier: str, body: str, show: str) -> ET.Element:
    result = node("Resource", ID=identifier, Name="Adult_CC_Visual", BaseVisual=SKELETON,
                  BodySetVisual=body, ShowEquipmentVisuals=show)
    children = ET.SubElement(result, "children")
    for slot in ("Head", "Hair", "Underwear", "Body", "Footwear", "Private Parts", "ModestyLeaf", "Tail"):
        children.append(node("Slots", Slot=slot, VisualResource=SKELETON, Bone=""))
    children.append(node("MaterialOverrides", MaterialResource="skin-and-tattoos"))
    return result


def fixture() -> Database:
    roots = {}
    for identifier, name, cv in [(NORMAL_ROOT, "Humans_Female_Player", NORMAL_VISUAL),
                                  (STRONG_ROOT, "Humans_Female_Strong_Player", STRONG_VISUAL)]:
        root = node("GameObjects", MapKey=identifier, Name=name, ParentTemplateId=BASE,
                    CharacterVisualResourceID=cv, Equipment="CC_Equipment", Stats="Adult_CC_Stats")
        children = ET.SubElement(root, "children")
        children.append(node("OnDeathActions", QuestState="preserved"))
        children.append(node("GameplayConfig", Ability="unchanged"))
        roots[identifier] = root
    roots[BASE] = node("GameObjects", MapKey=BASE, Name="Adult_Character_Base", Type="character", ParentTemplateId="")
    # A non-leaf CC source must be allowed without touching this descendant.
    roots[DESCENDANT] = node("GameObjects", MapKey=DESCENDANT, Name="Existing_NPC",
                             ParentTemplateId=NORMAL_ROOT, Type="character")
    return Database(templates=roots, visuals={NORMAL_VISUAL: visual(NORMAL_VISUAL, NORMAL_BODY, "True"),
                                             STRONG_VISUAL: visual(STRONG_VISUAL, STRONG_BODY, "False")})


def body_report() -> dict:
    rows = []
    mappings = {}
    for original, private, family, mesh in [
        (NORMAL_BODY, NORMAL_PRIVATE_BODY, "human", "HUM_F_NKD_Body_A_Mesh"),
        (STRONG_BODY, STRONG_PRIVATE_BODY, "human_strong", "HUM_FS_NKD_Body_A_Mesh"),
    ]:
        row = {"original_visual_id": original, "private_visual_id": private, "variant_id": "plush",
               "family_id": family, "mesh_name": mesh}
        rows.append(row)
        mappings[original] = [{key: row[key] for key in ("private_visual_id", "variant_id", "family_id")}]
    return {"variants": rows, "resource_map": mappings}


def preset(identifier: str, root: str, shape: str, body_type: str = "1", **extra: str) -> ET.Element:
    return node("CharacterCreationPreset", UUID=identifier, RootTemplate=root,
                BodyType=body_type, BodyShape=shape, RaceUUID=SKELETON,
                Overview="original-camera", **extra)


class TavPresetsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.output = self.base / "generated"
        self.file = self.base / "presets.lsx"
        self.nodes = [preset(NORMAL_PRESET, NORMAL_ROOT, "0"), preset(STRONG_PRESET, STRONG_ROOT, "1")]
        self.save_presets()
        self.db = fixture()
        self.bodies = body_report()

    def save_presets(self, nodes: list[ET.Element] | None = None, path: Path | None = None) -> Path:
        root = ET.Element("save")
        region = ET.SubElement(root, "region", {"id": "CharacterCreationPresets"})
        container = ET.SubElement(region, "node", {"id": "root"})
        ET.SubElement(container, "children").extend(copy.deepcopy(self.nodes if nodes is None else nodes))
        target = self.file if path is None else path
        ET.ElementTree(root).write(target, encoding="utf-8", xml_declaration=True)
        return target

    def build(self, files: list[Path] | None = None) -> dict:
        return create_tav_presets(self.db, files or [self.file], self.bodies, self.output)

    def test_both_body_shapes_use_new_roots_and_preserve_every_other_property(self) -> None:
        before_roots = {key: canonical(n) for key, n in self.db.templates.items()}
        before_visuals = {key: canonical(n) for key, n in self.db.visuals.items()}
        before_file = self.file.read_bytes()
        before_bodies = copy.deepcopy(self.bodies)
        report = self.build()
        self.assertEqual(report["counts"]["templates"], 2)
        self.assertEqual({entry["body_shape"] for entry in report["templates"]}, {"0", "1"})
        root_nodes = ET.parse(report["outputs"]["templates"]).findall('./region/node/children/node')
        visual_nodes = {attrs(n)["ID"]: n for n in ET.parse(report["outputs"]["visuals"]).findall('./region/node/children/node')}
        roots = {attrs(n)["MapKey"]: n for n in root_nodes}
        for entry in report["templates"]:
            self.assertNotIn(entry["private_template_id"], self.db.templates)
            original = self.db.templates[entry["original_template_id"]]
            root = roots[entry["private_template_id"]]
            self.assertEqual({k: v for k, v in attrs(root).items() if k not in {"MapKey", "Name", "CharacterVisualResourceID"}},
                             {k: v for k, v in attrs(original).items() if k not in {"MapKey", "Name", "CharacterVisualResourceID"}})
            self.assertEqual(canonical(root.find("children")), canonical(original.find("children")))
            original_visual = self.db.visuals[entry["original_visual_id"]]
            cloned = visual_nodes[entry["private_visual_id"]]
            self.assertEqual({k: v for k, v in attrs(cloned).items() if k not in {"ID", "Name", "BodySetVisual"}},
                             {k: v for k, v in attrs(original_visual).items() if k not in {"ID", "Name", "BodySetVisual"}})
            self.assertEqual(canonical(cloned.find("children")), canonical(original_visual.find("children")))
            self.assertEqual(attrs(cloned)["BodySetVisual"], entry["private_body_set_visual"])
            self.assertTrue(entry["review"]["adult"])
        cc = ET.parse(report["outputs"]["presets"])
        self.assertIsNotNone(cc.find('./region[@id="CharacterCreationPresets"]/node[@id="root"]'))
        emitted = {attrs(n)["UUID"]: n for n in cc.findall('./region/node/children/node')}
        self.assertEqual(set(emitted), {NORMAL_PRESET, STRONG_PRESET})
        for original in self.nodes:
            modified = emitted[attrs(original)["UUID"]]
            self.assertEqual({k: v for k, v in attrs(modified).items() if k != "RootTemplate"},
                             {k: v for k, v in attrs(original).items() if k != "RootTemplate"})
            self.assertNotIn(attrs(modified)["RootTemplate"], self.db.templates)
        self.assertEqual({key: canonical(n) for key, n in self.db.templates.items()}, before_roots)
        self.assertEqual({key: canonical(n) for key, n in self.db.visuals.items()}, before_visuals)
        self.assertEqual(self.file.read_bytes(), before_file)
        self.assertEqual(self.bodies, before_bodies)
        self.assertEqual(report["scope"], "new character creation only")
        self.assertEqual(report["existing_saves"], "not supported")
        self.assertEqual(report["in_game"], "not tested")

    def test_ids_are_stable_and_repeated_presets_share_one_private_root(self) -> None:
        self.nodes[1] = preset(STRONG_PRESET, NORMAL_ROOT, "0", OriginUUID=ZERO_UUID)
        self.save_presets()
        first = self.build()
        self.assertEqual(first, self.build())
        self.assertEqual(first["counts"]["presets"], 2)
        self.assertEqual(first["counts"]["templates"], 1)
        self.assertEqual(len(first["templates"][0]["preset_ids"]), 2)

    def test_later_file_wins_same_preset_uuid_without_overriding_original_root(self) -> None:
        later = self.save_presets([preset(NORMAL_PRESET, STRONG_ROOT, "1", CloseUpA="new-camera")], self.base / "later.lsx")
        report = self.build([self.file, later])
        self.assertEqual(report["counts"]["priority_replacements"], 1)
        self.assertEqual(report["counts"]["templates"], 1)
        self.assertEqual(report["counts"]["presets"], 2)
        cc = ET.parse(report["outputs"]["presets"])
        changed = next(n for n in cc.findall('./region/node/children/node') if attrs(n)["UUID"] == NORMAL_PRESET)
        self.assertEqual(attrs(changed)["CloseUpA"], "new-camera")
        self.assertEqual(report["templates"][0]["original_template_id"], STRONG_ROOT)

    def test_male_missing_root_unsupported_shape_and_origin_presets_are_skipped(self) -> None:
        cases = [preset(NORMAL_PRESET, NORMAL_ROOT, "0", body_type="0"),
                 preset(NORMAL_PRESET, NORMAL_ROOT, "2"),
                 preset(NORMAL_PRESET, "", "0"),
                 preset(NORMAL_PRESET, NORMAL_ROOT, "0", OriginUUID=SKELETON)]
        for candidate in cases:
            with self.subTest(fields=attrs(candidate)):
                self.save_presets([candidate])
                report = self.build()
                self.assertEqual(report["counts"]["presets"], 0)
                self.assertEqual(report["outputs"], {})
                self.assertFalse(self.output.exists())

    def test_minor_name_stats_tags_and_base_ancestry_veto_supported_body(self) -> None:
        for mode in ("name", "stats", "tag", "base"):
            with self.subTest(mode=mode):
                self.db = fixture()
                self.save_presets([self.nodes[0]])
                if mode in {"name", "stats"}:
                    key = "Name" if mode == "name" else "Stats"
                    element = self.db.templates[BASE].find(f'attribute[@id="{key}"]')
                    if element is None:
                        element = ET.SubElement(self.db.templates[BASE], "attribute", {"id": key, "type": "FixedString"})
                    element.set("value", "Child_Character")
                elif mode == "tag":
                    children = ET.SubElement(self.db.templates[BASE], "children")
                    tags = ET.SubElement(children, "node", {"id": "Tags"})
                    ET.SubElement(tags, "children").append(node("Tag", Object=next(iter(MINOR_TAGS))))
                else:
                    forbidden = next(iter(MINOR_BASES))
                    self.db.templates[forbidden] = node("GameObjects", MapKey=forbidden, Name="Neutral", Type="character")
                    self.db.templates[BASE].find('attribute[@id="ParentTemplateId"]').set("value", forbidden)
                report = self.build()
                self.assertEqual(report["counts"]["presets"], 0)
                self.assertIn("minor", report["skipped"][0]["reason"])
                self.assertFalse(self.output.exists())

    def test_cc_shape_must_match_exact_reviewed_body_source(self) -> None:
        self.save_presets([preset(NORMAL_PRESET, STRONG_ROOT, "0")])
        report = self.build()
        self.assertEqual(report["counts"]["presets"], 0)
        self.assertIn("BodyShape", report["skipped"][0]["reason"])
        self.assertFalse(self.output.exists())

    def test_unknown_body_is_not_admitted_without_child_tags(self) -> None:
        self.db.visuals[NORMAL_VISUAL].find('attribute[@id="BodySetVisual"]').set("value", SKELETON)
        self.save_presets([self.nodes[0]])
        report = self.build()
        self.assertEqual(report["counts"]["presets"], 0)
        self.assertIn("unsupported adult body", report["skipped"][0]["reason"])

    def test_wrong_family_or_ambiguous_profile_mapping_is_rejected_before_output(self) -> None:
        original = copy.deepcopy(self.bodies)
        self.bodies["variants"][0]["mesh_name"] = "HUM_FS_NKD_Body_A_Mesh"
        with self.assertRaisesRegex(ValueError, "mesh family disagrees"):
            self.build()
        self.assertFalse(self.output.exists())
        self.bodies = original
        self.bodies["resource_map"][NORMAL_BODY].append(copy.deepcopy(self.bodies["resource_map"][NORMAL_BODY][0]))
        with self.assertRaisesRegex(ValueError, "Ambiguous body profile"):
            self.build()
        self.assertFalse(self.output.exists())

    def test_private_ids_cannot_collide_with_original_roots(self) -> None:
        with patch("nudegate.tav_presets.uuid5", return_value=UUID(NORMAL_ROOT)):
            with self.assertRaisesRegex(ValueError, "UUID collides"):
                self.build()
        self.assertFalse(self.output.exists())

    def test_broken_ancestry_and_minor_character_visual_names_are_skipped(self) -> None:
        self.db.templates[NORMAL_ROOT].find('attribute[@id="ParentTemplateId"]').set("value", NORMAL_PRIVATE_BODY)
        self.db.visuals[STRONG_VISUAL].find('attribute[@id="Name"]').set("value", "Child_Visual")
        report = self.build()
        self.assertEqual(report["counts"]["presets"], 0)
        self.assertEqual(len(report["skipped"]), 2)
        self.assertFalse(self.output.exists())

    def test_unsafe_profile_and_missing_preset_files_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "profile_id"):
            create_tav_presets(self.db, [self.file], self.bodies, self.output, profile_id="../escape")
        with self.assertRaisesRegex(ValueError, "Missing preset LSX"):
            self.build([self.base / "missing.lsx"])
        self.assertFalse(self.output.exists())

    def test_duplicate_preset_attributes_or_missing_variant_provenance_are_rejected(self) -> None:
        ET.SubElement(self.nodes[0], "attribute", {"id": "BodyType", "type": "uint8", "value": "0"})
        self.save_presets()
        with self.assertRaisesRegex(ValueError, "duplicate attribute"):
            self.build()
        self.assertFalse(self.output.exists())
        self.nodes[0].remove(self.nodes[0][-1])
        self.save_presets()
        self.bodies["resource_map"][NORMAL_BODY][0]["private_visual_id"] = STRONG_PRIVATE_BODY
        with self.assertRaisesRegex(ValueError, "no matching built variant"):
            self.build()
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
