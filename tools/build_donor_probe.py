"""Package a validated donor/cloth experiment for private adult Tav creation.

This creates local artifacts only. It does not install a mod or alter saves,
NPC roots, the game installation or the active load order.
"""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sys
import tempfile
from uuid import UUID, uuid5
import xml.etree.ElementTree as ET
import zlib

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tools')]
from nudegate.core import Database, attrs
from nudegate.tav_presets import create_tav_presets
from nudegate.surface_intersections import geometry_fingerprint
from build import run

MODULE = 'NudegateDonorProbe'
SOURCE_BODY = 'db6e5918-8514-4dcc-8363-e8fd3c50cce5'
MESH = 'HUM_F_NKD_Body_A_Mesh'
NAMESPACE = UUID('ed2625b7-64d7-57dc-ad55-93a7b9f38160')
SOURCE_BANK_SHA256 = '301b79e3215173032f0e7e8f2c4660a7a3768847a50c3829e75230c097d3882c'
SOURCE_ROUNDING = 'Float64 captured source multiplied by scale, then IEEE Float32 round-to-nearest ties-to-even; promoted to Float64 only for predicates'
PLACED_SOURCE_ROUNDING = 'Float64 captured source multiplied by scale, then translation_bg3 added, then IEEE Float32 round-to-nearest ties-to-even; promoted to Float64 only for predicates'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_source_bank(path):
    actual = sha(path)
    if actual != SOURCE_BANK_SHA256:
        raise ValueError('Source VisualBank changed from the reviewed matched native resource')
    return actual


def verify_format_source(surface):
    """Bind the stated unposed source representation to its captured coordinates.

    This verifies provenance and report consistency, not a replacement search.
    The separately recorded checker report supplies the full intersection search.
    """
    paths = surface['input_paths']
    if 'raw_source' not in paths:
        raise ValueError('Format-matched source requires the hashed original raw source')
    with np.load(paths['raw_source'], allow_pickle=False) as raw:
        positions = np.asarray(raw['positions'], dtype=np.float64)
        triangles = np.asarray(raw['triangles'])
    if (positions.ndim != 2 or positions.shape[1] != 3 or not np.isfinite(positions).all()
            or triangles.ndim != 2 or triangles.shape[1] != 3
            or not np.issubdtype(triangles.dtype, np.integer)
            or np.any(triangles < 0) or np.any(triangles >= len(positions))):
        raise ValueError('Invalid captured source geometry')
    scale = surface['reference_representation']['uniform_scale']
    reference = positions[:, [0, 2, 1]] * scale
    if 'translation_bg3' in surface['reference_representation']:
        # Keep this operation order identical to the independent source audit.
        reference = reference + np.asarray(surface['reference_representation']['translation_bg3'], dtype=np.float64)
    reference = reference.astype('<f4').astype(np.float64)
    source_triangles = triangles[:, [0, 2, 1]]
    if (not np.isfinite(reference).all()
            or geometry_fingerprint(reference, source_triangles) != surface['source_format_geometry_sha256']):
        raise ValueError('Format-matched source coordinates do not match their recorded SHA256')
    pairs = surface.get('format_matched_source_pairs')
    if (not isinstance(pairs, list)
            or any(not isinstance(pair, list) or len(pair) != 2
                   or any(type(index) is not int for index in pair)
                   or not 0 <= pair[0] < pair[1] < len(source_triangles) for pair in pairs)):
        raise ValueError('Invalid format-matched source pair set')
    canonical = sorted(tuple(pair) for pair in pairs)
    if (len(set(canonical)) != len(canonical)
            or surface.get('format_matched_source_pair_count') != len(canonical)
            or hashlib.sha256(json.dumps(canonical, separators=(',', ':')).encode('ascii')).hexdigest()
               != surface['source_format_pair_sha256']):
        raise ValueError('Format-matched source pairs do not match their recorded SHA256/count')


