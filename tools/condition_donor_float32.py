"""Reproduce reviewed, source-fingerprinted Float32 donor export conditioning.

Creates a fresh local stage only; requires new complete prepared and actual
serialized audits. Original donor captures and source stages remain untouched.
"""
from __future__ import annotations
import argparse,copy,hashlib,json,shutil,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from nudegate.float32_conditioning import condition_float32_step,require_unconditioned_stage

FILES=('body_prepared.npz','neck_geometry.npz','body_payload.json','posed_dense.npz','report.json','global-pose-surface-audit.json')

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def load(path):
    with np.load(path,allow_pickle=False) as data:return dict(data)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--source-stage',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();config_path=args.config.resolve();config=json.loads(config_path.read_text())
    if config.get('schema_version')==2:
        from condition_donor_float32_vectors import vector_case
        return vector_case(args,config_path,config)
    if (config.get('schema_version')!=1 or config.get('no_predicate_or_pair_exceptions')is not True
            or config.get('requires_fresh_global_audits_and_actual_reexport')is not True):
        raise ValueError('A reviewed explicit representation-only configuration is required')
    source=args.source_stage.resolve()if args.source_stage else (ROOT/config['source_stage']).resolve()
    output=args.output.resolve()
    if output.exists()or output==source:raise ValueError('A fresh separate output stage is required')
    expected=config['expected_source_file_sha256']
    if set(expected)!=set(FILES):raise ValueError('Conditioning config must pin the complete reviewed source stage')
    hashes={name:sha(source/name)for name in FILES}
    if hashes!=expected:raise ValueError('Reviewed source-stage fingerprints changed')
    report=json.loads((source/'report.json').read_text())
    require_unconditioned_stage(report,source)
    patches=config.get('patches')
    if not isinstance(patches,list)or len(patches)!=1:raise ValueError('This schema permits exactly one reviewed correction')
    patch=patches[0]
    body,neck=[load(source/name)for name in ('body_prepared.npz','neck_geometry.npz')]
    old_body={k:v.copy()for k,v in body.items()};old_neck={k:v.copy()for k,v in neck.items()}
    payload=json.loads((source/'body_payload.json').read_text());old_payload=copy.deepcopy(payload)
    arguments={'expected_position':patch['before_float64_position'],'axis':patch['axis'],
        'ulp_direction':patch['ulp_direction'],'expected_before_float32':patch['before_float32_component'],
        'expected_after_float32':patch['after_float32_component'],'maximum_error_m':patch['maximum_allowed_error_m']}
    rows=patch['export_vertex_ids'];neck_rows=patch['neck_vertex_ids']
    if (any(int(body['source_vertex_ids'][row])!=patch['source_vertex_id']for row in rows)
            or any(int(body['geometry_vertex_ids'][row])!=patch['geometry_vertex_id']for row in rows)
            or neck_rows!=[patch['geometry_vertex_id']]):
        raise ValueError('Reviewed source/geometry vertex identity changed')
    body['positions'],detail=condition_float32_step(body['positions'],expected_rows=rows,**arguments)
    neck['positions'],_=condition_float32_step(neck['positions'],expected_rows=neck_rows,**arguments)
    mesh=payload['meshes'][0]
    if not np.array_equal(np.asarray(mesh['positions']),old_body['positions']):raise ValueError('Payload geometry differs from prepared source')
    for row in rows:mesh['positions'][row][patch['axis']]=detail['after_float32_component']
    if not np.array_equal(np.asarray(mesh['positions']),body['positions']):raise ValueError('Conditioned payload differs from prepared output')
    for arrays,original in ((body,old_body),(neck,old_neck)):
        for key in arrays:
            if key!='positions'and(arrays[key].dtype!=original[key].dtype or arrays[key].tobytes()!=original[key].tobytes()):
                raise ValueError('An unrelated source array changed: '+key)
    if any(mesh[key]!=old_payload['meshes'][0][key]for key in mesh if key!='positions')or payload['meshes'][1:]!=old_payload['meshes'][1:]:
        raise ValueError('Unrelated payload attributes or proxy changed')
    for name in FILES:
        if sha(source/name)!=hashes[name]:raise ValueError('Source changed during conditioning')
    output.mkdir(parents=True)
    for name in ('posed_dense.npz','global-pose-surface-audit.json'):shutil.copyfile(source/name,output/name)
    np.savez_compressed(output/'body_prepared.npz',**body);np.savez_compressed(output/'neck_geometry.npz',**neck)
    payload_path=output/'body_payload.json';payload_path.write_text(json.dumps(payload,separators=(',',':'),allow_nan=False))
    report['payload']=str(payload_path);report['payload_sha256']=sha(payload_path)
    report['post_neck_numeric_conditioning']={'configuration':str(config_path),'configuration_sha256':sha(config_path),
        'reviewed_case':config['id'],'source_file_sha256':hashes,'patch':dict(patch,**detail),
        'all_nonposition_arrays_bit_exact':True,'all_other_payload_attributes_equal':True,
        'original_capture_and_pose_unchanged':True,'surface_safety':'Requires fresh prepared and actual serialized global audits'}
    report['neck']['neck_operation_only_outside_neck_position_error']=report['neck']['outside_neck_position_error']
    report['neck']['outside_neck_position_error']=detail['displacement_from_original_float64_m']
    report['surface_audit_status']='Pending fresh global audits and actual GR2 re-export after reviewed Float32 conditioning'
    (output/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    (output/'numeric-conditioning-config.json').write_text(json.dumps(config,indent=2,allow_nan=False)+'\n')
    proof={'source_file_sha256':hashes,'configuration_sha256':sha(config_path),'patch':dict(patch,**detail),
        'new_file_sha256':{name:sha(output/name)for name in FILES},'source_files_unchanged':True,
        'all_nonposition_arrays_bit_exact':True,'all_other_payload_attributes_equal':True,
        'scope':'Reproduction parity only; this does not replace fresh global/serialized surface audits'}
    (output/'numeric-conditioning-parity.json').write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps({'output':str(output),'payload_sha256':report['payload_sha256'],'patch':detail},indent=2))

if __name__=='__main__':main()
