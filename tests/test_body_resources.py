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
STRONG = "9725b3db-6e40-054b-dc49-b8e479bc0cba"
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

    def make_multilod_fixture(self) -> None:
        """Five actual exported geometries/controllers with explicit order."""
        tree = ET.parse(self.dae)
        root = tree.getroot()
        geometries = root.find(f'{{{NS}}}library_geometries')
        controllers = root.find(f'{{{NS}}}library_controllers')
        original_geometry = copy.deepcopy(geometries[0])
        original_controller = copy.deepcopy(controllers[0])
        geometries.clear()
        controllers.clear()
        descriptors = []
        for level in range(5):
            geometry, controller = copy.deepcopy(original_geometry), copy.deepcopy(original_controller)
            suffix = "" if level == 0 else f"-lod{level}"
            renames = {n.get("id"): n.get("id") + suffix
                       for subtree in (geometry, controller) for n in subtree.iter() if n.get("id")}
            for subtree in (geometry, controller):
                for element in subtree.iter():
                    for key, value in list(element.attrib.items()):
                        if key == "id":
                            element.set(key, renames[value])
                        elif value.startswith("#") and value[1:] in renames:
                            element.set(key, "#" + renames[value[1:]])
            name = MESH if level == 0 else f"{MESH}_LOD{level}"
            geometry.set("name", name)
            extra = ET.SubElement(geometry.find(f'{{{NS}}}mesh'), f'{{{NS}}}extra')
            technique = ET.SubElement(extra, f'{{{NS}}}technique', {"profile": "LSTools"})
            ET.SubElement(technique, "ExportOrder").text = str(level)
            geometries.append(geometry)
            controllers.append(controller)
            descriptors.append({"lod": level, "geometry_id": geometry.get("id"), "mesh_name": name})
        tree.write(self.dae, encoding="utf-8", xml_declaration=True)
        family = self.manifest["families"][0]
        family["original_visual_ids"] = [STRONG]
        family["variants"][0]["lods"] = descriptors
        original = self.source.find('.//node[@id="Resource"]')
        original.find('attribute[@id="ID"]').set("value", STRONG)
        original.find('attribute[@id="Slot"]').set("value", "Unassigned")
        nested = original.find("children")
        for obj in list(nested.findall('node[@id="Objects"]')):
            nested.remove(obj)
        for level in range(5):
            nested.append(node("Objects", ObjectID=f"Original.SourceMesh_LOD{level}.{level}",
                               LOD=str(level), MaterialID=MATERIAL if level % 2 == 0 else OTHER_MATERIAL))
        self.save_bank()

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

    def test_strong_unassigned_resource_preserves_all_five_lods_and_each_material(self) -> None:
        self.make_multilod_fixture()
        # LOD 4 is deliberately larger; the resource bounds must use LOD 0.
        tree = ET.parse(self.dae)
        geometry = tree.find(f'.//{{{NS}}}geometry[@id="body-geom-lod4"]')
        geometry.find(f'.//{{{NS}}}float_array').text = "0 100 200 100 300 -400 200 400 600"
        tree.write(self.dae)
        report = self.build()
        resource = ET.parse(report["outputs"]["visuals"]).find('.//node[@id="Resource"]')
        self.assertEqual(values(resource)["Slot"], "Unassigned")
        self.assertEqual(values(resource)["BoundsMax"], "2 4 6")
        objects = resource.findall('./children/node[@id="Objects"]')
        self.assertEqual(len(objects), 5)
        for level, obj in enumerate(objects):
            name = MESH if level == 0 else f"{MESH}_LOD{level}"
            self.assertEqual(values(obj), {"ObjectID": f"balanced.{name}.{level}",
                                          "LOD": str(level),
                                          "MaterialID": MATERIAL if level % 2 == 0 else OTHER_MATERIAL})
        lods = report["variants"][0]["lods"]
        self.assertEqual([lod["lod"] for lod in lods], list(range(5)))
        self.assertEqual([lod["mesh_name"] for lod in lods],
                         [MESH] + [f"{MESH}_LOD{level}" for level in range(1, 5)])

    def test_unassigned_is_rejected_for_unregistered_body_uuid(self) -> None:
        self.source.find('.//node[@id="Resource"]/attribute[@id="Slot"]').set("value", "Unassigned")
        self.save_bank()
        self.assert_refused("not a NakedBody")

    def test_registered_strong_resource_requires_all_five_lods(self) -> None:
        self.manifest["families"][0]["original_visual_ids"] = [STRONG]
        self.source.find('.//node[@id="Resource"]/attribute[@id="ID"]').set("value", STRONG)
        self.save_bank()
        self.assert_refused("strong body resources require all five")

    def test_missing_or_duplicate_lod_declarations_are_rejected(self) -> None:
        self.make_multilod_fixture()
        lods = self.manifest["families"][0]["variants"][0]["lods"]
        missing = lods.pop()
        self.assert_refused("all five LODs")
        lods.append(missing)
        lods[4]["lod"] = 3
        self.assert_refused("all five LODs")

    def test_missing_or_extra_exported_lod_geometry_is_rejected(self) -> None:
        self.make_multilod_fixture()
        tree = ET.parse(self.dae)
        geometries = tree.find(f'{{{NS}}}library_geometries')
        removed = geometries[-1]
        geometries.remove(removed)
        tree.write(self.dae)
        self.assert_refused("match exactly the five")
        geometries.append(removed)
        extra = copy.deepcopy(removed)
        extra.set("id", "extra-geometry")
        geometries.append(extra)
        tree.write(self.dae)
        self.assert_refused("match exactly the five")

    def test_lod_controller_order_and_source_mapping_must_match(self) -> None:
        self.make_multilod_fixture()
        tree = ET.parse(self.dae)
        order = next(n for n in tree.find(f'.//{{{NS}}}geometry[@id="body-geom-lod2"]').iter()
                     if n.tag.split("}")[-1] == "ExportOrder")
        order.text = "4"
        tree.write(self.dae)
        self.assert_refused("ExportOrder")
        order.text = "2"
        tree.write(self.dae)
        mapping = self.source.find('.//node[@id="Resource"]/children')
        obj = next(n for n in mapping.findall('node[@id="Objects"]') if values(n)["LOD"] == "2")
        mapping.remove(obj)
        self.save_bank()
        self.assert_refused("one material mapping for each LOD")
        mapping.append(obj)
        self.save_bank()
        controller = tree.find(f'.//{{{NS}}}controller[@id="body-skin-lod2"]')
        controller.find(f'{{{NS}}}skin').set("source", "#body-geom-lod1")
        tree.write(self.dae)
        self.assert_refused("one skin controller per LOD")


if __name__ == "__main__":
    unittest.main()