def load_inputs(export_report, mapping_report, surface_audit):
    export = json.loads(Path(export_report).read_text())
    mapping = json.loads(Path(mapping_report).read_text())
    surface = json.loads(Path(surface_audit).read_text())
    if (export.get('validation_status') != 'passed'
            or mapping.get('validation_status') != 'passed'
            or mapping.get('rig_exact') is not True
            or export.get('rig_state_sha256') != export.get('readback_rig_state_sha256')
            or not export.get('rig_state_sha256')):
        raise ValueError('Export and mapping require matching native rig/readback validation')
    if (export.get('bone_bounds_rebuilt') is not True
            or export.get('original_binding_names_order_and_aux_exact') is not True
            or export.get('proxy_raw_records_exact') is not True):
        raise ValueError('Donor prototype requires rebuilt bounds and preserved native bindings/proxy')
    model = Path(export['output']).resolve()
    if (Path(mapping['source_gr2']).resolve() != model
            or sha(model) != export['output_sha256']
            or mapping['source_sha256'] != export['output_sha256']):
        raise ValueError('Model bytes do not match both validated export records')
    if mapping.get('mapping') != export.get('mapping') or mapping.get('bounds') != export.get('bounds'):
        raise ValueError('Mapping data and bounds do not match the validated model export')
    payload_path = Path(export['payload']).resolve()
    if sha(payload_path) != export['payload_sha256']:
        raise ValueError('Prepared payload changed after model export')
    representation = surface.get('reference_representation')
    if representation is not None:
        scale = representation.get('uniform_scale')
        placed = 'translation_bg3' in representation
        translation = representation.get('translation_bg3')
        valid_translation = (not placed or (isinstance(translation, list) and len(translation) == 3
            and all(type(value) in (float, int) and math.isfinite(value) for value in translation)))
        if (representation.get('axis_order') != [0, 2, 1]
                or type(scale) not in (float, int) or not math.isfinite(scale) or scale <= 0
                or not valid_translation
                or representation.get('pose_applied') is not False
                or representation.get('neck_cut_or_bridge_applied') is not False
                or representation.get('rounding') != (PLACED_SOURCE_ROUNDING if placed else SOURCE_ROUNDING)
                or surface.get('lossless_actual_buffers_verified') is not True
                or surface.get('actual_positions_bit_equal_float32_prepared') is not True
                or surface.get('actual_triangles_exact_prepared') is not True
                or surface.get('actual_model_sha256') != export['output_sha256']
                or not surface.get('source_format_geometry_sha256')
                or not surface.get('source_format_pair_sha256')):
            raise ValueError('Format-matched source requires an explicit unposed source and lossless readback proof')
        new_pairs = surface.get('introduced_relative_format_matched_source_pair_count')
        bridge_pairs = surface.get('bridge_pair_count')
        collapsed = surface.get('actual_collapsed_face_count')
    else:
        new_pairs = surface.get('introduced_relative_original_pair_count')
        bridge_pairs = surface.get('bridge_involved_pair_count')
        collapsed = surface.get('collapsed_face_count')
    if (surface.get('passed') is not True or surface.get('input_hashes_stable') is not True
            or new_pairs != 0 or bridge_pairs != 0 or collapsed != 0):
        raise ValueError('Donor pose and neck require a passed global rest-surface audit')
    for key, value in surface['input_paths'].items():
        if sha(value) != surface['input_sha256'][key]:
            raise ValueError('Surface audit inputs changed: ' + key)
    if not any(Path(value).resolve() == model and surface['input_sha256'][key] == export['output_sha256']
               for key, value in surface['input_paths'].items()):
        raise ValueError('Global surface audit must bind the actual serialized GR2')
    if surface.get('checker_sha256') != sha(ROOT / 'src/nudegate/surface_intersections.py'):
        raise ValueError('Surface checker changed after the recorded audit')
    if representation is not None:
        verify_format_source(surface)
    payload = json.loads(payload_path.read_text())
    body = next(mesh for mesh in payload['meshes'] if mesh['name'] == MESH)
    prepared_path = surface['input_paths'].get('prepared', surface['input_paths'].get('prepared_npz'))
    with np.load(prepared_path, allow_pickle=False) as prepared:
        if (not np.array_equal(np.asarray(body['positions']), prepared['positions'])
                or not np.array_equal(np.asarray(body['triangles']), prepared['triangles'])):
            raise ValueError('Exported geometry does not match the audited prepared body')
    info = mapping['mapping']
    raw = zlib.decompress(base64.b64decode(info['closest_vertices'], validate=True))
    if (hashlib.sha256(raw).hexdigest() != info['sha256_raw']
            or len(raw) != 2 * info['nb_closest_vertices']
            or info['nb_closest_vertices'] != 3 * info['target_marked_vertices']
            or info['target_mesh'] != MESH
            or info['physics_selected_positions'] <= 0):
        raise ValueError('Invalid cloth mapping buffer/count/mesh binding')
    rows = np.frombuffer(raw, dtype='<u2').reshape(-1, 3)
    if (not len(rows) or np.any(rows[:, 0] == 65535)
            or np.any((rows[:, 1] == 65535) & (rows[:, 2] != 65535))
            or np.any((rows != 65535) & (rows >= info['physics_selected_positions']))):
        raise ValueError('Cloth mapping references missing physics points')
    return export, mapping, surface


