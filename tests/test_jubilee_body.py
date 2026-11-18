import unittest
import numpy as np
from nudegate.jubilee_body import semantic_anchors,map_weights,validate_rig


class JubileeProfileTests(unittest.TestCase):
    def test_own_eight_spine_chest_neck_and_head_are_distinct(self):
        anchors=semantic_anchors()
        self.assertEqual([anchors['DEF-spine.%03d'%i] for i in range(4,8)],
                         ['Chest_M','Neck_M','Neck_M','Head_M'])
        result,_=map_weights(np.array([[.1,.2,.3,.4]]),
            ['DEF-spine.004','DEF-spine.005','DEF-spine.006','DEF-spine.007'],{},
            ['Chest_M','Neck_M','Head_M'])
        np.testing.assert_allclose(result,[[.1,.5,.4]])

    def test_butt_parent_is_reviewed_root_but_unknown_group_is_rejected(self):
        result,_=map_weights(np.ones((1,1)),['Butt.L'],{},['Root_M'])
        np.testing.assert_array_equal(result,[[1.]])
        with self.assertRaisesRegex(ValueError,'Unmapped positive Jubilee'):
            map_weights(np.ones((1,1)),['unknown'],{},['Root_M'])

    def test_other_source_cannot_use_jubilee_profile(self):
        with self.assertRaisesRegex(ValueError,'exact selected Marvel Rivals'):
            validate_rig({'id':'mercy_c','vertex_group_validation':{'active_vertex_group_rigs':['Mercy_rig']}})


if __name__=='__main__':unittest.main()
