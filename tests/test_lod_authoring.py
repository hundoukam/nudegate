"""All-LOD assembly and final export acceptance tests with indexed skins."""
from __future__ import annotations

import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import xml.etree.ElementTree as ET

from nudegate.collada import ColladaMesh, _canonical, _tag as q
from nudegate.lod_authoring import bake_lods, enumerate_lods, validate_lod_roundtrip, _vertex_bijection


IDENTITY = "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"


def source(parent, identifier, values, count, stride, params, kind="float_array"):
    node = ET.SubElement(parent, q("source"), {"id": identifier})
    ET.SubElement(node, q(kind), {"id": identifier + "-array", "count": str(len(values.split()))}).text = values
    accessor = ET.SubElement(ET.SubElement(node, q("technique_common")), q("accessor"),
                             {"source": "#" + identifier + "-array", "count": str(count), "stride": str(stride)})
    for name, param_type in params:
        ET.SubElement(accessor, q("param"), {"name": name, "type": param_type})


def fixture(lods=2):
    root = ET.Element(q("COLLADA"), {"version": "1.4.0"})
    geometries = ET.SubElement(root, q("library_geometries"))
    controllers = ET.SubElement(root, q("library_controllers"))
    scene = ET.SubElement(ET.SubElement(root, q("library_visual_scenes")), q("visual_scene"), {"id": "scene"})
    joint = ET.SubElement(scene, q("node"), {"id": "Root", "sid": "Root", "type": "JOINT"})
    ET.SubElement(joint, q("matrix")).text = IDENTITY
    ET.SubElement(joint, q("node"), {"id": "Spine", "sid": "Spine", "type": "JOINT"})
    for lod in range(lods):
        name = "Body" + (f"_LOD{lod}" if lod else "")
        geometry = ET.SubElement(geometries, q("geometry"), {"id": name + "-geom", "name": name, "custom": "retain"})
        mesh = ET.SubElement(geometry, q("mesh"))
        source(mesh, name + "-positions", "0 0 0 1 0 0 0 1 0", 3, 3, [(x, "float") for x in "XYZ"])
        source(mesh, name + "-normals", "0 0 1", 1, 3, [(x, "float") for x in "XYZ"])
        source(mesh, name + "-uv0", "0 0 1 0 0 1", 3, 2, [("S", "float"), ("T", "float")])
        source(mesh, name + "-uv1", ".1 .1 .9 .1 .1 .9", 3, 2, [("S", "float"), ("T", "float")])
        source(mesh, name + "-tangents", "1 0 0", 1, 3, [(x, "float") for x in "XYZ"])
        triangles = ET.SubElement(mesh, q("triangles"), {"count": "1", "material": "skin"})
        for semantic, key, offset, layer in (("VERTEX", "positions", 0, None), ("NORMAL", "normals", 1, None),
                                             ("TEXCOORD", "uv0", 2, "0"), ("TEXCOORD", "uv1", 3, "1"),
                                             ("TEXTANGENT", "tangents", 4, None)):
            attributes = {"semantic": semantic, "source": "#" + name + "-" + key, "offset": str(offset)}
            if layer is not None:
                attributes["set"] = layer
            ET.SubElement(triangles, q("input"), attributes)
        ET.SubElement(triangles, q("p")).text = "0 0 0 0 0 1 0 1 1 0 2 0 2 2 0"
        technique = ET.SubElement(ET.SubElement(mesh, q("extra")), q("technique"), {"profile": "LSTools"})
        ET.SubElement(technique, "ExportOrder").text = str(lod)
        if lod:
            ET.SubElement(technique, "LOD").text = str(lod)
        ET.SubElement(technique, "LODDistance").text = str(6 + lod * 7)
        controller = ET.SubElement(controllers, q("controller"), {"id": name + "-skin", "name": name + "_Skin"})
        skin = ET.SubElement(controller, q("skin"), {"source": "#" + name + "-geom"})
        ET.SubElement(skin, q("bind_shape_matrix")).text = IDENTITY
        source(skin, name + "-joints", "Root Spine", 2, 1, [("JOINT", "Name")], "Name_array")
        source(skin, name + "-poses", IDENTITY + " " + IDENTITY, 2, 16, [("TRANSFORM", "float4x4")])
        source(skin, name + "-weights", "1", 1, 1, [("WEIGHT", "float")])
        joints = ET.SubElement(skin, q("joints"))
        ET.SubElement(joints, q("input"), {"semantic": "JOINT", "source": "#" + name + "-joints"})
        ET.SubElement(joints, q("input"), {"semantic": "INV_BIND_MATRIX", "source": "#" + name + "-poses"})
        weights = ET.SubElement(skin, q("vertex_weights"), {"count": "3"})
        ET.SubElement(weights, q("input"), {"semantic": "JOINT", "source": "#" + name + "-joints", "offset": "0"})
        ET.SubElement(weights, q("input"), {"semantic": "WEIGHT", "source": "#" + name + "-weights", "offset": "1"})
        ET.SubElement(weights, q("vcount")).text = "1 1 1"
        ET.SubElement(weights, q("v")).text = "0 0 0 0 0 0"
        instance = ET.SubElement(ET.SubElement(scene, q("node"), {"id": name + "-node"}), q("instance_controller"),
                                 {"url": "#" + name + "-skin"})
        ET.SubElement(instance, q("skeleton")).text = "#Root"
    ET.SubElement(root, q("extra"), {"preserve": "root-metadata"})
    return root


