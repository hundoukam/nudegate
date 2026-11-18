"""Retransfer a verified native UV/paint field onto frozen donor geometry.

Only native lookup coordinates may differ. Native UVs, RGB paint, skin and
topology must remain exact in the lookup. The donor's existing neck geometry,
source IDs, positions, normals and skin are checked per final face corner.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from nudegate.donor_body import load_dae,transfer_native_surface,body_payload,sha


def arrays(path):
    with np.load(path) as source:return {key:source[key] for key in source.files}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage',type=Path,required=True)
    parser.add_argument('--native',type=Path,default=ROOT/'build/physics-probe/matched-v1/model-roundtrip/human_normal/source.dae')
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--reference-proof',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();stage=args.stage.resolve();out=args.output.resolve()
    if out.exists():raise ValueError('Attribute retransfer requires a new staging directory')
    body=arrays(stage/'neck_geometry.npz');old=arrays(stage/'body_prepared.npz')
    native=load_dae(args.native);reference=load_dae(args.reference)
    preserved={key:bool(np.array_equal(native[key],reference[key])) for key in
        ('triangles','bone_weights','inverse_bind')}
    preserved['bone_palette']=native['bone_palette']==reference['bone_palette']
    for semantic in ('TEXCOORD','COLOR'):
        preserved[semantic]=bool(np.array_equal(native['corners'][semantic],reference['corners'][semantic]))
    if not all(preserved.values()):raise ValueError('Lookup changed native semantic fields: '+str(preserved))
    prepared,transfer=transfer_native_surface(body,reference,native)
    prepared['source_face_ids']=body['source_face_ids']
    payload,quantization=body_payload(prepared,native)
    old_payload=json.loads((stage/'body_payload.json').read_text())['meshes'][0]
    new_payload=payload['meshes'][0]
    old_faces=old['triangles'];new_faces=prepared['triangles']
    checks={key:bool(np.array_equal(old[key][old_faces],prepared[key][new_faces]))
        for key in ('positions','normals','bone_weights','source_vertex_ids','geometry_vertex_ids')}
    checks['source_face_ids']=bool(np.array_equal(old['source_face_ids'],prepared['source_face_ids']))
    checks['geometry_triangle_ids']=bool(np.array_equal(prepared['geometry_vertex_ids'][new_faces],body['triangles']))
    checks['bone_palette']=old_payload['bone_palette']==new_payload['bone_palette']
    for key in ('bone_indices','bone_weights'):
        checks['serialized_'+key]=bool(np.array_equal(np.asarray(old_payload[key])[old_faces],
            np.asarray(new_payload[key])[new_faces]))
    if not all(checks.values()):raise ValueError('Attribute retransfer changed donor geometry/skin: '+str(checks))
    out.mkdir(parents=True)
    for name in ('posed_dense.npz','neck_geometry.npz'):
        shutil.copy2(stage/name,out/name)
    np.savez_compressed(out/'body_prepared.npz',**prepared)
    path=out/'body_payload.json';path.write_text(json.dumps(payload,separators=(',',':'),allow_nan=False))
    report=json.loads((stage/'report.json').read_text())
    report.update(surface_transfer=transfer,export_quantization=quantization,
        reference=str(args.reference.resolve()),reference_sha256=sha(args.reference),
        payload=str(path),payload_sha256=sha(path),complete=True,
        surface_audit_status='attribute-only geometry parity verified; independent prepared/serialized audits pending',
        material_quality='same-field native UV/paint prototype; game material and motion unverified')
    report['attribute_retransfer']={'source_stage':str(stage),'source_payload_sha256':sha(stage/'body_payload.json'),
        'native_semantic_fields_bit_equal':preserved,'donor_face_corner_parity':checks,
        'source_posed_npz_byte_equal':sha(stage/'posed_dense.npz')==sha(out/'posed_dense.npz'),
        'source_neck_geometry_npz_byte_equal':sha(stage/'neck_geometry.npz')==sha(out/'neck_geometry.npz'),
        'old_export_vertices':len(old['positions']),'new_export_vertices':len(prepared['positions']),
        'only_attributes_changed':['native UV lookup','native RGB paint lookup','UV-derived tangent/binormal frames','UV-island seam duplication'],
        'invented_physics_paint':False}
    if args.reference_proof:
        report['attribute_retransfer']['reference_proof']={'path':str(args.reference_proof.resolve()),'sha256':sha(args.reference_proof)}
    (out/'report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({'payload':str(path),'sha256':sha(path),'transfer':transfer,
        'checks':checks,'reference_native_semantics':preserved},indent=2))


if __name__=='__main__':main()
