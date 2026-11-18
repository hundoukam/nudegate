"""Opt-in schema2 bounded vector cases; schema1 remains in the original tool."""
from __future__ import annotations
import copy,hashlib,json,shutil,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from nudegate.float32_conditioning import condition_float32_vector,require_unconditioned_stage

FILES=('body_prepared.npz','neck_geometry.npz','body_payload.json','posed_dense.npz','report.json')
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def load(path):
    with np.load(path,allow_pickle=False)as data:return dict(data)


def vector_case(args,config_path,config):
    if (config.get('schema_version')!=2 or config.get('no_predicate_or_pair_exceptions')is not True
            or config.get('requires_fresh_global_audits_and_actual_reexport')is not True):
        raise ValueError('A reviewed bounded vector configuration is required')
    source=args.source_stage.resolve()if args.source_stage else(ROOT/config['source_stage']).resolve()
    output=args.output.resolve()
    if output.exists()or output==source:raise ValueError('A fresh separate output stage is required')
    expected=config['expected_source_file_sha256']
    if set(expected)!=set(FILES):raise ValueError('Vector configuration must pin the complete reviewed source stage')
    hashes={name:sha(source/name)for name in FILES}
    if hashes!=expected:raise ValueError('Reviewed source-stage fingerprints changed')
    report=json.loads((source/'report.json').read_text())
    require_unconditioned_stage(report,source)
    audit_path=(ROOT/config['source_pose_audit']).resolve()
    if sha(audit_path)!=config['source_pose_audit_sha256']:raise ValueError('Source pose proof changed')
    pose_audit=json.loads(audit_path.read_text())
    if pose_audit['posed_npz_sha256']!=hashes['posed_dense.npz']or pose_audit['proof']['safe']is not True:
        raise ValueError('Original pose requires its own matching passed source proof')
    guard=config['source_material_guard'];raw_path=(ROOT/guard['npz']).resolve();metadata_path=(ROOT/guard['metadata']).resolve()
    if sha(raw_path)!=guard['npz_sha256']or sha(metadata_path)!=guard['metadata_sha256']:
        raise ValueError('Reviewed source material provenance changed')
    raw=load(raw_path);metadata=json.loads(metadata_path.read_text())
    if metadata['id']!=guard['source_id']or metadata['npz_sha256']!=guard['npz_sha256']:
        raise ValueError('Conditioning source identity differs from reviewed capture')
    material=metadata['materials'].index(guard['exclusive_material_name'])
    source_faces=raw['triangles'];indices=raw['triangle_material_indices']
    exclusive=set(source_faces[indices==material].ravel())-set(source_faces[indices!=material].ravel())
    patches=config.get('patches')
    if not isinstance(patches,list)or not 1<=len(patches)<=64:
        raise ValueError('Vector schema requires 1–64 explicit disjoint copy groups')
    body,neck=[load(source/name)for name in('body_prepared.npz','neck_geometry.npz')]
    old_body={k:v.copy()for k,v in body.items()};old_neck={k:v.copy()for k,v in neck.items()}
    payload=json.loads((source/'body_payload.json').read_text());old_payload=copy.deepcopy(payload)
    if not np.array_equal(np.asarray(payload['meshes'][0]['positions']),body['positions']):
        raise ValueError('Payload geometry differs from prepared source')
    details=[];used=set()
    for patch in patches:
        rows=patch['export_vertex_ids'];neck_rows=patch['neck_vertex_ids']
        if (used.intersection(rows)or body['source_vertex_ids'][rows].tolist()!=patch['source_vertex_ids']
                or body['geometry_vertex_ids'][rows].tolist()!=patch['geometry_vertex_ids']
                or set(body['geometry_vertex_ids'][rows])!=set(neck_rows)
                or not all(int(value)in exclusive for value in body['source_vertex_ids'][rows])):
            raise ValueError('Reviewed material-exclusive source/copy identity changed')
        used.update(rows)
        arguments={'expected_position':patch['before_float64_position'],
            'conditioned_position':patch['after_float64_position'],'maximum_error_m':patch['maximum_allowed_error_m']}
        body['positions'],detail=condition_float32_vector(body['positions'],expected_rows=rows,**arguments)
        neck['positions'],_=condition_float32_vector(neck['positions'],expected_rows=neck_rows,**arguments)
        details.append(dict(patch,**detail))
    payload['meshes'][0]['positions']=body['positions'].tolist()
    for arrays,original in((body,old_body),(neck,old_neck)):
        for key in arrays:
            if key!='positions'and(arrays[key].dtype!=original[key].dtype or arrays[key].tobytes()!=original[key].tobytes()):
                raise ValueError('An unrelated source array changed: '+key)
    if any(payload['meshes'][0][key]!=old_payload['meshes'][0][key]for key in payload['meshes'][0]if key!='positions'):
        raise ValueError('Unrelated payload attributes changed')
    if any(payload[key]!=old_payload[key]for key in payload if key!='meshes')or payload['meshes'][1:]!=old_payload['meshes'][1:]:
        raise ValueError('Unrelated proxy or top-level payload changed')
    changed=np.any(body['positions']!=old_body['positions'],axis=1)
    if set(np.flatnonzero(changed))!=used:raise ValueError('Vector configuration changed unexpected export rows')
    maximum=float(np.linalg.norm(body['positions']-old_body['positions'],axis=1).max())
    if maximum>2e-7:raise ValueError('Combined conditioning exceeds original-relative vector budget')
    for name in FILES:
        if sha(source/name)!=hashes[name]:raise ValueError('Source changed during conditioning')
    for path,pin in ((raw_path,guard['npz_sha256']),(metadata_path,guard['metadata_sha256']),
                     (audit_path,config['source_pose_audit_sha256'])):
        if sha(path)!=pin:raise ValueError('Source provenance changed during conditioning')
    output.mkdir(parents=True)
    shutil.copyfile(source/'posed_dense.npz',output/'posed_dense.npz')
    shutil.copyfile(audit_path,output/'global-pose-surface-audit.json')
    np.savez_compressed(output/'body_prepared.npz',**body);np.savez_compressed(output/'neck_geometry.npz',**neck)
    payload_path=output/'body_payload.json';payload_path.write_text(json.dumps(payload,separators=(',',':'),allow_nan=False))
    report['payload']=str(payload_path);report['payload_sha256']=sha(payload_path)
    report['post_neck_numeric_conditioning']={'schema_version':2,'configuration':str(config_path),
        'configuration_sha256':sha(config_path),'reviewed_case':config['id'],'source_file_sha256':hashes,
        'patches':details,'maximum_displacement_from_original_float64_m':maximum,
        'all_nonposition_arrays_bit_exact':True,'all_other_payload_attributes_equal':True,
        'original_capture_pose_and_pre_neck_positions_unchanged':True,'material_guard':guard,
        'surface_safety':'Requires fresh prepared and actual serialized global audits'}
    report['neck']['neck_operation_only_outside_neck_position_error']=report['neck']['outside_neck_position_error']
    report['neck']['outside_neck_position_error']=maximum
    report['surface_audit_status']='Pending fresh global prepared and actual Float32 audits after bounded vector conditioning'
    (output/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    (output/'numeric-conditioning-config.json').write_text(json.dumps(config,indent=2,allow_nan=False)+'\n')
    proof={'source_file_sha256':hashes,'configuration_sha256':sha(config_path),'patches':details,
        'changed_export_rows':int(changed.sum()),'maximum_displacement_from_original_float64_m':maximum,
        'original_source_material':guard['exclusive_material_name'],'all_other_source_material_vertices_unchanged':True,
        'all_nonposition_arrays_bit_exact':True,'all_other_payload_attributes_equal':True,
        'source_files_unchanged':True,'scope':'Parity only; requires independent global/serialized surface proof'}
    (output/'numeric-conditioning-parity.json').write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps({'output':str(output),'payload_sha256':report['payload_sha256'],
        'changed_export_rows':int(changed.sum()),'maximum_displacement_m':maximum},indent=2))
