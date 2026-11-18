"""Author a donor-specific native cloth proxy and the same-field paint lookup.

This creates local authoring artifacts only. It never edits the dense donor,
original Blender sources, native GR2 records, game files or load order.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from nudegate.collada import ColladaMesh
from nudegate.donor_body import BODY_NAME, load_dae
from nudegate.native_proxy_fit import (fit_native_proxy, fit_disposable_lookup,
    exact_surface_distances, verify_only_position_arrays_changed)

PROXY_ID = BODY_NAME + '_Cloth_Physics-geom'
NATIVE_SHA256 = 'c5df3986d8066c1a27c1df0ccd2bcf594433cc723f2fc63cd164103a485d247c'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    with np.load(path, allow_pickle=False) as archive:
        return dict(archive)


def stats(value):
    if not len(value):
        return {'rows': 0}
    return {'rows': len(value), 'mean_m': float(value.mean()), 'median_m': float(np.median(value)),
        'p95_m': float(np.percentile(value, 95)), 'p99_m': float(np.percentile(value, 99)),
        'maximum_m': float(value.max())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-id', required=True)
    parser.add_argument('--source-manifest', type=Path, default=ROOT/'build/donors/selected-manifest.json')
    parser.add_argument('--target-pose', type=Path, required=True)
    parser.add_argument('--pose-audit', type=Path, required=True)
    parser.add_argument('--target-body', type=Path)
    parser.add_argument('--target-body-audit', type=Path,
                        help='Defaults to target body sibling global-prepared-surface-audit.json')
    parser.add_argument('--native', type=Path, default=ROOT/'build/physics-probe/matched-v1/model-roundtrip/human_normal/source.dae')
    parser.add_argument('--expected-native-sha256', default=NATIVE_SHA256)
    parser.add_argument('--radius', type=float, default=.02)
    parser.add_argument('--stabilizer', type=float, default=.05)
    parser.add_argument('--steps', type=int, default=64)
    parser.add_argument('--neighbours', type=int, default=96)
    parser.add_argument('--moving-centres', action='store_true')
    parser.add_argument('--projection-seeds', type=Path, help='Optional NPZ with positions; face selection only, never replaces original native controls')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    filenames = ['fitted_lookup.dae', 'fitted_lookup.jacobians.json', 'proxy_flow.npz', 'lookup_flow.npz', 'proxy-fit-report.json']
    if any((out/name).exists() for name in filenames):
        raise ValueError('Refusing to overwrite existing authoring artifacts')
    paths = {'source_manifest': args.source_manifest.resolve(), 'target_pose': args.target_pose.resolve(),
        'pose_audit': args.pose_audit.resolve(), 'native_dae': args.native.resolve(),
        'fit_implementation': ROOT/'src/nudegate/native_proxy_fit.py',
        'flow_implementation': ROOT/'src/nudegate/donor_flow.py',
        'surface_checker': ROOT/'src/nudegate/surface_intersections.py', 'authoring_tool': Path(__file__).resolve()}
    if args.target_body:
        paths['target_body'] = args.target_body.resolve()
        paths['target_body_audit'] = (args.target_body_audit.resolve() if args.target_body_audit
            else paths['target_body'].with_name('global-prepared-surface-audit.json'))
    elif args.target_body_audit:
        raise ValueError('A prepared-body audit requires --target-body')
    if args.projection_seeds:
        paths['projection_seeds'] = args.projection_seeds.resolve()
    hashes = {key: sha(path) for key, path in paths.items()}
    if hashes['native_dae'] != args.expected_native_sha256:
        raise ValueError('Native DAE does not match the explicit source pin')
    manifest = json.loads(paths['source_manifest'].read_text())
    entry = next(row for row in manifest['donors'] if row['id'] == args.source_id)
    paths['raw_source'] = Path(entry['npz']).resolve()
    paths['raw_source_metadata'] = Path(entry['metadata']).resolve()
    hashes['raw_source'] = sha(paths['raw_source'])
    hashes['raw_source_metadata'] = sha(paths['raw_source_metadata'])
    if hashes['raw_source'] != entry['npz_sha256'] or hashes['raw_source_metadata'] != entry['metadata_sha256']:
        raise ValueError('Frozen donor capture or metadata changed')
    metadata = json.loads(paths['raw_source_metadata'].read_text())
    pose = load(paths['target_pose'])
    raw = load(paths['raw_source'])
    audit = json.loads(paths['pose_audit'].read_text())
    if (audit['posed_npz_sha256'] != hashes['target_pose'] or audit['source_npz_sha256'] != hashes['raw_source']
            or audit['proof']['safe'] is not True):
        raise ValueError('Target pose requires its own passed source-bound surface audit')
    if (not np.array_equal(pose['source_vertex_ids'], np.arange(len(raw['positions'])))
            or not np.array_equal(pose['triangles'], raw['triangles'][:, [0, 2, 1]])):
        raise ValueError('Target pose lost original donor vertex/face identity')
    body = None
    if args.target_body:
        body_audit = json.loads(paths['target_body_audit'].read_text())
        if (body_audit['passed'] is not True or body_audit['input_sha256']['prepared'] != hashes['target_body']
                or body_audit['input_sha256']['posed'] != hashes['target_pose']
                or body_audit['input_sha256']['raw'] != hashes['raw_source']):
            raise ValueError('Painted target requires its own matching passed prepared-body audit')
        body = load(paths['target_body'])
        retained = body['source_vertex_ids'] >= 0
        if np.any(body['source_vertex_ids'][retained] >= len(pose['positions'])):
            raise ValueError('Painted target has invalid original vertex IDs')
    support = pose['source_breast_influence_left'] + pose['source_breast_influence_right']
    native = load_dae(paths['native_dae'], PROXY_ID)
    lookup = load_dae(paths['native_dae'])
    seeds = load(paths['projection_seeds'])['positions'] if args.projection_seeds else None
    fit = fit_native_proxy(native['positions'], native['triangles'], pose['positions'], pose['triangles'], support,
        radius=args.radius, stabilizer=args.stabilizer, neighbours=args.neighbours, steps=args.steps,
        moving_centres=args.moving_centres, time_sample_fraction=.5, projection_seed_positions=seeds)
    lookup_flow, lookup_proof = fit_disposable_lookup(fit, lookup['positions'], lookup['triangles'])
    out.mkdir(parents=True, exist_ok=True)
    authored = out/'fitted_lookup.dae'
    mesh = ColladaMesh.load(paths['native_dae'], geometry_id=BODY_NAME+'-geom')
    mesh.set_positions(lookup_flow.positions.tolist(), recalculate_normals=False)
    mesh.save(authored)
    mesh = ColladaMesh.load(authored, geometry_id=PROXY_ID)
    mesh.set_positions(fit.flow.positions.tolist(), recalculate_normals=False)
    mesh.save(authored)
    verify_only_position_arrays_changed(paths['native_dae'], authored, [BODY_NAME+'-geom', PROXY_ID])
    if (load_dae(authored, PROXY_ID)['positions'].tobytes() != fit.flow.positions.tobytes()
            or load_dae(authored)['positions'].tobytes() != lookup_flow.positions.tobytes()):
        raise ValueError('DAE coordinate serialization changed the sampled map')
    jac_path = out/'fitted_lookup.jacobians.json'
    jac_path.write_text(json.dumps({'geometries': {BODY_NAME+'-geom': {'jacobians': lookup_flow.jacobians.tolist()},
        PROXY_ID: {'jacobians': fit.flow.jacobians.tolist()}}}, separators=(',', ':')))
    np.savez_compressed(out/'proxy_flow.npz', positions=fit.flow.positions, triangles=native['triangles'],
        jacobians=fit.flow.jacobians, source_positions=native['positions'], controls=fit.control_points,
        velocities=fit.control_velocities, targets=fit.targets, target_source_face_ids=fit.target_source_face_ids,
        target_barycentrics=fit.target_barycentrics, target_normal_agreement=fit.target_normal_agreement,
        source_component_labels=fit.source_component_labels)
    np.savez_compressed(out/'lookup_flow.npz', positions=lookup_flow.positions, triangles=lookup['triangles'],
        jacobians=lookup_flow.jacobians)
    report = dict(fit.report, source_id=args.source_id, purpose='Donor-specific native proxy and same-field disposable paint lookup',
        input_paths={key: str(path) for key, path in paths.items()}, input_sha256=hashes,
        source_blend=metadata['source'], source_blend_sha256=metadata['source_sha256'],
        source_body_mesh=metadata['body_mesh'], source_applied_shape_keys=metadata['applied_shape_keys'],
        output=str(authored), output_sha256=sha(authored), jacobians=str(jac_path), jacobians_sha256=sha(jac_path),
        controls=str(out/'proxy_flow.npz'), controls_sha256=sha(out/'proxy_flow.npz'),
        parameters=dict(fit.field_parameters, steps=args.steps, time_sample_fraction=.5, neighbours=args.neighbours),
        render_lookup_flow_report=lookup_flow.report, native_render_lookup_surface_proof=lookup_proof,
        render_lookup_minimum_jacobian_determinant=float(np.linalg.det(lookup_flow.jacobians).min()),
        all_native_dae_records_except_two_position_arrays_exact=True,
        same_field_for_native_proxy_and_lookup=True, dense_actual_donor_geometry_changed=False,
        actual_serialized_mapper_readback='pending', runtime_physics='not tested')
    if args.target_body:
        marked = body['colors_rgba8'][:, 0] > 0
        query = body['positions'][marked]
        surface = exact_surface_distances(query, fit.flow.positions, native['triangles'])
        nearest, _ = cKDTree(fit.flow.positions).query(query, k=3)
        report['paint_to_proxy_surface'] = stats(surface)
        report['paint_to_nearest_proxy_vertex'] = stats(nearest[:, 0])
        report['paint_to_third_nearest_proxy_vertex'] = stats(nearest[:, 2])
        report['paint_distance_scope'] = 'All native proxy triangles; nearest3 logical points. Actual serialized mapper readback remains separate.'
    for key, path in paths.items():
        if sha(path) != hashes[key]:
            raise ValueError('Source changed during authoring: '+key)
    report['input_hashes_stable'] = True
    (out/'proxy-fit-report.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    print(json.dumps({key: report[key] for key in ('output', 'output_sha256', 'minimum_proxy_jacobian_determinant',
        'render_lookup_minimum_jacobian_determinant', 'passed')}, indent=2))


if __name__ == '__main__':
    main()
