"""Independent Cinderella calibration and seven-spine skin semantics."""
import unittest
from unittest import mock
import numpy as np

from nudegate.cinderella_body import (calibrate, active_bones, map_weights, pose,
                                     validate_optional_uncompressed, OPTIONAL_UNCOMPRESSED_KEYS, apply_pose_coherence)
from nudegate.surface_intersections import geometry_fingerprint


def metadata():
    bones = [{'name': 'DEF-spine' + ('.%03d' % i if i else ''), 'parent': None, 'deform': True,
              'posed_head_world': [0, .04, .5 + i * .15]} for i in range(7)]
    for side, sign in [('L', 1), ('R', -1)]:
        for name, point in [('upper_arm', [.2 * sign, 0, 1]), ('forearm', [.4 * sign, 0, 1]),
                            ('hand', [.6 * sign, 0, 1]), ('thigh', [.1 * sign, 0, .9]),
                            ('shin', [.1 * sign, 0, .5]), ('foot', [.1 * sign, 0, .1])]:
            bones.append({'name': 'DEF-' + name + '.' + side, 'parent': None, 'deform': True,
                          'posed_head_world': point})
    return {'rigs': [{'name': 'Rig', 'bones': bones}],
            'vertex_group_validation': {'active_vertex_group_rigs': ['Rig']}}


def matrix(point):
    result = np.eye(4)
    result[:3, 3] = point
    return result


