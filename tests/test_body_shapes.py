import unittest
from nudegate.body_shapes import seam_locks, surface_quality, attachment_falloff


class GeometryAcceptanceTests(unittest.TestCase):
    def test_attachment_blend_is_continuous_and_uv_split_invariant(self):
        points = [[x,y,0] for x in (0,.01,.02,.04) for y in (0,.005)]
        faces = [[i,i+2,i+1] for i in (0,2,4)] + [[i+1,i+2,i+3] for i in (0,2,4)]
        points.append(points[2][:])
        faces.append([0,8,1])
        weights = attachment_falloff(points, faces, {0,1})
        self.assertEqual(weights[:2], [0,0])
        self.assertTrue(0 < weights[2] < weights[4] < weights[6])
        self.assertEqual(weights[6], 1)
        self.assertEqual(weights[2], weights[8])

    def test_boundary_protection_welds_duplicate_positions(self):
        tetra = [[0,0,0],[1,0,0],[0,1,0],[0,0,1]]
        faces = [[0,2,1],[0,1,3],[1,2,3],[2,0,3]]
        points = [tetra[i] for face in faces for i in face]
        # A closed surface whose every face has separate UV-split indices
        # still has no open geometric boundary to lock.
        triangles = [[i,i+1,i+2] for i in range(0,12,3)]
        self.assertEqual(seam_locks(points, triangles, rings=0), set())

    def test_rigid_and_positive_scale_keep_surface_orientation(self):
        source = [[0,0,0],[1,0,0],[0,1,0]]
        result = surface_quality(source, [[3,1,1],[5,1,1],[3,3,1]], [[0,1,2]])
        self.assertEqual(result, {'reversed_faces':0,'new_collapsed_faces':0})

    def test_reversed_or_collapsed_faces_stop_acceptance(self):
        source = [[0,0,0],[1,0,0],[0,1,0]]
        for changed in ([[0,0,0],[0,1,0],[1,0,0]], [[0,0,0],[1,0,0],[2,0,0]]):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                surface_quality(source, changed, [[0,1,2]])

    def test_position_count_changes_are_rejected(self):
        with self.assertRaises(ValueError):
            surface_quality([[0,0,0]], [], [])