def reindex(root, geometry_id, mapping, *, reorder_weight_table=False):
    geometry = next(item for item in root.findall(f"{q('library_geometries')}/{q('geometry')}")
                    if item.get("id") == geometry_id)
    mesh = geometry.find(q("mesh"))
    name = geometry.get("name")
    positions = mesh.find(f"{q('source')}[@id='{name}-positions']/{q('float_array')}")
    original = list(map(float, positions.text.split()))
    replacement = [None] * len(mapping)
    for old, new in mapping.items():
        replacement[new] = original[old * 3:old * 3 + 3]
    positions.text = " ".join(str(value) for point in replacement for value in point)
    for triangle in mesh.findall(q("triangles")):
        inputs = triangle.findall(q("input"))
        stride = max(int(item.get("offset", "0")) for item in inputs) + 1
        offset = next(int(item.get("offset", "0")) for item in inputs if item.get("semantic") == "VERTEX")
        p = triangle.find(q("p"))
        values = list(map(int, p.text.split()))
        for corner in range(0, len(values), stride):
            values[corner + offset] = mapping[values[corner + offset]]
        p.text = " ".join(map(str, values))
    skin = next(item for item in root.findall(f"{q('library_controllers')}/{q('controller')}/{q('skin')}")
                if item.get("source") == "#" + geometry_id)
    influences = skin.find(q("vertex_weights"))
    offsets = {item.get("semantic"): int(item.get("offset", "0")) for item in influences.findall(q("input"))}
    stride = max(offsets.values()) + 1
    counts = list(map(int, influences.find(q("vcount")).text.split()))
    values = list(map(int, influences.find(q("v")).text.split()))
    if reorder_weight_table:
        reference = next(item.get("source")[1:] for item in influences.findall(q("input")) if item.get("semantic") == "WEIGHT")
        array = skin.find(f"{q('source')}[@id='{reference}']/{q('float_array')}")
        weights = list(map(float, array.text.split()))
        weight_map = {old: (old + 1) % len(weights) for old in range(len(weights))}
        changed_weights = [None] * len(weights)
        for old, new in weight_map.items():
            changed_weights[new] = weights[old]
        array.text = " ".join(map(str, changed_weights))
        for cursor in range(0, len(values), stride):
            values[cursor + offsets["WEIGHT"]] = weight_map[values[cursor + offsets["WEIGHT"]]]
    replacement = [None] * len(counts)
    cursor = 0
    for old, count in enumerate(counts):
        replacement[mapping[old]] = values[cursor:cursor + count * stride]
        cursor += count * stride
    changed_counts = [None] * len(counts)
    for old, new in mapping.items():
        changed_counts[new] = counts[old]
    influences.find(q("vcount")).text = " ".join(map(str, changed_counts))
    influences.find(q("v")).text = " ".join(str(value) for record in replacement for value in record)


class LodAuthoringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.reference = self.directory / "reference.dae"
        self.authored = self.directory / "authored.dae"
        self.exported = self.directory / "exported.dae"
        self.write(fixture(), self.reference)

    def write(self, root, path):
        ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)

    def transform(self, mesh, lod):
        positions = mesh.positions
        positions[2][2] += .1 * (lod + 1)
        return positions

    def bake(self):
        return bake_lods(self.reference, self.authored, self.transform, expected_lods=2)

    def test_enumerates_all_explicit_indexed_skinned_lods(self):
        rows = enumerate_lods(self.reference, expected_lods=2)
        self.assertEqual([(row["lod"], row["mesh_name"]) for row in rows], [(0, "Body"), (1, "Body_LOD1")])
        self.assertTrue(all(row["vertex_count"] == 3 and row["snapshot"]["skin_weighted_vertices"] == 3 for row in rows))
        with self.assertRaisesRegex(ValueError, "Expected all 5 LODs"):
            enumerate_lods(self.reference, expected_lods=5)

    def test_assembly_processes_every_lod_and_preserves_external_xml(self):
        calls = []
        def transform(mesh, lod):
            calls.append(lod)
            return self.transform(mesh, lod)
        report = bake_lods(self.reference, self.authored, transform, expected_lods=2)
        self.assertEqual(calls, [0, 1])
        self.assertEqual(report["lod_count"], 2)
        self.assertTrue(report["all_lods_processed"])
        before, after = ET.parse(self.reference).getroot(), ET.parse(self.authored).getroot()
        for tag in ("library_controllers", "library_visual_scenes", "extra"):
            self.assertEqual(_canonical(before.find(q(tag))), _canonical(after.find(q(tag))))
        for row in report["lods"]:
            geometry = next(g for g in after.findall(f"{q('library_geometries')}/{q('geometry')}") if g.get("id") == row["geometry_id"])
            self.assertEqual(geometry.get("custom"), "retain")
            positions = ColladaMesh.load(self.authored, row["geometry_id"]).positions
            self.assertAlmostEqual(positions[2][2], .1 * (row["lod"] + 1))
            self.assertEqual(row["snapshot"]["controller_sha256"], row["authored_snapshot"]["controller_sha256"])
            self.assertEqual(row["snapshot"]["uv_sha256"], row["authored_snapshot"]["uv_sha256"])

    def test_invalid_later_lod_never_publishes_partial_output(self):
        self.authored.write_text("prior output")
        def transform(mesh, lod):
            return self.transform(mesh, lod) if lod == 0 else [[0, 0, 0]]
        with self.assertRaisesRegex(ValueError, "preserve vertex count"):
            bake_lods(self.reference, self.authored, transform, expected_lods=2)
        self.assertEqual(self.authored.read_text(), "prior output")

    def test_roundtrip_checks_all_lods_and_all_uv_sets(self):
        self.bake()
        self.exported.write_bytes(self.authored.read_bytes())
        report = validate_lod_roundtrip(self.reference, self.authored, self.exported, expected_lods=2)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["lod_count"], 2)
        self.assertTrue(report["all_lods_validated"])
        self.assertEqual(report["max_position_drift"], 0)
        self.assertEqual(report["max_corner_uv_drift"], 0)

    def test_export_cannot_leave_later_lod_at_source_shape(self):
        self.bake()
        authored, original = ET.parse(self.authored), ET.parse(self.reference)
        target = authored.find(f".//{q('source')}[@id='Body_LOD1-positions']/{q('float_array')}")
        target.text = original.find(f".//{q('source')}[@id='Body_LOD1-positions']/{q('float_array')}").text
        authored.write(self.exported, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "LOD 1 position drift"):
            validate_lod_roundtrip(self.reference, self.authored, self.exported, expected_lods=2)

    def test_secondary_uv_set_regression_is_rejected(self):
        self.bake()
        tree = ET.parse(self.authored)
        array = tree.find(f".//{q('source')}[@id='Body_LOD1-uv1']/{q('float_array')}")
        values = array.text.split()
        values[0] = ".11"
        array.text = " ".join(values)
        tree.write(self.exported, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "corner UVs beyond tolerance"):
            validate_lod_roundtrip(self.reference, self.authored, self.exported, expected_lods=2)

    def test_topology_joint_weight_and_binding_regressions_are_rejected(self):
        self.bake()
        for error in ("topology", "joints", "weights", "inverse", "bind_shape"):
            with self.subTest(error=error):
                tree = ET.parse(self.authored)
                if error == "topology":
                    p = tree.find(f".//{q('triangles')}/{q('p')}")
                    values = p.text.split()
                    values[0], values[5] = values[5], values[0]
                    p.text = " ".join(values)
                elif error == "joints":
                    tree.find(f".//{q('source')}[@id='Body-joints']/{q('Name_array')}").text = "Spine Root"
                elif error == "weights":
                    tree.find(f".//{q('source')}[@id='Body-weights']/{q('float_array')}").text = ".9"
                elif error == "inverse":
                    array = tree.find(f".//{q('source')}[@id='Body-poses']/{q('float_array')}")
                    values = array.text.split()
                    values[0] = "1.001"
                    array.text = " ".join(values)
                else:
                    matrix = tree.find(f".//{q('bind_shape_matrix')}")
                    values = matrix.text.split()
                    values[0] = "1.001"
                    matrix.text = " ".join(values)
                tree.write(self.exported, encoding="utf-8")
                with self.assertRaises(ValueError):
                    validate_lod_roundtrip(self.reference, self.authored, self.exported, expected_lods=2)

    def test_expected_export_precision_tolerances_are_allowed(self):
        self.bake()
        tree = ET.parse(self.authored)
        for source_id, delta in (("Body-positions", 1e-6), ("Body-uv1", 5e-7), ("Body-poses", 2e-5)):
            array = tree.find(f".//{q('source')}[@id='{source_id}']/{q('float_array')}")
            values = list(map(float, array.text.split()))
            values[0] += delta
            array.text = " ".join(map(str, values))
        tree.write(self.exported, encoding="utf-8")
        report = validate_lod_roundtrip(self.reference, self.authored, self.exported, expected_lods=2)
        self.assertLessEqual(report["max_position_drift"], 3e-6)

    def test_missing_duplicate_and_contradictory_lod_metadata_are_rejected(self):
        for error in ("missing", "duplicate", "contradictory", "controller"):
            with self.subTest(error=error):
                root = fixture()
                techniques = root.findall(f".//{q('mesh')}/{q('extra')}/{q('technique')}")
                if error == "missing":
                    techniques[1].remove(techniques[1].find("ExportOrder"))
                elif error == "duplicate":
                    techniques[1].find("ExportOrder").text = "0"
                    techniques[1].find("LOD").text = "0"
                elif error == "contradictory":
                    techniques[1].find("LOD").text = "2"
                else:
                    library = root.find(q("library_controllers"))
                    duplicate = copy.deepcopy(library[0])
                    duplicate.set("id", "duplicate-controller")
                    library.append(duplicate)
                self.write(root, self.reference)
                with self.assertRaises(ValueError):
                    enumerate_lods(self.reference, expected_lods=2)

    def test_missing_lod_in_export_is_rejected_even_without_expected_count(self):
        self.bake()
        self.write(fixture(lods=1), self.exported)
        with self.assertRaisesRegex(ValueError, "changed or omitted explicit LOD identities"):
            validate_lod_roundtrip(self.reference, self.authored, self.exported)

    def weighted_source(self):
        root = fixture()
        array = root.find(f".//{q('source')}[@id='Body-weights']/{q('float_array')}")
        array.text = "1 .7 .2"
        array.set("count", "3")
        root.find(f".//{q('source')}[@id='Body-weights']/{q('technique_common')}/{q('accessor')}").set("count", "3")
        root.find(f".//{q('skin')}[@source='#Body-geom']/{q('vertex_weights')}/{q('v')}").text = "0 0 1 1 0 2"
        self.write(root, self.reference)

    def test_bijective_vertex_and_weight_table_reindexing_are_accepted(self):
        self.weighted_source()
        self.bake()
        tree = ET.parse(self.authored)
        reindex(tree.getroot(), "Body-geom", {0: 1, 1: 2, 2: 0}, reorder_weight_table=True)
        tree.write(self.exported, encoding="utf-8")
        report = validate_lod_roundtrip(self.reference, self.authored, self.exported, expected_lods=2)
        self.assertEqual(report["lods"][0]["vertex_bijection"]["reindexed_vertices"], 3)
        self.assertEqual(report["lods"][0]["max_skin_weight_drift"], 0)
        self.assertEqual(report["max_position_drift"], 0)

    def test_reindexed_vertex_cannot_receive_a_different_skin_weight(self):
        self.weighted_source()
        self.bake()
        tree = ET.parse(self.authored)
        reindex(tree.getroot(), "Body-geom", {0: 1, 1: 2, 2: 0}, reorder_weight_table=True)
        v = tree.find(f".//{q('skin')}[@source='#Body-geom']/{q('vertex_weights')}/{q('v')}")
        values = v.text.split()
        values[1] = "1"  # New vertex 0 should carry source vertex 2's .2 weight.
        v.text = " ".join(values)
        tree.write(self.exported, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "mapped skin weights"):
            validate_lod_roundtrip(self.reference, self.authored, self.exported, expected_lods=2)

    def test_vertex_bijection_rejects_welds_splits_and_unused_vertices(self):
        before = SimpleNamespace(positions=[[0, 0, 0]] * 4, triangles=[(0, 1, 2), (1, 3, 2)])
        for triangles in ([(2, 0, 3), (1, 1, 3)], [(2, 0, 3), (0, 2, 3)]):
            with self.subTest(triangles=triangles), self.assertRaises(ValueError):
                _vertex_bijection(before, SimpleNamespace(positions=[[0, 0, 0]] * 4, triangles=triangles))
        before = SimpleNamespace(positions=[[0, 0, 0]] * 5, triangles=[(0, 1, 2), (1, 3, 2)])
        with self.assertRaisesRegex(ValueError, "every source and export vertex"):
            _vertex_bijection(before, before)


if __name__ == "__main__":
    unittest.main()
