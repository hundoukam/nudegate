"""Bounded local fitting cleanup for an explicitly audited donor pose.

The source topology is never changed. Only declared one-ring neighborhoods of
the supplied new contacts may move, inside narrow underarm/groin masks, with a
hard one-millimetre cumulative displacement limit. All other vertices are exact.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import time
import numpy as np

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from nudegate.donor_body import sha,normalized_deform_weights
from nudegate.surface_intersections import SurfaceIntersectionChecker,_exact_pair_intersects


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--pose',type=Path,required=True)
    parser.add_argument('--audit',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--max-displacement',type=float,default=.001)
    args=parser.parse_args()
    if not 0<args.max_displacement<=.001:raise ValueError('Review bounds permit at most one millimetre')
    if args.output.exists():raise ValueError('Corrective requires a new staging directory')
    args.output.mkdir(parents=True)
    with np.load(args.pose) as source:posed={k:source[k] for k in source.files}
    with np.load(args.source) as source:raw={k:source[k] for k in source.files}
    metadata=json.loads(args.source.with_suffix('.json').read_text())
    source_report=json.loads(args.pose.with_name('report.json').read_text())
    baseline=raw['positions'][:,[0,2,1]]*source_report['uniform_scale']
    triangles=raw['triangles'][:,[0,2,1]]
    if not np.array_equal(triangles,posed['triangles']):raise ValueError('Corrective requires unchanged original donor topology')
    original=posed['positions'].copy();current=original.copy()
    audit=json.loads(args.audit.read_text());proof=audit.get('proof',audit)
    original_pairs=[tuple(pair) for pair in proof['introduced_intersection_pairs']]
    seed=np.unique(triangles[np.array(original_pairs).reshape(-1)])
    incident=np.any(np.isin(triangles,seed),axis=1)
    neighborhood=np.unique(triangles[incident])
    allowed=np.zeros(len(current),bool);allowed[neighborhood]=True
    x,y,z=current.T
    underarm=(abs(x)>.115)&(abs(x)<.23)&(y>1.35)&(y<1.47)&(z>-.04)&(z<.145)
    groin=(abs(x)<.07)&(y>.94)&(y<1.025)&(z>-.085)&(z<.035)
    breast=(posed['source_breast_influence_left']+posed['source_breast_influence_right'])>0
    allowed&=(underarm|groin)&~breast
    # Source arm/clavicle/leg influences establish that this is a pose region.
    weights,names,bones,_=normalized_deform_weights(raw,metadata)
    clavicle=weights[:,[names.index('DEF-shoulder.'+s) for s in ('L','R')]].sum(1)
    allowed&=(posed['limb_influence']+clavicle)>0
    # Analysis-only coincidence groups. Coordinates are not merged or welded.
    _,group=np.unique(original,axis=0,return_inverse=True)
    members=np.bincount(group);group_count=len(members)
    fixed_members=np.bincount(group,weights=(~allowed).astype(int),minlength=group_count)
    group_allowed=(fixed_members==0)
    displacement=np.zeros((group_count,3));group_origin=np.empty_like(displacement)
    group_origin[group]=original
    inverse_cost=1/np.maximum(members,1)
    group_order=np.argsort(group,kind='stable');group_offsets=np.r_[0,np.cumsum(members)]
    checker=SurfaceIntersectionChecker(baseline,triangles,topology_id='juno_e_original')
    print('SOURCE_BASELINE '+str(len(checker.source_pairs)),flush=True)
    initial=checker.check(current)
    if set(map(tuple,initial['introduced_intersection_pairs']))!=set(original_pairs):
        raise ValueError('Supplied audit does not describe the exact input pose')
    cross0=np.cross(original[triangles[:,1]]-original[triangles[:,0]],original[triangles[:,2]]-original[triangles[:,0]])
    area0=np.linalg.norm(cross0,axis=1)*.5
    touched=np.any(allowed[triangles],axis=1)
    pair_history=[];pairs=list(original_pairs);margin=2e-6

    def coordinates():return group_origin[group]+displacement[group]

    def update_group(g):
        rows=group_order[group_offsets[g]:group_offsets[g+1]]
        current[rows]=group_origin[g]+displacement[g]

    def valid_surface(points):
        q=points[triangles[touched]];cross=np.cross(q[:,1]-q[:,0],q[:,2]-q[:,0])
        return bool(np.all(np.linalg.norm(cross,axis=1)*.5>1e-12) and
                    np.all(np.sum(cross*cross0[touched],axis=1)>0))

    def option(anchor,moved,sign):
        a=current[anchor];b=current[moved];normal=np.cross(a[1]-a[0],a[2]-a[0])
        length=np.linalg.norm(normal)
        if length<1e-14:return None
        normal=normal/length*sign;ga=group[anchor];shared=set(ga.tolist())
        constraints=[];cost=0
        for vertex in moved:
            gb=int(group[vertex])
            if gb in shared:continue
            distance=float((current[vertex]-a.mean(0))@normal)-margin
            if distance>=0:continue
            coefficients={gb:1.}
            for g in ga:coefficients[int(g)]=coefficients.get(int(g),0)-1/3
            coefficients={g:c for g,c in coefficients.items() if group_allowed[g] and abs(c)>1e-15}
            denominator=sum(c*c*inverse_cost[g] for g,c in coefficients.items())
            if denominator<=0:return None
            cost+=distance*distance/denominator
            constraints.append((int(vertex),anchor,normal,coefficients,denominator))
        if not constraints:return None
        return cost,constraints

    started=time.perf_counter();last_global=initial
    for phase in range(5):
        for iteration in range(80):
            before=displacement.copy()
            for ia,ib in pairs:
                a,b=triangles[ia],triangles[ib]
                if not _exact_pair_intersects(current[a],current[b],checker.welded_triangles[ia],
                        checker.welded_triangles[ib],checker.tolerance):continue
                alternatives=[v for v in (option(a,b,1),option(a,b,-1),option(b,a,1),option(b,a,-1)) if v is not None]
                if not alternatives:continue
                _,constraints=min(alternatives,key=lambda item:item[0])
                for vertex,anchor,normal,coefficients,denominator in constraints:
                    distance=float((current[vertex]-current[anchor].mean(0))@normal)-margin
                    if distance>=0:continue
                    scale=-distance/denominator*.8
                    for g,c in coefficients.items():
                        step=normal*(scale*c*inverse_cost[g])
                        step_norm=np.linalg.norm(step)
                        if step_norm>.00005:step*=.00005/step_norm
                        displacement[g]+=step
                        norm=np.linalg.norm(displacement[g])
                        if norm>args.max_displacement:displacement[g]*=args.max_displacement/norm
                        update_group(g)
            for _ in range(40):
                if valid_surface(current):break
                displacement=(before+displacement)*.5;current=coordinates()
            else:
                displacement=before;current=coordinates()
                print('LOCAL_STALL orientation guard',flush=True)
                break
            remaining=[]
            for ia,ib in pairs:
                if _exact_pair_intersects(current[triangles[ia]],current[triangles[ib]],
                    checker.welded_triangles[ia],checker.welded_triangles[ib],checker.tolerance):remaining.append((ia,ib))
            pair_history.append({'phase':phase,'iteration':iteration,'remaining_tracked_pairs':len(remaining),
                'maximum_displacement_m':float(np.linalg.norm(displacement,axis=1).max())})
            if iteration%5==0:print('LOCAL '+json.dumps(pair_history[-1]),flush=True)
            if not remaining:break
            if np.max(abs(displacement-before))<1e-10:break
        last_global=checker.check(current)
        print('GLOBAL '+json.dumps({'phase':phase,'new_pairs':last_global['introduced_intersection_count'],
            'collapsed':last_global['new_collapsed_faces']}),flush=True)
        if last_global['safe']:break
        pairs=list(map(tuple,last_global['introduced_intersection_pairs']))
    delta=current-original;changed=np.flatnonzero(np.linalg.norm(delta,axis=1)>1e-12)
    if np.linalg.norm(delta,axis=1).max()>args.max_displacement+1e-12:raise ValueError('Corrective exceeded its displacement bound')
    if not np.array_equal(current[~allowed],original[~allowed]):raise ValueError('Corrective changed protected/outside vertices')
    cross=np.cross(current[triangles[:,1]]-current[triangles[:,0]],current[triangles[:,2]]-current[triangles[:,0]])
    area=np.linalg.norm(cross,axis=1)*.5
    posed['positions']=current;posed['pose_displacement']=current-posed['scaled_source_positions']
    posed['local_pose_corrective_displacement']=delta
    np.savez_compressed(args.output/'posed_dense.npz',**posed)
    report=source_report.copy();report['local_pose_corrective']={
        'input_pose':str(args.pose.resolve()),'input_pose_sha256':sha(args.pose),
        'input_audit':str(args.audit.resolve()),'input_audit_sha256':sha(args.audit),
        'original_new_pair_count':len(original_pairs),'final_new_pair_count':last_global['introduced_intersection_count'],
        'declared_one_ring_source_vertex_ids':neighborhood.tolist(),'allowed_source_vertex_ids':np.flatnonzero(allowed).tolist(),
        'changed_source_vertex_ids':changed.tolist(),'deltas_m':delta[changed].tolist(),
        'maximum_delta_m':float(np.linalg.norm(delta,axis=1).max()),
        'rms_delta_changed_m':float(np.sqrt(np.mean(np.sum(delta[changed]**2,axis=1)))) if len(changed) else 0,
        'all_outside_and_protected_positions_bit_equal':True,'breast_weighted_vertices_changed':0,
        'new_collapsed_faces':int((area<=1e-12).sum()),
        'local_area_ratio_min':float((area[touched]/area0[touched]).min()),
        'local_area_ratio_max':float((area[touched]/area0[touched]).max()),
        'new_reversed_faces_from_input_pose':int((np.sum(cross*cross0,axis=1)<0).sum()),
        'bound_m':args.max_displacement,'safety_clearance_m':margin,
        'algorithm':'minimum-cost local signed-plane constraints with hard cumulative displacement projection; no smoothing',
        'iteration_history':pair_history,'elapsed_seconds':time.perf_counter()-started,
        'passed':last_global['safe']}
    (args.output/'report.json').write_text(json.dumps(report,indent=2))
    (args.output/'corrective-global-audit.json').write_text(json.dumps(last_global,indent=2))
    print('CORRECTIVE_RESULT '+json.dumps({k:v for k,v in report['local_pose_corrective'].items()
        if k not in ('declared_one_ring_source_vertex_ids','allowed_source_vertex_ids','changed_source_vertex_ids','deltas_m','iteration_history')}),flush=True)
    if not last_global['safe']:raise SystemExit(2)


if __name__=='__main__':main()
