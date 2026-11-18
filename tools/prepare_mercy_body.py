"""Prepare the selected authored large Mercy body in separate local staging."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from nudegate.mercy_body import calibrate,pose,map_weights
from nudegate.donor_body import load_dae,trim_and_bridge,transfer_native_surface,body_payload,sha


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--donor',type=Path,default=ROOT/'build/donors/skinned-repaired/mercy_c.npz')
    parser.add_argument('--native',type=Path,default=ROOT/'build/physics-probe/matched-v1/model-roundtrip/human_normal/source.dae')
    parser.add_argument('--reference',type=Path)
    parser.add_argument('--output',type=Path,default=ROOT/'build/donors/mercy_actual_v1')
    parser.add_argument('--align-hip-x',action='store_true')
    parser.add_argument('--protect-pelvic-seam',action='store_true',help='Preserve the authored anatomical midline during offline neutral leg pose changes')
    args=parser.parse_args()
    if args.output.exists():raise ValueError('Mercy preparation requires fresh staging')
    metadata=json.loads(args.donor.with_suffix('.json').read_text())
    if sha(args.donor)!=metadata['npz_sha256'] or metadata.get('id')!='mercy_c':
        raise ValueError('Expected the exact pinned Mercy C skin capture')
    with np.load(args.donor,allow_pickle=False) as data:arrays=dict(data)
    native=load_dae(args.native);calibration=calibrate(arrays,metadata,native)
    posed,weights,names,bones,report=pose(arrays,metadata,native,calibration,
        align_hip_x=args.align_hip_x,protect_pelvic_seam=args.protect_pelvic_seam)
    mapped,report['skin_mapping']=map_weights(weights,names,bones,native['bone_palette'])
    body,report['neck']=trim_and_bridge(posed,mapped,native,cut=calibration['head_cut_base_height'],
        band=calibration['neck_transition_band'],allow_inherited_openings=True)
    reference_path=args.reference or args.native
    prepared,report['surface_transfer']=transfer_native_surface(body,load_dae(reference_path),native)
    prepared['source_face_ids']=body['source_face_ids']
    payload,report['export_quantization']=body_payload(prepared,native)
    args.output.mkdir(parents=True)
    np.savez_compressed(args.output/'posed_dense.npz',**posed)
    np.savez_compressed(args.output/'neck_geometry.npz',**body)
    np.savez_compressed(args.output/'body_prepared.npz',**prepared)
    path=args.output/'body_payload.json';path.write_text(json.dumps(payload,separators=(',',':'),allow_nan=False))
    report.update(donor_state_id='mercy_c',display_label='Mercy C / authored large',
        source_npz=str(args.donor.resolve()),source_npz_sha256=sha(args.donor),
        source_metadata_sha256=sha(args.donor.with_suffix('.json')),
        frozen_geometry_parity=metadata.get('geometry_reference'),explicit_skin_repair=metadata.get('explicit_skin_repair'),
        native=str(args.native.resolve()),native_sha256=sha(args.native),reference=str(reference_path.resolve()),
        reference_sha256=sha(reference_path),payload=str(path.resolve()),payload_sha256=sha(path),complete=True,
        surface_audit_status='not audited; do not export or package as accepted body',
        material_quality='unfitted native UV/paint prototype; own fit and proxy pending',in_game_motion='not tested',
        positive_head_weight_vertices=int(np.count_nonzero(prepared['bone_weights'][:,native['bone_palette'].index('Head_M')]>0)))
    (args.output/'report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({'output':str(args.output.resolve()),'calibration':calibration,
                      'vertices':len(prepared['positions']),'triangles':len(prepared['triangles']),
                      'head_weight_vertices':report['positive_head_weight_vertices']},indent=2))


if __name__=='__main__':main()
