import tempfile
from pathlib import Path
import unittest

import numpy as np

from nudegate.native_proxy_fit import (fit_native_proxy, fit_disposable_lookup,
    exact_surface_distances, verify_only_position_arrays_changed, anterior_pole_seeds)


def plane(z=0.):
    return (np.array([[-.01, -.01, z], [.01, -.01, z], [.01, .01, z], [-.01, .01, z]]),
            np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int32))


class NativeProxyFitTests(unittest.TestCase):
    def test_pole_seeds_preserve_inputs_and_follow_only_authored_sides(self):
        native = np.array([[.04, 0., -.1], [.05, .01, -.05], [.01, .02, -.02],
            [-.04, 0., -.1], [-.05, .01, -.05], [-.01, .02, -.02]])
        left, right = np.array([1., 1., 0., 0., 0., 0.]), np.array([0., 0., 0., 1., 1., 0.])
        donor = native+[0., 0., -.02]
        original = donor.copy()
        seeds, report = anterior_pole_seeds(native, donor, left, right)
        np.testing.assert_array_equal(donor, original)
        np.testing.assert_allclose(seeds[[0, 3]], donor[[0, 3]], atol=1e-16)
        np.testing.assert_array_equal(seeds[[2, 5]], native[[2, 5]])
        self.assertEqual([row['donor_source_vertex_id'] for row in report['poles']], [0, 3])
        identity, _ = anterior_pole_seeds(native, native, left, right)
        self.assertEqual(identity.tobytes(), native.tobytes())

    def test_pole_seeds_reject_missing_or_invalid_author_support(self):
        native = np.array([[.04, 0., -.1], [-.04, 0., -.1], [0., .01, -.02]])
        for left, right in [([0, 0, 0], [0, 1, 0]), ([1, 0, 0], [0, np.nan, 0]),
                            ([1, 0], [0, 1, 0])]:
            with self.subTest(left=left), self.assertRaises(ValueError):
                anterior_pole_seeds(native, native, left, right)

    def test_identity_keeps_surface_and_jacobians_exact(self):
        positions, triangles = plane()
        original = positions.copy()
        fit = fit_native_proxy(positions, triangles, positions, triangles, np.ones(4),
            radius=.03, moving_centres=True)
        np.testing.assert_array_equal(positions, original)
        self.assertEqual(fit.flow.positions.tobytes(), positions.tobytes())
        np.testing.assert_array_equal(fit.flow.jacobians, np.broadcast_to(np.eye(3), (4, 3, 3)))
        self.assertEqual(fit.report['global_original_proxy_surface_proof']['candidate_intersection_count'], 0)
        lookup, proof = fit_disposable_lookup(fit, positions, triangles)
        self.assertEqual(lookup.positions.tobytes(), positions.tobytes())
        self.assertTrue(proof['safe'])

    def test_normal_translation_has_surface_targets_and_correct_flow_derivative(self):
        positions, triangles = plane()
        donor = positions + [0., 0., .004]
        fit = fit_native_proxy(positions, triangles, donor, triangles, np.ones(4),
            radius=.03, moving_centres=True)
        np.testing.assert_allclose(fit.targets, donor, atol=1e-16)
        self.assertTrue(np.all(fit.flow.positions[:, 2] > .003))
        self.assertTrue(np.all(fit.flow.positions[:, 2] < .004))
        self.assertGreater(fit.report['minimum_proxy_jacobian_determinant'], .9)
        query = np.array([[.001, -.002, .001], [-.003, .004, .002]])
        analytic = fit.field().flow(query, steps=64, time_sample_fraction=.5).jacobians
        numerical = np.empty_like(analytic)
        for axis in range(3):
            shift = np.zeros(3)
            shift[axis] = 1e-6
            plus = fit.field().flow(query+shift, steps=64, time_sample_fraction=.5).positions
            minus = fit.field().flow(query-shift, steps=64, time_sample_fraction=.5).positions
            numerical[:, :, axis] = (plus-minus)/2e-6
        np.testing.assert_allclose(analytic, numerical, atol=1e-8, rtol=0)

    def test_disconnected_breast_support_is_rejected(self):
        positions, triangles = plane()
        donor = np.vstack([positions, positions+[0., 0., .1]])
        faces = np.vstack([triangles, triangles+4])
        with self.assertRaisesRegex(ValueError, 'disconnected'):
            fit_native_proxy(positions, triangles, donor, faces, np.ones(8))

    def test_only_small_anatomical_island_is_rejected(self):
        positions, triangles = plane()
        donor = np.vstack([positions, [[.1, 0, 0], [.11, 0, 0], [.1, .01, 0]]])
        faces = np.vstack([triangles, [[4, 5, 6]]])
        with self.assertRaisesRegex(ValueError, 'main connected'):
            fit_native_proxy(positions, triangles, donor, faces, [0, 0, 0, 0, 1, 1, 1])

    def test_invalid_geometry_and_score_inputs_fail_closed(self):
        positions, triangles = plane()
        cases = [('nan-coordinate', np.where(positions == .01, np.nan, positions), triangles, {}),
            ('bad-index', positions, np.array([[0, 1, 9]]), {}),
            ('float-index', positions, triangles.astype(float), {}),
            ('collapsed', positions, np.array([[0, 0, 1]]), {}),
            ('zero-radius', positions, triangles, {'radius': 0}),
            ('normal-score', positions, triangles, {'minimum_normal_agreement': 2}),
            ('invalid-seeds', positions, triangles, {'projection_seed_positions': [[0, 0, 0]]}),
            ('bad-neighbours', positions, triangles, {'neighbours': True})]
        for name, points, faces, options in cases:
            with self.subTest(name=name), self.assertRaises(ValueError):
                fit_native_proxy(points, faces, positions, triangles, np.ones(4), **options)

    def test_projection_seed_never_replaces_original_control_points(self):
        positions, triangles = plane()
        fit = fit_native_proxy(positions, triangles, positions, triangles, np.ones(4),
            radius=.03, projection_seed_positions=positions+[0, 0, .02])
        self.assertTrue(fit.report['projection_seeds_used'])
        np.testing.assert_array_equal(fit.control_points, positions)
        np.testing.assert_allclose(fit.targets, positions, atol=1e-16)
        np.testing.assert_allclose(fit.flow.positions, positions, atol=1e-16)

    def test_surface_distance_search_includes_every_triangle(self):
        positions, triangles = plane()
        query = np.array([[0., 0., .03], [.02, 0., 0.]])
        distance = exact_surface_distances(query, positions, triangles, chunk_size=1)
        np.testing.assert_allclose(distance, [.03, .01], atol=1e-16)

    def test_xml_guard_allows_positions_and_rejects_other_native_records(self):
        template = '''<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema"><!--Keep--><library_geometries><geometry id="mesh"><mesh><source id="p"><float_array count="3">{positions}</float_array></source><source id="color"><float_array count="3">{color}</float_array></source><vertices><input semantic="POSITION" source="#p"/></vertices></mesh></geometry></library_geometries></COLLADA>'''
        with tempfile.TemporaryDirectory() as temp:
            reference, authored = Path(temp)/'reference.dae', Path(temp)/'authored.dae'
            reference.write_text(template.format(positions='0 0 0', color='1 0 0'))
            authored.write_text(template.format(positions='0 0 1', color='1 0 0'))
            self.assertTrue(verify_only_position_arrays_changed(reference, authored, ['mesh']))
            authored.write_text(template.format(positions='0 0 1', color='0 1 0'))
            with self.assertRaisesRegex(ValueError, 'Unrelated native'):
                verify_only_position_arrays_changed(reference, authored, ['mesh'])


if __name__ == '__main__':
    unittest.main()
