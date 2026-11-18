"""Tests for geometry-preserving donor math and fail-closed skin mapping."""
import unittest
import numpy as np

from nudegate.donor_body import (rotation_between,quantize_weights,closest_triangles,
    plane_barycentric,normalized_deform_weights,map_native_weights,ordered_boundary,tangent_frames,
    repair_juno_stray_facial_weights,JUNO_STRAY_FACIAL_SOURCE_IDS)
from nudegate.donor_body import pose_donor
from nudegate.donor_body import validate_open_boundary_provenance
from nudegate.donor_body import fractional_rotation,transport_corresponding_surface


class DonorBodyMathTests(unittest.TestCase):
    def test_original_openings_require_exact_edge_ancestry_and_explicit_mode(self):
        collar=np.array([3,4,5]);ids=np.array([10,11,12,-2,-2,-2])
        source=np.array([[0,1,2]])
        final=np.array([[3,4],[4,5],[5,3],[0,1]])
        with self.assertRaisesRegex(ValueError,'Unexpected open boundary'):
            validate_open_boundary_provenance(final,ids,collar,source,[10,11,12])
        result=validate_open_boundary_provenance(final,ids,collar,source,[10,11,12],allow_inherited=True)
        self.assertEqual(result['inherited_source_edge_ids'],[[10,11]])
        self.assertEqual(result['introduced_noncollar_open_edges'],0)
        new=np.vstack([final,[0,3]])
        with self.assertRaisesRegex(ValueError,'new non-collar opening'):
            validate_open_boundary_provenance(new,ids,collar,source,[10,11,12],allow_inherited=True)
        with self.assertRaisesRegex(ValueError,'collar boundary is missing'):
            validate_open_boundary_provenance(final[1:],ids,collar,source,[10,11,12],allow_inherited=True)

    def test_fractional_segment_rotation_is_proper(self):
        full=rotation_between([1,0,0],[0,1,0]);half=fractional_rotation(full,.5)
        np.testing.assert_allclose(half@[1,0,0],[2**-.5,2**-.5,0],atol=1e-12)
        np.testing.assert_allclose(half.T@half,np.eye(3),atol=1e-12)
        self.assertAlmostEqual(np.linalg.det(half),1.)
        with self.assertRaises(ValueError):fractional_rotation(full,1.1)

    def test_correspondence_transport_has_exact_affine_chart_jacobian(self):
        p=np.array([[0,0,0],[2,0,0],[0,2,0]],float);faces=np.array([[0,1,2]])
        target=p*np.array([2,3,1])+[.1,.2,.3]
        query=np.array([[.2,.3,.4],[.5,.1,-.2]])
        result,jac,correspondence=transport_corresponding_surface(query,np.array([[0,0,1]]*2),p,target,faces)
        np.testing.assert_allclose(result,query*np.array([2,3,1])+[.1,.2,.3])
        np.testing.assert_allclose(jac,np.broadcast_to(np.diag([2,3,1]),(2,3,3)))
        np.testing.assert_array_equal(correspondence['source_face_ids'],[0,0])

    def test_native_hip_translation_is_source_weighted_and_keeps_torso_exact(self):
        bones=[{'name':'DEF-spine','parent':None,'deform':True}];native_world={}
        for side,sign in [('L',1),('R',-1)]:
            for source,target,x,z in [('upper_arm','Shoulder',.2,1.5),('forearm','Elbow',.4,1.4),
                    ('hand','Wrist',.6,1.3),('thigh','Hip',.1,1.),('shin','Knee',.1,.5),('foot','Ankle',.1,0.)]:
                bones.append({'name':'DEF-'+source+'.'+side,'parent':None,'deform':True,
                    'posed_head_world':[sign*x,0,z]})
                matrix=np.eye(4);matrix[:3,3]=[sign*(x+(.02 if source in ('thigh','shin','foot') else 0)),z,0]
                if side=='L' and source in ('upper_arm','forearm','hand'):matrix[:3,3]+=[.02,.03,-.01]
                native_world[target+'_'+side]=matrix
        metadata={'rigs':[{'name':'Rig','bones':bones}],
            'vertex_group_names':['DEF-thigh.L','DEF-thigh.R','DEF-spine','DEF-upper_arm.L'],
            'vertex_group_validation':{'active_vertex_group_rigs':['Rig']}}
        arrays={'positions':np.array([[.1,0,1.],[-.1,0,1.],[0,0,1.2],[.2,0,1.5]]),
            'triangles':np.array([[0,1,2],[0,2,3]]),'group_offsets':np.arange(5),
            'group_indices':np.arange(4),'group_weights':np.ones(4)}
        result,_,_,_,report=pose_donor(arrays,metadata,{'bone_world':native_world},1,align_hip_x=True)
        np.testing.assert_allclose(result['positions'],[[.12,1,0],[-.12,1,0],[0,1.2,0],[.2,1.5,0]])
        np.testing.assert_array_equal(result['positions'][2],result['scaled_source_positions'][2])
        self.assertEqual(report['torso_uninfluenced_max_error'],0)
        registered,_,_,_,report=pose_donor(arrays,metadata,{'bone_world':native_world},1,
            align_hip_x=True,align_arm_pivot=True)
        np.testing.assert_allclose(registered['positions'][3],[.22,1.53,-.01])
        np.testing.assert_array_equal(registered['positions'][2],result['positions'][2])
        left_arm=next(f for f in report['limb_fixtures'] if f['side']=='L' and f['source_chain'][0]=='upper_arm')
        np.testing.assert_allclose(left_arm['pivot_native_offset_m'],[0,0,0])

    def test_rotation_preserves_lengths_and_handles_opposite_directions(self):
        for target in ([0,1,0],[-1,0,0],[1,0,0]):
            rotation=rotation_between([1,0,0],target)
            np.testing.assert_allclose(rotation@[1,0,0],target,atol=1e-12)
            np.testing.assert_allclose(rotation.T@rotation,np.eye(3),atol=1e-12)
            self.assertAlmostEqual(np.linalg.det(rotation),1)

    def test_byte_weights_keep_strongest_four_and_sum_to_255(self):
        w=np.array([[.2,.2,.2,.2,.2],[.51,.49,0,0,0]])
        ids,byte,report=quantize_weights(w)
        self.assertEqual(ids[0].tolist(),[0,1,2,3])
        self.assertEqual(byte[0].tolist(),[64,64,64,63])
        self.assertEqual(byte.sum(1).tolist(),[255,255])
        self.assertAlmostEqual(report['maximum_dropped_weight'],.2)

    def test_nondeform_masks_do_not_affect_pose_weights(self):
        arrays={'positions':np.zeros((2,3)),'group_offsets':np.array([0,2,4]),
                'group_indices':np.array([0,1,0,1]),'group_weights':np.array([.5,1,.2,.8])}
        metadata={'vertex_group_names':['DEF-spine','MSK_Top'],
            'vertex_group_validation':{'active_vertex_group_rigs':['Rig']},
            'rigs':[{'name':'Rig','bones':[{'name':'DEF-spine','deform':True,'parent':None}]}]}
        weights,names,bones,report=normalized_deform_weights(arrays,metadata)
        np.testing.assert_array_equal(weights,[[1,0],[1,0]])
        self.assertEqual(report['nondeform_assignments_ignored'],2)

    def test_unknown_positive_bone_fails_instead_of_spine_fallback(self):
        with self.assertRaisesRegex(ValueError,'Unmapped positive'):
            map_native_weights(np.ones((1,1)),['unknown'],{'unknown':{'parent':None}},['Root_M'])
        mapped,report=map_native_weights(np.ones((1,1)),['l_breast'],
            {'l_breast':{'parent':'DEF-spine.003'}},['Chest_M'])
        np.testing.assert_array_equal(mapped,[[1]])

    def test_raw_out_of_range_deform_weights_require_explicit_repair(self):
        metadata={'vertex_group_names':['DEF-spine'],
            'vertex_group_validation':{'active_vertex_group_rigs':['Rig']},
            'rigs':[{'name':'Rig','bones':[{'name':'DEF-spine','deform':True}]}]}
        for value in (-2.5679188553340282e-08,1.0000001,float('nan')):
            arrays={'positions':np.zeros((1,3)),'group_offsets':np.array([0,1]),
                    'group_indices':np.array([0]),'group_weights':np.array([value])}
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'explicit repair'):
                normalized_deform_weights(arrays,metadata)

    def test_closest_triangle_uses_true_edge_projection(self):
        triangle=np.array([[[0,0,0],[2,0,0],[0,1,0]]],dtype=float)
        bary,distance=closest_triangles(np.array([[2,1,0]]),triangle)
        np.testing.assert_allclose(bary,[[0,.8,.2]])
        np.testing.assert_allclose(distance,[.8])
        uv=plane_barycentric(np.array([[2,1,0]]),triangle)
        np.testing.assert_allclose(uv,[[-1,1,1]])

    def test_boundary_rejects_multiple_disconnected_loops(self):
        with self.assertRaisesRegex(ValueError,'multiple'):
            ordered_boundary([[0,1],[1,2],[2,0],[3,4],[4,5],[5,3]])

    def test_tangent_frame_is_finite_orthonormal(self):
        p=np.array([[0,0,0],[1,0,0],[0,1,0]],float);t=np.array([[0,1,2]])
        n=np.array([[0,0,1]]*3,float);uv=p[:,:2]
        tangent,binormal,report=tangent_frames(p,t,n,uv)
        np.testing.assert_allclose(tangent,[[1,0,0]]*3)
        np.testing.assert_allclose(binormal,[[0,1,0]]*3)
        self.assertEqual(report['degenerate_uv_triangles'],0)

    def test_reviewed_facial_repair_changes_only_approved_skin_rows(self):
        count=len(JUNO_STRAY_FACIAL_SOURCE_IDS)
        payload={'schema_version':1,'meshes':[{'bone_palette':['Root_M','Head_M'],
            'bone_indices':[[0,1,0,0]]*count,'bone_weights':[[250,5,0,0]]*count,
            'positions':[[0,1,0]]*count,'triangles':[[0,1,2]]}]}
        prepared={'source_vertex_ids':np.array(JUNO_STRAY_FACIAL_SOURCE_IDS),
                  'bone_weights':np.tile([250/255,5/255],(count,1))}
        bone={'name':'DEF.Tongue.004','parent':'DEF.Tongue.003',
            'rest_head_world':[0,0,1.406],'posed_head_world':[0,0,1.406],
            'rest_tail_world':[0,0,1.405],'posed_tail_world':[0,0,1.405]}
        updated,full,report=repair_juno_stray_facial_weights(payload,prepared,{'DEF.Tongue.004':bone})
        self.assertEqual(updated['meshes'][0]['positions'],payload['meshes'][0]['positions'])
        self.assertEqual(updated['meshes'][0]['bone_weights'],[[255,0,0,0]]*count)
        self.assertEqual(payload['meshes'][0]['bone_weights'],[[250,5,0,0]]*count)
        np.testing.assert_allclose(full,np.tile([1,0],(count,1)))
        self.assertEqual(report['changed_export_vertices'],17)
        bad=dict(prepared);bad['source_vertex_ids']=np.arange(count)
        with self.assertRaisesRegex(ValueError,'explicit 17-vertex'):
            repair_juno_stray_facial_weights(payload,bad,{'DEF.Tongue.004':bone})


if __name__=='__main__':unittest.main()
