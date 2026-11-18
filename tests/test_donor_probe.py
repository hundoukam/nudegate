"""Synthetic proof binding and private resource packaging checks; no game assets."""
import base64
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET
import zlib

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('nudegate_donor_probe_build', ROOT / 'tools/build_donor_probe.py')
PROBE = importlib.util.module_from_spec(SPEC)
with mock.patch.object(sys, 'path', [str(ROOT / 'tools'), *sys.path]):
    SPEC.loader.exec_module(PROBE)


class DonorProbeInputsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model = self.root / 'synthetic.GR2'
        self.model.write_bytes(b'Synthetic proof fixture, not a usable game model.')
        self.prepared = self.root / 'prepared.npz'
        self.positions = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]])
        self.triangles = np.array([[0, 1, 2]])
        np.savez(self.prepared, positions=self.positions, triangles=self.triangles)
        self.payload_path = self.root / 'payload.json'
        self.payload = {'schema_version': 1, 'meshes': [{'name': PROBE.MESH,
            'positions': self.positions.tolist(), 'triangles': self.triangles.tolist()}]}
        self.payload_path.write_text(json.dumps(self.payload))
        self.info = {'target_mesh': PROBE.MESH, 'proxy_mesh': PROBE.MESH + '_Cloth_Physics',
                     'physics_selected_positions': 3, 'target_marked_vertices': 3}
        self.set_buffer([[0, 65535, 65535], [1, 2, 65535], [2, 0, 1]])
        bounds = [{'mesh': PROBE.MESH, 'min': [0, 0, 0], 'max': [1, 1, 0]}]
        rig_hash = hashlib.sha256(b'native-rig-state').hexdigest()
        self.export = {'validation_status': 'passed', 'output': str(self.model),
            'output_sha256': PROBE.sha(self.model), 'payload': str(self.payload_path),
            'payload_sha256': PROBE.sha(self.payload_path), 'rig_state_sha256': rig_hash,
            'readback_rig_state_sha256': rig_hash, 'bone_bounds_rebuilt': True,
            'original_binding_names_order_and_aux_exact': True, 'proxy_raw_records_exact': True,
            'mapping': copy.deepcopy(self.info), 'bounds': copy.deepcopy(bounds)}
        self.mapping = {'validation_status': 'passed', 'rig_exact': True,
            'source_gr2': str(self.model), 'source_sha256': PROBE.sha(self.model),
            'mapping': copy.deepcopy(self.info), 'bounds': copy.deepcopy(bounds)}
        self.surface = {'passed': True, 'input_hashes_stable': True,
            'introduced_relative_original_pair_count': 0, 'bridge_involved_pair_count': 0,
            'collapsed_face_count': 0,
            'input_paths': {'prepared': str(self.prepared), 'model': str(self.model)},
            'input_sha256': {'prepared': PROBE.sha(self.prepared), 'model': PROBE.sha(self.model)},
            'checker_sha256': PROBE.sha(ROOT / 'src/nudegate/surface_intersections.py')}

    def set_buffer(self, rows):
        raw = np.asarray(rows, dtype='<u2').tobytes()
        self.info.update(closest_vertices=base64.b64encode(zlib.compress(raw)).decode(),
                         sha256_raw=hashlib.sha256(raw).hexdigest(), nb_closest_vertices=len(raw) // 2)

    def load(self):
        paths = []
        for name, value in [('export', self.export), ('mapping', self.mapping), ('surface', self.surface)]:
            path = self.root / (name + '.json')
            path.write_text(json.dumps(value))
            paths.append(path)
        return PROBE.load_inputs(*paths)

    def synchronize_mapping(self):
        self.export['mapping'] = copy.deepcopy(self.info)
        self.mapping['mapping'] = copy.deepcopy(self.info)

    def use_format_source(self, translation=None):
        raw = self.root / 'raw_source.npz'
        positions = np.concatenate([self.positions, self.positions + 10])
        triangles = np.array([[0, 1, 2], [3, 4, 5]])
        np.savez(raw, positions=positions, triangles=triangles)
        reference = positions[:, [0, 2, 1]] * 1.165
        if translation is not None:
            reference = reference + np.asarray(translation, dtype=np.float64)
        reference = reference.astype('<f4').astype('<f8')
        source_hash = hashlib.sha256(reference.tobytes() + triangles[:, [0, 2, 1]].astype('<i8').tobytes()).hexdigest()
        self.surface['input_paths']['raw_source'] = str(raw)
        self.surface['input_sha256']['raw_source'] = PROBE.sha(raw)
        # Exercise the actual serialized audit's alternative prepared input key.
        self.surface['input_paths']['prepared_npz'] = self.surface['input_paths'].pop('prepared')
        self.surface['input_sha256']['prepared_npz'] = self.surface['input_sha256'].pop('prepared')
        self.surface.update(reference_representation={'axis_order': [0, 2, 1], 'uniform_scale': 1.165,
            'pose_applied': False, 'neck_cut_or_bridge_applied': False,
            'rounding': 'Float64 captured source multiplied by scale, then IEEE Float32 round-to-nearest ties-to-even; promoted to Float64 only for predicates'},
            lossless_actual_buffers_verified=True, actual_positions_bit_equal_float32_prepared=True,
            actual_triangles_exact_prepared=True, actual_model_sha256=PROBE.sha(self.model),
            source_format_geometry_sha256=source_hash, source_format_pair_sha256=hashlib.sha256(b'[]').hexdigest(),
            format_matched_source_pairs=[], format_matched_source_pair_count=0,
            introduced_relative_format_matched_source_pair_count=0, bridge_pair_count=0,
            actual_collapsed_face_count=0)
        if translation is not None:
            self.surface['reference_representation'].update(translation_bg3=translation,
                rounding=PROBE.PLACED_SOURCE_ROUNDING)

    def test_consistent_synthetic_proofs_are_accepted_without_game_assets(self):
        export, mapping, surface = self.load()
        self.assertEqual(export['output_sha256'], PROBE.sha(self.model))
        self.assertEqual(mapping['mapping']['nb_closest_vertices'], 9)
        self.assertTrue(surface['passed'])

    def test_explicit_unposed_format_source_is_accepted_with_independent_hashes(self):
        self.use_format_source()
        # The separately retained Double result does not define the format baseline.
        self.surface['introduced_relative_original_pair_count'] = 2
        _, _, surface = self.load()
        self.assertFalse(surface['reference_representation']['pose_applied'])
        self.assertEqual(surface['format_matched_source_pair_count'], 0)

    def test_explicit_placed_source_uses_scale_then_translation_then_float32(self):
        self.use_format_source(translation=[.1, -.2, .3])
        self.load()
        self.surface['reference_representation']['translation_bg3'][1] = -.21
        with self.assertRaisesRegex(ValueError, 'source coordinates'):
            self.load()

    def test_placed_source_requires_finite_translation_and_explicit_operation_order(self):
        self.use_format_source(translation=[.1, -.2, .3])
        representation = self.surface['reference_representation']
        for value in (None, [0, 0], [0, 0, True], [0, 0, float('nan')]):
            with self.subTest(value=value):
                representation['translation_bg3'] = value
                with self.assertRaisesRegex(ValueError, 'explicit unposed source'):
                    self.load()
        representation['translation_bg3'] = [.1, -.2, .3]
        representation['rounding'] = PROBE.SOURCE_ROUNDING
        with self.assertRaisesRegex(ValueError, 'explicit unposed source'):
            self.load()

    def test_format_source_rejects_pose_neck_axes_rounding_or_invalid_scale(self):
        self.use_format_source()
        representation = self.surface['reference_representation']
        for key, value in [('pose_applied', True), ('pose_applied', 0),
                           ('neck_cut_or_bridge_applied', True), ('axis_order', [0, 1, 2]),
                           ('rounding', 'unspecified'), ('uniform_scale', 0),
                           ('uniform_scale', True), ('uniform_scale', float('inf'))]:
            with self.subTest(key=key, value=value):
                original = representation[key]
                representation[key] = value
                with self.assertRaisesRegex(ValueError, 'explicit unposed source'):
                    self.load()
                representation[key] = original

    def test_format_source_requires_actual_lossless_buffer_and_model_proofs(self):
        self.use_format_source()
        for key, value in [('lossless_actual_buffers_verified', False),
                           ('actual_positions_bit_equal_float32_prepared', False),
                           ('actual_triangles_exact_prepared', False), ('actual_model_sha256', 'changed'),
                           ('source_format_geometry_sha256', ''), ('source_format_pair_sha256', '')]:
            with self.subTest(key=key):
                original = self.surface[key]
                self.surface[key] = value
                with self.assertRaisesRegex(ValueError, 'explicit unposed source'):
                    self.load()
                self.surface[key] = original

    def test_format_source_hash_binds_raw_unposed_coordinates_and_scale(self):
        self.use_format_source()
        self.surface['reference_representation']['uniform_scale'] = 1.2
        with self.assertRaisesRegex(ValueError, 'source coordinates'):
            self.load()
        self.surface['reference_representation']['uniform_scale'] = 1.165
        self.surface['source_format_geometry_sha256'] = 'a' * 64
        with self.assertRaisesRegex(ValueError, 'source coordinates'):
            self.load()

    def test_format_source_requires_original_source_path_and_unchanged_bytes(self):
        self.use_format_source()
        raw = self.surface['input_paths'].pop('raw_source')
        raw_hash = self.surface['input_sha256'].pop('raw_source')
        with self.assertRaisesRegex(ValueError, 'hashed original raw source'):
            self.load()
        self.surface['input_paths']['raw_source'] = raw
        self.surface['input_sha256']['raw_source'] = raw_hash
        with Path(raw).open('ab') as output:
            output.write(b'changed captured source')
        with self.assertRaisesRegex(ValueError, 'audit inputs changed'):
            self.load()

    def test_format_pair_hash_and_count_cannot_be_tampered(self):
        self.use_format_source()
        for key, value in [('source_format_pair_sha256', 'a' * 64),
                           ('format_matched_source_pair_count', 1),
                           ('format_matched_source_pairs', [[0, 1]]),
                           ('format_matched_source_pairs', [[0, 1], [0, 1]])]:
            with self.subTest(key=key, value=value):
                original = self.surface[key]
                self.surface[key] = value
                with self.assertRaisesRegex(ValueError, 'source pairs'):
                    self.load()
                self.surface[key] = original

    def test_format_branch_still_rejects_new_bridge_or_collapsed_pairs(self):
        self.use_format_source()
        for key in ('introduced_relative_format_matched_source_pair_count', 'bridge_pair_count',
                    'actual_collapsed_face_count'):
            with self.subTest(key=key):
                self.surface[key] = 1
                with self.assertRaisesRegex(ValueError, 'global rest-surface'):
                    self.load()
                self.surface[key] = 0

    def test_model_and_payload_bytes_remain_bound_to_export(self):
        self.model.write_bytes(b'changed model bytes')
        with self.assertRaisesRegex(ValueError, 'Model bytes'):
            self.load()
        self.export['output_sha256'] = self.mapping['source_sha256'] = PROBE.sha(self.model)
        self.surface['input_sha256']['model'] = PROBE.sha(self.model)
        self.payload_path.write_text(self.payload_path.read_text() + '\n')
        with self.assertRaisesRegex(ValueError, 'payload changed'):
            self.load()

    def test_mapping_cannot_claim_another_model_or_rig(self):
        other = self.root / 'other.GR2'
        other.write_bytes(self.model.read_bytes())
        self.mapping['source_gr2'] = str(other)
        with self.assertRaisesRegex(ValueError, 'Model bytes'):
            self.load()
        self.mapping['source_gr2'] = str(self.model)
        self.mapping['rig_exact'] = False
        with self.assertRaisesRegex(ValueError, 'native rig'):
            self.load()

    def test_unpassed_or_unbound_global_audit_is_rejected(self):
        for key, value in [('passed', False), ('input_hashes_stable', False),
                           ('introduced_relative_original_pair_count', 1),
                           ('bridge_involved_pair_count', 1), ('collapsed_face_count', 1)]:
            with self.subTest(key=key):
                original = self.surface[key]
                self.surface[key] = value
                with self.assertRaisesRegex(ValueError, 'global rest-surface'):
                    self.load()
                self.surface[key] = original
        del self.surface['input_paths']['model']
        del self.surface['input_sha256']['model']
        with self.assertRaisesRegex(ValueError, 'actual serialized GR2'):
            self.load()

    def test_audit_npz_or_checker_changes_are_rejected(self):
        self.surface['checker_sha256'] = 'changed-checker'
        with self.assertRaisesRegex(ValueError, 'checker changed'):
            self.load()
        self.surface['checker_sha256'] = PROBE.sha(ROOT / 'src/nudegate/surface_intersections.py')
        with self.prepared.open('ab') as output:
            output.write(b'changed audit input')
        with self.assertRaisesRegex(ValueError, 'audit inputs changed'):
            self.load()

    def test_payload_positions_and_triangle_order_match_prepared_geometry(self):
        for field, replacement in [('positions', [[0, 0, .01], [1, 0, 0], [0, 1, 0]]),
                                   ('triangles', [[0, 2, 1]])]:
            with self.subTest(field=field):
                original = self.payload['meshes'][0][field]
                self.payload['meshes'][0][field] = replacement
                self.payload_path.write_text(json.dumps(self.payload))
                self.export['payload_sha256'] = PROBE.sha(self.payload_path)
                with self.assertRaisesRegex(ValueError, 'audited prepared body'):
                    self.load()
                self.payload['meshes'][0][field] = original

    def test_changed_mapping_or_bounds_cannot_disagree_with_export(self):
        self.mapping['mapping']['sha256_raw'] = 'changed-buffer'
        with self.assertRaises(ValueError):
            self.load()
        self.mapping['mapping'] = copy.deepcopy(self.info)
        raw = np.asarray([[1, 65535, 65535], [1, 2, 65535], [2, 0, 1]], dtype='<u2').tobytes()
        self.mapping['mapping'].update(closest_vertices=base64.b64encode(zlib.compress(raw)).decode(),
                                       sha256_raw=hashlib.sha256(raw).hexdigest())
        with self.assertRaises(ValueError):
            self.load()
        self.mapping['mapping'] = copy.deepcopy(self.info)
        self.mapping['bounds'][0]['max'][0] = 99
        with self.assertRaises(ValueError):
            self.load()

    def test_mapping_hash_count_and_mesh_gates_are_independent(self):
        for field, value in [('sha256_raw', 'wrong-hash'), ('nb_closest_vertices', 6),
                             ('target_marked_vertices', 4), ('target_mesh', 'other-mesh'),
                             ('physics_selected_positions', 0)]:
            with self.subTest(field=field):
                original = self.info[field]
                self.info[field] = value
                self.synchronize_mapping()
                with self.assertRaisesRegex(ValueError, 'Invalid cloth mapping'):
                    self.load()
                self.info[field] = original

    def test_mapping_requires_present_in_range_physics_points(self):
        for rows in [[[65535, 65535, 65535], [1, 2, 65535], [2, 0, 1]],
                     [[3, 65535, 65535], [1, 2, 65535], [2, 0, 1]]]:
            with self.subTest(rows=rows):
                self.set_buffer(rows)
                self.synchronize_mapping()
                with self.assertRaisesRegex(ValueError, 'missing physics points'):
                    self.load()

    def test_corrupt_base64_or_compressed_mapping_is_rejected(self):
        for encoded in ('not-base64!', base64.b64encode(b'not-zlib').decode()):
            with self.subTest(encoded=encoded):
                self.info['closest_vertices'] = encoded
                self.synchronize_mapping()
                with self.assertRaises((ValueError, zlib.error)):
                    self.load()

    def test_missing_first_neighbor_cannot_be_followed_by_a_valid_index(self):
        self.set_buffer([[65535, 0, 65535], [1, 2, 65535], [2, 0, 1]])
        self.synchronize_mapping()
        with self.assertRaisesRegex(ValueError, 'physics points'):
            self.load()

    def test_unused_neighbor_sentinels_must_be_trailing(self):
        self.set_buffer([[0, 65535, 1], [1, 2, 65535], [2, 0, 1]])
        self.synchronize_mapping()
        with self.assertRaisesRegex(ValueError, 'physics points'):
            self.load()


class DonorProbeResourceTests(unittest.TestCase):
    def test_creation_roundtrip_normalizes_only_nonstored_region_alias(self):
        expected = ET.ElementTree(ET.fromstring('<save><region id="CharacterCreationPresets"><node id="root"><attribute id="value" value="original"/></node></region></save>'))
        decoded = copy.deepcopy(expected)
        decoded.find('./region').set('id', 'root')
        self.assertEqual(PROBE.document_regions(expected), PROBE.document_regions(decoded))
        decoded.find('./region/node/attribute').set('value', 'changed')
        self.assertNotEqual(PROBE.document_regions(expected), PROBE.document_regions(decoded))

    def creation_fixture(self):
        private_root = '11111111-1111-4111-8111-111111111111'
        private_visual = '22222222-2222-4222-8222-222222222222'
        private_body = '33333333-3333-4333-8333-333333333333'
        original_root = '44444444-4444-4444-8444-444444444444'
        preset = '55555555-5555-4555-8555-555555555555'
        tav = {'templates': [{'private_template_id': private_root, 'private_visual_id': private_visual,
            'original_template_id': original_root, 'original_body_set_visual': PROBE.SOURCE_BODY,
            'private_body_set_visual': private_body, 'body_type': '1', 'body_shape': '0', 'review': {'adult': True}}],
            'presets': [{'preset_id': preset, 'private_template_id': private_root}]}
        documents = {}
        for label, attributes in {
            'templates': {'MapKey': private_root, 'CharacterVisualResourceID': private_visual},
            'visuals': {'ID': private_visual, 'BodySetVisual': private_body},
            'presets': {'UUID': preset, 'RootTemplate': private_root, 'BodyType': '1', 'BodyShape': '0'},
        }.items():
            root = ET.fromstring('<save><region><node><children><node/></children></node></region></save>')
            record = root.find('./region/node/children/node')
            for key, value in attributes.items():
                ET.SubElement(record, 'attribute', {'id': key, 'value': value})
            documents[label] = ET.ElementTree(root)
        return tav, documents, private_body

    def test_compiled_creation_chain_uses_only_private_roots_visuals_and_body(self):
        tav, documents, body = self.creation_fixture()
        result = PROBE.verify_creation_isolation(tav, documents, body)
        self.assertEqual(result['original_root_overrides'], 0)
        self.assertEqual(result['selected_generic_presets'], 1)
        self.assertEqual(result['private_roots'], 1)

    def test_compiled_creation_cannot_add_an_original_root_or_change_body_chain(self):
        for failure in ('original_root', 'wrong_body', 'preset_root', 'extra_root'):
            with self.subTest(failure=failure):
                tav, documents, body = self.creation_fixture()
                if failure == 'original_root':
                    record = documents['templates'].find('./region/node/children/node')
                    PROBE.set_attr(record, 'MapKey', tav['templates'][0]['original_template_id'])
                elif failure == 'wrong_body':
                    record = documents['visuals'].find('./region/node/children/node')
                    PROBE.set_attr(record, 'BodySetVisual', PROBE.SOURCE_BODY)
                elif failure == 'preset_root':
                    record = documents['presets'].find('./region/node/children/node')
                    PROBE.set_attr(record, 'RootTemplate', tav['templates'][0]['original_template_id'])
                else:
                    children = documents['templates'].find('./region/node/children')
                    original = copy.deepcopy(children[0])
                    PROBE.set_attr(original, 'MapKey', tav['templates'][0]['original_template_id'])
                    children.append(original)
                with self.assertRaises(ValueError):
                    PROBE.verify_creation_isolation(tav, documents, body)

    def test_compiled_creation_rejects_missing_adult_review_or_strong_body(self):
        for key, value in [('body_shape', '1'), ('body_type', '0'), ('review', {'adult': False})]:
            with self.subTest(key=key):
                tav, documents, body = self.creation_fixture()
                tav['templates'][0][key] = value
                with self.assertRaisesRegex(ValueError, 'reviewed adult normal-human'):
                    PROBE.verify_creation_isolation(tav, documents, body)

    def test_source_visualbank_pin_rejects_unreviewed_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'source.lsx'
            path.write_bytes(b'synthetic source bank')
            with self.assertRaisesRegex(ValueError, 'reviewed matched native resource'):
                PROBE.verify_source_bank(path)
            with mock.patch.object(PROBE, 'SOURCE_BANK_SHA256', PROBE.sha(path)):
                self.assertEqual(PROBE.verify_source_bank(path), PROBE.sha(path))

    def test_private_clone_preserves_solver_object_ids_and_other_native_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'native.lsx'
            tree = ET.ElementTree(ET.fromstring('<save><region id="VisualBank"><node id="VisualBank"><children/></node></region></save>'))
            container = tree.find('./region/node/children')
            source = ET.SubElement(container, 'node', {'id': 'Resource'})
            values = {'ID': PROBE.SOURCE_BODY, 'Name': 'native', 'SourceFile': 'Public/Native/HUM.GR2',
                      'Template': 'Public/Native/HUM.HUM_F_NKD_Body_A_Mesh',
                      'BoundsMin': '-1 0 -1', 'BoundsMax': '1 2 1', 'SkeletonResource': 'native-rig',
                      'ObjectID': 'native-body-object', 'MaterialID': 'native-material'}
            for key, value in values.items():
                ET.SubElement(source, 'attribute', {'id': key, 'type': 'FixedString', 'value': value})
            children = ET.SubElement(source, 'children')
            cloth = ET.SubElement(children, 'node', {'id': 'ClothParams'})
            for key, value in {'ObjectID': 'native-proxy-object', 'Gravity': '1', 'SolverIterations': '8'}.items():
                ET.SubElement(cloth, 'attribute', {'id': key, 'value': value})
            high = ET.SubElement(children, 'node', {'id': 'ClothHighResInfo'})
            native_buffer = base64.b64encode(zlib.compress(np.asarray([0, 65535, 65535], dtype='<u2').tobytes())).decode()
            ET.SubElement(high, 'attribute', {'id': 'ClosestVertices', 'value': native_buffer})
            ET.SubElement(high, 'attribute', {'id': 'NbClosestVertices', 'value': '3'})
            tree.write(path)
            before = PROBE.semantic(source)
            new_buffer = base64.b64encode(zlib.compress(np.asarray([1, 2, 65535] * 3, dtype='<u2').tobytes())).decode()
            mapping = {'mapping': {'closest_vertices': new_buffer, 'nb_closest_vertices': 9},
                       'bounds': [{'mesh': PROBE.MESH, 'min': [-.2, 0, -.3], 'max': [.2, 1.6, .3]}]}
            result, clone, relative, identifier = PROBE.private_resource(path, mapping, 'donor_test')
            self.assertNotEqual(identifier, PROBE.SOURCE_BODY)
            self.assertTrue(relative.as_posix().startswith('Public/NudegateDonorProbe/Assets/donor_test/'))
            self.assertEqual(relative.name, 'HUM.GR2')
            self.assertEqual(PROBE.semantic(clone.find("children/node[@id='ClothParams']")),
                             PROBE.semantic(source.find("children/node[@id='ClothParams']")))
            for key in ('SkeletonResource', 'ObjectID', 'MaterialID'):
                self.assertEqual(PROBE.attrs(clone)[key], values[key])
            self.assertTrue(PROBE.attrs(clone)['Template'].endswith('.HUM_F_NKD_Body_A_Mesh'))
            self.assertEqual(len(result.findall(".//node[@id='Resource']")), 1)
            # Restore exactly the documented replacement attributes, then compare every remaining field.
            changed = {'ID', 'Name', 'SourceFile', 'Template', 'BoundsMin', 'BoundsMax',
                       'ClosestVertices', 'NbClosestVertices'}
            original_attrs = {element.attrib['id']: element.attrib for element in source.iter('attribute')}
            for element in clone.iter('attribute'):
                key = element.attrib['id']
                if key in changed:
                    element.attrib.clear()
                    element.attrib.update(original_attrs[key])
            self.assertEqual(PROBE.semantic(clone), before)
            self.assertEqual(PROBE.semantic(source), before)


if __name__ == '__main__':
    unittest.main()
