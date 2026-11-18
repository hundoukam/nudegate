"""Author a state-specific native proxy through exact donor shape correspondence.

Only a disposable template's existing proxy positions change. The actual dense
render donor is never fitted, and its source arrays remain read-only.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from nudegate.collada import ColladaMesh
from nudegate.donor_body import (BODY_NAME,load_dae,vertex_normals,transport_corresponding_surface,sha)
from nudegate.donor_body import closest_triangles
from nudegate.surface_intersections import SurfaceIntersectionChecker


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from-donor',type=Path,required=True)
    parser.add_argument('--to-donor',type=Path,required=True)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--native',type=Path,default=ROOT/'build/physics-probe/matched-v1/model-roundtrip/human_normal/source.dae')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--painted-body',type=Path,help='Prepared body for provisional paint-marked proxy coverage distances')
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    with np.load(args.from_donor) as d:source={k:d[k] for k in d.files}
    with np.load(args.to_donor) as d:target={k:d[k] for k in d.files}
    if not np.array_equal(source['source_vertex_ids'],target['source_vertex_ids']):
        raise ValueError('Donor states do not share exact original vertex identity')
    provenance=[];loop_maps=[]
    for pose_path in (args.from_donor,args.to_donor):
        pose_report=json.loads(pose_path.with_name('report.json').read_text())
        raw_path=Path(pose_report['source_npz']);metadata=json.loads(raw_path.with_suffix('.json').read_text())
        with np.load(raw_path) as raw:
            loops=raw['corner_loop_indices'].reshape(-1);vertices=raw['triangles'].reshape(-1)
            unique,first,inverse=np.unique(loops,return_index=True,return_inverse=True)
            mapping=vertices[first]
            if not np.array_equal(mapping[inverse],vertices):raise ValueError('Original polygon loop changes vertex identity')
            loop_maps.append(np.column_stack([unique,mapping]))
        provenance.append({'source':metadata['source'],'source_sha256':metadata['source_sha256'],
            'body_mesh':metadata['body_mesh'],'original_counts':metadata['original_counts'],
            'raw_capture':str(raw_path),'raw_capture_sha256':sha(raw_path)})
    if not np.array_equal(loop_maps[0],loop_maps[1]):raise ValueError('Original donor polygon-loop topology differs')
    for key in ('source_sha256','body_mesh','original_counts'):
        if provenance[0][key]!=provenance[1][key]:raise ValueError('Corresponding donor provenance differs: '+key)
    proxy_id=BODY_NAME+'_Cloth_Physics-geom'
    reference=load_dae(args.reference,proxy_id);p=reference['positions'];triangles=reference['triangles']
    normals=vertex_normals(p,triangles)
    candidate,jac,correspondence=transport_corresponding_surface(p,normals,
        source['positions'],target['positions'],source['triangles'])
    determinant=np.linalg.det(jac)
    if determinant.min()<=.01:raise ValueError('Proxy correspondence has a folded/singular analytic chart: '+str(determinant.min()))
    proxy=ColladaMesh.load(args.reference,geometry_id=proxy_id)
    proxy.set_positions(candidate.tolist(),recalculate_normals=True)
    output=out/'fitted_proxy.dae';proxy.save(output)
    # Native lookup render geometry is disposable and stays exact; final dense
    # geometry replaces it before high-resolution mapping regeneration.
    body=ColladaMesh.load(args.reference,geometry_id=BODY_NAME+'-geom')
    jac_path=out/'fitted_proxy.jacobians.json'
    jac_path.write_text(json.dumps({'geometries':{BODY_NAME+'-geom':{
        'jacobians':np.broadcast_to(np.eye(3),(len(body.positions),3,3)).tolist()},
        proxy_id:{'jacobians':jac.tolist()}}},separators=(',',':')))
    native=load_dae(args.native,proxy_id)
    proof=SurfaceIntersectionChecker(native['positions'],native['triangles'],topology_id='native-proxy').check(candidate)
    previous_proof=SurfaceIntersectionChecker(p,triangles,topology_id='previous-state-proxy').check(candidate)
    np.savez_compressed(out/'proxy_correspondence.npz',positions=candidate,jacobians=jac,
        source_proxy_positions=p,triangles=triangles,**correspondence)
    report={'schema_version':1,'purpose':'state-specific disposable native proxy template',
        'from_donor':str(args.from_donor.resolve()),'from_donor_sha256':sha(args.from_donor),
        'to_donor':str(args.to_donor.resolve()),'to_donor_sha256':sha(args.to_donor),
        'reference':str(args.reference.resolve()),'reference_sha256':sha(args.reference),
        'native':str(args.native.resolve()),'native_sha256':sha(args.native),
        'output':str(output),'output_sha256':sha(output),'jacobians':str(jac_path),
        'method':'F(p)=p+sum(plane-barycentric_i(p)*(target_donor_i-source_donor_i)); nearest agreeing original donor face',
        'raw_source_provenance':provenance,'source_polygon_loop_vertex_map_bit_equal':True,
        'evaluated_triangle_indices_equal':bool(np.array_equal(source['triangles'],target['triangles'])),
        'triangulation_policy':'Original vertex and polygon-loop identity are exact; chart uses from-state triangle diagonals on target positions',
        'dense_donor_geometry_changed':False,'lookup_render_geometry_changed':False,
        'proxy_vertices':len(candidate),'proxy_triangles':len(triangles),
        'minimum_proxy_jacobian_determinant':float(determinant.min()),
        'maximum_proxy_displacement_m':float(np.linalg.norm(candidate-p,axis=1).max()),
        'source_surface_distance_mean_m':float(correspondence['source_surface_distance'].mean()),
        'source_surface_distance_max_m':float(correspondence['source_surface_distance'].max()),
        'native_proxy_proof':proof,'previous_proxy_proof':previous_proof,
        'passed':proof['safe'] and previous_proof['safe']}
    if args.painted_body:
        from scipy.spatial import cKDTree
        with np.load(args.painted_body) as prepared:
            ids=prepared['source_vertex_ids'];mark=(prepared['colors_rgba8'][:,0]>0)&(ids>=0)
            query=target['positions'][ids[mark]]
        triangles_p=candidate[triangles];tree=cKDTree(triangles_p.mean(1))
        _,faces=tree.query(query,k=min(64,len(triangles)))
        _,distance=closest_triangles(query[:,None,:],triangles_p[faces]);surface=np.sqrt(distance.min(1))
        distance3,_=cKDTree(candidate).query(query,k=3)
        report['provisional_painted_body_coverage']={'prepared_body':str(args.painted_body.resolve()),
            'prepared_body_sha256':sha(args.painted_body),'painted_rows':len(query),
            'positions':'same original donor vertex IDs at to-donor pose; paint remains provisional native-reference paint',
            'surface_distance_mean_m':float(surface.mean()),'surface_distance_p95_m':float(np.percentile(surface,95)),
            'surface_distance_p99_m':float(np.percentile(surface,99)),'surface_distance_max_m':float(surface.max()),
            'nearest_vertex_distance_mean_m':float(distance3[:,0].mean()),
            'third_nearest_vertex_distance_p99_m':float(np.percentile(distance3[:,2],99)),
            'third_nearest_vertex_distance_max_m':float(distance3[:,2].max()),
            'actual_primary_mapper_readback':'pending; these distances do not replace native mapper verification'}
    (out/'proxy-fit-report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in report.items() if not k.endswith('proof')},indent=2))


if __name__=='__main__':main()
