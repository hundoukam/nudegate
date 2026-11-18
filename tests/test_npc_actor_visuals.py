"""A placed visual is active only when every known consumer is admitted."""

import copy
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "src")]
from npc_actor_visuals import compile_actor_visuals, filter_root_catalog
from nudegate.core import _document, _set_attr, attrs
from test_core import ADULT, BASE, BODY, MINOR_TAGS, VISUAL, add_tag, fixture, node


class PlacedActorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.db = fixture()
        self.visual = str(uuid4())
        source = copy.deepcopy(self.db.visuals[VISUAL])
        _set_attr(source, "ID", self.visual)
        self.db.visuals[self.visual] = source
        self.actor_id = str(uuid4())
        self.actor = node("GameObjects", MapKey=self.actor_id, TemplateName=ADULT,
                          Name="S_Smith", Type="character", CharacterVisualResourceID=self.visual)
        self.rows = [self.actor]
        self.core = {"templates": []}
        self.catalog = {"schema_version": 1, "actors": [{
            "actor_id": self.actor_id, "template_id": ADULT, "expected_name": "S_Smith",
            "expected_body_set_visual": BODY, "expected_visual_id": self.visual,
            "review": {"adult": True, "evidence": "Named adult smith reviewed in game records."},
        }]}

    def build(self):
        path = self.dir / "actors.lsx"
        _document("Templates", self.rows).write(path)
        return compile_actor_visuals(self.db, [path], self.catalog, self.core, self.dir / "output")

    def test_exclusive_override_preserves_head_and_original_resource_and_changes_only_visuals(self):
        original = ET.tostring(self.db.visuals[self.visual])
        report = self.build()
        self.assertEqual(report["templates"][0]["actor_ids"], [self.actor_id])
        output = Path(report["outputs"]["visuals"])
        compiled = ET.parse(output).find("./region/node/children/node")
        self.assertEqual(attrs(compiled)["ID"], self.visual)
        self.assertEqual(attrs(compiled)["ShowEquipmentVisuals"], "False")
        self.assertEqual(ET.tostring(self.db.visuals[self.visual]), original)
        self.assertTrue(any(attrs(s).get("Slot") == "Head" for s in compiled.findall("./children/node")))
        self.assertFalse(any("RootTemplates" in p.parts for p in (self.dir / "output").rglob("*")))

    def test_unreviewed_actor_sharing_visual_blocks_entire_group(self):
        other = copy.deepcopy(self.actor)
        _set_attr(other, "MapKey", str(uuid4()))
        _set_attr(other, "Name", "Anonymous")
        self.rows.append(other)
        report = self.build()
        self.assertEqual(report["templates"], [])
        self.assertEqual(report["skipped"][0]["unreviewed_actor_ids"], [attrs(other)["MapKey"]])

    def test_unreviewed_inheriting_root_blocks_entire_shared_visual(self):
        _set_attr(self.db.templates[BASE], "CharacterVisualResourceID", self.visual)
        self.core["templates"] = [{"template_id": BASE, "review_evidence": "Reviewed adult."}]
        report = self.build()
        self.assertEqual(report["templates"], [])
        self.assertEqual(report["skipped"][0]["unreviewed_template_ids"], [ADULT])

    def test_minor_actor_tag_vetoes_positive_catalog_entry(self):
        add_tag(self.actor, next(iter(MINOR_TAGS)))
        report = self.build()
        self.assertFalse(report["templates"])
        self.assertIn("minor", report["skipped"][0]["reason"])

    def test_minor_ancestor_vetoes_actor_even_with_its_own_visual(self):
        _set_attr(self.db.templates[BASE], "Stats", "Tiefling_Child")
        report = self.build()
        self.assertFalse(report["templates"])
        self.assertIn("minor", report["skipped"][0]["reason"])

    def test_missing_parent_prevents_ambiguous_inventory_from_being_used(self):
        _set_attr(self.actor, "TemplateName", str(uuid4()))
        with self.assertRaisesRegex(ValueError, "Missing template"):
            self.build()

    def filter_roots(self):
        path = self.dir / "actors.lsx"
        _document("Templates", self.rows).write(path)
        return filter_root_catalog(self.db, [path], {"adults": [{"template_id": ADULT}]}, self.catalog)

    def test_unknown_inheriting_child_blocks_the_root_even_if_root_was_reviewed(self):
        child = node("GameObjects", MapKey=str(uuid4()), TemplateName=ADULT,
                     Name="S_Child", Type="character")
        self.rows.append(child)
        filtered, audit = self.filter_roots()
        self.assertEqual(filtered["adults"], [])
        self.assertEqual(audit["skipped_roots"][0]["blocked_by"][0]["actor_id"], attrs(child)["MapKey"])

    def test_unrelated_explicit_visual_is_a_barrier_to_root_inheritance(self):
        child = node("GameObjects", MapKey=str(uuid4()), TemplateName=ADULT, Name="S_Child",
                     Type="character", CharacterVisualResourceID=VISUAL)
        self.rows.append(child)
        filtered, audit = self.filter_roots()
        self.assertEqual(len(filtered["adults"]), 1)
        self.assertEqual(audit["skipped_roots"], [])

    def test_positive_inherited_actor_identity_keeps_root_without_pinning_a_visual(self):
        self.actor.remove(self.actor.find("attribute[@id='CharacterVisualResourceID']"))
        review = self.catalog["actors"].pop()
        for field in ("expected_body_set_visual", "expected_visual_id"):
            review.pop(field)
        self.catalog["root_inheritors"] = [review]
        filtered, audit = self.filter_roots()
        self.assertEqual(len(filtered["adults"]), 1)
        self.assertEqual(audit["inheriting_actors_by_root"][ADULT][0]["actor_id"], self.actor_id)
