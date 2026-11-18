"""Donor extraction must retain authored defaults and the exact reviewed state."""
import copy
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

import numpy as np


SPEC=importlib.util.spec_from_file_location('blender_donor_export',Path(__file__).resolve().parents[1]/'tools/export_blender_donors.py')
EXPORT=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXPORT)


class DonorSelectionTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.source=str(Path(self.folder.name)/'original.blend')
        self.plans=[{'id':'Example','source':self.source,'body_mesh':'Body','adult_model':True,
                     'presets':[{'id':'A','keys':{}},{'id':'C','keys':{'Size':-1}}]}]
        self.pins=[{'id':'Example','source':self.source,'source_sha256':'a'*64}]

    def test_exact_preset_is_copied_and_bound_to_original_file(self):
        plan,preset,pin,name=EXPORT.selected_presets(self.plans,['Example:C'],self.pins)[0]
        self.assertEqual(preset['keys'],{'Size':-1})
        self.assertEqual(name,'example_c')
        preset['keys']['Size']=0
        plan['body_mesh']='changed'
        self.assertEqual(self.plans[0]['presets'][1]['keys']['Size'],-1)
        self.assertEqual(self.plans[0]['body_mesh'],'Body')

    def test_unknown_duplicate_and_unpinned_selections_fail_closed(self):
        for selections in ([],['Unknown:C'],['Example:Z'],['Example:C','Example:C']):
            with self.subTest(selections=selections),self.assertRaises(ValueError):
                EXPORT.selected_presets(self.plans,selections,self.pins)
        for pins in ([],self.pins+self.pins,[{**self.pins[0],'source':'other.blend'}],
                     [{**self.pins[0],'source_sha256':'invalid'}]):
            with self.subTest(pins=pins),self.assertRaises(ValueError):
                EXPORT.selected_presets(self.plans,['Example:C'],pins)

    def test_different_model_ids_cannot_overwrite_one_output(self):
        plans=[{**self.plans[0],'id':name} for name in ('A.B','A_B')]
        pins=[{**self.pins[0],'id':name} for name in ('A.B','A_B')]
        with self.assertRaisesRegex(ValueError,'output filename'):
            EXPORT.selected_presets(plans,['A.B:C','A_B:C'],pins)

    def test_unreviewed_body_plan_is_not_admitted(self):
        plan={**self.plans[0],'adult_model':False}
        with self.assertRaisesRegex(ValueError,'reviewed adult'):
            EXPORT.selected_presets([plan],['Example:C'],self.pins)


class AuthoredStateTests(unittest.TestCase):
    def setUp(self):
        self.saved={
            'Size':{'value':-.04,'mute':False,'min':-1.,'max':1.3},
            'Size_SDF':{'value':-.04,'mute':True,'min':-1.,'max':1.3},
            'Fat':{'value':1.,'mute':True,'min':0.,'max':1.},
            'BodyShape':{'value':.75,'mute':False,'min':0.,'max':1.},
            'FineDetail':{'value':.4,'mute':False,'min':0.,'max':1.}}

    def test_exact_negative_enlargement_and_paired_key_keep_other_defaults(self):
        original=copy.deepcopy(self.saved)
        result=EXPORT.authored_states(self.saved,['Fat'],{'Size':-1})
        self.assertEqual(result['Size']['value'],-1)
        self.assertEqual(result['Size_SDF']['value'],-1)
        self.assertFalse(result['Size_SDF']['mute'])
        self.assertEqual(result['Fat']['value'],0)
        self.assertFalse(result['Fat']['mute'])
        for name in ('BodyShape','FineDetail'):
            self.assertEqual(result[name],self.saved[name])
        self.assertEqual(self.saved,original)

    def test_default_does_not_flatten_muted_or_active_source_keys(self):
        self.assertEqual(EXPORT.authored_states(self.saved,[],{}),self.saved)

    def test_missing_nonfinite_and_out_of_authored_range_overrides_rejected(self):
        for overrides in ({'Unknown':.5},{'Size':-2},{'Size':float('nan')},
                          {'Size':float('inf')},{'Size':True}):
            with self.subTest(overrides=overrides),self.assertRaises(ValueError):
                EXPORT.authored_states(self.saved,[],overrides)


