"""Private resource output must preserve materials/rigs without global overrides."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import UUID
import xml.etree.ElementTree as ET

from nudegate.body_resources import create_body_resources


ORIGINAL = "11111111-1111-4111-8111-111111111111"
ALIAS = "22222222-2222-4222-8222-222222222222"
MATERIAL = "33333333-3333-4333-8333-333333333333"
SKELETON = "44444444-4444-4444-8444-444444444444"
OTHER_MATERIAL = "55555555-5555-4555-8555-555555555555"
MESH = "HUM_F_NKD_Body_A_Mesh"
NS = "http://www.collada.org/2005/11/COLLADASchema"
MAGIC = bytes.fromhex("e59b495e6f631f141e13eba990beedc4")


def values(node: ET.Element) -> dict:
    return {n.get("id"): n.get("value") for n in node.findall("attribute")}


def node(name: str, **attributes: str) -> ET.Element:
    result = ET.Element("node", {"id": name})
    for key, value in attributes.items():
        ET.SubElement(result, "attribute", {"id": key, "type": "FixedString", "value": value})
    return result


def source_visual(identifier: str) -> ET.Element:
    result = node("Resource", ID=identifier, Name="OriginalBody", Slot="NakedBody",
                  SkeletonResource=SKELETON, SoftbodyResourceID=ALIAS,
                  ClothColliderResourceID=ORIGINAL, SourceFile="Generated/Original.GR2",
                  Template="Generated/Original.Dummy_Root.0", SupportsVertexColorMask="True",
                  BoundsMin="-10 -10 -10", BoundsMax="10 10 10", _OriginalFileVersion_="123")
    children = ET.SubElement(result, "children")
    children.append(node("Base", CustomPreservedValue="material-and-rig-metadata"))
    for lod in ("0", "4"):
        children.append(node("Objects", ObjectID=f"Original.STALE_NAME.{lod}",
                             MaterialID=MATERIAL, LOD=lod))
    mapping = ET.SubElement(children, "node", {"id": "ClothProxyMapping"})
    ET.SubElement(mapping, "children").append(node("Object", MapKey="..0"))
    return result


DAE = f'''<COLLADA xmlns="{NS}" version="1.4.1">
<library_geometries><geometry id="body-geom" name="{MESH}"><mesh>
<source id="positions"><float_array id="positions-array" count="9">0 1 2 1 3 -4 2 4 6</float_array>
<technique_common><accessor source="#positions-array" count="3" stride="3">
<param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/>
</accessor></technique_common></source>
<vertices id="vertices"><input semantic="POSITION" source="#positions"/></vertices>
<triangles count="1"><input semantic="VERTEX" source="#vertices" offset="0"/><p>0 1 2</p></triangles>
</mesh></geometry></library_geometries>
<library_controllers><controller id="body-skin"><skin source="#body-geom">
<source id="joints"><Name_array id="joints-array" count="1">Dummy_Root</Name_array>
<technique_common><accessor source="#joints-array" count="1" stride="1"><param name="JOINT" type="Name"/></accessor></technique_common></source>
<source id="weights"><float_array id="weights-array" count="1">1</float_array>
<technique_common><accessor source="#weights-array" count="1" stride="1"><param name="WEIGHT" type="float"/></accessor></technique_common></source>
<vertex_weights count="3"><input semantic="JOINT" source="#joints" offset="0"/>
<input semantic="WEIGHT" source="#weights" offset="1"/><vcount>1 1 1</vcount><v>0 0 0 0 0 0</v></vertex_weights>
</skin></controller></library_controllers></COLLADA>'''


class BodyResourcesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.output = self.base / "output"
        self.bank = self.base / "source.lsx"
        self.gr2 = self.base / "prototype.GR2"
        self.gr2.write_bytes(MAGIC + b"\0" * 16 + b"opaque-gr2-payload")
        self.dae = self.base / "prototype.dae"
        self.dae.write_text(DAE, encoding="utf-8")
        root = ET.Element("save")
        ET.SubElement(root, "version", {"major": "4", "minor": "0", "revision": "9", "build": "0"})
        region = ET.SubElement(root, "region", {"id": "VisualBank"})
        parent = ET.SubElement(ET.SubElement(region, "node", {"id": "VisualBank"}), "children")
        parent.extend([source_visual(ORIGINAL), source_visual(ALIAS)])
        self.source = ET.ElementTree(root)
        self.save_bank()
        self.manifest = {"schema_version": 1, "families": [{
            "id": "human", "label": "Normal human female",
            "original_visual_ids": [ORIGINAL], "variants": [{
                "id": "balanced", "label": "Balanced", "gr2": str(self.gr2),
                "dae": str(self.dae), "mesh_name": MESH}]}]}

    def save_bank(self) -> None:
        self.source.write(self.bank, encoding="utf-8", xml_declaration=True)

    def build(self) -> dict:
        return create_body_resources(self.manifest, self.bank, self.output)

    def assert_refused(self, message: str) -> None:
        with self.assertRaisesRegex(ValueError, message):
            self.build()
        self.assertFalse(self.output.exists(), "Validation failure must not publish artifacts")

    def test_private_resource_keeps_skin_rig_and_metadata_but_replaces_stale_objects(self) -> None:
        before = self.bank.read_bytes()
        manifest_before = copy.deepcopy(self.manifest)
        report = self.build()
        resource = ET.parse(report["outputs"]["visuals"]).find('.//node[@id="Resource"]')
        attributes = values(resource)
        entry = report["variants"][0]
        self.assertNotEqual(attributes["ID"], ORIGINAL)
        self.assertEqual(attributes["ID"], entry["private_visual_id"])
        self.assertEqual(attributes["SkeletonResource"], SKELETON)
        self.assertEqual(attributes["SoftbodyResourceID"], ALIAS)
        self.assertEqual(attributes["SupportsVertexColorMask"], "True")
        self.assertEqual(attributes["_OriginalFileVersion_"], "123")
        self.assertEqual(values(resource.find('./children/node[@id="Base"]')),
                         {"CustomPreservedValue": "material-and-rig-metadata"})
        relative = "Generated/Public/Nudegate/Assets/Bodies/human/balanced.GR2"
        self.assertEqual(attributes["SourceFile"], relative)
        self.assertEqual(attributes["Template"], relative[:-4] + ".Dummy_Root.0")
        objects = resource.findall('./children/node[@id="Objects"]')
        self.assertEqual([values(obj) for obj in objects], [{
            "ObjectID": f"balanced.{MESH}.0", "MaterialID": MATERIAL, "LOD": "0"}])
        self.assertFalse(resource.findall('.//node[@id="ClothProxyMapping"]'))
        self.assertFalse(resource.findall('.//node[@id="ClothParams"]'))
        self.assertEqual(attributes["BoundsMin"], "0 1 -4")
        self.assertEqual(attributes["BoundsMax"], "2 4 6")
        self.assertEqual((self.output / relative).read_bytes(), self.gr2.read_bytes())
        self.assertEqual(entry["source_gr2_sha256"], hashlib.sha256(self.gr2.read_bytes()).hexdigest())
        self.assertEqual(entry["material_ids"], [MATERIAL])
        self.assertEqual(report["physics"], "not included")
        self.assertEqual(report["in_game"], "not tested")
        self.assertEqual(report["counts"], {"families": 1, "resources": 1, "meshes": 1})
        self.assertEqual(self.bank.read_bytes(), before)
        self.assertEqual(self.manifest, manifest_before)

    def test_aliases_get_distinct_private_resources_but_share_the_single_mesh_copy(self) -> None:
        self.manifest["families"][0]["original_visual_ids"].append(ALIAS)
        report = self.build()
        self.assertEqual(report["counts"], {"families": 1, "resources": 2, "meshes": 1})
        self.assertEqual(set(report["resource_map"]), {ORIGINAL, ALIAS})
        self.assertEqual(len({r["private_visual_id"] for r in report["variants"]}), 2)
        self.assertEqual(report["resource_map"][ORIGINAL][0]["family_id"], "human")

    def test_id_is_deterministic_and_changes_when_gr2_content_changes(self) -> None:
        first = self.build()
        self.assertEqual(first, self.build())
        self.gr2.write_bytes(self.gr2.read_bytes() + b"changed-shape")
        self.output = self.base / "second-output"
        second = self.build()
        self.assertNotEqual(first["variants"][0]["private_visual_id"],
                            second["variants"][0]["private_visual_id"])

    def test_existing_conflicting_artifact_is_not_overwritten(self) -> None:
        report = self.build()
        bank_before = Path(report["outputs"]["visuals"]).read_bytes()
        self.gr2.write_bytes(self.gr2.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "Output collision"):
            self.build()
        self.assertEqual(Path(report["outputs"]["visuals"]).read_bytes(), bank_before)
        self.assertEqual(Path(report["outputs"]["meshes"][0]).read_bytes(), MAGIC + b"\0" * 16 + b"opaque-gr2-payload")

    def test_unsafe_family_variant_and_mesh_names_are_rejected(self) -> None:
        baseline = copy.deepcopy(self.manifest)
        for location, field, bad in [("family", "id", "../escape"), ("family", "id", "CON"),
                                     ("variant", "id", "x/y"), ("variant", "id", "x\\y"),
                                     ("variant", "mesh_name", "mesh.0"), ("variant", "model_name", "bad/root")]:
            with self.subTest(field=field, value=bad):
                self.manifest = copy.deepcopy(baseline)
                target = self.manifest["families"][0]
                if location == "variant":
                    target = target["variants"][0]
                target[field] = bad
                self.assert_refused("Unsafe|Reserved")

    def test_invalid_missing_or_relative_files_are_rejected(self) -> None:
        variant = self.manifest["families"][0]["variants"][0]
        original = variant["gr2"]
        for bad in ("relative.GR2", str(self.base / "missing.GR2"), str(self.dae)):
            with self.subTest(path=bad):
                variant["gr2"] = bad
                self.assert_refused("Missing or invalid")
        variant["gr2"] = original
        self.gr2.write_bytes(b"this is not a GR2")
        self.assert_refused("GR2 header")

    def test_unknown_uuid_and_duplicate_original_admission_are_rejected(self) -> None:
        family = self.manifest["families"][0]
        family["original_visual_ids"] = [SKELETON]
        self.assert_refused("Unknown original")
        family["original_visual_ids"] = [ORIGINAL, ORIGINAL]
        self.assert_refused("only one family")

    def test_unrelated_source_drafts_are_ignored_but_selected_duplicates_are_rejected(self) -> None:
        parent = self.source.find('./region/node/children')
        parent.append(node("Resource", ID="", Name="unrelated-draft"))
        parent.append(source_visual(ALIAS))  # unrelated duplicate UUID
        self.save_bank()
        report = self.build()
        self.assertEqual(report["ignored_unrelated_malformed_source_records"], 1)
        self.output = self.base / "duplicate-output"
        parent.append(source_visual(ORIGINAL))
        self.save_bank()
        self.assert_refused("Duplicate selected source")

    def test_mesh_name_must_match_dae_and_single_skin_is_required(self) -> None:
        variant = self.manifest["families"][0]["variants"][0]
        variant["mesh_name"] = "different_mesh"
        self.assert_refused("mesh_name")
        variant["mesh_name"] = MESH
        tree = ET.parse(self.dae)
        tree.getroot().remove(tree.find(f'{{{NS}}}library_controllers'))
        tree.write(self.dae)
        self.assert_refused("one skin controller")

    def test_cloth_inputs_are_rejected_instead_of_silently_losing_physics(self) -> None:
        first = self.source.find('.//node[@id="Resource"]/children')
        first.append(node("ClothParams", Damping="0.07 0.07 0.07"))
        self.save_bank()
        self.assert_refused("cloth physics")
        first.remove(first.find('node[@id="ClothParams"]'))
        self.save_bank()
        tree = ET.parse(self.dae)
        ET.SubElement(tree.getroot(), "DivModelType").text = "ClothPhysics"
        tree.write(self.dae)
        self.assert_refused("matched physics")

    def test_conflicting_materials_and_private_uuid_collisions_are_rejected(self) -> None:
        obj = self.source.find('.//node[@id="Resource"]/children/node[@id="Objects"]')
        obj.find('attribute[@id="MaterialID"]').set("value", OTHER_MATERIAL)
        self.save_bank()
        self.assert_refused("consistent source skin material")
        obj.find('attribute[@id="MaterialID"]').set("value", MATERIAL)
        self.save_bank()
        with patch("nudegate.body_resources.uuid5", return_value=UUID(ORIGINAL)):
            self.assert_refused("UUID collision")

    def test_output_link_cannot_redirect_generated_assets(self) -> None:
        outside = self.base / "outside"
        outside.mkdir()
        link = self.base / "linked-output"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("Creating symbolic links is not permitted on this host")
        with self.assertRaisesRegex(ValueError, "link/reparse point"):
            create_body_resources(self.manifest, self.bank, link)
        self.assertEqual(list(outside.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
