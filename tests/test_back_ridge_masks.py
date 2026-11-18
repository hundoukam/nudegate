"""Reviewed racial ridge preservation is opt-in, smooth, and UV-welded."""
import copy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from nudegate.expansion import author_expansion_masks


def source(points):
    return SimpleNamespace(positions=points,triangles=[(0,1,2)],topology_id='mask-fixture')


def authored(points):
    count=len(points)
    return {'positions':copy.deepcopy(points),'soft_weights':[.6]*count,
            'attachment_weights':[1]*count,
            'regions':{name:{'weights':[0]*count}
                       for name in ('chest_left','chest_right','waist','hips','thighs')}}, {'source':'fixture'}


def masks(points,*,frame=None,preserve=False):
    with patch('nudegate.expansion.author_masks',return_value=authored(points)):
        return author_expansion_masks(source(points),frame,preserve_back_ridges=preserve)


class BackRidgeMaskTests(unittest.TestCase):
    def test_default_preserves_existing_masks_and_protection_only_changes_soft_weights(self):
        points=[[.05,1.35,.10],[.05,1.35,-.10],[.05,1.10,.10],
                [.25,1.35,.10],[.12,1.35,.10]]
        before=copy.deepcopy(points)
        normal,default_report=masks(points)
        protected,report=masks(points,preserve=True)
        self.assertEqual(normal['soft_weights'],[.6]*5)
        self.assertNotIn('back_ridge_protection',default_report)
        self.assertEqual(protected['soft_weights'][:4],[0,.6,.6,.6])
        self.assertGreater(protected['soft_weights'][4],0)
        self.assertLess(protected['soft_weights'][4],.6)
        self.assertEqual({k:v for k,v in protected.items() if k!='soft_weights'},
                         {k:v for k,v in normal.items() if k!='soft_weights'})
        self.assertEqual(points,before)
        self.assertEqual(report['back_ridge_protection']['fully_protected_vertices'],1)

    def test_normal_and_strong_frames_select_the_same_canonical_feature(self):
        points=[[.05,1.35,.10],[.12,1.35,.10],[.05,1.29,.10],[.05,1.35,-.10]]
        frame=[1.226154,1.12049,1.15]
        strong=[[p[k]*frame[k] for k in range(3)] for p in points]
        normal,_=masks(points,preserve=True)
        larger,_=masks(strong,frame=frame,preserve=True)
        for a,b in zip(normal['soft_weights'],larger['soft_weights']):
            self.assertAlmostEqual(a,b,places=12)

    def test_feathers_are_continuous_and_source_uv_splits_get_equal_protection(self):
        points=[[.05,1.28,.10],[.05,1.280001,.10],[.05,1.45,.10],
                [.1200001,1.35,.10],[.1200002,1.35,.10]]
        result,_=masks(points,preserve=True)
        weights=result['soft_weights']
        self.assertEqual(weights[0],.6)
        self.assertLess(weights[1],weights[0])
        self.assertLess(weights[0]-weights[1],1e-7)
        self.assertEqual(weights[2],.6)
        self.assertEqual(weights[3],weights[4])

    def test_opt_in_requires_a_boolean(self):
        points=[[.05,1.35,.1],[.1,1.35,.1],[.05,1.4,.1]]
        for invalid in (1,0,None,'yes'):
            with self.subTest(invalid=invalid),self.assertRaisesRegex(ValueError,'boolean'):
                author_expansion_masks(source(points),preserve_back_ridges=invalid)


if __name__=='__main__':
    unittest.main()
