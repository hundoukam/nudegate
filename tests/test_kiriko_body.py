"""Independent Kiriko profile and source-anatomy preservation contracts."""
import unittest
import numpy as np
from nudegate.kiriko_body import (source_limb,map_weights,semantic_anchors,validate_rig,
    protect_anatomical_source_pose,protect_author_breast_support)


class KirikoProfileTests(unittest.TestCase):
    def test_breast_support_is_exact_source_with_local_fade_and_distal_guard(self):
        groups=['breast.L','breast.R','DEF-breast.L','DEF-breast.R','DEF-spine','DEF-hand.L']
        bones={name:{'parent':None,'posed_head_world':[0,0,1.3],
            'posed_tail_world':[0,-.1,1.3]}for name in groups}
        source=np.array([[-.04,1.4,-.1],[.04,1.4,-.1],[.052,1.4,-.1],[.1,1.4,-.1],[.5,1.2,0.],[.041,1.4,-.1]])
        displacement=np.tile([.002,.001,0.],(6,1));previous=source+displacement
        data={'positions':previous.copy(),'scaled_source_positions':source.copy(),'pose_displacement':displacement.copy()}
        weights=np.zeros((6,6));weights[:2,0]=1;weights[2:4,4]=1;weights[4,5]=1;weights[5,[0,5]]=[.25,.75]
        saved=weights.copy()
        report=protect_author_breast_support(data,weights,groups,bones,{'uniform_scale':1.})
        np.testing.assert_array_equal(data['positions'][:2],source[:2])
        np.testing.assert_array_equal(data['positions'][3:],previous[3:])
        self.assertGreater(data['positions'][2,0],source[2,0]);self.assertLess(data['positions'][2,0],previous[2,0])
        np.testing.assert_array_equal(weights,saved)
        self.assertEqual(report['hands_and_feet_changed'],0)
        self.assertTrue(report['full_dominant_thoracic_support_bit_equal_to_scaled_source'])
        self.assertFalse(report['collision_pair_ids_used_to_define_field'])
        invalid={'positions':previous.copy(),'scaled_source_positions':source.copy(),'pose_displacement':displacement.copy()}
        weights[0]=[.75,0,0,0,0,.25]
        with self.assertRaisesRegex(ValueError,'reached hand/foot skin support'):
            protect_author_breast_support(invalid,weights,groups,bones,{'uniform_scale':1.})

    def test_independently_parented_toes_receive_foot_pose(self):
        bones={'DEF-toes.L.003':{'parent':'ORG-toe.L'},'ORG-toe.L':{'parent':'ORG-foot.L'},
               'ORG-foot.L':{'parent':None},'nail':{'parent':'DEF-toes.R.013'},
               'DEF-toes.R.013':{'parent':'DEF-toes.R.012'}}
        self.assertEqual(source_limb('DEF-toes.L.003',bones),('toe','L'))
        self.assertEqual(source_limb('nail',bones),('toe','R'))
        self.assertIsNone(source_limb('unknown',bones))

    def test_extra_toes_anatomy_and_both_active_breast_families_keep_mass(self):
        names=['DEF-toes.L.013','DEF-toe.L','Vagina_bone_1','Anus_control','DEF-breast.L','breast.L']
        bones={'Vagina_bone_1':{'parent':'Vagina_Overall'},'Vagina_Overall':{'parent':'tweak_spine'},
               'Anus_control':{'parent':'tweak_spine'}}
        weights=np.array([[.1,.1,.15,.15,.2,.3]])
        mapped,report=map_weights(weights,names,bones,['Toes_L','Root_M','Chest_M'])
        np.testing.assert_allclose(mapped,[[.2,.3,.5]])
        self.assertEqual(report['resolved_positive_groups']['Vagina_bone_1']['anchor'],'tweak_spine')

    def test_unknown_positive_group_fails_closed(self):
        with self.assertRaisesRegex(ValueError,'Unmapped positive Kiriko'):
            map_weights(np.ones((1,1)),['unknown'],{},['Root_M'])

    def test_own_neck_chain_and_other_rig_rejection(self):
        anchors=semantic_anchors()
        self.assertEqual(anchors['DEF-spine.004'],'Neck_M')
        self.assertEqual(anchors['DEF-spine.005'],'Neck_M')
        self.assertEqual(anchors['DEF-spine.006'],'Head_M')
        with self.assertRaisesRegex(ValueError,'exact reviewed active source rig'):
            validate_rig({'id':'juno_b','vertex_group_validation':{'active_vertex_group_rigs':['G9_Rig']}})

    def test_source_anatomy_mask_keeps_source_midline_outer_body_and_skin(self):
        bones={'Vagina_Overall':{'parent':'tweak_spine','deform':True,
                'posed_head_world':[0,-.02,1.0],'posed_tail_world':[0,-.02,1.016]},
            'Anus_control':{'parent':'tweak_spine','deform':True,
                'posed_head_world':[0,.02,.995],'posed_tail_world':[0,.02,1.011]},
            'tweak_spine':{'parent':'spine_fk','posed_head_world':[0,.03,1.0],
                'posed_tail_world':[0,.03,1.08]}}
        source=np.array([[0,1.01,.02],[.08,1.01,.02],[-.02,1.01,.01],[.02,1.01,.01],
                         [0,1.4,-.15],[.015,1.01,.02]])
        delta=np.array([[.000068,0,0],[.005,0,0],[0,0,0],[0,0,0],[.001,0,.003],[.0005,0,0]])
        posed=source+delta
        result={'positions':posed.copy(),'scaled_source_positions':source.copy(),'pose_displacement':delta.copy(),
            'source_breast_influence_left':np.array([0,0,0,0,1,0]),'source_breast_influence_right':np.zeros(6)}
        weights=np.array([[0,1],[0,1],[.5,.5],[.5,.5],[0,1],[0,1.]])
        before=weights.copy()
        report=protect_anatomical_source_pose(result,weights,['Anus_control','DEF-spine'],bones,
            {'uniform_scale':1.,'translation_bg3':[0,0,0]})
        np.testing.assert_array_equal(result['positions'][0],source[0])
        np.testing.assert_array_equal(result['positions'][[1,4]],posed[[1,4]])
        np.testing.assert_array_equal(weights,before)
        self.assertGreater(result['positions'][5,0],source[5,0])
        self.assertLess(result['positions'][5,0],posed[5,0])
        self.assertFalse(report['collision_pair_ids_used_to_define_field'])
        self.assertEqual(report['breast_vertices_changed'],0)

    def test_wrong_anatomy_parent_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'anatomy hierarchy changed'):
            protect_anatomical_source_pose({},np.zeros((0,0)),[],
                {'Vagina_Overall':{'parent':'pelvis','deform':True}}, {'uniform_scale':1.,'translation_bg3':[0,0,0]})

    def test_complete_author_support_is_coherent_before_distance_fade(self):
        bones={'Vagina_Overall':{'parent':'tweak_spine','deform':True,
                'posed_head_world':[0,-.02,1.0],'posed_tail_world':[0,-.02,1.016]},
            'Anus_control':{'parent':'tweak_spine','deform':True,
                'posed_head_world':[0,.02,.995],'posed_tail_world':[0,.02,1.011]},
            'tweak_spine':{'parent':'spine_fk','posed_head_world':[0,.03,1.0],
                'posed_tail_world':[0,.03,1.08]}}
        source=np.array([[0,1.01,.02],[.08,1.01,.01],[-.02,1.01,.01],[.02,1.01,.01],
                         [0,1.4,-.15],[.028,1.01,.01]])
        delta=np.array([[.000068,0,0],[.005,0,0],[0,0,0],[0,0,0],[.001,0,.003],[.0005,0,0]])
        original=source+delta
        data={'positions':original.copy(),'scaled_source_positions':source.copy(),'pose_displacement':delta.copy(),
            'source_breast_influence_left':np.array([0,0,0,0,1,0]),'source_breast_influence_right':np.zeros(6)}
        weights=np.array([[0,.1,.9],[0,0,1],[.5,0,.5],[.5,0,.5],[0,0,1],[0,0,1.]])
        saved=weights.copy()
        report=protect_anatomical_source_pose(data,weights,['Anus_control','Vagina_Overall','DEF-spine'],
            bones,{'uniform_scale':1.,'translation_bg3':[0,0,0]},mode='source-support')
        np.testing.assert_array_equal(data['positions'][0],source[0])
        np.testing.assert_array_equal(data['positions'][[1,4]],original[[1,4]])
        self.assertGreater(data['positions'][5,0],source[5,0])
        self.assertLess(data['positions'][5,0],original[5,0])
        np.testing.assert_array_equal(weights,saved)
        self.assertEqual(report['mask_mode'],'source-support')
        self.assertEqual(report['full_anatomical_support_vertices'],3)
        self.assertEqual(report['breast_vertices_changed'],0)


if __name__=='__main__':unittest.main()
