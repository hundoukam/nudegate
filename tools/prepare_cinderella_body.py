"""Stage the original Cinderella A surface with independently calibrated anatomy."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from nudegate.cinderella_body import calibrate, pose, map_weights, validate_optional_uncompressed, apply_pose_coherence
from nudegate.donor_body import load_dae, trim_and_bridge, transfer_native_surface, body_payload, sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--donor', type=Path, default=ROOT / 'build/donors/skinned-others/cinderella_a.npz')
    parser.add_argument('--native', type=Path, default=ROOT / 'build/physics-probe/matched-v1/model-roundtrip/human_normal/source.dae')
    parser.add_argument('--reference', type=Path, help='Native-topology UV/paint lookup fitted to this donor; original native is provisional default')
    parser.add_argument('--output', type=Path, default=ROOT / 'build/donors/cinderella_actual_v1')
    parser.add_argument('--pose-only', action='store_true')
    parser.add_argument('--align-hip-x', action='store_true')
    parser.add_argument('--arm-fraction', type=float, default=1.)
    parser.add_argument('--leg-fraction', type=float, default=1.)
    parser.add_argument('--optional-uncompressed-study', action='store_true',
                        help='Explicit separate study of the three verified wardrobe switches; never selected A')
    parser.add_argument('--pelvic-pose-corrective', type=Path,
                        help='Explicit fingerprinted <=1mm local pose-coherence parameters, never a source sculpt')
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Cinderella preparation requires a fresh output directory')
    metadata_path = args.donor.with_suffix('.json')
    metadata = json.loads(metadata_path.read_text())
    expected_id = 'cinderella_optional_uncompressed' if args.optional_uncompressed_study else 'cinderella_a'
    if metadata.get('id') != expected_id or sha(args.donor) != metadata['npz_sha256']:
        raise ValueError('Expected exact fingerprinted Cinderella A capture')
    optional_review = None
    if args.optional_uncompressed_study:
        selected = json.loads((ROOT / 'build/donors/skinned-others/cinderella_a.json').read_text())
        optional_review = validate_optional_uncompressed(metadata, selected)
    with np.load(args.donor, allow_pickle=False) as source:
        arrays = {key: source[key] for key in source.files}
    native = load_dae(args.native)
    calibration = calibrate(arrays, metadata, native)
    posed, weights, names, bones, report = pose(arrays, metadata, native, calibration,
        align_hip_x=args.align_hip_x, arm_fraction=args.arm_fraction, leg_fraction=args.leg_fraction)
    if args.pelvic_pose_corrective:
        parameters = json.loads(args.pelvic_pose_corrective.read_text())
        posed, report['pelvic_pose_corrective'] = apply_pose_coherence(posed, parameters, sha(args.donor))
        report['pelvic_pose_corrective'].update(parameters=str(args.pelvic_pose_corrective.resolve()),
            parameters_sha256=sha(args.pelvic_pose_corrective))
        fixed = posed['limb_influence'] == 0
        report['torso_uninfluenced_max_error_before_explicit_corrective'] = report['torso_uninfluenced_max_error']
        report['torso_uninfluenced_max_error'] = float(np.linalg.norm(
            posed['positions'][fixed] - posed['scaled_source_positions'][fixed], axis=1).max(initial=0))
        report['torso_uninfluenced_metric_scope'] = 'Includes the explicitly permitted local pelvic pose corrective; all points outside its support remain exact.'
    mapped, skin_report = map_weights(weights, names, bones, native['bone_palette'])
    report.update(donor_state_id=metadata['id'], display_label='Cinderella optional U' if optional_review else 'Cinderella A',
        optional_authored_key_study=optional_review, source_npz=str(args.donor.resolve()),
        source_npz_sha256=sha(args.donor), source_metadata_sha256=sha(metadata_path),
        frozen_geometry_parity=metadata.get('geometry_reference'), native=str(args.native.resolve()), native_sha256=sha(args.native),
        skin_mapping=skin_report, complete=False, surface_audit_status='pending independent global source/pose/prepared audits',
        in_game_motion='not tested', source_geometry_policy='original sculpt retained outside explicit uniform placement, limb pose and local neck operations')
    args.output.mkdir(parents=True)
    np.savez_compressed(args.output / 'posed_dense.npz', **posed)
    if not args.pose_only:
        body, report['neck'] = trim_and_bridge(posed, mapped, native,
            cut=calibration['head_cut_base_height'], band=calibration['neck_transition_band'])
        np.savez_compressed(args.output / 'neck_geometry.npz', **body)
        reference_path = args.reference or args.native
        reference = load_dae(reference_path)
        final, report['surface_transfer'] = transfer_native_surface(body, reference, native)
        final['source_face_ids'] = body['source_face_ids']
        payload, report['export_quantization'] = body_payload(final, native)
        np.savez_compressed(args.output / 'body_prepared.npz', **final)
        payload_path = args.output / 'body_payload.json'
        payload_path.write_text(json.dumps(payload, separators=(',', ':'), allow_nan=False))
        report.update(complete=True, payload=str(payload_path.resolve()), payload_sha256=sha(payload_path),
            reference=str(reference_path.resolve()), reference_sha256=sha(reference_path),
            material_quality='native UV/paint transfer prototype; not material or physics accepted',
            positive_head_weight_vertices=int(np.count_nonzero(final['bone_weights'][:, native['bone_palette'].index('Head_M')] > 0)))
    (args.output / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'output': str(args.output.resolve()), 'calibration': calibration,
                      'complete': report['complete'], 'payload_sha256': report.get('payload_sha256')}, indent=2))


if __name__ == '__main__':
    main()
