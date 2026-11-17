import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

SPEC = importlib.util.spec_from_file_location('nudegate_build_tools', Path(__file__).resolve().parents[1] / 'tools/build.py')
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)


class BodyAssignmentTests(unittest.TestCase):
    def fixture(self, root):
        path = root / 'Public/Nudegate/Content/[PAK]_CharacterVisuals/_merged.lsx'
        path.parent.mkdir(parents=True)
        document = ET.Element('save')
        children = ET.SubElement(ET.SubElement(ET.SubElement(document, 'region'), 'node'), 'children')
        entries = []
        for identity, body in [('normal', 'supported'), ('vanity', 'supported'), ('other', 'unknown')]:
            node = ET.SubElement(children, 'node')
            ET.SubElement(node, 'attribute', {'id':'ID','value':identity})
            ET.SubElement(node, 'attribute', {'id':'BodySetVisual','value':body})
            entries.append({'template_id':identity,'private_visual_id':identity,'body_set_visual':body})
        ET.ElementTree(document).write(path)
        return {'templates':entries}, {'adults':[{'template_id':e['template_id'],'body_seed':'same-character'} for e in entries]}

    def test_identity_aliases_share_profile_and_unknown_body_is_retained(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report, catalog = self.fixture(root)
            resources = {'resource_map':{'supported':[
                {'variant_id':'lean','private_visual_id':'lean-private','family_id':'family'},
                {'variant_id':'full','private_visual_id':'full-private','family_id':'family'}]}}
            BUILD.assign_body_studies(root, report, catalog, resources)
            self.assertEqual(report['templates'][0]['body_set_visual'], report['templates'][1]['body_set_visual'])
            self.assertEqual(report['templates'][2]['body_set_visual'], 'unknown')
            self.assertNotIn('body_study', report['templates'][2])

    def test_palette_order_does_not_change_stable_selection(self):
        selected = []
        for reverse in (False, True):
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                report, catalog = self.fixture(root)
                palette = [{'variant_id':name,'private_visual_id':name,'family_id':'family'} for name in ('lean','full','balanced')]
                resources = {'resource_map':{'supported':list(reversed(palette)) if reverse else palette}}
                BUILD.assign_body_studies(root, report, catalog, resources)
                selected.append(report['templates'][0]['body_set_visual'])
        self.assertEqual(selected[0], selected[1])

    def test_ambiguous_compatible_palette_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report, catalog = self.fixture(root)
            choice = {'variant_id':'lean','private_visual_id':'private','family_id':'family'}
            with self.assertRaises(ValueError):
                BUILD.assign_body_studies(root, report, catalog, {'resource_map':{'supported':[choice,copy.deepcopy(choice)]}})
