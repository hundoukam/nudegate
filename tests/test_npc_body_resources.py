"""Check model isolation and per-LOD materials when reusing existing body banks."""

from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from npc_donor_resources import _relocate, publish_resources
from npc_native_resources import _restore_materials
from nudegate.core import attrs


def node(parent, name, **values):
    child = ET.SubElement(parent, "node", id=name)
    for key, value in values.items():
        ET.SubElement(child, "attribute", id=key, value=str(value))
    return child


class NpcBodyResourcesTests(unittest.TestCase):
    def test_moving_a_probe_leaves_nested_cloth_and_mesh_identifiers_intact(self):
        path = Path("Public/NudegateDonorProbe/Assets/donor_test/model.GR2")
        resource = node(ET.Element("children"), "Resource", ID="old", Name="test",
                        SourceFile=path.as_posix(), Template=path.with_suffix("").as_posix() + ".Dummy_Root.0")
        children = ET.SubElement(resource, "children")
        node(children, "Objects", ObjectID="model.body.0", MaterialID="native")
        node(children, "ClothParams", UUID="model.cloth.1")
        node(children, "ClothProxyMapping", ClosestVertices="a-mapping")
        nested = ET.tostring(children)
        new, identifier = _relocate(resource, path, "Nudegate", "donor_test")
        self.assertEqual(ET.tostring(children), nested)
        self.assertEqual(attrs(resource)["ID"], identifier)
        self.assertNotEqual(identifier, "old")
        self.assertEqual(attrs(resource)["Template"], new.with_suffix("").as_posix() + ".Dummy_Root.0")
        self.assertEqual(attrs(resource)["SourceFile"], new.as_posix())

    def test_materials_with_distinct_lods_match_by_lod_independent_of_xml_order(self):
        resource = ET.Element("node")
        children = ET.SubElement(resource, "children")
        low = node(children, "Objects", LOD="1", ObjectID="low", MaterialID="private-low")
        high = node(children, "Objects", LOD="0", ObjectID="high", MaterialID="private-high")
        entry = {"lods": [{"lod": 0, "object_id": "high", "original_material_id": "native-high"},
                          {"lod": 1, "object_id": "low", "original_material_id": "native-low"}]}
        palette = {"native-high": "private-high", "native-low": "private-low"}
        self.assertEqual(_restore_materials(resource, entry, palette), 2)
        self.assertEqual(attrs(high)["MaterialID"], "native-high")
        self.assertEqual(attrs(low)["MaterialID"], "native-low")

    def test_conflict_during_publication_keeps_prior_stage_intact(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            info = root / "new-resource"
            info.write_bytes(b"new")
            stage = root / "stage"
            stage.mkdir()
            (stage / "existing").write_bytes(b"accepted")
            with self.assertRaises(FileExistsError):
                publish_resources(stage, {Path("first"): info, Path("existing"): info})
            self.assertFalse((stage / "first").exists())
            self.assertEqual((stage / "existing").read_bytes(), b"accepted")
