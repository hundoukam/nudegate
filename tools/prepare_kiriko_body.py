"""Prepare the frozen authored-large Kiriko 2.0 C body in private staging."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from nudegate.kiriko_body import calibrate,pose,map_weights
from nudegate.donor_body import load_dae,trim_and_bridge,transfer_native_surface,body_payload,sha


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--donor',type=Path,default=ROOT/'build/donors/skinned-repaired/kiriko_2_0_c.npz')
    parser.add_argument('--native',type=Path,default=ROOT/'build/physics-probe/matched-v1/model-roundtrip/human_normal/source.dae')
    parser.add_argument('--reference',type=Path)
    parser.add_argument('--output',type=Path,default=ROOT/'build/donors/kiriko_actual_v1')
    parser.add_argument('--align-hip-x',action='store_true')
    parser.add_argument('--protect-pelvic-seam',action='store_true')
    parser.add_argument('--pelvic-mask-mode',choices=['axis','source-support'],default='source-support')
    parser.add_argument('--pose-only',action='store_true')
    parser.add_argument('--fit-native-joints',action='store_true',help='opt-in longitudinal limb fit with full native pivot XYZ and authored breast support protection')
    args=parser.parse_args()
    if args.output.exists():raise ValueError('Kiriko preparation requires fresh staging')
    metadata=json.loads(args.donor.with_suffix('.json').read_text())
    if sha(args.donor)!=metadata['npz_sha256']:raise ValueError('Kiriko repaired source capture fingerprint changed')
    with np.load(args.donor,allow_pickle=False) as source:arrays={key:source[key]for key in source.files}
    native=load_dae(args.native);calibration=calibrate(arrays,metadata,native)
    posed,weights,names,bones,report=pose(arrays,metadata,native,calibration,
        align_hip_x=args.align_hip_x,protect_pelvic_seam=args.protect_pelvic_seam,pelvic_mask_mode=args.pelvic_mask_mode,
        fit_native_joints=args.fit_native_joints)
    args.output.mkdir(parents=True)
    np.savez_compressed(args.output/'posed_dense.npz',**posed)
    report.update(donor_state_id='kiriko_2_0_c',display_label='Kiriko 2.0 C / '+('native joint-fit study'if args.fit_native_joints else 'authored large'),
        source_npz=str(args.donor.resolve()),source_npz_sha256=sha(args.donor),
        source_metadata_sha256=sha(args.donor.with_suffix('.json')),frozen_geometry_parity=metadata.get('geometry_reference'),
        explicit_skin_repair=metadata.get('explicit_skin_repair'),native=str(args.native.resolve()),native_sha256=sha(args.native),
        complete=False,surface_audit_status='not audited; do not export or package as accepted body',in_game_motion='not tested')
    if not args.pose_only:
        mapped,report['skin_mapping']=map_weights(weights,names,bones,native['bone_palette'])
        body,report['neck']=trim_and_bridge(posed,mapped,native,cut=calibration['head_cut_base_height'],
            band=calibration['neck_transition_band'],allow_inherited_openings=True)
        reference_path=args.reference or args.native
        prepared,report['surface_transfer']=transfer_native_surface(body,load_dae(reference_path),native)
        prepared['source_face_ids']=body['source_face_ids']
        payload,report['export_quantization']=body_payload(prepared,native)
        np.savez_compressed(args.output/'neck_geometry.npz',**body)
        np.savez_compressed(args.output/'body_prepared.npz',**prepared)
        path=args.output/'body_payload.json';path.write_text(json.dumps(payload,separators=(',',':'),allow_nan=False))
        head=prepared['bone_weights'][:,native['bone_palette'].index('Head_M')]>0
        exported=np.asarray(payload['meshes'][0]['bone_weights'])
        exported_indices=np.asarray(payload['meshes'][0]['bone_indices'])
        exported_head=np.any((exported_indices==native['bone_palette'].index('Head_M'))&(exported>0),axis=1)
        report.update(complete=True,reference=str(reference_path.resolve()),reference_sha256=sha(reference_path),
            payload=str(path.resolve()),payload_sha256=sha(path),
            material_quality='unfitted native UV/paint prototype; own proxy fit pending',
            positive_head_weight_vertices=int(head.sum()),
            positive_head_weight_bounds=([prepared['positions'][head].min(0).tolist(),prepared['positions'][head].max(0).tolist()]if head.any()else []),
            positive_head_weight_vertices_exported_byte=int(exported_head.sum()),
            native_head_binding_required=bool(exported_head.any()))
    (args.output/'report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({'output':str(args.output.resolve()),'calibration':calibration,
        'source_vertices':len(posed['positions']),'source_triangles':len(posed['triangles']),
        'complete':report['complete'],'payload_sha256':report.get('payload_sha256')},indent=2))


if __name__=='__main__':main()