def set_attr(node, key, value):
    found = node.findall(f"attribute[@id='{key}']")
    if len(found) != 1:
        raise ValueError('Expected one native attribute: ' + key)
    found[0].set('value', str(value))


def private_resource(source_bank, mapping, profile):
    tree = ET.parse(source_bank)
    records = [node for node in tree.findall(".//node[@id='Resource']") if attrs(node).get('ID') == SOURCE_BODY]
    if len(records) != 1:
        raise ValueError('Expected the exact reviewed adult human-normal source resource')
    resource = copy.deepcopy(records[0])
    source = attrs(resource)
    original_prefix = source['SourceFile'].rsplit('.', 1)[0]
    if not source['Template'].startswith(original_prefix + '.'):
        raise ValueError('Unreviewed native template/model binding')
    relative = Path('Public') / MODULE / 'Assets' / profile / Path(source['SourceFile']).name
    private_id = str(uuid5(NAMESPACE, 'body:' + SOURCE_BODY + ':' + profile))
    for key, value in {'ID': private_id, 'Name': 'Nudegate donor prototype / ' + profile,
                       'SourceFile': relative.as_posix(),
                       'Template': relative.with_suffix('').as_posix() + source['Template'][len(original_prefix):]}.items():
        set_attr(resource, key, value)
    cloth = resource.findall(".//attribute[@id='ClosestVertices']")
    counts = resource.findall(".//attribute[@id='NbClosestVertices']")
    if len(cloth) != 1 or len(counts) != 1 or resource.find("children/node[@id='ClothParams']") is None:
        raise ValueError('Source has no single matched cloth mapping/solver record')
    cloth[0].set('value', mapping['mapping']['closest_vertices'])
    counts[0].set('value', str(mapping['mapping']['nb_closest_vertices']))
    body = next(bound for bound in mapping['bounds'] if bound['mesh'] == MESH)
    set_attr(resource, 'BoundsMin', ' '.join(format(float(x), '.9g') for x in body['min']))
    set_attr(resource, 'BoundsMax', ' '.join(format(float(x), '.9g') for x in body['max']))
    container = tree.find("./region[@id='VisualBank']/node/children")
    if container is None:
        raise ValueError('Invalid native VisualBank')
    container[:] = [resource]
    return tree, resource, relative, private_id


def semantic(node):
    attributes = dict(node.attrib)
    if node.tag == 'attribute' and attributes.get('id') == 'ClosestVertices':
        attributes['value'] = hashlib.sha256(zlib.decompress(base64.b64decode(attributes['value']))).hexdigest()
    if node.tag == 'attribute' and attributes.get('id') in {'BoundsMin', 'BoundsMax'}:
        attributes['value'] = ' '.join(format(float(x), '.6g') for x in attributes['value'].split())
    return (node.tag, tuple(sorted(attributes.items())),
            tuple(sorted((semantic(child) for child in node), key=repr)))


def document_regions(tree):
    """Compare game records using LSF's stored root-node name as region ID.

    Official LSFReader.ReadRegions sets RegionName = region.Name; a separate
    LSX region alias (CharacterCreationPresets around node root) is not stored.
    """
    regions = []
    for region in tree.findall('./region'):
        roots = region.findall('node')
        if len(roots) != 1 or not roots[0].get('id'):
            raise ValueError('Resource region requires one named root node')
        canonical = copy.deepcopy(region)
        canonical.set('id', roots[0].get('id'))
        regions.append(semantic(canonical))
    return tuple(sorted(regions, key=repr))


