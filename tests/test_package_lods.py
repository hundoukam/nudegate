"""Packaging cannot relabel one passed mesh as all native LODs."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from nudegate.collada import ColladaMesh
from nudegate.lod_authoring import enumerate_lods
from nudegate.surface_intersections import SurfaceIntersectionChecker, geometry_fingerprint
from test_lod_authoring import fixture


SPEC = importlib.util.spec_from_file_location('package_lod_build',Path(__file__).resolve().parents[1]/'tools/build.py')
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)


class PackageLodTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        folder = Path(self.temp.name)
        source,authored = folder/'source.dae',folder/'authored.dae'
        tree = ET.ElementTree(fixture(5))
        tree.write(source,encoding='utf-8',xml_declaration=True)
        tree.write(authored,encoding='utf-8',xml_declaration=True)
        rows = enumerate_lods(source,expected_lods=5)
        anchor = ColladaMesh.load(source,geometry_id=rows[0]['geometry_id'])
        calibration = {'schema_version':1,'source_lod':0,'family_id':'fixture','profile_sha256':'a'*64,
            'source_topology_id':anchor.topology_id,
            'source_geometry_sha256':geometry_fingerprint(anchor.positions,anchor.triangles),
            'baked_geometry_sha256':geometry_fingerprint(anchor.positions,anchor.triangles),
            'source_vertex_count':3,'source_triangle_count':1,'frame':[1,1,1],
            'wall_landmark_vertices':[0],'wall_z':0.0}
        calibration['calibration_sha256'] = hashlib.sha256(json.dumps(calibration,sort_keys=True,
            separators=(',',':'),allow_nan=False).encode()).hexdigest()
        stats = {}
        for row in rows:
            mesh = ColladaMesh.load(source,geometry_id=row['geometry_id'])
            proof = SurfaceIntersectionChecker(mesh.positions,mesh.triangles,topology_id=mesh.topology_id).validate(mesh.positions)
            stats[str(row['lod'])] = {'surface_intersections':proof,'breast_size':{'wall_calibration':calibration}}
        self.variant = {'id':'exp_curvy_b000','base_body_id':'curvy','breast_percent':0,
            'base_profile_sha256':'a'*64,'dae':str(authored),'geometry_id':rows[0]['geometry_id'],
            'lods':[{key:row[key] for key in ('lod','geometry_id')} for row in rows],
            'sculpt':{**copy.deepcopy(stats['0']),'lods':stats}}
        self.family = {'id':'fixture','source':str(source),'lod_count':5,'variants':[self.variant]}

    def test_each_actual_native_geometry_is_accepted_and_source_mapping_is_cached(self):
        cache = {}
        BUILD.validate_expansion_surfaces(self.family,self.variant,cache)
        native = cache[('native_lod_identities',self.family['source'],5)]
        self.assertEqual(native,[(row['lod'],row['geometry_id']) for row in self.variant['lods']])
        BUILD.validate_expansion_surfaces(self.family,self.variant,cache)

    def test_repeated_lod_zero_geometry_cannot_reuse_its_proof_for_other_native_lods(self):
        forged = copy.deepcopy(self.variant)
        for row in forged['lods'][1:]:
            row['geometry_id'] = forged['geometry_id']
            forged['sculpt']['lods'][str(row['lod'])] = copy.deepcopy(forged['sculpt']['lods']['0'])
        with self.assertRaisesRegex(ValueError,'actual native LOD geometry'):
            BUILD.validate_expansion_surfaces(self.family,forged,{})

    def test_duplicate_rows_and_swapped_lod_geometry_bindings_are_rejected(self):
        duplicate = copy.deepcopy(self.variant)
        duplicate['lods'].append(copy.deepcopy(duplicate['lods'][0]))
        swapped = copy.deepcopy(self.variant)
        swapped['lods'][1]['geometry_id'],swapped['lods'][2]['geometry_id'] = (
            swapped['lods'][2]['geometry_id'],swapped['lods'][1]['geometry_id'])
        swapped['sculpt']['lods']['1'],swapped['sculpt']['lods']['2'] = (
            swapped['sculpt']['lods']['2'],swapped['sculpt']['lods']['1'])
        for invalid in (duplicate,swapped):
            with self.assertRaisesRegex(ValueError,'actual native LOD geometry'):
                BUILD.validate_expansion_surfaces(self.family,invalid,{})


if __name__ == '__main__':
    unittest.main()
