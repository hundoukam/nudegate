import importlib.util
from pathlib import Path
import unittest
import numpy as np

spec=importlib.util.spec_from_file_location('skin_repair',Path(__file__).resolve().parents[1]/'tools/repair_donor_skin_capture.py')
REPAIR=importlib.util.module_from_spec(spec);spec.loader.exec_module(REPAIR)


class EnumeratedSkinRepairTests(unittest.TestCase):
    def test_mercy_root_placeholder_cannot_affect_a_referenced_vertex(self):
        arrays={'positions':np.zeros((12942,3)),'triangles':np.array([[0,1,2]]),
            'group_offsets':np.zeros(12943,dtype=np.int64),'group_indices':np.array([],dtype=np.int32),
            'group_weights':np.array([],dtype=float)}
        metadata={'vertex_group_names':['DEF-spine'],
            'vertex_group_validation':{'active_vertex_group_rigs':['Mercy_rig']},
            'rigs':[{'name':'Mercy_rig','bones':[{'name':'DEF-spine','deform':True}]}]}
        fixed,report=REPAIR.repair_mercy(arrays,metadata)
        self.assertEqual(report['rendered_vertices_changed'],0)
        np.testing.assert_array_equal(fixed['positions'],arrays['positions'])
        self.assertEqual(fixed['group_weights'].tolist(),[1.])
        self.assertEqual(len(arrays['group_weights']),0)
        arrays['triangles'][0,0]=12941
        with self.assertRaisesRegex(ValueError,'nonrendered orphan'):
            REPAIR.repair_mercy(arrays,metadata)

    def test_kiriko_only_changes_the_four_exact_captured_residuals(self):
        weights=np.full(max(REPAIR.KIRIKO_RESIDUALS)+1,.5)
        for index,value in REPAIR.KIRIKO_RESIDUALS.items():weights[index]=value
        arrays={'group_weights':weights,'group_indices':np.zeros(len(weights),dtype=int),
                'group_offsets':np.arange(len(weights)+1)}
        result,report=REPAIR.repair_kiriko(arrays,{'vertex_group_names':['Bone']})
        changed=np.flatnonzero(result['group_weights']!=weights).tolist()
        self.assertEqual(changed,list(REPAIR.KIRIKO_RESIDUALS))
        self.assertEqual(report['maximum_absolute_weight_delta'],2.5679188553340282e-08)
        weights[17185]=np.nextafter(weights[17185],0)
        with self.assertRaisesRegex(ValueError,'residual value changed'):
            REPAIR.repair_kiriko(arrays,{'vertex_group_names':['Bone']})


if __name__=='__main__':unittest.main()