class CinderellaProfileTests(unittest.TestCase):
    def corrective_fixture(self):
        source = np.array([[0., 0, 0], [.01, 0, -0.], [0, 1, 0]])
        positions = source.copy()
        positions[0, 1] = .0006
        posed = {'scaled_source_positions': source, 'positions': positions,
                 'triangles': np.array([[0, 1, 2]]),
                 'source_breast_influence_left': np.zeros(3), 'source_breast_influence_right': np.zeros(3)}
        parameters = {'schema_version': 1, 'operation': 'explicit pose-coherence fixture',
            'source_npz_sha256': 'synthetic-source',
            'source_pose_geometry_sha256': geometry_fingerprint(positions, posed['triangles']),
            'inner_min': [-.001, -.001, -.001], 'inner_max': [.001, .001, .001],
            'target_displacement': [0, .0003, 0], 'fade_m': .001, 'maximum_allowed_corrective_m': .001}
        return posed, parameters

    def test_local_pose_corrective_preserves_every_outside_position_bit(self):
        posed, parameters = self.corrective_fixture()
        before = posed['positions'].copy()
        result, report = apply_pose_coherence(posed, parameters, 'synthetic-source')
        np.testing.assert_allclose(result['positions'][0], [0, .0003, 0])
        self.assertEqual(result['positions'][1:].tobytes(), before[1:].tobytes())
        self.assertEqual(posed['positions'].tobytes(), before.tobytes())
        self.assertEqual(report['changed_source_vertex_ids'], [0])
        self.assertTrue(report['all_positions_outside_corrective_bit_exact'])

    def test_local_pose_corrective_rejects_another_source_pose_or_excess_displacement(self):
        posed, parameters = self.corrective_fixture()
        with self.assertRaisesRegex(ValueError, 'source/pose fingerprints'):
            apply_pose_coherence(posed, parameters, 'another-source')
        parameters['target_displacement'][1] = .002
        with self.assertRaisesRegex(ValueError, 'displacement bound'):
            apply_pose_coherence(posed, parameters, 'synthetic-source')
        posed['positions'][0, 0] = .00001
        with self.assertRaisesRegex(ValueError, 'source/pose fingerprints'):
            apply_pose_coherence(posed, parameters, 'synthetic-source')

    def test_pelvic_pose_corrective_cannot_reach_breast_influences(self):
        posed, parameters = self.corrective_fixture()
        posed['source_breast_influence_left'][0] = .1
        with self.assertRaisesRegex(ValueError, 'breast influences'):
            apply_pose_coherence(posed, parameters, 'synthetic-source')

    def test_optional_study_cannot_change_another_selected_shape_control(self):
        import copy
        states = {key: {'value': 1., 'mute': False} for key in (*OPTIONAL_UNCOMPRESSED_KEYS, 'ass')}
        selected = {'source_sha256': 'selected-source', 'applied_shape_keys': states}
        optional = {'id': 'cinderella_optional_uncompressed', 'source_sha256': 'selected-source',
                    'key_overrides': {key: 0 for key in OPTIONAL_UNCOMPRESSED_KEYS},
                    'applied_shape_keys': copy.deepcopy(states)}
        for key in OPTIONAL_UNCOMPRESSED_KEYS:
            optional['applied_shape_keys'][key]['value'] = 0.
        self.assertTrue(validate_optional_uncompressed(optional, selected)['all_other_selected_settings_exact'])
        optional['applied_shape_keys']['ass']['value'] = 0.
        with self.assertRaisesRegex(ValueError, 'another selected authored setting'):
            validate_optional_uncompressed(optional, selected)

    def test_scale_and_placement_come_from_own_ground_shoulder_and_neck(self):
        data = metadata()
        bones = {bone['name']: bone for bone in data['rigs'][0]['bones']}
        for side, sign in [('L', 1), ('R', -1)]:
            bones['DEF-upper_arm.' + side]['posed_head_world'] = [.2 * sign, .07, 1.1]
        bones['DEF-spine.005']['posed_head_world'] = [0, .04, 1.4]
        scale = 1.2
        translation = np.array([.03, .2, -.05])
        place = lambda p: np.asarray(p)[[0, 2, 1]] * scale + translation
        worlds = {name: matrix(place(bones[source]['posed_head_world'])) for name, source in
                  [('Shoulder_L', 'DEF-upper_arm.L'), ('Shoulder_R', 'DEF-upper_arm.R'),
                   ('Neck_M', 'DEF-spine.005')]}
        worlds['Head_M'] = matrix(worlds['Neck_M'][:3, 3] + [0, .1, 0])
        native = {'positions': np.array([[0, .08, 0], [0, 1.86, 0], [.1, 1.87, 0], [-.1, 1.87, 0]]),
                  'bone_world': worlds}
        arrays = {'positions': np.array([[0, 0, -.1], [0, 0, 1.5]])}
        with mock.patch('nudegate.cinderella_body.native_collar', return_value=np.array([1, 2, 3])):
            result = calibrate(arrays, data, native)
        self.assertAlmostEqual(result['uniform_scale'], scale)
        np.testing.assert_allclose(result['translation_bg3'], translation, atol=1e-15)
        np.testing.assert_allclose(result['placed_shoulder_residual'], 0, atol=1e-15)
        np.testing.assert_allclose(result['placed_neck_residual'], 0, atol=1e-15)
        self.assertEqual(result['source_neck_anchor'], 'DEF-spine.005')

    def test_eight_spine_rig_cannot_silently_use_cinderella_profile(self):
        data = metadata()
        data['rigs'][0]['bones'].append({'name': 'DEF-spine.007'})
        with self.assertRaisesRegex(ValueError, 'seven-spine'):
            active_bones(data)

    def test_neck_and_head_mapping_differs_from_juno_eight_spine_map(self):
        names = ['DEF-spine.003', 'DEF-spine.004', 'DEF-spine.005', 'DEF-spine.006',
                 'DEF-pelvis.L', 'DEF-Ass.R', 'DEF-breast.L.002']
        targets = ['Root_M', 'Chest_M', 'Neck_M', 'Head_M']
        weights, report = map_weights(np.eye(len(names)), names, {}, targets)
        self.assertEqual(np.argmax(weights, axis=1).tolist(), [1, 2, 2, 3, 0, 0, 1])
        self.assertEqual(report['unknown_positive_groups'], [])
        np.testing.assert_array_equal(weights.sum(axis=1), 1)

    def test_unknown_positive_groups_fail_without_nearest_bone_fallback(self):
        with self.assertRaisesRegex(ValueError, 'Unmapped positive Cinderella'):
            map_weights(np.ones((1, 1)), ['unreviewed-bone'], {'unreviewed-bone': {'parent': None}}, ['Root_M'])

    def test_limb_pose_preserves_core_and_uses_original_deform_weights(self):
        data = metadata()
        data['vertex_group_names'] = ['DEF-spine', 'DEF-upper_arm.L', 'DEF-thigh.R']
        arrays = {'positions': np.array([[0, 0, 1.1], [.4, 0, 1], [-.1, 0, .6]]),
                  'triangles': np.array([[0, 1, 2]]), 'group_offsets': np.arange(4),
                  'group_indices': np.arange(3), 'group_weights': np.ones(3)}
        worlds = {}
        for side, sign in [('L', 1), ('R', -1)]:
            for name, point in [('Shoulder', [.2 * sign, 1, 0]), ('Elbow', [.3 * sign, .9, 0]),
                                ('Wrist', [.4 * sign, .8, 0]), ('Hip', [.1 * sign, .9, 0]),
                                ('Knee', [.1 * sign, .5, 0]), ('Ankle', [.1 * sign, .1, 0])]:
                worlds[name + '_' + side] = matrix(point)
        result, _, _, _, report = pose(arrays, data, {'bone_world': worlds},
            {'uniform_scale': 1., 'translation_bg3': [0, 0, 0]})
        np.testing.assert_array_equal(result['positions'][0], [0, 1.1, 0])
        np.testing.assert_allclose(result['positions'][1], [.2 + .2 / np.sqrt(2), 1 - .2 / np.sqrt(2), 0])
        np.testing.assert_array_equal(result['triangles'], [[0, 2, 1]])
        self.assertEqual(report['torso_uninfluenced_max_error'], 0)


if __name__ == '__main__':
    unittest.main()
