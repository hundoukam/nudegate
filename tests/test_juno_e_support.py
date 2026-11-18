import copy
import importlib.util
from pathlib import Path
import unittest

import numpy as np

from nudegate.juno_e_support import (_restore_positions, _distance_field,
    _proximal_axis_gate, _descends, _point, validate_source, SOURCE_SHA256, SCALE)
from nudegate.donor_body import _orient_bridge_from_body, trim_and_bridge, _cut_height

SPEC = importlib.util.spec_from_file_location('prepare_juno_e_support',
    Path(__file__).resolve().parents[1] / 'tools/prepare_juno_e_support.py')
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)


class SourceSupportFieldTests(unittest.TestCase):
    def test_exact_constant_regions_and_true_blend(self):
        source = np.array([[1., -0., 3.], [4., 5., 6.], [0., 0., 0.]])
        previous = np.array([[9., 8., 7.], [-0., 2., 3.], [8., 4., 2.]])
        actual = _restore_positions(source, previous, np.array([1., 0., .25]))
        self.assertEqual(actual[0].tobytes(), source[0].tobytes())
        self.assertEqual(actual[1].tobytes(), previous[1].tobytes())
        np.testing.assert_array_equal(actual[2], [6., 3., 1.5])
        np.testing.assert_array_equal(previous[2], [8., 4., 2.])

    def test_invalid_field_cannot_silently_move_geometry(self):
        points = np.zeros((2, 3))
        for field in (np.array([0., 1.01]), np.array([-.01, 1.]), np.array([np.nan, 0.]), np.zeros(3)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                _restore_positions(points, points, field)

    def test_anatomical_margin_restores_adjacent_zero_weight_rows(self):
        # A zero-weight seam beside a weighted anatomy patch is also source
        # protected, avoiding a hard discontinuity across coincident surfaces.
        points = np.array([[0., 0., 0.], [.005, 0., 0.], [.01, 0., 0.], [.02, 0., 0.]])
        actual = _distance_field(points, np.array([True, False, False, False]), .005, .01)
        np.testing.assert_array_equal(actual, [1., 1., .5, 0.])
        with self.assertRaises(ValueError):
            _distance_field(points, np.zeros(4, bool), .005, .01)

    def test_weak_breast_tail_does_not_freeze_distal_arm(self):
        actual = _proximal_axis_gate(np.array([0., .375, .5, 1.]), np.array([0., 0., .001, .1]))
        np.testing.assert_array_equal(actual, [1., .5, 0., 0.])

    def test_breast_majority_bypasses_projected_arm_axis(self):
        # The larger authored breast extends past the projected arm axis;
        # freezing only weak labels would incorrectly alter the actual shape.
        actual = _proximal_axis_gate(np.array([.75, .75, .75]), np.array([.25, .375, .5]))
        np.testing.assert_array_equal(actual, [0., .5, 1.])

    def test_support_ancestry_is_real_and_cycle_safe(self):
        bones = {'genitals': {'parent': 'spine'}, 'vagina': {'parent': 'genitals'},
            'Butt': {'parent': 'spine'}, 'cycle': {'parent': 'cycle'}}
        self.assertTrue(_descends('vagina', {'genitals'}, bones))
        self.assertFalse(_descends('Butt', {'genitals'}, bones))
        self.assertFalse(_descends('cycle', {'genitals'}, bones))

    def test_source_points_preserve_axis_order_and_uniform_placement(self):
        bones = {'neck': {'posed_head_world': [1., 2., 3.]}}
        np.testing.assert_array_equal(_point(bones, 'neck'), np.array([1., 3., 2.]) * SCALE)


class SourceStateGuardTests(unittest.TestCase):
    def metadata(self):
        parents = {'l_breast': 'DEF-spine.003', 'r_breast': 'DEF-spine.003',
            'l_breast2': 'l_breast', 'r_breast2': 'r_breast',
            'DEF-shoulder.L': 'ORG-shoulder.L', 'DEF-shoulder.R': 'ORG-shoulder.R',
            'genitals': 'DEF-spine', 'genit.front': 'genitals', 'vagina': 'genit.front',
            'anus_01': 'genitals', 'anus_02': 'anus_01'}
        parents.update({'DEF-spine': 'root', **{'DEF-spine.%03d' % i:
            ('DEF-spine' if i == 1 else 'DEF-spine.%03d' % (i - 1)) for i in range(1, 8)}})
        bones = [{'name': name, 'parent': parent, 'deform': True} for name, parent in parents.items()]
        bones += [{'name': 'unused_%d' % i, 'parent': None, 'deform': False} for i in range(693 - len(bones))]
        return {'id': 'juno_e', 'key_overrides': {'Chubby': 1}, 'npz_sha256': SOURCE_SHA256,
            'vertex_group_validation': {'active_vertex_group_rigs': ['G9_Rig']},
            'rigs': [{'name': 'G9_Rig', 'bones': bones}]}

    def test_selected_state_and_rig_guards(self):
        valid = self.metadata()
        self.assertIn('vagina', validate_source(valid))
        for key, value in [('id', 'juno_b'), ('key_overrides', {'Chubby': .5}), ('npz_sha256', '0' * 64)]:
            changed = copy.deepcopy(valid); changed[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_source(changed)

    def test_source_hierarchy_change_is_not_treated_as_same_support(self):
        changed = self.metadata()
        next(bone for bone in changed['rigs'][0]['bones'] if bone['name'] == 'anus_02')['parent'] = 'DEF-thigh.L'
        with self.assertRaises(ValueError):
            validate_source(changed)


class AttributeRetransferGuardTests(unittest.TestCase):
    def fixture(self):
        previous = {'positions': np.eye(3), 'normals': np.eye(3),
            'source_vertex_ids': np.array([4, 5, 6]), 'geometry_vertex_ids': np.arange(3),
            'bone_weights': np.array([[1., 0.], [.5, .5], [0., 1.]]),
            'source_face_ids': np.array([23]), 'triangles': np.array([[0, 1, 2]])}
        current = {key: value[[0, 1, 2, 0]].copy() if key not in ('source_face_ids', 'triangles')
            else value.copy() for key, value in previous.items()}
        current['triangles'][0, 0] = 3
        old_mesh = {'bone_palette': ['Root', 'Chest'],
            'bone_indices': [[0, 0, 0, 0], [0, 1, 0, 0], [1, 0, 0, 0]],
            'bone_weights': [[255, 0, 0, 0], [128, 127, 0, 0], [255, 0, 0, 0]]}
        new_mesh = copy.deepcopy(old_mesh)
        for key in ('bone_indices', 'bone_weights'):
            new_mesh[key].append(new_mesh[key][0].copy())
        return previous, current, old_mesh, new_mesh

    def test_uv_seam_duplication_is_allowed_with_exact_face_corner_skin(self):
        self.assertTrue(all(TOOL.verify_corner_parity(*self.fixture()).values()))

    def test_geometry_or_reviewed_skin_drift_is_rejected(self):
        for key in ('positions', 'normals', 'source_vertex_ids', 'bone_weights'):
            previous, current, old_mesh, new_mesh = self.fixture()
            current[key][3] += 1
            with self.subTest(key=key), self.assertRaises(ValueError):
                TOOL.verify_corner_parity(previous, current, old_mesh, new_mesh)
        previous, current, old_mesh, new_mesh = self.fixture()
        new_mesh['bone_weights'][0][0] -= 1
        new_mesh['bone_weights'][0][1] += 1
        # This modified unused seam copy is not a final corner. Modify the
        # active copy as well so the material's actual rendered skin is tested.
        new_mesh['bone_weights'][3] = new_mesh['bone_weights'][0].copy()
        with self.assertRaises(ValueError):
            TOOL.verify_corner_parity(previous, current, old_mesh, new_mesh)

    def test_native_lookup_may_move_positions_but_not_uv_paint_or_rig(self):
        native = {'positions': np.eye(3), 'triangles': np.array([[0, 1, 2]]),
            'bone_weights': np.ones((3, 1)), 'inverse_bind': np.eye(4)[None],
            'bone_palette': ['Root'], 'corners': {'TEXCOORD': np.zeros((1, 3, 2)), 'COLOR': np.ones((1, 3, 4))}}
        reference = copy.deepcopy(native); reference['positions'] += 5
        self.assertTrue(all(TOOL.verify_lookup_semantics(native, reference).values()))
        reference['corners']['COLOR'][0, 0, 0] = 0
        with self.assertRaises(ValueError):
            TOOL.verify_lookup_semantics(native, reference)


class LocalNeckBridgeTests(unittest.TestCase):
    def test_bridge_has_one_global_orientation_opposite_original_rim(self):
        body = np.array([[0, 1, 2]])
        bridge = np.array([[1, 0, 3], [0, 4, 3]])
        np.testing.assert_array_equal(_orient_bridge_from_body(body, bridge), bridge)
        np.testing.assert_array_equal(_orient_bridge_from_body(body, bridge[:, [0, 2, 1]]), bridge)
        with self.assertRaisesRegex(ValueError, 'internal winding'):
            _orient_bridge_from_body(body, np.array([[1, 0, 3], [0, 3, 4]]))
        with self.assertRaisesRegex(ValueError, 'rim has inconsistent'):
            _orient_bridge_from_body(np.array([[0, 1, 2], [4, 3, 5]]), np.array([[1, 0, 3], [3, 0, 4]]))

    @staticmethod
    def cylinder(samples, top, radius, closed_top):
        angle = np.arange(samples) * 2 * np.pi / samples
        ring = np.column_stack((radius * np.cos(angle), np.zeros(samples), radius * np.sin(angle)))
        upper = ring.copy(); upper[:, 1] = top
        points = np.vstack((ring, upper, [0., 0., 0.], [0., top, 0.]))
        faces = []
        for i in range(samples):
            j = (i + 1) % samples
            faces.extend([[i, samples + i, samples + j], [i, samples + j, j], [2 * samples, i, j]])
            if closed_top:
                faces.append([2 * samples + 1, samples + j, samples + i])
        # The unused top center is not needed by the native open collar.
        if not closed_top:
            points = points[:-1]
        return points, np.asarray(faces)

    def test_explicit_original_cut_callback_is_bit_exact_to_default(self):
        positions, triangles = self.cylinder(16, 1.7, .06, True)
        np_, nt = self.cylinder(18, 1.56, .05, False)
        normal = np_.copy(); normal[:, 1] = 0.
        normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-12)
        native = {'positions': np_, 'triangles': nt, 'bone_weights': np.ones((len(np_), 1)),
            'corners': {'NORMAL': normal[nt]}}
        posed = {'positions': positions, 'triangles': triangles, 'source_vertex_ids': np.arange(len(positions))}
        mapped = np.ones((len(positions), 1))
        original, _ = trim_and_bridge(posed, mapped, native)
        explicit, _ = trim_and_bridge(posed, mapped, native, cut_height=_cut_height)
        self.assertEqual(set(original), set(explicit))
        for key in original:
            with self.subTest(key=key):
                self.assertEqual(original[key].tobytes(), explicit[key].tobytes())
        with self.assertRaisesRegex(ValueError, 'cut height field'):
            trim_and_bridge(posed, mapped, native, cut_height=lambda x, cut: np.full(len(x), np.nan))

    def test_safe_default_prevents_radial_face_flips_on_wide_sloping_neck(self):
        points, faces = self.cylinder(16, 1.8, .12, True)
        np_, nt = self.cylinder(18, 1.56, .05, False)
        top = np.arange(18, 36); np_[top, 1] -= .5 * np_[top, 2]
        normal = np_.copy(); normal[:, 1] = 0.
        normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-12)
        native = {'positions': np_, 'triangles': nt, 'bone_weights': np.ones((len(np_), 1)),
            'corners': {'NORMAL': normal[nt]}}
        posed = {'positions': points, 'triangles': faces, 'source_vertex_ids': np.arange(len(points))}
        safe, report = trim_and_bridge(posed, np.ones((len(points), 1)), native)
        legacy, _ = trim_and_bridge(posed, np.ones((len(points), 1)), native, bridge_orientation='radial')
        def conflicts(triangles):
            edges = {}
            for face in triangles:
                for a, b in zip(face, np.roll(face, -1)):
                    edges.setdefault(tuple(sorted((int(a), int(b)))), []).append((int(a), int(b)))
            return sum(len(directions) == 2 and directions[0] == directions[1] for directions in edges.values())
        self.assertEqual(conflicts(safe['triangles']), 0)
        self.assertGreater(conflicts(legacy['triangles']), 0)
        self.assertEqual(safe['positions'].tobytes(), legacy['positions'].tobytes())
        self.assertEqual(report['bridge_internal_winding_conflicts'], 0)
        self.assertEqual(report['body_bridge_boundary_winding_conflicts'], 0)


if __name__ == '__main__':
    unittest.main()
