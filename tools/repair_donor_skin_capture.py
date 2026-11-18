"""Apply enumerated skin-only repairs into NEW local donor captures.

Original geometry, UVs, sources and raw skin captures remain unchanged. This is
not a general unweighted-vertex fallback or arbitrary weight-clamping utility.
"""
from pathlib import Path
import argparse,copy,hashlib,json,sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from export_blender_donors import sparse_vertex_groups,verify_reference_arrays

KIRIKO_RESIDUALS={17185:-2.5679188553340282e-08,17342:-4.282955934353794e-12,
                  19798:-3.5653133223512157e-10,263457:-3.5653133223512157e-10}
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()


def repair_mercy(arrays,metadata):
    result={name:value.copy() for name,value in arrays.items()}
    vertex=12941
    if len(result['positions'])<=vertex or np.any(result['triangles']==vertex):
        raise ValueError('Mercy placeholder requires the exact nonrendered orphan vertex')
    active=set(metadata['vertex_group_validation']['active_vertex_group_rigs'])
    deform={b['name'] for r in metadata['rigs'] if r['name'] in active for b in r['bones'] if b['deform']}
    start,end=result['group_offsets'][vertex:vertex+2]
    if any(metadata['vertex_group_names'][i] in deform and w>0 for i,w in
           zip(result['group_indices'][start:end],result['group_weights'][start:end])):
        raise ValueError('Mercy orphan already has a deform assignment')
    if 'DEF-spine' not in deform:raise ValueError('Missing reviewed Mercy root placeholder bone')
    index=metadata['vertex_group_names'].index('DEF-spine')
    result['group_indices']=np.insert(result['group_indices'],end,index)
    result['group_weights']=np.insert(result['group_weights'],end,1.)
    result['group_offsets'][vertex+1:]+=1
    return result,{'kind':'nonrendered orphan placeholder','source_vertex_ids':[vertex],
        'group':'DEF-spine','weight':1.,'incident_triangles':0,'rendered_vertices_changed':0,
        'geometry_changed':False,'reason':'Unreferenced source vertex is compacted out before the render body is exported.'}


def repair_kiriko(arrays,metadata):
    result={name:value.copy() for name,value in arrays.items()}
    outside=np.flatnonzero((result['group_weights']<0)|(result['group_weights']>1)).tolist()
    if outside!=list(KIRIKO_RESIDUALS):raise ValueError('Kiriko residual assignment IDs changed')
    changes=[]
    for index,value in KIRIKO_RESIDUALS.items():
        if result['group_weights'][index]!=value:raise ValueError('Kiriko residual value changed')
        changes.append({'csr_index':index,
            'source_vertex_id':int(np.searchsorted(result['group_offsets'],index,side='right')-1),
            'group':metadata['vertex_group_names'][result['group_indices'][index]],'before':value,'after':0.})
        result['group_weights'][index]=0.
    return result,{'kind':'four explicitly enumerated negative evaluation residuals','changes':changes,
        'maximum_absolute_weight_delta':max(abs(value) for value in KIRIKO_RESIDUALS.values()),
        'geometry_changed':False,'normalization_applied':False}


def stage(identifier,source_dir,reference_dir,output):
    path=source_dir/(identifier+'.npz');destination=output/path.name
    if destination.exists() or destination.with_suffix('.json').exists():
        raise ValueError('Skin repair requires fresh output files')
    metadata_path=path.with_suffix('.json');metadata=json.loads(metadata_path.read_text())
    reference=reference_dir/path.name;frozen_metadata=json.loads(reference.with_suffix('.json').read_text())
    if (metadata.get('id')!=identifier or frozen_metadata.get('id')!=identifier
            or sha(path)!=metadata['npz_sha256'] or sha(reference)!=frozen_metadata['npz_sha256']
            or metadata['source_sha256']!=frozen_metadata['source_sha256']
            or metadata['source_sha256_after']!=metadata['source_sha256']):
        raise ValueError('Raw and frozen capture source fingerprints do not agree')
    with np.load(path,allow_pickle=False) as loaded:original=dict(loaded)
    with np.load(reference,allow_pickle=False) as loaded:frozen=dict(loaded)
    verify_reference_arrays(frozen,original)
    arrays,repair=(repair_mercy if identifier=='mercy_c' else repair_kiriko)(original,metadata)
    for name in original:
        if name not in ('group_offsets','group_indices','group_weights'):
            if original[name].tobytes()!=arrays[name].tobytes():raise ValueError('Skin repair changed '+name)
    verify_reference_arrays(frozen,arrays)
    active=set(metadata['vertex_group_validation']['active_vertex_group_rigs'])
    deform={b['name'] for r in metadata['rigs'] if r['name'] in active for b in r['bones'] if b['deform']}
    _,validation=sparse_vertex_groups(
        [list(zip(arrays['group_indices'][a:b].tolist(),arrays['group_weights'][a:b].tolist()))
         for a,b in zip(arrays['group_offsets'][:-1],arrays['group_offsets'][1:])],metadata['vertex_group_names'],deform)
    validation['active_vertex_group_rigs']=metadata['vertex_group_validation']['active_vertex_group_rigs']
    output.mkdir(parents=True,exist_ok=True)
    np.savez_compressed(destination,**arrays)
    result=copy.deepcopy(metadata)
    result.update(npz=str(destination.resolve()),npz_sha256=sha(destination),vertex_group_validation=validation,
        raw_skin_capture={'path':str(path.resolve()),'sha256':sha(path),'metadata_sha256':sha(metadata_path)},
        explicit_skin_repair=repair)
    destination.with_suffix('.json').write_text(json.dumps(result,indent=2)+'\n')
    return {'id':identifier,'output':str(destination.resolve()),'sha256':sha(destination),'repair':repair}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selection',nargs='+',choices=('mercy_c','kiriko_2_0_c'),default=['mercy_c','kiriko_2_0_c'])
    parser.add_argument('--source',type=Path,default=ROOT/'build/donors/skinned-others')
    parser.add_argument('--reference',type=Path,default=ROOT/'build/donors/selected')
    parser.add_argument('--output',type=Path,default=ROOT/'build/donors/skinned-repaired')
    args=parser.parse_args()
    for identifier in args.selection:print(json.dumps(stage(identifier,args.source,args.reference,args.output),indent=2))


if __name__=='__main__':main()
