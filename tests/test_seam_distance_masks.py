"""Physical seam protection must not grow with coarse triangle edge lengths."""
import math
import unittest

from nudegate.body_shapes import author_masks,seam_locks,seam_distance_locks


def grid(spacing):
    points=[[col*spacing,row*spacing,0] for row in range(5) for col in range(5)]
    faces=[]
    for row in range(4):
        for col in range(4):
            a=row*5+col
            faces.extend([[a,a+1,a+6],[a,a+6,a+5]])
    return points,faces


def coarse_torso():
    points=[]
    for y in (.1,.4,.8,1.1,1.35,1.48,1.57):
        for i in range(16):
            angle=2*math.pi*i/16
            points.append([.16*math.cos(angle),y,.13*math.sin(angle)])
    faces=[]
    for row in range(6):
        for i in range(16):
            a,b=row*16+i,row*16+(i+1)%16
            faces.extend([[a,b,b+16],[a,b+16,a+16]])
    return points,faces


class SeamDistanceTests(unittest.TestCase):
    def test_distance_is_physical_and_true_boundaries_always_stay_locked(self):
        fine,faces=grid(.01)
        coarse,_=grid(.10)
        boundary=seam_locks(fine,faces,rings=0)
        fine_locks=seam_distance_locks(fine,faces,.012)
        coarse_locks=seam_distance_locks(coarse,faces,.012)
        self.assertTrue(boundary<=fine_locks)
        self.assertEqual(coarse_locks,boundary)
        self.assertIn(6,fine_locks)     # 10 mm from boundary
        self.assertNotIn(12,fine_locks) # 20 mm from boundary
        self.assertIn(12,seam_locks(coarse,faces,rings=2))
        self.assertEqual(seam_distance_locks(fine,faces,0),boundary)

    def test_geodesic_does_not_jump_to_spatially_near_disconnected_component(self):
        # An open triangle sits near a closed tetrahedron; only the open
        # component has a true boundary even though everything is close.
        points=[[0,0,0],[.001,0,0],[0,.001,0],
                [.002,0,0],[.003,0,0],[.002,.001,0],[.002,0,.001]]
        faces=[[0,1,2],[3,5,4],[3,4,6],[4,5,6],[5,3,6]]
        self.assertEqual(seam_distance_locks(points,faces,.012),{0,1,2})

    def test_uv_split_faces_share_the_same_distance_protection(self):
        positions,faces=grid(.01)
        split=[positions[i][:] for face in faces for i in face]
        split_faces=[[i,i+1,i+2] for i in range(0,len(split),3)]
        expected={tuple(positions[i]) for i in seam_distance_locks(positions,faces,.012)}
        actual={tuple(split[i]) for i in seam_distance_locks(split,split_faces,.012)}
        self.assertEqual(actual,expected)

    def test_default_retains_exact_two_ring_and_spatial_locks(self):
        positions,faces=coarse_torso()
        default,report=author_masks(positions,faces,'torso')
        explicit,explicit_report=author_masks(positions,faces,'torso',seam_distance=None)
        self.assertEqual((default,report),(explicit,explicit_report))
        expected=seam_locks(positions,faces,rings=2)
        expected.update(i for i,(x,y,z) in enumerate(positions)
                        if y>1.48 or y<.20 or abs(x)>.55
                        or (.79<y<1.12 and abs(x)<.045))
        self.assertEqual(set(default['locked_vertices']),expected)
        self.assertNotIn('seam_protection',report)
        physical,physical_report=author_masks(positions,faces,'torso',seam_distance=.012)
        apex=4*16+14
        self.assertIn(apex,default['locked_vertices'])
        self.assertNotIn(apex,physical['locked_vertices'])
        self.assertTrue(seam_locks(positions,faces,rings=0)<=set(physical['locked_vertices']))
        self.assertEqual(physical_report['seam_protection']['distance_canonical_metres'],.012)

    def test_strong_frame_uses_canonical_distance(self):
        positions,faces=coarse_torso()
        normal,_=author_masks(positions,faces,'torso',seam_distance=.012)
        frame=[1.226154,1.12049,1.15]
        larger=[[p[k]*frame[k] for k in range(3)] for p in positions]
        strong,_=author_masks(larger,faces,'torso',frame,seam_distance=.012)
        self.assertEqual(normal['locked_vertices'],strong['locked_vertices'])
        for a,b in zip(normal['attachment_weights'],strong['attachment_weights']):
            self.assertAlmostEqual(a,b,places=12)

    def test_invalid_distance_rejected(self):
        positions,faces=coarse_torso()
        for value in (True,'0.012',math.nan,math.inf,-.001,.051):
            with self.subTest(value=value),self.assertRaises(ValueError):
                author_masks(positions,faces,'torso',seam_distance=value)


if __name__=='__main__':
    unittest.main()
