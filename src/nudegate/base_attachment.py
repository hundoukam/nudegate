"""Bounded lower/medial-pole fairing for the reviewed new adult body collection.

This is a local candidate corrective, not an age classifier or a replacement
for final triangle-intersection validation. It preserves topology, seams, source
attachments and the upper-pole/apex neighborhood. Legacy assets are not inputs
to an automatic write or replacement operation.
"""
from __future__ import annotations

from collections import defaultdict
import math

from .body_shapes import band, smooth


def _finite(value):
    if isinstance(value,bool) or not isinstance(value,(int,float)):return False
    try:return math.isfinite(value)
    except OverflowError:return False


def _points(values, label):
    if not isinstance(values,(list,tuple)) or not values:
        raise ValueError(label+' must be a nonempty position list')
    result=[]
    for point in values:
        if (not isinstance(point,(list,tuple)) or len(point)!=3
                or any(not _finite(value) for value in point)):
            raise ValueError(label+' requires finite XYZ coordinates')
        result.append([float(value) for value in point])
    return result


def round_base_attachments(mesh:dict, positions:list, *, passes:int=32,
                           strength:float=.35, maximum_correction_metres:float=.012) -> dict:
    """Fair only an explicitly reviewed body's lower and medial attachment.

    ``mesh`` supplies original positions, triangles, locked_vertices, reviewed
    chest_left/right masks, frame, and topology_id. ``positions`` is the new
    collection's already baked base. The function returns positions/report and
    changes no source object or asset. A separate actual-intersection proof is
    required before the returned candidate is accepted for export.
    """
    if not isinstance(mesh,dict):raise ValueError('Expected reviewed source mesh')
    if not isinstance(mesh.get('topology_id'),str) or not mesh['topology_id'].strip():
        raise ValueError('Corrective requires an explicit reviewed topology identifier')
    source=_points(mesh.get('positions'),'Source')
    target=_points(positions,'Target')
    if len(source)!=len(target):raise ValueError('Target vertex count differs from source')
    if type(passes) is not int or not 0<=passes<=100:raise ValueError('Fairing passes must be within 0..100')
    if not _finite(strength) or not 0<strength<=.5:raise ValueError('Fairing strength must be within (0,.5]')
    if not _finite(maximum_correction_metres) or not 0<maximum_correction_metres<=.025:
        raise ValueError('Fairing correction bound must be within (0,.025] metres')
    frame=mesh.get('frame',[1,1,1])
    if (not isinstance(frame,(list,tuple)) or len(frame)!=3
            or any(not _finite(value) or not .8<=value<=1.4 for value in frame)):raise ValueError('Invalid reviewed body frame')
    triangles=mesh.get('triangles')
    if (not isinstance(triangles,(list,tuple)) or not triangles
            or any(not isinstance(tri,(list,tuple)) or len(tri)!=3
                   or any(type(index) is not int or not 0<=index<len(source) for index in tri) for tri in triangles)):
        raise ValueError('Expected in-range source triangles')
    locked=mesh.get('locked_vertices')
    if (not isinstance(locked,(list,tuple,set))
            or any(type(index) is not int or not 0<=index<len(source) for index in locked)):
        raise ValueError('Invalid protected source vertices')
    locked=set(locked)
    if any(target[index]!=source[index] for index in locked):
        raise ValueError('Baked body moved a protected source attachment')
    groups=[];lookup={};vertex_groups=[]
    for index,point in enumerate(source):
        key=tuple(point)
        if key not in lookup:lookup[key]=len(groups);groups.append([])
        group=lookup[key];groups[group].append(index);vertex_groups.append(group)
        if target[index]!=target[groups[group][0]]:raise ValueError('Coincident source vertices must remain welded')
    canonical=[[source[indices[0]][axis]/frame[axis] for axis in range(3)] for indices in groups]
    initial=[[target[indices[0]][axis]/frame[axis] for axis in range(3)] for indices in groups]
    current=[list(point) for point in initial]
    blocked={group for group,indices in enumerate(groups) if locked.intersection(indices)}
    regions=mesh.get('regions',{})
    apex_groups={}
    for side,sign in (('left',-1),('right',1)):
        region=regions.get('chest_'+side)
        weights=region.get('weights') if isinstance(region,dict) else None
        if (not isinstance(weights,(list,tuple)) or len(weights)!=len(source)
                or any(not _finite(value) or not 0<=value<=1 for value in weights)):
            raise ValueError('Corrective requires reviewed chest masks')
        candidates=[group for group,indices in enumerate(groups)
                    if 1.30<canonical[group][1]<1.43 and sign*canonical[group][0]>.025
                    and any(weights[index]>0 for index in indices)]
        if not candidates:raise ValueError('Reviewed source has no protected upper-pole landmark')
        apex_groups[side]=min(candidates,key=lambda group:initial[group][2])
    active_weights=[]
    for group,(x,y,z) in enumerate(canonical):
        under=band(y,1.19,1.23,1.305,1.345)*band(abs(x),.012,.025,.175,.23)
        medial=.75*band(y,1.23,1.265,1.38,1.42)*band(abs(x),.010,.025,.065,.095)
        front=1-smooth(-.045,.005,z)
        weight=max(under,medial)*front
        for apex in apex_groups.values():
            distance=math.hypot(x-canonical[apex][0],y-canonical[apex][1])
            weight*=smooth(.018,.035,distance)
        active_weights.append(0.0 if group in blocked else weight)
    neighbors=defaultdict(set)
    for triangle in triangles:
        for a,b in zip(triangle,triangle[1:]+triangle[:1]):
            first,second=vertex_groups[a],vertex_groups[b]
            if first!=second:neighbors[first].add(second);neighbors[second].add(first)
    reverse_strength=-strength*1.03
    for _ in range(passes):
        # A forward/reverse pair damps short-wavelength corners without the
        # sustained lower-lobe shrink of repeated one-way averaging.
        for coefficient in (strength,reverse_strength):
            result=[list(point) for point in current]
            for group,weight in enumerate(active_weights):
                if weight<=0 or not neighbors[group]:continue
                average=[math.fsum(current[neighbor][axis] for neighbor in sorted(neighbors[group]))/len(neighbors[group])
                         for axis in range(3)]
                candidate=[value+coefficient*weight*(mean-value) for value,mean in zip(current[group],average)]
                delta=[(candidate[axis]-initial[group][axis])*frame[axis] for axis in range(3)]
                distance=math.hypot(*delta);limit=maximum_correction_metres*weight
                if distance>limit:
                    candidate=[initial[group][axis]+delta[axis]*(limit/distance)/frame[axis] for axis in range(3)]
                result[group]=candidate
            current=result
    output=[list(point) for point in positions]
    for index,group in enumerate(vertex_groups):
        if active_weights[group]>0 and current[group]!=initial[group]:
            output[index]=[current[group][axis]*frame[axis] for axis in range(3)]
    if any(output[index]!=list(positions[index]) for index in locked):raise ValueError('Corrective moved an attachment')
    for group in apex_groups.values():
        if any(output[index]!=list(positions[index]) for index in groups[group]):raise ValueError('Corrective moved an apex')
    distances=[math.dist(a,b) for a,b in zip(target,output)]
    return {'positions':output,'report':{
        'corrective':'reviewed-lower-medial-pole-fairing-v1','status':'candidate; actual intersection proof required',
        'topology_id':mesh.get('topology_id'),'passes':passes,'strength':strength,
        'reverse_strength':reverse_strength,'fairing':'paired forward/reverse; bounded local correction',
        'maximum_allowed_correction_metres':maximum_correction_metres,
        'max_correction_metres':max(distances,default=0.0),'moved_vertices':sum(distance>1e-10 for distance in distances),
        'protected_vertices_unchanged':True,'apex_neighborhoods_unchanged':True,
        'apex_vertices':{side:groups[group][0] for side,group in apex_groups.items()},
        'legacy_collection_changed':False}}
