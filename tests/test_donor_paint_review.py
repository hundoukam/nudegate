"""Read-only paint QA must not call cross-side weight noise a breast tip."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

import numpy as np


_spec=importlib.util.spec_from_file_location('review_donor_paint',
    Path(__file__).resolve().parents[1]/'tools/review_donor_paint.py')
_module=importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)


class DonorPaintReviewTests(unittest.TestCase):
    def test_true_tips_use_authored_side_despite_positive_cross_side_tails(self):
        with tempfile.TemporaryDirectory() as temp:
            stage=Path(temp)
            np.savez(stage/'posed_dense.npz',positions=np.array([[.08,1.4,-.2],[-.08,1.4,-.19]]),
                source_breast_influence_left=np.array([.99,1e-9]),
                source_breast_influence_right=np.array([1e-9,.99]))
            np.savez(stage/'body_prepared.npz',source_vertex_ids=np.arange(2),
                colors_rgba8=np.array([[127,0,0,255],[126,0,0,255]],dtype=np.uint8))
            report=_module.review(stage)
            self.assertEqual(report['sides']['left']['tip_source_id'],0)
            self.assertEqual(report['sides']['right']['tip_source_id'],1)
            self.assertEqual(report['sides']['right']['tip_RGBA8'],[[126,0,0,255]])
            # Tiny tails remain present in influence accounting; QA alone
            # restricts the physical pole selection, and rewrites no source.
            self.assertEqual(report['sides']['right']['author_positive_vertices'],2)


if __name__=='__main__':unittest.main()
