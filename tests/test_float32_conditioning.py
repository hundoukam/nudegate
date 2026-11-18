import unittest
import numpy as np
from nudegate.float32_conditioning import condition_float32_step,condition_float32_vector


class Float32ConditioningTests(unittest.TestCase):
    def test_vector_budget_is_euclidean_and_original_relative(self):
        original=np.array([[.125,.001,-0.],[.125,.001,-0.],[.2,.3,-0.]],dtype=np.float64)
        after=original[0].copy();after[:2]=np.array([.125+1.5e-7,.001+1.5e-7],np.float32)
        with self.assertRaisesRegex(ValueError,'Euclidean'):
            condition_float32_vector(original,expected_position=original[0],expected_rows=[0,1],
                conditioned_position=after,maximum_error_m=2e-7)
        after=original[0].copy();after[1]=np.float32(.001+1e-8)
        result,report=condition_float32_vector(original,expected_position=original[0],expected_rows=[0,1],
            conditioned_position=after,maximum_error_m=2e-7)
        np.testing.assert_array_equal(result[:2,1],after[1])
        self.assertEqual(result[:,2].tobytes(),original[:,2].tobytes())
        self.assertEqual(result[2].tobytes(),original[2].tobytes())
        self.assertGreater(report['ulp_steps_per_axis'][1],1)
        self.assertLess(report['displacement_from_original_float64_m'],2e-7)

    def test_vector_requires_all_copies_and_exact_representable_changed_components(self):
        original,options=self.values();after=original[0].copy();after[1]=np.float32(after[1])
        for rows,value in [([0],after),([0,1],original[0]+[0,1e-9,0])]:
            with self.subTest(rows=rows),self.assertRaises(ValueError):
                condition_float32_vector(original,expected_position=original[0],expected_rows=rows,
                    conditioned_position=value,maximum_error_m=2e-7)

    def values(self):
        original=np.array([[-.7279659781267239,1.0843637753345614,-.04417751126067687],
            [-.7279659781267239,1.0843637753345614,-.04417751126067687],[-0.,0.,-0.]])
        options=dict(expected_position=original[0].tolist(),expected_rows=[0,1],axis=1,ulp_direction=-1,
            expected_before_float32=1.0843638181686401,expected_after_float32=1.0843636989593506,maximum_error_m=2e-7)
        return original,options

    def test_all_coincident_copies_step_one_ulp_without_other_bit_changes(self):
        original,options=self.values();before=original.tobytes();result,report=condition_float32_step(original,**options)
        self.assertEqual(original.tobytes(),before)
        self.assertEqual(result[2].tobytes(),original[2].tobytes())
        self.assertEqual(result[:,0].tobytes(),original[:,0].tobytes())
        self.assertEqual(result[:,2].tobytes(),original[:,2].tobytes())
        self.assertEqual(result[0,1],options['expected_after_float32'])
        self.assertEqual(result[0].tobytes(),result[1].tobytes())
        self.assertAlmostEqual(report['displacement_from_original_float64_m'],7.637521082237697e-8)

    def test_incomplete_copy_identity_or_changed_source_is_rejected(self):
        original,options=self.values()
        with self.assertRaisesRegex(ValueError,'copy IDs'):
            condition_float32_step(original,**dict(options,expected_rows=[0]))
        changed=original.copy();changed[0,0]+=1e-9
        with self.assertRaisesRegex(ValueError,'copy IDs'):
            condition_float32_step(changed,**options)

    def test_wrong_neighbour_or_excessive_error_is_rejected(self):
        original,options=self.values()
        for changed in [{'expected_after_float32':options['expected_before_float32']},
                        {'maximum_error_m':1e-8},{'maximum_error_m':1e-3},
                        {'ulp_direction':0},{'axis':True}]:
            with self.subTest(changed=changed),self.assertRaises(ValueError):
                condition_float32_step(original,**dict(options,**changed))

    def test_uncaptured_float32_or_nonfinite_source_is_rejected(self):
        original,options=self.values()
        with self.assertRaises(ValueError):condition_float32_step(original.astype(np.float32),**options)
        original[2,0]=np.nan
        with self.assertRaises(ValueError):condition_float32_step(original,**options)


if __name__=='__main__':unittest.main()
