"""Analytic checks for offline donor fields and their sampled spatial maps."""
import copy
import unittest

import numpy as np

from nudegate.donor_flow import CompactVelocityField, euler_flow


def finite_difference(function, query, epsilon=1e-6):
    return np.stack([(function(query+np.eye(3)[axis]*epsilon)
                      -function(query-np.eye(3)[axis]*epsilon))/(2*epsilon)
                     for axis in range(3)],axis=2)


def example_field(**overrides):
    settings={'radius':.4,
              'lower_y':(.1,.35),'upper_y':(.55,.8),
              'boundary_points':[[-.18,.32,.02],[.2,.7,.12]],
              'boundary_band':(.015,.18)}
    settings.update(overrides)
    return CompactVelocityField(
        [[-.12,.3,.05],[.05,.5,-.03],[.15,.45,.08],[-.04,.68,.02]],
        [[.025,-.012,.015],[-.02,.014,.025],[.012,-.015,-.01],[-.018,.02,.01]],
        **settings)


class EulerFlowTests(unittest.TestCase):
    def test_constant_velocity_is_translation_with_identity_jacobian(self):
        q=np.array([[.2,-.1,.4],[-.5,.3,.2]])
        initial=q.copy()
        value=np.array([.3,-.2,.1])
        result=euler_flow(lambda p,**_: (np.broadcast_to(value,p.shape),np.zeros((len(p),3,3))),
                          q,steps=64,duration=.7)
        np.testing.assert_allclose(result.positions,q+.7*value,atol=2e-15,rtol=1e-14)
        np.testing.assert_array_equal(result.jacobians,np.broadcast_to(np.eye(3),(2,3,3)))
        np.testing.assert_array_equal(q,initial)
        self.assertEqual(result.report['minimum_jacobian_determinant'],1)
        self.assertEqual(result.report['maximum_sampled_step_derivative_norm'],0)

    def test_affine_field_matches_the_closed_discrete_euler_map(self):
        matrix=np.array([[.08,.04,0],[-.03,-.06,.02],[.01,0,.05]])
        offset=np.array([.01,-.02,.015])
        q=np.array([[.2,-.1,.4],[-.5,.3,.2]])
        steps,duration=12,.8
        result=euler_flow(lambda p,**_: (p@matrix.T+offset,np.broadcast_to(matrix,(len(p),3,3))),
                          q,steps=steps,duration=duration)
        update=np.eye(4)
        update[:3,:3]+=matrix*duration/steps
        update[:3,3]=offset*duration/steps
        combined=np.linalg.matrix_power(update,steps)
        expected=np.column_stack((q,np.ones(len(q))))@combined.T
        np.testing.assert_allclose(result.positions,expected[:,:3],atol=2e-15,rtol=1e-13)
        np.testing.assert_allclose(result.jacobians,np.broadcast_to(combined[:3,:3],(len(q),3,3)),atol=2e-15)
        self.assertAlmostEqual(result.report['maximum_sampled_step_derivative_norm'],
                               np.linalg.norm(matrix*duration/steps),places=14)
        self.assertAlmostEqual(result.report['minimum_sampled_step_jacobian_determinant'],
                               np.linalg.det(update[:3,:3]),places=14)

    def test_non_autonomous_field_uses_left_euler_sample_times(self):
        def velocity(q,*,time):
            value=np.zeros_like(q);value[:,0]=time
            return value,np.zeros((len(q),3,3))
        result=euler_flow(velocity,[[0,0,0]],steps=4,start_time=2,duration=1)
        self.assertAlmostEqual(result.positions[0,0],sum((2+step*.25)*.25 for step in range(4)))
        sampled=euler_flow(velocity,[[0,0,0]],steps=4,start_time=2,duration=1,time_sample_fraction=.5)
        self.assertAlmostEqual(sampled.positions[0,0],sum((2+(step+.5)*.25)*.25 for step in range(4)))
        self.assertEqual(sampled.report['time_sample_fraction'],.5)

    def test_finite_negative_jacobian_is_reported_without_a_false_safety_claim(self):
        def folding(q,**_):
            derivative=np.zeros((len(q),3,3));derivative[:,0,0]=-2
            value=np.zeros_like(q);value[:,0]=-2*q[:,0]
            return value,derivative
        result=euler_flow(folding,[[1,0,0]],steps=1)
        self.assertEqual(result.positions[0,0],-1)
        self.assertEqual(result.report['minimum_jacobian_determinant'],-1)
        self.assertNotIn('safe',result.report)
        self.assertIn('not a global',result.report['scope'])

    def test_zero_field_preserves_signed_zero_bits_and_empty_queries(self):
        q=np.array([[-0.,.25,-0.],[.2,-0.,.1]])
        result=euler_flow(lambda p,**_: (np.zeros_like(p),np.zeros((len(p),3,3))),q)
        self.assertEqual(result.positions.tobytes(),q.tobytes())
        empty=euler_flow(lambda *a,**k: self.fail('Empty query evaluated the field'),np.empty((0,3)))
        self.assertEqual(empty.positions.shape,(0,3))
        self.assertEqual(empty.jacobians.shape,(0,3,3))
        self.assertIsNone(empty.report['minimum_jacobian_determinant'])
        self.assertEqual(empty.report['evaluated_steps'],0)

    def test_invalid_integration_inputs_or_callback_results_are_rejected(self):
        zero=lambda p,**_: (np.zeros_like(p),np.zeros((len(p),3,3)))
        for kwargs in ({'steps':0},{'steps':-1},{'steps':True},{'steps':1.5},
                       {'duration':0},{'duration':-1},{'duration':float('nan')},
                       {'duration':True},{'start_time':float('inf')},
                       {'time_sample_fraction':-1},{'time_sample_fraction':2},
                       {'time_sample_fraction':float('nan')}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                euler_flow(zero,[[0,0,0]],**kwargs)
        for callback in (None,lambda p,**_: None,
                         lambda p,**_: (np.zeros((1,2)),np.zeros((1,3,3))),
                         lambda p,**_: (np.full((1,3),np.nan),np.zeros((1,3,3))),
                         lambda p,**_: (np.zeros((1,3)),np.zeros((1,2,3)))):
            with self.subTest(callback=callback),self.assertRaises(ValueError):
                euler_flow(callback,[[0,0,0]])


class CompactFieldTests(unittest.TestCase):
    def test_single_control_matches_normalized_kernel_value_and_derivative(self):
        velocity=np.array([2.,3.,-1.])
        field=CompactVelocityField([[0,0,0]],[velocity],1,stabilizer=.05)
        value,jacobian=field.evaluate([[0,0,0],[.5,0,0],[1,0,0],[2,0,0]])
        np.testing.assert_allclose(value[0],velocity/1.05)
        np.testing.assert_array_equal(jacobian[0],np.zeros((3,3)))
        weight=.5**4*3
        weight_gradient=np.array([-1.25,0,0])
        np.testing.assert_allclose(value[1],velocity*weight/(weight+.05))
        np.testing.assert_allclose(jacobian[1],np.outer(velocity,weight_gradient)*.05/(weight+.05)**2)
        np.testing.assert_array_equal(value[2:],np.zeros((2,3)))
        np.testing.assert_array_equal(jacobian[2:],np.zeros((2,3,3)))

    def test_analytic_velocity_derivative_includes_y_and_boundary_gates(self):
        field=example_field()
        q=np.array([[-.04,.27,.04],[.08,.48,.03],[-.03,.62,.08]])
        initial=q.copy()
        value,jacobian=field.evaluate(q)
        numeric=finite_difference(lambda p:field.evaluate(p)[0],q)
        np.testing.assert_allclose(jacobian,numeric,atol=2e-9,rtol=2e-7)
        np.testing.assert_array_equal(q,initial)
        self.assertTrue(np.isfinite(value).all())

    def test_composed_flow_jacobian_matches_numerical_map_derivative(self):
        field=example_field()
        q=np.array([[-.04,.27,.04],[.08,.48,.03],[-.03,.62,.08]])
        result=field.flow(q,steps=24)
        numeric=finite_difference(lambda p:field.flow(p,steps=24).positions,q)
        np.testing.assert_allclose(result.jacobians,numeric,atol=3e-9,rtol=3e-7)
        self.assertGreater(result.report['minimum_jacobian_determinant'],0)
        self.assertEqual(result.report['field']['version'],field.configuration['version'])

    def test_moving_centres_are_explicit_and_have_correct_spatial_jacobians(self):
        controls=np.array([[0,0,0],[.1,.05,.02]])
        velocities=np.array([[.04,-.02,.03],[-.025,.035,.01]])
        time=.7
        moving=CompactVelocityField(controls,velocities,.3,moving_centres=True)
        equivalent=CompactVelocityField(controls+time*velocities,velocities,.3)
        q=np.array([[.03,.04,.01],[-.04,.02,.03]])
        value,jacobian=moving.evaluate(q,time=time)
        expected,expected_jacobian=equivalent.evaluate(q)
        np.testing.assert_allclose(value,expected,atol=1e-15)
        np.testing.assert_allclose(jacobian,expected_jacobian,atol=1e-15)
        numeric=finite_difference(lambda p:moving.flow(p,steps=24,start_time=.2,time_sample_fraction=.5).positions,q)
        np.testing.assert_allclose(moving.flow(q,steps=24,start_time=.2,time_sample_fraction=.5).jacobians,numeric,atol=3e-9,rtol=3e-7)
        self.assertTrue(moving.configuration['experimental_moving_centres'])
        self.assertFalse(equivalent.configuration['experimental_moving_centres'])

    def test_protected_boundary_band_and_y_extents_are_exactly_fixed(self):
        field=CompactVelocityField([[0,0,0],[.5,.5,0]],[[.1,.02,.03],[.1,.02,.03]],2,
                                  boundary_points=[[0,0,0]],boundary_band=(.1,.3))
        q=np.array([[-0.,0.,-0.],[.05,0.,0.],[.1,0.,0.],[.25,0.,0.]])
        result=field.flow(q)
        self.assertEqual(result.positions[:3].tobytes(),q[:3].tobytes())
        np.testing.assert_array_equal(result.jacobians[:3],np.broadcast_to(np.eye(3),(3,3,3)))
        self.assertGreater(np.linalg.norm(result.positions[3]-q[3]),0)
        y_field=CompactVelocityField([[0,.5,0]],[[.1,.02,.03]],2,lower_y=(.1,.2),upper_y=(.8,.9))
        y=np.array([[0,0,0],[0,.1,0],[0,.9,0],[0,1,0],[0,.5,0]])
        result=y_field.flow(y)
        np.testing.assert_array_equal(result.positions[:4],y[:4])
        self.assertGreater(np.linalg.norm(result.positions[4]-y[4]),0)

    def test_no_implicit_body_bounds_and_inputs_are_owned_without_mutation(self):
        controls=np.array([[0,0,0.]])
        velocities=np.array([[.1,.02,.03]])
        field=CompactVelocityField(controls,velocities,1)
        before=copy.deepcopy(field.configuration)
        q=np.array([[0,-.2,0.]])
        expected=field.evaluate(q)
        self.assertGreater(np.linalg.norm(expected[0]),0)
        controls[:]=100;velocities[:]=100
        actual=field.evaluate(q)
        np.testing.assert_array_equal(actual[0],expected[0])
        np.testing.assert_array_equal(actual[1],expected[1])
        self.assertEqual(field.configuration,before)
        self.assertIsNone(field.configuration['lower_y'])
        self.assertIsNone(field.configuration['upper_y'])

    def test_zero_control_velocity_and_outside_support_have_identity_maps(self):
        field=CompactVelocityField([[0,0,0]],[[0,0,0]],1)
        q=np.array([[-0.,.2,0],[.1,.2,.3]])
        result=field.flow(q)
        self.assertEqual(result.positions.tobytes(),q.tobytes())
        np.testing.assert_array_equal(result.jacobians,np.broadcast_to(np.eye(3),(2,3,3)))
        outside=CompactVelocityField([[0,0,0]],[[1,2,3]],1).flow([[2,2,2]])
        np.testing.assert_array_equal(outside.positions,[[2,2,2]])
        self.assertEqual(field.evaluate([])[0].shape,(0,3))

    def test_invalid_field_inputs_queries_and_mask_configuration_are_rejected(self):
        for controls,velocities,radius,kwargs in (
            ([],[],1,{}),([[0,0]],[[0,0,0]],1,{}),([[0,0,0]],[[0,0,0],[1,1,1]],1,{}),
            ([[np.nan,0,0]],[[0,0,0]],1,{}),([[0,0,0]],[[np.inf,0,0]],1,{}),
            ([[0,0,0]],[[0,0,0]],0,{}),([[0,0,0]],[[0,0,0]],True,{}),
            ([[0,0,0]],[[0,0,0]],np.inf,{}),([[0,0,0]],[[0,0,0]],1,{'stabilizer':0}),
            ([[0,0,0]],[[0,0,0]],1,{'moving_centres':1}),
            ([[0,0,0]],[[0,0,0]],1,{'lower_y':(1,0)}),
            ([[0,0,0]],[[0,0,0]],1,{'upper_y':np.array(1.)}),
            ([[0,0,0]],[[0,0,0]],1,{'boundary_points':[[0,0,0]]}),
            ([[0,0,0]],[[0,0,0]],1,{'boundary_band':(0,.2)}),
            ([[0,0,0]],[[0,0,0]],1,{'boundary_points':[[0,0,0]],'boundary_band':(-1,.2)})):
            with self.subTest(controls=controls,radius=radius,kwargs=kwargs),self.assertRaises(ValueError):
                CompactVelocityField(controls,velocities,radius,**kwargs)
        field=CompactVelocityField([[0,0,0]],[[1,0,0]],1)
        for query in ([1,2,3],[[1,2]],[[1,2,3j]],[[True,False,True]],[[np.nan,0,0]]):
            with self.subTest(query=query),self.assertRaises(ValueError):field.evaluate(query)
        with self.assertRaises(ValueError):field.evaluate([[0,0,0]],time=np.inf)


if __name__=='__main__':
    unittest.main()
