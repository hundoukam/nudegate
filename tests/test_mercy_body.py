import unittest
import numpy as np
from nudegate.mercy_body import map_weights,semantic_anchors,validate_rig,protect_pelvic_source_pose


class MercyProfileTests(unittest.TestCase):
    def test_anatomical_pose_mask_restores_midline_and_preserves_skin_and_outer_body(self):
        bones={
            'Genitals':{'parent':'pelvis','deform':True,'posed_head_world':[0,-.02,1.],
                        'posed_tail_world':[0,-.02,1.04]},
            'Anus':{'parent':'pelvis','deform':True,'posed_head_world':[0,.04,1.01],
                    'posed_tail_world':[0,.04,1.05]},
            'pelvis':{'parent':'hip','deform':True,'posed_head_world':[0,0,1.2],
                      'posed_tail_world':[0,0,1.15]}}
        source=np.array([[0,1.02,.1],[.08,1.02,.1],[-.012,1.01,.04],
                         [.012,1.01,.04],[0,1.4,-.15],[.01,1.02,.1]])
        delta=np.array([[.003,0,0],[.006,0,0],[0,0,0],[0,0,0],[.001,0,.003],[.003,0,0]])
        posed=source+delta
        result={'positions':posed.copy(),'scaled_source_positions':source.copy(),'pose_displacement':delta.copy(),
            'source_breast_influence_left':np.array([0,0,0,0,1,0]),'source_breast_influence_right':np.zeros(6),
            'triangles':np.array([[0,1,5]])}
        weights=np.array([[0,.8,.2],[0,0,1],[.2,.8,0],[.2,.8,0],[0,1,0],[0,.8,.2]])
        before=weights.copy();faces=result['triangles'].copy()
        report=protect_pelvic_source_pose(result,weights,['Anus','pelvis','l.ThighBend'],bones,
            {'uniform_scale':1.,'translation_bg3':[0,0,0]})
        np.testing.assert_array_equal(result['positions'][0],source[0])
        np.testing.assert_array_equal(result['positions'][[1,4]],posed[[1,4]])
        self.assertGreater(result['positions'][5,0],source[5,0])
        self.assertLess(result['positions'][5,0],posed[5,0])
        np.testing.assert_array_equal(weights,before)
        np.testing.assert_array_equal(result['triangles'],faces)
        self.assertFalse(report['collision_pair_ids_used_to_define_field'])
        self.assertEqual(report['breast_vertices_changed'],0)

    def test_anatomical_pose_mask_rejects_unreviewed_hierarchy(self):
        with self.assertRaisesRegex(ValueError,'Genitals/Anus to pelvis'):
            protect_pelvic_source_pose({},np.zeros((0,0)),[],
                {'Genitals':{'parent':'head','deform':True}}, {'uniform_scale':1.,'translation_bg3':[0,0,0]})

    def test_weighted_hybrid_neck_and_duplicate_pelvis_columns_keep_mass(self):
        names=['pelvis','pelvis','neckLower','head neck upper','l_Pectoral']
        native=['Root_M','Neck_M','Head_M','Chest_M']
        weights=np.array([[.2,.3,.1,.15,.25]])
        result,report=map_weights(weights,names,{},native)
        np.testing.assert_allclose(result,[[.5,.1,.15,.25]])
        self.assertEqual(report['resolved_positive_groups']['neckLower']['target'],'Neck_M')
        self.assertEqual(semantic_anchors()['DEF-spine.004'],'Neck_M')

    def test_unknown_weighted_group_never_becomes_root_implicitly(self):
        with self.assertRaisesRegex(ValueError,'Unmapped positive Mercy'):
            map_weights(np.ones((1,1)),['unknown'],{},['Root_M'])

    def test_other_rig_cannot_use_mercy_landmark_profile(self):
        with self.assertRaisesRegex(ValueError,'exact reviewed active hybrid rig'):
            validate_rig({'id':'juno_b','vertex_group_validation':{'active_vertex_group_rigs':['G9_Rig']}})


if __name__=='__main__':unittest.main()