class BlenderLoadTests(unittest.TestCase):
    def test_existing_capture_is_preserved_before_opening_blender_source(self):
        with tempfile.TemporaryDirectory() as folder:
            destination=Path(folder);existing=destination/'example_a.npz'
            existing.write_bytes(b'Frozen selected body')
            fake_bpy=SimpleNamespace()
            with patch.dict('sys.modules',{'bpy':fake_bpy}):
                with self.assertRaisesRegex(ValueError,'write-once'):
                    EXPORT.export_one({'source':str(destination/'source.blend')},
                                      {},{},'example_a',destination,1)
            self.assertEqual(existing.read_bytes(),b'Frozen selected body')

    def test_critical_load_error_cannot_publish_a_plausible_partial_body(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source.blend'
            source.write_bytes(b'Load failure fixture')
            destination=Path(folder)/'export'
            open_file=Mock(side_effect=RuntimeError('Critical blend-file corruption'))
            fake_bpy=SimpleNamespace(ops=SimpleNamespace(wm=SimpleNamespace(open_mainfile=open_file)))
            with patch.dict('sys.modules',{'bpy':fake_bpy}):
                with self.assertRaisesRegex(RuntimeError,'Critical blend-file corruption'):
                    EXPORT.export_one({'source':str(source),'body_mesh':'Plausible partial body'},
                                      {'keys':{}},{'source_sha256':EXPORT.file_sha256(source)},
                                      'example_a',destination,1)
            self.assertFalse(destination.exists())
            self.assertEqual(source.read_bytes(),b'Load failure fixture')
            open_file.assert_called_once_with(filepath=str(source.resolve()),use_scripts=False)


class SparseVertexGroupTests(unittest.TestCase):
    def test_csr_keeps_all_assignments_and_reports_actual_deform_coverage(self):
        rows=[[(0,.6),(1,.4),(2,.9)],[(2,1.)],[(0,.75),(1,.75)]]
        arrays,report=EXPORT.sparse_vertex_groups(rows,['DEF-spine','DEF-thigh','WardrobeMask'],
                                                  ['DEF-spine','DEF-thigh','UnweightedBone'])
        np.testing.assert_array_equal(arrays['group_offsets'],[0,3,4,6])
        np.testing.assert_array_equal(arrays['group_indices'],[0,1,2,2,0,1])
        np.testing.assert_array_equal(arrays['group_weights'],[.6,.4,.9,1.,.75,.75])
        self.assertEqual(arrays['group_offsets'].dtype,np.int64)
        self.assertEqual(arrays['group_indices'].dtype,np.int32)
        self.assertEqual(arrays['group_weights'].dtype,np.float64)
        self.assertEqual(report['weighted_vertex_count'],2)
        self.assertEqual(report['unweighted_vertex_count'],1)
        self.assertEqual(report['maximum_deform_sum'],1.5)
        self.assertFalse(report['normalization_applied'])
        self.assertFalse(report['positive_deform_sums_within_1e_3_of_one'])
        self.assertEqual(rows[2],[(0,.75),(1,.75)])

    def test_invalid_groups_and_weights_cannot_be_serialized_as_skinning(self):
        for row in ([(-1,.5)],[(2,.5)],[(True,.5)],[(0,.5),(0,.2)],
                    [(0,float('nan'))],[(0,float('inf'))],[(0,True)]):
            with self.subTest(row=row),self.assertRaises(ValueError):
                EXPORT.sparse_vertex_groups([row],['A','B'],['A'])
        for names in ([''],[None]):
            with self.subTest(names=names),self.assertRaises(ValueError):
                EXPORT.sparse_vertex_groups([[]],names)

    def test_raw_capture_retains_finite_out_of_range_weights_and_reports_them(self):
        values=[-2.5679188553340282e-08,1.0000001]
        arrays,report=EXPORT.sparse_vertex_groups([[(0,values[0]),(1,values[1])]],['A','B'],['A','B'])
        np.testing.assert_array_equal(arrays['group_weights'],values)
        self.assertEqual(report['negative_weight_assignments'],1)
        self.assertEqual(report['above_one_weight_assignments'],1)
        self.assertFalse(report['indices_and_weights_valid'])
        self.assertFalse(report['normalization_applied'])

    def test_duplicate_labels_keep_distinct_source_group_indices(self):
        arrays,report=EXPORT.sparse_vertex_groups([[(0,.2),(1,.3),(2,.5)]],
                                                 ['DEF-spine','DEF-spine','Mask'],['DEF-spine'])
        np.testing.assert_array_equal(arrays['group_indices'],[0,1,2])
        np.testing.assert_array_equal(arrays['group_weights'],[.2,.3,.5])
        self.assertEqual(report['duplicate_name_group_indices'],{'DEF-spine':[0,1]})
        self.assertEqual(report['minimum_deform_sum'],.5)

    def test_unweighted_vertices_keep_empty_rows_without_invented_influences(self):
        arrays,report=EXPORT.sparse_vertex_groups([[],[]],[],[])
        np.testing.assert_array_equal(arrays['group_offsets'],[0,0,0])
        self.assertEqual(len(arrays['group_indices']),0)
        self.assertEqual(report['unweighted_vertex_count'],2)
        self.assertEqual(report['maximum_deform_sum'],0)


class FrozenGeometryReferenceTests(unittest.TestCase):
    def test_frozen_uv_reuse_preserves_geometry_and_skin_columns_without_consuming_new_uvs(self):
        reference={'positions':np.array([[0.,1.,2.]]),'triangles':np.array([[0,0,0]]),
            'corner_loop_indices':np.array([[0,1,2]]),'uv0':np.ones((1,3,2))}
        candidate={k:v.copy() for k,v in reference.items()}
        candidate['uv0'][0,0,0]=np.nextafter(1.,2.)
        candidate['group_offsets']=np.array([0,1])
        before=candidate['uv0'].copy()
        result,report=EXPORT.retain_reference_uvs(reference,candidate)
        self.assertTrue(EXPORT.verify_reference_arrays(reference,result)['bit_equal'])
        self.assertFalse(report['fresh_uvs_consumed'])
        self.assertEqual(report['restored']['uv0']['different_values'],1)
        np.testing.assert_array_equal(result['group_offsets'],[0,1])
        np.testing.assert_array_equal(candidate['uv0'],before)
        candidate['positions'][0,1]=np.nextafter(1.,2.)
        with self.assertRaisesRegex(ValueError,'array changed: positions'):
            EXPORT.retain_reference_uvs(reference,candidate)

    def test_frozen_uv_reuse_requires_complete_loop_indexed_geometry(self):
        with self.assertRaisesRegex(ValueError,'complete evaluated geometry'):
            EXPORT.retain_reference_uvs({'uv0':np.zeros((1,3,2))},{'uv0':np.zeros((1,3,2))})

    def test_additional_skin_data_preserves_all_geometry_and_reference_arrays(self):
        reference={'positions':np.array([[-0.,1.,2.]]),'triangles':np.array([[0,0,0]],dtype=np.int32)}
        candidate={name:value.copy() for name,value in reference.items()}
        candidate['group_offsets']=np.array([0,1],dtype=np.int64)
        before={name:value.tobytes() for name,value in reference.items()}
        report=EXPORT.verify_reference_arrays(reference,candidate)
        self.assertTrue(report['bit_equal'])
        self.assertEqual(report['extra_arrays'],['group_offsets'])
        self.assertEqual({name:value.tobytes() for name,value in reference.items()},before)

    def test_one_bit_signed_zero_dtype_shape_or_missing_array_changes_are_rejected(self):
        reference={'positions':np.array([[-0.,1.,2.]])}
        changed=reference['positions'].copy();changed[0,1]=np.nextafter(1.,2.)
        positive_zero=reference['positions'].copy();positive_zero[0,0]=0.
        for candidate in ({}, {'positions':changed},{'positions':positive_zero},
                          {'positions':reference['positions'].astype(np.float32)},
                          {'positions':reference['positions'].reshape(3)}):
            with self.subTest(candidate=candidate),self.assertRaises(ValueError):
                EXPORT.verify_reference_arrays(reference,candidate)


if __name__=='__main__':
    unittest.main()