def verify_creation_isolation(tav, documents, private_body_id):
    records = {}
    for label, key in [('templates', 'MapKey'), ('visuals', 'ID'), ('presets', 'UUID')]:
        nodes = documents[label].findall('./region/node/children/node')
        entries = [attrs(node) for node in nodes]
        if any(key not in entry for entry in entries) or len({entry[key] for entry in entries}) != len(entries):
            raise ValueError('Compiled creation records have missing or duplicate UUIDs: ' + label)
        records[label] = {entry[key]: entry for entry in entries}
    expected_roots = {entry['private_template_id'] for entry in tav['templates']}
    expected_visuals = {entry['private_visual_id'] for entry in tav['templates']}
    expected_presets = {entry['preset_id'] for entry in tav['presets']}
    if (set(records['templates']) != expected_roots or set(records['visuals']) != expected_visuals
            or set(records['presets']) != expected_presets):
        raise ValueError('Compiled creation files contain unexpected original or private UUIDs')
    originals = {entry['original_template_id'] for entry in tav['templates']}
    if expected_roots & originals:
        raise ValueError('Compiled creation files override an original root')
    for entry in tav['templates']:
        if (entry['review'].get('adult') is not True or entry['body_type'] != '1' or entry['body_shape'] != '0'
                or entry['original_body_set_visual'] != SOURCE_BODY
                or entry['private_body_set_visual'] != private_body_id
                or records['templates'][entry['private_template_id']].get('CharacterVisualResourceID') != entry['private_visual_id']
                or records['visuals'][entry['private_visual_id']].get('BodySetVisual') != private_body_id):
            raise ValueError('Compiled creation root/visual/body escapes the reviewed adult normal-human chain')
    for entry in tav['presets']:
        if records['presets'][entry['preset_id']].get('RootTemplate') != entry['private_template_id']:
            raise ValueError('Compiled creation preset does not reference its private root')
    return {'private_roots': len(expected_roots), 'private_visuals': len(expected_visuals),
            'selected_generic_presets': len(expected_presets), 'original_root_overrides': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export-report', type=Path, required=True)
    parser.add_argument('--mapping-report', type=Path, required=True)
    parser.add_argument('--surface-audit', type=Path, required=True)
    parser.add_argument('--source-bank', type=Path, default=ROOT / 'build/physics-probe/matched-v1/source-banks/human_normal.lsx')
    parser.add_argument('--source-root', type=Path, default=Path.home() / '.cache/nudegate/sources/49a08a2abcd0d562')
    parser.add_argument('--packages', nargs='+', default=['Shared', 'Gustav', 'GustavX', 'Patch8_HotFix9', 'Patch8_HotFix10'])
    parser.add_argument('--presets', nargs='+', type=Path, default=[Path.home() / ('.cache/nudegate/cc-inspection/Public/' + module + '/CharacterCreationPresets/CharacterCreationPresets.lsx') for module in ('Shared', 'SharedDev')])
    parser.add_argument('--divine', type=Path, default=Path.home() / '.cache/nudegate/gr2-tools/Divine-1.20.4/Divine.exe')
    parser.add_argument('--output', type=Path, default=ROOT / 'build/donors/juno-cc-probe')
    parser.add_argument('--profile', default='donor_juno_b')
    args = parser.parse_args()
    if not re.fullmatch('[a-z][a-z0-9_]{0,45}', args.profile):
        raise ValueError('Unsafe profile identifier')
    output = args.output.resolve()
    if not output.is_relative_to((ROOT / 'build').resolve()):
        raise ValueError('Experimental package output must stay inside the project build directory')
    source_bank_sha256 = verify_source_bank(args.source_bank)
    export, mapping, surface = load_inputs(args.export_report, args.mapping_report, args.surface_audit)
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='donor-probe-', dir=output) as temp:
        work = Path(temp).resolve()
        if not work.is_relative_to(output):
            raise ValueError('Temporary stage escaped the intended build directory')
        stage = work / 'package'
        tree, resource, relative, private_id = private_resource(args.source_bank, mapping, args.profile)
        model = stage / relative
        model.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(export['output'], model)
        bank = work / 'donor-visual.lsx'
        tree.write(bank, encoding='utf-8', xml_declaration=True)
        compiled = stage / 'Public' / MODULE / 'Content/[PAK]_BodyVisuals/donor.lsf'
        compiled.parent.mkdir(parents=True, exist_ok=True)
        run(args.divine, '-a', 'convert-resource', '-s', bank, '-d', compiled)
        resources = {'resource_map': {SOURCE_BODY: [{'family_id': 'human_elf_f', 'variant_id': args.profile, 'private_visual_id': private_id}]},
                     'variants': [{'family_id': 'human_elf_f', 'variant_id': args.profile, 'original_visual_id': SOURCE_BODY,
                                   'private_visual_id': private_id, 'mesh_name': MESH}]}
        db = Database.load(args.source_root, args.packages)
        tav = create_tav_presets(db, args.presets, resources, work / 'creation', profile_id=args.profile)
        if not tav['counts']['presets']:
            raise ValueError('No reviewed adult normal-human new-Tav presets matched')
        creation_expected = {}
        for label, path in tav['outputs'].items():
            source = Path(path)
            target = stage / source.relative_to(work / 'creation').as_posix().replace('Public/Nudegate/', 'Public/' + MODULE + '/', 1)
            target = target.with_suffix('.lsf')
            target.parent.mkdir(parents=True, exist_ok=True)
            run(args.divine, '-a', 'convert-resource', '-s', source, '-d', target)
            creation_expected[label] = (source, target.relative_to(stage))
        meta = ET.parse(ROOT / 'mod/Mods/Nudegate/meta.lsx')
        info = meta.find(".//node[@id='ModuleInfo']")
        module_id = str(uuid5(NAMESPACE, 'module:' + args.profile))
        for key, value in {'Folder': MODULE, 'UUID': module_id, 'Name': 'Nudegate / donor physics creation prototype',
                           'Version64': '1', 'Description': 'Experimental new-Tav donor body. Native cloth mapping; motion and skin appearance require in-game review.'}.items():
            set_attr(info, key, value)
        meta_path = stage / 'Mods' / MODULE / 'meta.lsx'
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta.write(meta_path, encoding='utf-8', xml_declaration=True)
        pak = output / ('Nudegate-' + args.profile + '-creation-probe.pak')
        run(args.divine, '-a', 'create-package', '-s', stage, '-d', pak)
        check = work / 'extracted'
        run(args.divine, '-a', 'extract-package', '-s', pak, '-d', check)
        expected = {p.relative_to(stage).as_posix(): sha(p) for p in stage.rglob('*') if p.is_file()}
        actual = {p.relative_to(check).as_posix(): sha(p) for p in check.rglob('*') if p.is_file()}
        if actual != expected:
            raise RuntimeError('Experimental package file round trip failed')
        verified_bank = work / 'verified-visual.lsx'
        run(args.divine, '-a', 'convert-resource', '-s', check / compiled.relative_to(stage), '-d', verified_bank)
        if semantic(ET.parse(verified_bank).find(".//node[@id='Resource']")) != semantic(resource):
            raise RuntimeError('Physics resource fields changed during compilation')
        creation_decoded = {}
        for label, (source, relative_output) in creation_expected.items():
            decoded = work / ('verified-creation-' + label + '.lsx')
            run(args.divine, '-a', 'convert-resource', '-s', check / relative_output, '-d', decoded)
            tree_decoded = ET.parse(decoded)
            if document_regions(tree_decoded) != document_regions(ET.parse(source)):
                raise RuntimeError('Creation records changed during compilation: ' + label)
            creation_decoded[label] = tree_decoded
        creation_isolation = verify_creation_isolation(tav, creation_decoded, private_id)
        report = {'schema_version': 1, 'kind': 'experimental donor new-Tav creation probe',
                  'package': str(pak), 'package_sha256': sha(pak), 'module_id': module_id,
                  'private_body_id': private_id, 'profile': args.profile, 'files': expected,
                  'export_report': {'path': str(args.export_report.resolve()), 'sha256': sha(args.export_report)},
                  'mapping_report': {'path': str(args.mapping_report.resolve()), 'sha256': sha(args.mapping_report)},
                  'surface_audit': {'path': str(args.surface_audit.resolve()), 'sha256': sha(args.surface_audit)},
                  'source_bank': {'path': str(args.source_bank.resolve()), 'sha256': sha(args.source_bank),
                                  'reviewed_sha256': source_bank_sha256},
                  'tav_presets': tav, 'validation': {'package_file_round_trip': 'passed', 'physics_resource_round_trip': 'passed',
                    'creation_resource_round_trip': 'passed', 'creation_uuid_isolation': creation_isolation,
                    'new_rest_intersections_vs_recorded_source': 0, 'reference_representation': surface.get('reference_representation', 'authored source'),
                    'npc_overrides': 'none', 'installed': False,
                    'in_game_motion': 'not tested', 'material_quality': 'prototype; requires in-game review',
                    'new_gravity_or_squeeze': 'not implemented'}}
        (output / 'probe-report.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({'package': str(pak), 'presets': tav['counts']['presets'], 'validation': report['validation']}, indent=2))


if __name__ == '__main__':
    main()
