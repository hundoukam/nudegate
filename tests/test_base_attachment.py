"""Bounded, welded new-base attachment candidates preserve source controls."""
import copy
import math
import unittest

from nudegate.base_attachment import round_base_attachments


def fixture():
    positions=[];triangles=[]
    for sign in (-1,1):
        start=len(positions)
        for row in range(5):
            for column in range(5):positions.append([sign*(.04+.02*column),1.24+.015*row,-.11])
        for row in range(4):
            for column in range(4):
                a=start+row*5+column
                triangles.extend([(a,a+1,a+5),(a+1,a+6,a+5)])
    positions.extend([[-.08,1.36,-.2],[.08,1.36,-.2],[.6,1.15,0]])
    duplicate=len(positions);positions.append(list(positions[12]))
    target=copy.deepcopy(positions)
    for index in (12,37,duplicate):target[index][2]=-.14
    regions={side:{'center':[sign*.08,1.35,-.055],
                   'weights':[1. if point[0]*sign>0 and abs(point[0])<.2 else 0. for point in positions]}
             for side,sign in [('chest_left',-1),('chest_right',1)]}
    mesh={'positions':positions,'triangles':triangles,'locked_vertices':[0,25],
          'regions':regions,'frame':[1,1,1],'topology_id':'reviewed-fixture'}
    return mesh,target,duplicate


class BaseAttachmentTests(unittest.TestCase):
    def test_fairing_softens_local_spike_with_bounded_correction(self):
        mesh,target,_=fixture()
        result=round_base_attachments(mesh,target)
        self.assertGreater(result['positions'][12][2],target[12][2])
        self.assertLessEqual(max(math.dist(a,b) for a,b in zip(target,result['positions'])),.012+1e-12)
        self.assertEqual(len(result['positions']),len(target))
        self.assertTrue(result['report']['apex_neighborhoods_unchanged'])
        self.assertIn('actual intersection proof required',result['report']['status'])

    def test_source_seams_apices_unmasked_coordinates_and_inputs_are_preserved(self):
        mesh,target,duplicate=fixture();before_mesh=copy.deepcopy(mesh);before_target=copy.deepcopy(target)
        result=round_base_attachments(mesh,target)
        self.assertEqual(result['positions'][12],result['positions'][duplicate])
        for index in (0,25,50,51,52):self.assertEqual(result['positions'][index],target[index])
        self.assertEqual(mesh,before_mesh);self.assertEqual(target,before_target)

    def test_locked_duplicate_protects_the_entire_welded_group(self):
        mesh,target,duplicate=fixture()
        target[12]=list(mesh['positions'][12]);target[duplicate]=list(mesh['positions'][duplicate])
        mesh['locked_vertices'].append(duplicate)
        result=round_base_attachments(mesh,target)
        self.assertEqual(result['positions'][12],mesh['positions'][12])
        self.assertEqual(result['positions'][duplicate],mesh['positions'][duplicate])

    def test_zero_passes_are_an_exact_identity(self):
        mesh,target,_=fixture();mesh['frame']=[1.2,1.1,1.15]
        # Keep the canonical landmarks in the reviewed domain.
        for array in (mesh['positions'],target):
            for point in array:
                for axis in range(3):point[axis]*=mesh['frame'][axis]
        self.assertEqual(round_base_attachments(mesh,target,passes=0)['positions'],target)

    def test_invalid_source_target_and_parameters_fail_before_changes(self):
        for failure in ('nan','large_integer','weld','lock','triangle','mask','topology'):
            with self.subTest(failure=failure):
                mesh,target,duplicate=fixture()
                if failure=='nan':target[1][0]=float('nan')
                elif failure=='large_integer':target[1][0]=10**1000
                elif failure=='weld':target[duplicate][0]+=.001
                elif failure=='lock':target[0][0]+=.001
                elif failure=='triangle':mesh['triangles'][0]=(0,1,len(target))
                elif failure=='mask':mesh['regions']['chest_left']['weights']=[]
                else:mesh['topology_id']=''
                with self.assertRaises(ValueError):round_base_attachments(mesh,target)
        for kwargs in ({'passes':True},{'passes':101},{'strength':float('inf')},{'maximum_correction_metres':.03}):
            with self.subTest(kwargs=kwargs):
                mesh,target,_=fixture()
                with self.assertRaises(ValueError):round_base_attachments(mesh,target,**kwargs)


if __name__=='__main__':unittest.main()
