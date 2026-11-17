import copy
import math
import unittest
from nudegate.soften import soften_surface


class SurfaceSofteningTests(unittest.TestCase):
    def setUp(self):
        self.points = [[-1,0,0],[1,0,0],[0,1,0],[0,-1,0],[0,0,.3],[0,0,.3]]
        self.faces = [[0,1,4],[1,2,4],[2,0,4],[0,3,5],[3,1,5]]

    def test_protected_and_unmasked_vertices_are_exact_and_inputs_unchanged(self):
        source = copy.deepcopy(self.points)
        result, report = soften_surface(self.points,self.faces,[0,0,0,0,1,1],[],passes=3)
        self.assertEqual(result[:4], source[:4])
        self.assertEqual(self.points, source)
        self.assertNotEqual(result[4], source[4])
        self.assertTrue(report['protected_vertices_unchanged'])

    def test_uv_split_deltas_match_and_any_protected_member_locks_the_group(self):
        result, _ = soften_surface(self.points,self.faces,[1]*6,[],padding=.005)
        self.assertEqual(result[4], result[5])
        protected, _ = soften_surface(self.points,self.faces,[1]*6,[4])
        self.assertEqual(protected[4:], self.points[4:])

    def test_displacement_is_bounded_and_zero_mask_is_identity(self):
        result, report = soften_surface(self.points,self.faces,[1]*6,[],passes=16,padding=.02,max_displacement=.01)
        self.assertLessEqual(report['max_displacement_metres'], .01000000001)
        unchanged, _ = soften_surface(self.points,self.faces,[0]*6,[],padding=.02)
        self.assertEqual(unchanged, self.points)

    def test_invalid_mesh_masks_and_parameters_are_rejected(self):
        cases = [dict(weights=[1]),dict(weights=[1,1,1,1,1,.5]),dict(locked_vertices=[-1]),
                 dict(triangles=[[0,1,99]]),dict(passes=0),dict(padding=float('nan')),
                 dict(max_displacement=.1),dict(strength=True)]
        for overrides in cases:
            args = dict(positions=self.points,triangles=self.faces,weights=[1]*6,locked_vertices=[])
            args.update(overrides)
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                soften_surface(**args)
