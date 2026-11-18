"""Stage reviewed original-support restoration of the selected Juno E body."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from nudegate.juno_e_support import (restore_original_support, SOURCE_SHA256,
    BASELINE_POSE_SHA256, PROFILE, local_neck_cut)
from nudegate.donor_body import (sha, load_dae, normalized_deform_weights, map_native_weights,
    trim_and_bridge, transfer_native_surface, body_payload, repair_juno_stray_facial_weights)

NATIVE_SHA256 = 'c5df3986d8066c1a27c1df0ccd2bcf594433cc723f2fc63cd164103a485d247c'


def verify_lookup_semantics(native, reference):
    checks = {key: bool(np.array_equal(native[key], reference[key]))
        for key in ('triangles', 'bone_weights', 'inverse_bind')}
    checks['bone_palette'] = native['bone_palette'] == reference['bone_palette']
    for semantic in ('TEXCOORD', 'COLOR'):
        checks[semantic] = bool(np.array_equal(native['corners'][semantic], reference['corners'][semantic]))
    if not all(checks.values()):
        raise ValueError('Native UV/paint lookup changed protected fields: ' + str(checks))
    return checks


def verify_corner_parity(previous, current, old_mesh, new_mesh):
    old_faces, new_faces = previous['triangles'], current['triangles']
    checks = {key: bool(np.array_equal(previous[key][old_faces], current[key][new_faces]))
        for key in ('positions', 'normals', 'source_vertex_ids', 'geometry_vertex_ids', 'bone_weights')}
    checks['source_face_ids'] = bool(np.array_equal(previous['source_face_ids'], current['source_face_ids']))
    checks['bone_palette'] = old_mesh['bone_palette'] == new_mesh['bone_palette']
    for key in ('bone_indices', 'bone_weights'):
        checks['serialized_' + key] = bool(np.array_equal(np.asarray(old_mesh[key])[old_faces],
            np.asarray(new_mesh[key])[new_faces]))
    if not all(checks.values()):
        raise ValueError('Own lookup retransfer changed preserved donor geometry or skin: ' + str(checks))
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'build/donors/skinned-e/juno_e.npz')
    parser.add_argument('--baseline-pose', type=Path, default=ROOT / 'build/donors/juno_e_pose_nativearms_v3/posed_dense.npz')
    parser.add_argument('--native', type=Path, default=ROOT / 'build/physics-probe/matched-v1/model-roundtrip/human_normal/source.dae')
    parser.add_argument('--reference', type=Path, help='Own fitted native topology for provisional UV/paint transfer')
    parser.add_argument('--compare-geometry-stage', type=Path,
        help='Require exact face-corner geometry and reviewed skin parity with an earlier accepted E stage')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--pose-only', action='store_true')
    parser.add_argument('--local-neck-cut', action='store_true',
        help='Separate E-local lower central cut; original default neck operation remains available')
    neck=parser.add_mutually_exclusive_group()
    neck.add_argument('--consistent-neck-winding',dest='neck_orientation',action='store_const',const='source-boundary',
        help='Coherent body-boundary bridge orientation (default)')
    neck.add_argument('--legacy-radial-neck-winding',dest='neck_orientation',action='store_const',const='radial',
        help='Explicit archive reproduction only: original per-face radial orientation')
    parser.set_defaults(neck_orientation='source-boundary')
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Original-support preparation requires a fresh output directory')
    if sha(args.source) != SOURCE_SHA256 or sha(args.baseline_pose) != BASELINE_POSE_SHA256:
        raise ValueError('Original-support source or reviewed full-arm baseline fingerprint differs')
    if sha(args.native) != NATIVE_SHA256:
        raise ValueError('Original native collar/rig source fingerprint differs')
    if args.pose_only and args.compare_geometry_stage:
        raise ValueError('Geometry-stage comparison requires complete body preparation')
    metadata = json.loads(args.source.with_suffix('.json').read_text())
    arrays = dict(np.load(args.source, allow_pickle=False))
    baseline = dict(np.load(args.baseline_pose, allow_pickle=False))
    posed, restoration = restore_original_support(baseline, arrays, metadata)
    report = json.loads(args.baseline_pose.with_name('report.json').read_text())
    report.update(source_npz=str(args.source.resolve()), source_npz_sha256=sha(args.source),
        source_metadata_sha256=sha(args.source.with_suffix('.json')),
        baseline_pose=str(args.baseline_pose.resolve()), baseline_pose_sha256=sha(args.baseline_pose),
        donor_state_id='juno_e', display_label='Juno E / original support',
        original_support_pose_restoration=restoration, profile=PROFILE,
        surface_audit_status='pending independent full source/pose/prepared/serialized audits',
        game_animation_validation='unverified; original v3 limb fixture offsets retained',
        sculpt_changes=0, complete=False)
    args.output.mkdir(parents=True)
    np.savez_compressed(args.output / 'posed_dense.npz', **posed)
    if not args.pose_only:
        native = load_dae(args.native)
        weights, names, bones, _ = normalized_deform_weights(arrays, metadata)
        mapped, report['skin_mapping'] = map_native_weights(weights, names, bones, native['bone_palette'])
        if args.local_neck_cut:
            cut_function, cut, parameters = local_neck_cut(native)
            # The lower cut must not remove even one breast-majority source
            # point. Microscopic shoulder paint tails are not body contours.
            from nudegate.juno_e_support import _descends
            columns = [i for i, name in enumerate(names) if _descends(name, {'l_breast', 'r_breast'}, bones)]
            dominant = weights[:, columns].sum(1) >= .5
            clipped = dominant & (posed['positions'][:, 1] > cut_function(posed['positions'][:, 0], cut))
            if clipped.any():
                raise ValueError('E local neck cut would remove authored breast-majority geometry')
            body, report['neck'] = trim_and_bridge(posed, mapped, native, cut=cut, cut_height=cut_function,
                bridge_orientation=args.neck_orientation)
            report['neck']['local_profile_parameters'] = parameters
            report['neck']['breast_majority_source_vertices_clipped'] = 0
        else:
            body, report['neck'] = trim_and_bridge(posed, mapped, native,
                bridge_orientation=args.neck_orientation)
        np.savez_compressed(args.output / 'neck_geometry.npz', **body)
        reference_path = args.reference or args.native
        reference = load_dae(reference_path)
        report['native_lookup_preserved_semantics'] = verify_lookup_semantics(native, reference)
        final, report['surface_transfer'] = transfer_native_surface(body, reference, native)
        final['source_face_ids'] = body['source_face_ids']
        payload, report['export_quantization'] = body_payload(final, native)
        mesh = payload['meshes'][0]
        head_index = mesh['bone_palette'].index('Head_M')
        index = np.asarray(mesh['bone_indices']); weight = np.asarray(mesh['bone_weights'])
        head_rows = ((index == head_index) & (weight > 0)).any(1)
        if head_rows.any():
            payload, final['bone_weights'], report['explicit_skin_repair'] = repair_juno_stray_facial_weights(payload, final, bones)
        report['positive_head_byte_rows_before_reviewed_repair'] = int(head_rows.sum())
        mesh = payload['meshes'][0]
        report['positive_head_byte_rows_after_reviewed_repair'] = int(np.count_nonzero(
            ((np.asarray(mesh['bone_indices']) == head_index) & (np.asarray(mesh['bone_weights']) > 0)).any(1)))
        if args.compare_geometry_stage:
            previous = dict(np.load(args.compare_geometry_stage / 'body_prepared.npz', allow_pickle=False))
            old_payload_path = args.compare_geometry_stage / 'body_payload.json'
            old_mesh = json.loads(old_payload_path.read_text())['meshes'][0]
            report['attribute_retransfer'] = {'source_stage': str(args.compare_geometry_stage.resolve()),
                'source_payload_sha256': sha(old_payload_path),
                'donor_face_corner_parity': verify_corner_parity(previous, final, old_mesh, mesh),
                'only_attributes_changed': ['native UV lookup', 'native RGB paint lookup',
                    'UV-derived tangent/binormal frames', 'UV-island seam duplication'],
                'invented_physics_paint': False}
        np.savez_compressed(args.output / 'body_prepared.npz', **final)
        payload_path = args.output / 'body_payload.json'
        payload_path.write_text(json.dumps(payload, separators=(',', ':'), allow_nan=False))
        report.update(complete=True, payload=str(payload_path.resolve()), payload_sha256=sha(payload_path),
            native=str(args.native.resolve()), native_sha256=sha(args.native),
            reference=str(reference_path.resolve()), reference_sha256=sha(reference_path),
            material_quality='provisional native lookup; own E proxy and same-field attributes still required')
    (args.output / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'output': str(args.output.resolve()), 'complete': report['complete'],
        'changed_vertices': restoration['changed_vertices'], 'maximum_restoration_m': restoration['maximum_restoration_towards_source_m'],
        'payload_sha256': report.get('payload_sha256')}, indent=2))


if __name__ == '__main__':
    main()
