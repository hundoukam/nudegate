"""Indexed COLLADA editing, split normals, and rig/UV preservation tests."""

from __future__ import annotations

import math
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from nudegate.collada import ColladaMesh, NS, validate_smooth_seams


def q(name: str) -> str:
    return f"{{{NS}}}{name}"


def add_source(parent: ET.Element, name: str, values: str, count: int, stride: int,
               names: tuple[str, ...], array_type: str = "float_array") -> None:
    source = ET.SubElement(parent, q("source"), {"id": name})
    array = ET.SubElement(source, q(array_type), {"id": name + "-array", "count": str(len(values.split()))})
    array.text = values
    accessor = ET.SubElement(ET.SubElement(source, q("technique_common")), q("accessor"),
                             {"source": "#" + name + "-array", "count": str(count), "stride": str(stride)})
    for param in names:
        ET.SubElement(accessor, q("param"), {"name": param,
                     "type": "Name" if array_type == "Name_array" else "float"})


def document(*, direct_vertex: bool = False) -> ET.Element:
    root = ET.Element(q("COLLADA"), {"version": "1.4.0"})
    materials = ET.SubElement(root, q("library_materials"))
    ET.SubElement(materials, q("material"), {"id": "skin-material", "name": "Original material"})
    geometry = ET.SubElement(ET.SubElement(root, q("library_geometries")), q("geometry"), {"id": "body"})
    mesh = ET.SubElement(geometry, q("mesh"))
    add_source(mesh, "positions", "0 0 0 2 0 0 0 1 0 0 0 2", 4, 3, ("X", "Y", "Z"))
    add_source(mesh, "normals", "0 0 1 0 1 0", 2, 3, ("X", "Y", "Z"))
    add_source(mesh, "uv", "0 0 1 0 0 1 .1 .1 .9 .1 .1 .9", 6, 2, ("S", "T"))
    add_source(mesh, "tangents", "1 0 0 0 0 1", 2, 3, ("X", "Y", "Z"))
    vertices = ET.SubElement(mesh, q("vertices"), {"id": "vertices"})
    ET.SubElement(vertices, q("input"), {"semantic": "POSITION", "source": "#positions"})
    triangles = ET.SubElement(mesh, q("triangles"), {"count": "2", "material": "skin-material"})
    for semantic, source, offset in (("VERTEX", "positions" if direct_vertex else "vertices", 0),
                                     ("NORMAL", "normals", 1), ("TEXCOORD", "uv", 2),
                                     ("TEXTANGENT", "tangents", 3)):
        ET.SubElement(triangles, q("input"), {"semantic": semantic, "source": "#" + source, "offset": str(offset)})
    # The same position 0 has different normal indices on these two faces.
    ET.SubElement(triangles, q("p")).text = "0 0 0 0 1 0 1 0 2 0 2 0 0 1 3 1 3 1 4 1 1 1 5 1"
    controller = ET.SubElement(ET.SubElement(root, q("library_controllers")), q("controller"), {"id": "skin"})
    skin = ET.SubElement(controller, q("skin"), {"source": "#body"})
    ET.SubElement(skin, q("bind_shape_matrix")).text = "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"
    add_source(skin, "joints", "Root Spine", 2, 1, ("JOINT",), "Name_array")
    add_source(skin, "weights", "1 .5 .5 1", 4, 1, ("WEIGHT",))
    joints = ET.SubElement(skin, q("joints"))
    ET.SubElement(joints, q("input"), {"semantic": "JOINT", "source": "#joints"})
    weights = ET.SubElement(skin, q("vertex_weights"), {"count": "4"})
    ET.SubElement(weights, q("input"), {"semantic": "JOINT", "source": "#joints", "offset": "0"})
    ET.SubElement(weights, q("input"), {"semantic": "WEIGHT", "source": "#weights", "offset": "1"})
    ET.SubElement(weights, q("vcount")).text = "1 2 1 1"
    ET.SubElement(weights, q("v")).text = "0 0 0 1 1 2 0 3 0 0"
    extra = ET.SubElement(root, q("extra"))
    ET.SubElement(extra, q("technique"), {"profile": "LSLib"}).text = "Keep exporter metadata"
    return root


class ColladaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.path = self.directory / "body.dae"

    def write(self, root: ET.Element) -> Path:
        ET.ElementTree(root).write(self.path, encoding="utf-8", xml_declaration=True)
        return self.path

    def load(self, root: ET.Element | None = None) -> ColladaMesh:
        return ColladaMesh.load(self.write(root if root is not None else document()))

    def test_reads_standard_and_lslib_direct_vertex_inputs(self) -> None:
        for direct in (False, True):
            with self.subTest(direct_vertex=direct):
                mesh = self.load(document(direct_vertex=direct))
                self.assertEqual(mesh.positions, [[0, 0, 0], [2, 0, 0], [0, 1, 0], [0, 0, 2]])
                self.assertEqual(mesh.triangles, [(0, 1, 2), (0, 3, 1)])
                self.assertEqual(mesh.snapshot()["skin_weighted_vertices"], 4)

    def test_deformation_preserves_skin_uv_materials_topology_and_other_xml(self) -> None:
        mesh = self.load()
        before = mesh.snapshot()
        changed = mesh.positions
        changed[2][2] = 1
        report = mesh.set_positions(changed)
        after = mesh.snapshot()
        self.assertEqual(report["normals_updated"], 1)
        self.assertEqual(report["normals_preserved"], 1)
        for key in ("topology_id", "controller_sha256", "uv_sha256", "tangent_sha256", "material_sha256"):
            self.assertEqual(before[key], after[key], key)
        self.assertNotEqual(before["position_sha256"], after["position_sha256"])
        self.assertNotEqual(before["normal_sha256"], after["normal_sha256"])
        output = self.directory / "deformed.dae"
        mesh.save(output)
        reloaded = ColladaMesh.load(output)
        self.assertEqual(after, reloaded.snapshot())
        root = ET.parse(output).getroot()
        self.assertEqual(root.find(f"{q('extra')}/{q('technique')}").text, "Keep exporter metadata")

    def test_split_corner_normals_remain_split_and_are_recalculated(self) -> None:
        mesh = self.load()
        changed = mesh.positions
        changed[2][2] = 1
        mesh.set_positions(changed)
        output = self.directory / "normals.dae"
        mesh.save(output)
        normals = list(map(float, ET.parse(output).find(f".//{q('source')}[@id='normals']/{q('float_array')}").text.split()))
        self.assertEqual(normals[0], 0)
        self.assertAlmostEqual(normals[1], -1 / math.sqrt(2))
        self.assertAlmostEqual(normals[2], 1 / math.sqrt(2))
        self.assertEqual(normals[3:], [0, 1, 0])

    def test_smooth_normal_accumulates_area_once_per_face(self) -> None:
        root = document()
        p = root.find(f".//{q('triangles')}/{q('p')}")
        values = list(map(int, p.text.split()))
        for offset in range(1, len(values), 4):
            values[offset] = 0
        p.text = " ".join(map(str, values))
        mesh = self.load(root)
        changed = mesh.positions
        changed[1][0] = 3  # Same area ratio, but triggers a real normal update.
        mesh.set_positions(changed)
        output = self.directory / "smooth.dae"
        mesh.save(output)
        normals = list(map(float, ET.parse(output).find(f".//{q('source')}[@id='normals']/{q('float_array')}").text.split()))
        self.assertEqual(normals[0], 0)
        self.assertAlmostEqual(normals[1], 4 / math.sqrt(20))
        self.assertAlmostEqual(normals[2], 2 / math.sqrt(20))
        self.assertEqual(normals[3:], [0, 1, 0], "Unused normal entries must remain intact")

    def test_position_accessor_stride_preserves_extra_components(self) -> None:
        root = document()
        source = root.find(f".//{q('source')}[@id='positions']")
        array = source.find(q("float_array"))
        array.text = "0 0 0 7 2 0 0 8 0 1 0 9 0 0 2 10"
        array.set("count", "16")
        accessor = source.find(f"{q('technique_common')}/{q('accessor')}")
        accessor.set("stride", "4")
        ET.SubElement(accessor, q("param"), {"name": "W", "type": "float"})
        mesh = self.load(root)
        changed = mesh.positions
        changed[2][2] = 1
        mesh.set_positions(changed)
        output = self.directory / "stride.dae"
        mesh.save(output)
        values = list(map(float, ET.parse(output).find(f".//{q('source')}[@id='positions']/{q('float_array')}").text.split()))
        self.assertEqual(values[3::4], [7, 8, 9, 10])

    def test_explicit_selection_required_for_multiple_meshes(self) -> None:
        root = document()
        geometries = root.find(q("library_geometries"))
        ET.SubElement(ET.SubElement(geometries, q("geometry"), {"id": "other"}), q("mesh"))
        self.write(root)
        with self.assertRaisesRegex(ValueError, "Explicit geometry_id required"):
            ColladaMesh.load(self.path)
        self.assertEqual(ColladaMesh.load(self.path, "body").geometry_id, "body")
        with self.assertRaisesRegex(ValueError, "exactly one mesh"):
            ColladaMesh.load(self.path, "absent")

    def test_malformed_position_normal_uv_and_skin_indices_are_rejected(self) -> None:
        for semantic, offset, invalid in (("POSITION", 0, "4"), ("NORMAL", 1, "2"),
                                          ("TEXCOORD", 2, "6"), ("negative", 0, "-1")):
            with self.subTest(semantic=semantic):
                root = document()
                p = root.find(f".//{q('triangles')}/{q('p')}")
                values = p.text.split()
                values[offset] = invalid
                p.text = " ".join(values)
                with self.assertRaises(ValueError):
                    self.load(root)
        root = document()
        root.find(f".//{q('vertex_weights')}/{q('v')}").text = "0 9 0 1 1 2 0 3 0 0"
        with self.assertRaisesRegex(ValueError, "Skin WEIGHT index out of bounds"):
            self.load(root)

    def test_malformed_array_index_counts_and_accessor_bounds_are_rejected(self) -> None:
        for failure in ("array_count", "p_count", "accessor", "skin_count"):
            with self.subTest(failure=failure):
                root = document()
                if failure == "array_count":
                    root.find(f".//{q('float_array')}").set("count", "1")
                elif failure == "p_count":
                    root.find(f".//{q('triangles')}").set("count", "3")
                elif failure == "accessor":
                    root.find(f".//{q('accessor')}").set("offset", "1")
                else:
                    root.find(f".//{q('vertex_weights')}").set("count", "3")
                with self.assertRaises(ValueError):
                    self.load(root)

    def test_rejects_nonfinite_sources_and_unsupported_primitives(self) -> None:
        root = document()
        root.find(f".//{q('float_array')}").text = "nan 0 0 2 0 0 0 1 0 0 0 2"
        with self.assertRaisesRegex(ValueError, "Nonfinite float array"):
            self.load(root)
        root = document()
        ET.SubElement(root.find(f".//{q('mesh')}"), q("polylist"), {"count": "1"})
        with self.assertRaisesRegex(ValueError, "Unsupported mesh primitive"):
            self.load(root)

    def test_topology_hash_tracks_indices_and_skin_but_excludes_positions_and_normals(self) -> None:
        baseline = self.load().topology_id
        root = document()
        root.find(f".//{q('source')}[@id='positions']/{q('float_array')}").text = "0 0 0 3 0 0 0 1 0 0 0 2"
        root.find(f".//{q('source')}[@id='normals']/{q('float_array')}").text = "0 0 -1 0 -1 0"
        self.assertEqual(self.load(root).topology_id, baseline)
        root.find(f".//{q('triangles')}/{q('p')}").text = "1 0 0 0 0 0 1 0 2 0 2 0 0 1 3 1 3 1 4 1 1 1 5 1"
        self.assertNotEqual(self.load(root).topology_id, baseline)
        root = document()
        root.find(f".//{q('source')}[@id='weights']/{q('float_array')}").text = ".9 .5 .5 1"
        self.assertNotEqual(self.load(root).topology_id, baseline)

    def test_invalid_updates_are_atomic_and_require_same_vertex_count(self) -> None:
        mesh = self.load()
        original = mesh.snapshot()
        for invalid in ([[0, 0, 0]], [[0, 0, float('nan')]] * 4,
                        [[True, 0, 0]] * 4, [[0, 0, 0]] * 4):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    mesh.set_positions(invalid)
                self.assertEqual(mesh.snapshot(), original)

    def test_missing_normals_can_only_be_updated_with_explicit_opt_out(self) -> None:
        root = document()
        triangles = root.find(f".//{q('triangles')}")
        triangles.remove(next(item for item in triangles.findall(q("input")) if item.get("semantic") == "NORMAL"))
        mesh = self.load(root)
        original = mesh.snapshot()
        positions = mesh.positions
        positions[2][2] = 1
        with self.assertRaisesRegex(ValueError, "explicit NORMAL binding"):
            mesh.set_positions(positions)
        self.assertEqual(mesh.snapshot(), original)
        self.assertEqual(mesh.set_positions(positions, recalculate_normals=False)["normals_updated"], 0)

    def test_exposed_positions_and_triangles_are_defensive_copies(self) -> None:
        mesh = self.load()
        positions = mesh.positions
        positions[0][0] = 999
        triangles = mesh.triangles
        triangles[0] = (3, 3, 3)
        self.assertEqual(mesh.positions[0], [0, 0, 0])
        self.assertEqual(mesh.triangles[0], (0, 1, 2))

    def test_mutable_sources_cannot_alias_preserved_attribute_arrays(self) -> None:
        root = document()
        tangent = next(item for item in root.findall(f".//{q('triangles')}/{q('input')}")
                       if item.get("semantic") == "TEXTANGENT")
        tangent.set("source", "#normals")
        with self.assertRaisesRegex(ValueError, "shared with another attribute"):
            self.load(root)

    def test_matrix_accessor_width_is_validated(self) -> None:
        root = document()
        skin = root.find(f".//{q('skin')}")
        add_source(skin, "poses", " ".join(["1"] * 17), 2, 16, ("TRANSFORM",))
        param = skin.find(f"{q('source')}[@id='poses']/{q('technique_common')}/{q('accessor')}/{q('param')}")
        param.set("type", "float4x4")
        with self.assertRaisesRegex(ValueError, "Accessor exceeds array bounds"):
            self.load(root)

    def split_position_root(self, smooth: bool) -> ET.Element:
        root = document()
        root.remove(root.find(q("library_controllers")))
        source = root.find(f".//{q('source')}[@id='positions']")
        source.find(q("float_array")).text += " 0 0 0"
        source.find(q("float_array")).set("count", "15")
        source.find(f"{q('technique_common')}/{q('accessor')}").set("count", "5")
        p = root.find(f".//{q('triangles')}/{q('p')}")
        values = p.text.split()
        values[12] = "4"
        p.text = " ".join(values)
        if smooth:
            root.find(f".//{q('source')}[@id='normals']/{q('float_array')}").text = (
                "0 .8944271909999159 .4472135954999579 0 .8944271909999159 .4472135954999579")
        return root

    def test_originally_smooth_uv_split_positions_share_new_normals(self) -> None:
        reference = self.load(self.split_position_root(smooth=True))
        current = self.load(self.split_position_root(smooth=True))
        changed = current.positions
        changed[2][2] = 1
        current.set_positions(changed)
        output = self.directory / "smooth-split.dae"
        current.save(output)
        normals = list(map(float, ET.parse(output).find(f".//{q('source')}[@id='normals']/{q('float_array')}").text.split()))
        self.assertEqual(normals[:3], normals[3:])
        self.assertAlmostEqual(normals[1], 1 / math.sqrt(2))
        self.assertAlmostEqual(normals[2], 1 / math.sqrt(2))
        report = validate_smooth_seams(reference, ColladaMesh.load(output))
        self.assertEqual(report["source_smooth_seam_groups"], 1)
        self.assertLess(report["max_smooth_seam_angle_degrees"], 1e-5)

    def test_original_hard_edge_at_coincident_positions_stays_split(self) -> None:
        reference = self.load(self.split_position_root(smooth=False))
        current = self.load(self.split_position_root(smooth=False))
        changed = current.positions
        changed[2][2] = 1
        current.set_positions(changed)
        output = self.directory / "hard-split.dae"
        current.save(output)
        normals = list(map(float, ET.parse(output).find(f".//{q('source')}[@id='normals']/{q('float_array')}").text.split()))
        self.assertNotEqual(normals[:3], normals[3:])
        self.assertEqual(normals[3:], [0, 1, 0])
        self.assertEqual(validate_smooth_seams(reference, current)["source_smooth_seam_groups"], 0)

    def test_untouched_neighborhoods_retain_authored_normal_values(self) -> None:
        mesh = self.load()
        before = mesh.snapshot()
        report = mesh.set_positions(mesh.positions)
        self.assertEqual(report["normals_updated"], 0)
        self.assertEqual(report["normals_preserved"], 2)
        output = self.directory / "unchanged.dae"
        mesh.save(output)
        normals = list(map(float, ET.parse(output).find(f".//{q('source')}[@id='normals']/{q('float_array')}").text.split()))
        self.assertEqual(normals, [0, 0, 1, 0, 1, 0])
        self.assertEqual(before["topology_id"], mesh.topology_id)

    def test_seam_acceptance_rejects_new_split_but_accepts_source(self) -> None:
        root = self.split_position_root(smooth=True)
        reference = self.load(root)
        self.assertEqual(validate_smooth_seams(reference, reference)["status"], "passed")
        root.find(f".//{q('source')}[@id='normals']/{q('float_array')}").text = "0 0 1 0 1 0"
        changed = self.load(root)
        with self.assertRaisesRegex(ValueError, "New smooth-normal seam exceeds"):
            validate_smooth_seams(reference, changed)


if __name__ == "__main__":
    unittest.main()
