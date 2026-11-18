"""Collection merging, independent distribution, and isolated style packaging."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET


SPEC = importlib.util.spec_from_file_location('nudegate_variety_build', Path(__file__).resolve().parents[1] / 'tools/build.py')
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)

M1 = '11111111-1111-4111-8111-111111111111'
M2 = '22222222-2222-4222-8222-222222222222'
SOFT1 = '33333333-3333-4333-8333-333333333333'
SOFT2 = '44444444-4444-4444-8444-444444444444'
STYLE_SOFT = '55555555-5555-4555-8555-555555555555'
STYLE_DEFINED = '66666666-6666-4666-8666-666666666666'


def collection(name, variant_id):
    result = {'schema_version':1, 'collection_id':name, 'families':[{
        'id':'human', 'label':'Human', 'original_visual_ids':['body'], 'source_sha256':'source-sha',
        'vertices':3, 'triangles':1, 'source_snapshot':{
            'topology_id':'topology', 'position_sha256':'positions', 'controller_sha256':'controller', 'uv_sha256':'uv'},
        'variants':[{'id':variant_id, 'label':variant_id}]}]}
    if variant_id.startswith('exp_'):
        base = variant_id.split('_')[1]
        percent = int(variant_id.rsplit('_b',1)[1])
        result['families'][0]['variants'][0].update(base_body_id=base,breast_percent=percent)
        result.update(build_status='complete',completed_variant_count=1,
                      requested_grid={'families':['human'],'profile_ids':[base],
                                      'percentages':[percent],'expected_variants':1})
    return result


def candidate(base, percent):
    return {'variant_id':f'exp_{base}_b{percent:03}', 'private_visual_id':f'{base}-{percent}', 'family_id':'human',
            'collection_id':'expansion-v0.3', 'base_body_id':base, 'breast_percent':percent, 'skin_style':'soft'}


def bank(identifier, value):
    root = ET.Element('save')
    inner = ET.SubElement(ET.SubElement(ET.SubElement(root, 'region', {'id':'MaterialBank'}),
                                      'node', {'id':'MaterialBank'}), 'children')
    resource = ET.SubElement(inner, 'node', {'id':'Resource'})
    ET.SubElement(resource, 'attribute', {'id':'ID', 'value':identifier})
    ET.SubElement(resource, 'attribute', {'id':'Value', 'value':value})
    return ET.ElementTree(root)


class VarietyCollectionTests(unittest.TestCase):
    def test_merge_retains_originals_and_metadata_without_mutating_sources(self):
        original, new = collection('original-v0.2', 'plush'), collection('expansion-v0.3', 'exp_curvy_b000')
        new['families'][0]['variants'][0].update(base_body_id='curvy', breast_percent=0, skin_style='soft')
        before = copy.deepcopy(original)
        merged = BUILD.merge_body_manifests([original, new])
        self.assertEqual(original, before)
        variants = merged['families'][0]['variants']
        self.assertEqual([item['id'] for item in variants], ['plush', 'exp_curvy_b000'])
        self.assertEqual(variants[0]['collection_id'], 'original-v0.2')
        self.assertEqual(variants[0]['base_body_id'], 'plush')
        self.assertEqual(variants[1]['skin_style'], 'soft')

    def test_changed_source_pins_and_duplicate_variants_are_rejected(self):
        original = collection('original-v0.2', 'plush')
        for failure in ('source', 'topology', 'original_ids', 'variant'):
            with self.subTest(failure=failure):
                new = collection('expansion-v0.3', 'exp_curvy_b000')
                family = new['families'][0]
                if failure == 'source': family['source_sha256'] = 'different'
                elif failure == 'topology': family['source_snapshot']['topology_id'] = 'different'
                elif failure == 'original_ids': family['original_visual_ids'] = ['another-body']
                else: family['variants'][0]['id'] = 'plush'
                with self.assertRaises(ValueError): BUILD.merge_body_manifests([original, new])

    def test_resource_map_receives_variant_metadata(self):
        manifest = collection('expansion-v0.3', 'exp_curvy_b050')
        variant = manifest['families'][0]['variants'][0]
        variant.update(collection_id='expansion-v0.3', base_body_id='curvy', breast_percent=50, skin_style='soft')
        entry = {'family_id':'human', 'variant_id':'exp_curvy_b050', 'private_visual_id':'private'}
        resources = {'variants':[copy.deepcopy(entry)], 'resource_map':{'body':[copy.deepcopy(entry)]}}
        BUILD.annotate_body_resources(resources, manifest)
        for item in [resources['variants'][0], resources['resource_map']['body'][0]]:
            self.assertEqual(item['breast_percent'], 50)
            self.assertEqual(item['base_body_id'], 'curvy')

    def test_legacy_selection_is_byte_for_byte_algorithm_compatible(self):
        candidates = [{'variant_id':name, 'private_visual_id':name, 'family_id':'human'} for name in BUILD.LEGACY_BODY_WEIGHTS]
        ordered = sorted(candidates, key=lambda item:item['variant_id'])
        for number in range(100):
            seed = f'character-{number}'
            bucket = int.from_bytes(hashlib.sha256(('nudegate-body-v1:' + seed).encode()).digest()[:8], 'big') % 100
            expected = None
            for item in ordered:
                bucket -= BUILD.LEGACY_BODY_WEIGHTS[item['variant_id']]
                if bucket < 0:
                    expected = item['variant_id']; break
            actual, report = BUILD.select_body_candidate(list(reversed(candidates)), seed)
            self.assertEqual(actual['variant_id'], expected)
            self.assertEqual(report['algorithm'], 'legacy-v1')

    def test_breast_combo_count_does_not_bias_base_selection(self):
        sparse = [candidate('curvy', 0), candidate('chubby', 0),
                  {'variant_id':'plush', 'private_visual_id':'old-plush', 'family_id':'human'}]
        expanded = sparse + [candidate('curvy', percent) for percent in (50, 100)]
        for number in range(200):
            seed = f'character-{number}'
            old, _ = BUILD.select_body_candidate(sparse, seed)
            new, _ = BUILD.select_body_candidate(list(reversed(expanded)), seed)
            self.assertEqual(old.get('base_body_id', old['variant_id']), new.get('base_body_id', new['variant_id']))
            self.assertIn(new['variant_id'], {item['variant_id'] for item in expanded})

    def test_invalid_or_unbuilt_metadata_is_refused(self):
        invalid = candidate('curvy', 50)
        invalid['breast_percent'] = 100
        with self.assertRaises(ValueError): BUILD.select_body_candidate([invalid], 'character')

    def test_current_release_cap_rejects_200_candidates_and_stale_manifests(self):
        with self.assertRaises(ValueError):
            BUILD.select_body_candidate([candidate('curvy',200)],'character')
        with self.assertRaises(ValueError):
            BUILD.merge_body_manifests([collection('expansion-v0.3','exp_curvy_b200')])

    def test_capped_grid_retains_every_requested_0_50_100_combo(self):
        manifest = collection('expansion-v0.3','exp_curvy_b000')
        variants = manifest['families'][0]['variants']
        for percent in (50,100):
            variants.append({'id':f'exp_curvy_b{percent:03}','label':str(percent),
                             'base_body_id':'curvy','breast_percent':percent})
        manifest['requested_grid'].update(percentages=[0,50,100],expected_variants=3)
        manifest['completed_variant_count'] = 3
        merged = BUILD.merge_body_manifests([manifest])
        self.assertEqual(merged['completed_variant_count'],3)
        palette = [candidate('curvy',p) for p in (0,50,100)]
        selected = {BUILD.select_body_candidate(palette,f'cap-{i}')[0]['breast_percent'] for i in range(200)}
        self.assertEqual(selected,{0,50,100})

    def test_partial_or_incomplete_requested_grid_cannot_be_packaged(self):
        for error in ('in_progress','missing_grid','missing_combo'):
            with self.subTest(error=error):
                manifest = collection('expansion-v0.3','exp_curvy_b000')
                if error=='in_progress': manifest['build_status']='in_progress'
                elif error=='missing_grid': del manifest['requested_grid']
                else:
                    manifest['requested_grid']['percentages']=[0,50]
                    manifest['requested_grid']['expected_variants']=2
                with self.assertRaises(ValueError): BUILD.merge_body_manifests([manifest])

    def test_completed_batches_keep_their_exact_requested_grids(self):
        first = collection('expansion-v0.3','exp_curvy_b000')
        second = collection('expansion-v0.3','exp_curvy_b050')
        merged = BUILD.merge_body_manifests([first,second])
        self.assertEqual(merged['build_status'],'complete')
        self.assertEqual(merged['completed_variant_count'],2)
        self.assertEqual(len(merged['requested_grids']),2)
        self.assertEqual(len(BUILD.validate_expansion_request(merged)),2)


class VarietySkinTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def resources(self):
        path = self.root / 'body.lsx'
        root = ET.Element('save')
        children = ET.SubElement(ET.SubElement(ET.SubElement(root, 'region'), 'node'), 'children')
        variants = []
        for name, original, current, style in [('plush', M1, SOFT1, None), ('exp_curvy_b000', M1, SOFT1, 'soft'),
                                                ('exp_pear_b000', M2, SOFT2, 'soft')]:
            private = name + '-private'
            node = ET.SubElement(children, 'node', {'id':'Resource'})
            ET.SubElement(node, 'attribute', {'id':'ID', 'value':private})
            obj = ET.SubElement(ET.SubElement(node, 'children'), 'node', {'id':'Objects'})
            ET.SubElement(obj, 'attribute', {'id':'MaterialID', 'value':current})
            entry = {'family_id':'human', 'variant_id':name, 'private_visual_id':private,
                     'material_ids':[current], 'original_material_ids':[original]}
            if style: entry['skin_style'] = style
            variants.append(entry)
        ET.ElementTree(root).write(path)
        return {'outputs':{'visuals':str(path)}, 'variants':variants,
                'resource_map':{'body':[{'family_id':'human','variant_id':item['variant_id'],
                                        'private_visual_id':item['private_visual_id']} for item in variants]}}

    def test_styles_leave_legacy_unchanged_and_report_normal_family_fallback(self):
        resources = self.resources()
        legacy = copy.deepcopy(resources['variants'][0])
        styles = {'material_map':{M1:{'soft':STYLE_SOFT, 'defined':STYLE_DEFINED}}}
        application = BUILD.apply_skin_styles(resources, self.root, styles, {'material_map':{M1:SOFT1, M2:SOFT2}})
        self.assertEqual(resources['variants'][0], legacy)
        self.assertEqual(resources['variants'][1]['material_ids'], [STYLE_SOFT])
        self.assertEqual(resources['variants'][2]['material_ids'], [SOFT2])
        self.assertEqual(resources['variants'][2]['skin_style_applied'], 'legacy_soft_fallback')
        self.assertEqual(application['legacy_resources_unchanged'], 1)
        self.assertTrue(application['variants'][1]['materials'][0]['fallback'])

    def package_fixture(self):
        package = self.root / 'styles'
        files = {
            'Mods/Nudegate/ScriptExtender/Config.json':json.dumps({'RequiredVersion':12,'ModTable':'Nudegate','FeatureFlags':[]}),
            'Mods/Nudegate/ScriptExtender/VirtualTextures.json':json.dumps({'Mappings':[{'GTexName':'new','GTS':'Public/Nudegate/new.gts'}]}),
            'Public/Nudegate/new.gts':'validated-gts',
            'Public/Nudegate/styles.lsf':'validated-bank',
        }
        records = []
        for name, content in files.items():
            path = package / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content.encode())
            records.append({'path':name, 'bytes':len(content.encode()), 'sha256':hashlib.sha256(content.encode()).hexdigest()})
        report = {'schema_version':1, 'material_map':{M1:{'soft':STYLE_SOFT,'defined':STYLE_DEFINED}},
                  'files':records, 'validation':{'lslib_vt_validation':'passed','resource_lsf_roundtrip':'passed'}}
        report_path = self.root / 'styles.json'
        report_path.write_text(json.dumps(report))
        return package, report_path

    def test_style_files_are_hash_bound_and_se_config_merges(self):
        package, report_path = self.package_fixture()
        styles = BUILD.load_skin_style_package(package, report_path)
        stage = self.root / 'stage'
        config = stage / 'Mods/Nudegate/ScriptExtender/Config.json'
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({'RequiredVersion':15,'ModTable':'Nudegate','FeatureFlags':['Lua']}))
        BUILD.copy_skin_style_package(package, stage, styles, Path('not-needed'))
        self.assertEqual(json.loads(config.read_text())['RequiredVersion'], 15)
        self.assertEqual(json.loads(config.read_text())['FeatureFlags'], ['Lua'])
        (package / 'Public/Nudegate/new.gts').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'changed after validation'):
            BUILD.load_skin_style_package(package, report_path)

    def test_resource_bank_collisions_merge_without_overriding_legacy(self):
        merged = BUILD.merge_resource_documents(bank(SOFT1, 'legacy'), bank(STYLE_SOFT, 'new'))
        values = {BUILD.attrs(node)['ID']:BUILD.attrs(node)['Value'] for node in merged.findall('./region/node/children/node')}
        self.assertEqual(values, {SOFT1:'legacy', STYLE_SOFT:'new'})
        with self.assertRaisesRegex(ValueError, 'override an existing private resource'):
            BUILD.merge_resource_documents(bank(SOFT1, 'legacy'), bank(SOFT1, 'different'))


if __name__ == '__main__':
    unittest.main()
