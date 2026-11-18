import copy
import math
import hashlib
import json
from types import SimpleNamespace
import unittest

from nudegate.geometry_proofs import validate_geometry_proof, validate_wall_calibration
from nudegate.surface_intersections import SurfaceIntersectionChecker, geometry_fingerprint


class GeometryProofTests(unittest.TestCase):
    def setUp(self):
        self.source = SimpleNamespace(positions=[[0.,0.,0.],[1.,0.,0.],[0.,1.,0.]],
                                      triangles=[[0,1,2]],topology_id='fixture')
        angle = math.radians(120)
        self.authored = SimpleNamespace(positions=[[0.,0.,0.],[math.cos(angle),0.,math.sin(angle)],[0.,1.,0.]],
                                        triangles=[[0,1,2]],topology_id='fixture')
        self.proof = SurfaceIntersectionChecker(self.source.positions,self.source.triangles,
                                                topology_id='fixture').validate(self.authored.positions)

    def test_legitimate_surface_turn_passes_without_claiming_zero_normal_turns(self):
        self.assertEqual(self.proof['reference_normal_turns'],1)
        self.assertTrue(validate_geometry_proof(self.source,self.authored,self.proof))

    def test_different_authored_or_source_geometry_cannot_reuse_a_passed_proof(self):
        for name in ('source','authored'):
            source,authored = copy.deepcopy(self.source),copy.deepcopy(self.authored)
            (source if name=='source' else authored).positions[1][0] += .01
            with self.subTest(name=name),self.assertRaises(ValueError):
                validate_geometry_proof(source,authored,self.proof)

    def test_changed_topology_and_unreviewed_tolerance_are_rejected(self):
        changed = copy.deepcopy(self.authored)
        changed.triangles = [[0,2,1]]
        with self.assertRaises(ValueError):
            validate_geometry_proof(self.source,changed,self.proof)
        proof = copy.deepcopy(self.proof)
        proof['tolerances']['linear'] = .1
        with self.assertRaises(ValueError):
            validate_geometry_proof(self.source,self.authored,proof)

    def test_failed_or_inconsistent_pair_records_cannot_be_packaged(self):
        for update in ({'safe':False},{'new_collapsed_faces':1},{'introduced_intersection_count':1},
                       {'source_intersection_pair_sha256':'0'*64},{'candidate_intersection_count':3}):
            with self.subTest(update=update),self.assertRaises(ValueError):
                validate_geometry_proof(self.source,self.authored,{**self.proof,**update})

    def test_wall_record_is_bound_to_the_authored_zero_size_base(self):
        record = {'schema_version':1,'source_lod':0,'family_id':'fixture','profile_sha256':'a'*64,
                  'source_topology_id':self.source.topology_id,
                  'source_geometry_sha256':geometry_fingerprint(self.source.positions,self.source.triangles),
                  'baked_geometry_sha256':geometry_fingerprint(self.authored.positions,self.authored.triangles),
                  'source_vertex_count':3,'source_triangle_count':1,'frame':[1,1,1],
                  'wall_landmark_vertices':[0],'wall_z':0.0}
        record['calibration_sha256'] = hashlib.sha256(json.dumps(record,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        options = dict(family_id='fixture',profile_sha256='a'*64,frame=[1,1,1])
        self.assertTrue(validate_wall_calibration(record,self.source,self.authored,**options))
        with self.assertRaises(ValueError):
            validate_wall_calibration(record,self.source,self.source,**options)
        with self.assertRaises(ValueError):
            validate_wall_calibration({**record,'wall_z':.1},self.source,self.authored,**options)

    def test_pair_validation_does_not_clone_the_mesh_for_each_pair(self):
        points = self.source.positions*9
        triangles = [[3*i,3*i+1,3*i+2] for i in range(9)]
        proof = SurfaceIntersectionChecker(points,triangles,topology_id='overlap-fixture').check(points)
        self.assertGreater(proof['source_intersection_count'],20)

        class DefensiveMesh:
            topology_id = 'overlap-fixture'
            def __init__(self):
                self.position_reads = self.triangle_reads = 0
            @property
            def positions(self):
                self.position_reads += 1
                return copy.deepcopy(points)
            @property
            def triangles(self):
                self.triangle_reads += 1
                return copy.deepcopy(triangles)

        source,authored = DefensiveMesh(),DefensiveMesh()
        self.assertTrue(validate_geometry_proof(source,authored,proof))
        for mesh in (source,authored):
            self.assertLessEqual(mesh.position_reads,3)
            self.assertLessEqual(mesh.triangle_reads,3)
