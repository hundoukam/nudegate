"""Geometry-preserving preparation of an evaluated, skinned Blender donor.

The donor positions already include its saved pose. Default corrections rotate
limb segments using original deform weights. An explicit segment endpoint helper
can additionally fit axial lengths while preserving individual cross-sections.
These methods never fit the donor surface to a native body. Native body data is
a skin/UV/paint reference.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np

NS = {'c': 'http://www.collada.org/2005/11/COLLADASchema'}
BODY_NAME = 'HUM_F_NKD_Body_A_Mesh'


def load_dae(path, geometry_id=BODY_NAME+'-geom'):
    """Read native corner attributes and its own named skin palette."""
    root = ET.parse(path).getroot()
    geom = root.find("c:library_geometries/c:geometry[@id='%s']" % geometry_id, NS)
    if geom is None:
        raise ValueError('Missing native geometry: '+geometry_id)
    mesh = geom.find('c:mesh', NS)
    sources = {}
    for source in mesh.findall('c:source', NS):
        accessor = source.find('c:technique_common/c:accessor', NS)
        values = np.fromstring(source.find('c:float_array', NS).text, sep=' ')
        stride = int(accessor.get('stride', '1')); offset = int(accessor.get('offset', '0'))
        sources[source.get('id')] = values[offset:].reshape(-1, stride)
    vertices = {v.get('id'): v.find('c:input', NS).get('source')[1:]
                for v in mesh.findall('c:vertices', NS)}
    attributes = {}; triangle_list = []
    for primitive in mesh.findall('c:triangles', NS):
        inputs = primitive.findall('c:input', NS)
        width = max(int(i.get('offset', '0')) for i in inputs)+1
        indices = np.fromstring(primitive.find('c:p', NS).text, sep=' ', dtype=np.int64).reshape(-1, 3, width)
        for item in inputs:
            semantic = item.get('semantic'); source = item.get('source')[1:]
            if semantic == 'VERTEX':
                semantic = 'POSITION'; source = vertices.get(source, source)
                pos = sources[source][:, :3]
                triangle_list.append(indices[:, :, int(item.get('offset'))])
            array = sources[source][indices[:, :, int(item.get('offset'))]]
            attributes.setdefault(semantic, []).append(array)
    triangles = np.concatenate(triangle_list)
    result = {'positions': pos, 'triangles': triangles,
              'corners': {k: np.concatenate(v) for k, v in attributes.items()}}
    skins = root.findall('c:library_controllers/c:controller/c:skin', NS)
    skin = next(s for s in skins if s.get('source') == '#'+geometry_id)
    ss = {s.get('id'): s for s in skin.findall('c:source', NS)}
    joints = {i.get('semantic'): ss[i.get('source')[1:]] for i in skin.find('c:joints', NS)}
    names = joints['JOINT'].find('c:Name_array', NS).text.split()
    binds = np.fromstring(joints['INV_BIND_MATRIX'].find('c:float_array', NS).text, sep=' ').reshape(-1, 4, 4)
    vw = skin.find('c:vertex_weights', NS)
    vi = {i.get('semantic'): i for i in vw.findall('c:input', NS)}
    wc = int(ss[vi['WEIGHT'].get('source')[1:]].find('c:technique_common/c:accessor', NS).get('stride','1'))
    if wc != 1:
        raise ValueError('Expected scalar native weights')
    weights = np.fromstring(ss[vi['WEIGHT'].get('source')[1:]].find('c:float_array', NS).text, sep=' ')
    stride = max(int(i.get('offset')) for i in vi.values())+1
    pairs = np.fromstring(vw.find('c:v', NS).text, sep=' ', dtype=np.int64).reshape(-1, stride)
    counts = np.fromstring(vw.find('c:vcount', NS).text, sep=' ', dtype=np.int64)
    full = np.zeros((len(pos),len(names)))
    vertex = np.repeat(np.arange(len(pos)), counts)
    np.add.at(full, (vertex,pairs[:,int(vi['JOINT'].get('offset'))]), weights[pairs[:,int(vi['WEIGHT'].get('offset'))]])
    if np.any(full.sum(1) <= 0):
        raise ValueError('Native has unweighted positions')
    full /= full.sum(1,keepdims=True)
    result.update(bone_palette=names,inverse_bind=binds,bone_weights=full,
                  bone_world=dict(zip(names,np.linalg.inv(binds))))
    return result


def normalized_deform_weights(arrays, metadata):
    """Keep only active deform bones; original CSR arrays remain untouched."""
    active = set(metadata['vertex_group_validation']['active_vertex_group_rigs'])
    bones = {b['name']: b for r in metadata['rigs'] if r['name'] in active for b in r['bones']}
    names = metadata['vertex_group_names']
    deform = np.array([n in bones and bones[n]['deform'] for n in names])
    row = np.repeat(np.arange(len(arrays['positions'])),np.diff(arrays['group_offsets']))
    cols = arrays['group_indices']; value = arrays['group_weights']
    if (not np.isfinite(value).all() or np.any(value[deform[cols]]<0)
            or np.any(value[deform[cols]]>1)):
        raise ValueError('Source deform weights need explicit repair before normalization')
    valid = deform[cols] & (value > 0)
    full = np.zeros((len(arrays['positions']),len(names)))
    np.add.at(full,(row[valid],cols[valid]),value[valid])
    sums = full.sum(1)
    if np.any(sums <= 0) or not np.isfinite(full).all():
        raise ValueError('Unweighted or invalid donor deform influences')
    return full/sums[:,None], names, bones, {'raw_deform_sum_min':float(sums.min()),
             'raw_deform_sum_max':float(sums.max()),'nondeform_assignments_ignored':int((~valid).sum())}


def rotation_between(a,b):
    """Shortest proper rotation, including an explicit antiparallel case."""
    a=np.asarray(a,float); b=np.asarray(b,float)
    if min(np.linalg.norm(a),np.linalg.norm(b))<1e-10:
        raise ValueError('Zero limb direction')
    a=a/np.linalg.norm(a); b=b/np.linalg.norm(b)
    cross=np.cross(a,b); dot=float(np.clip(a@b,-1,1))
    if dot < -.999999:
        axis=np.cross(a,[1.,0.,0.])
        if np.linalg.norm(axis)<.01: axis=np.cross(a,[0.,1.,0.])
        axis/=np.linalg.norm(axis)
        return 2*np.outer(axis,axis)-np.eye(3)
    k=np.array([[0.,-cross[2],cross[1]],[cross[2],0.,-cross[0]],[-cross[1],cross[0],0.]])
    return np.eye(3)+k+k@k/(1+dot)


def fit_segment_endpoints(source_start,source_end,target_start,target_end):
    """Map segment endpoints exactly, scaling only along its original axis.

    The returned affine matrix applies a proper shortest rotation after the
    longitudinal scale. Every cross-section perpendicular to the source axis
    keeps its distances and area; no radial/girth scale is introduced. This is
    an opt-in limb proportion fit, separate from the default rigid pose math.
    """
    a,b,ta,tb=[np.asarray(value,dtype=float) for value in
        (source_start,source_end,target_start,target_end)]
    if any(value.shape!=(3,) or not np.isfinite(value).all() for value in (a,b,ta,tb)):
        raise ValueError('Segment endpoints must be finite three-dimensional points')
    direction=b-a;target=tb-ta
    length=float(np.linalg.norm(direction));target_length=float(np.linalg.norm(target))
    if min(length,target_length)<1e-10:raise ValueError('Zero segment length')
    axis=direction/length;scale=target_length/length
    rotation=rotation_between(direction,target)
    matrix=rotation@(np.eye(3)+(scale-1)*np.outer(axis,axis))
    offset=ta-matrix@a
    report={'source_length_m':length,'native_length_m':target_length,
        'longitudinal_scale':scale,'cross_section_scale':1.,'rotation':rotation.tolist(),
        'source_start':a.tolist(),'source_end':b.tolist(),
        'target_start':ta.tolist(),'target_end':tb.tolist(),
        'start_residual_m':float(np.linalg.norm(matrix@a+offset-ta)),
        'end_residual_m':float(np.linalg.norm(matrix@b+offset-tb))}
    return matrix,offset,report


def fractional_rotation(rotation,fraction):
    """Interpolate a proper segment rotation by its axis/angle, not a sculpt."""
    if not np.isfinite(fraction) or not 0<=fraction<=1:
        raise ValueError('Pose rotation fraction must be in [0,1]')
    if fraction==1:return rotation
    if fraction==0:return np.eye(3)
    angle=float(np.arccos(np.clip((np.trace(rotation)-1)/2,-1,1)))
    if angle<1e-12:return np.eye(3)
    axis=np.array([rotation[2,1]-rotation[1,2],rotation[0,2]-rotation[2,0],rotation[1,0]-rotation[0,1]])
    if np.linalg.norm(axis)<1e-8:
        values,vectors=np.linalg.eigh(rotation);axis=vectors[:,np.argmax(values)]
    axis/=np.linalg.norm(axis);angle*=fraction
    k=np.array([[0.,-axis[2],axis[1]],[axis[2],0.,-axis[0]],[-axis[1],axis[0],0.]])
    return np.eye(3)+np.sin(angle)*k+(1-np.cos(angle))*(k@k)


def _limb_root(name,bones):
    """Resolve anatomical source chains through real hierarchy, not proximity."""
    seen=set()
    while name and name not in seen:
        seen.add(name)
        for part in ('hand','forearm','upper_arm','toe','foot','shin','thigh'):
            for side in ('L','R'):
                if name in ('DEF-'+part+'.'+side,'DEF-'+part+'.'+side+'.001'):
                    return part,side
        name=bones.get(name,{}).get('parent')
    return None


def pose_donor(arrays, metadata, native, scale=1.165, *, align_hip_x=False, stance_extra=0.,
               arm_rotation_fraction=1.,leg_rotation_fraction=1.,arm_lateral_extra=0.,align_arm_pivot=False):
    """Rotate source-weighted limbs toward native bind directions; keep core."""
    if not np.isfinite(scale) or not .5 <= scale <= 1.5:
        raise ValueError('Uniform scale must be finite and in [0.5,1.5]')
    if not np.isfinite(stance_extra) or not 0 <= stance_extra <= .03:
        raise ValueError('Additional per-side stance must be finite and in [0,.03] metres')
    if stance_extra and not align_hip_x:
        raise ValueError('Additional stance requires explicit native lateral hip alignment')
    if not np.isfinite(arm_lateral_extra) or not 0<=arm_lateral_extra<=.03:
        raise ValueError('Additional per-side arm pivot shift must be in [0,.03] metres')
    weights,names,bones,report=normalized_deform_weights(arrays,metadata)
    # Blender Z-up -> BG3 Y-up is a reflection. Reverse winding separately.
    points=np.asarray(arrays['positions'],float)[:,[0,2,1]]*scale
    native_heads={n:m[:3,3] for n,m in native['bone_world'].items()}
    transforms={}; fixtures=[]
    for side in ('L','R'):
        for chain,target in [(('upper_arm','forearm','hand'),('Shoulder','Elbow','Wrist')),
                             (('thigh','shin','foot'),('Hip','Knee','Ankle'))]:
            a,b,c=[np.array(bones['DEF-'+p+'.'+side]['posed_head_world'])[[0,2,1]]*scale for p in chain]
            ta,tb,tc=[native_heads[p+'_'+side] for p in target]
            upper=rotation_between(b-a,tb-ta); lower=rotation_between(c-b,tc-tb)
            fraction=leg_rotation_fraction if chain[0]=='thigh' else arm_rotation_fraction
            upper=fractional_rotation(upper,fraction);lower=fractional_rotation(lower,fraction)
            offset=np.zeros(3)
            if chain[0]=='thigh' and align_hip_x:
                offset[0]=ta[0]-a[0]+np.sign(a[0])*stance_extra
            if chain[0]=='upper_arm':
                if align_arm_pivot:offset=ta-a
                offset[0]+=np.sign(a[0])*arm_lateral_extra
            corrected_pivot=a+offset
            elbow=corrected_pivot+upper@(b-a)
            end=elbow+lower@(c-b)
            transforms[(chain[0],side)]=(upper,corrected_pivot-upper@a)
            transforms[(chain[1],side)]=(lower,elbow-lower@b)
            transforms[(chain[2],side)]=(lower,elbow-lower@b)
            if chain[2]=='foot': transforms[('toe',side)]=transforms[('foot',side)]
            fixtures.append({'side':side,'source_chain':list(chain),'native_chain':list(target),
                'upper_angle_degrees':float(np.rad2deg(np.arccos(np.clip((np.trace(upper)-1)/2,-1,1)))),
                'lower_angle_degrees':float(np.rad2deg(np.arccos(np.clip((np.trace(lower)-1)/2,-1,1)))),
                'source_pivot':a.tolist(),'corrected_pivot':corrected_pivot.tolist(),
                'rotation_fraction':fraction,
                'lateral_pivot_translation':offset.tolist(),'corrected_mid_joint':elbow.tolist(),
                'corrected_end_joint':end.tolist(),
                'pivot_native_offset_m':(corrected_pivot-ta).tolist(),
                'mid_native_offset_m':(elbow-tb).tolist(),'end_native_offset_m':(end-tc).tolist(),
                'mid_native_offset_length_m':float(np.linalg.norm(elbow-tb)),
                'end_native_offset_length_m':float(np.linalg.norm(end-tc))})
    displacement=np.zeros_like(points); mask=np.zeros(len(points))
    for i,name in enumerate(names):
        limb=_limb_root(name,bones)
        if limb not in transforms: continue
        r,t=transforms[limb]; w=weights[:,i]
        displacement+=((points@r.T+t)-points)*w[:,None]
        mask+=w
    posed=points+displacement
    fixed=mask==0
    if not np.array_equal(points[fixed],posed[fixed]):
        raise ValueError('Pose correction changed vertices with no limb influence')
    report.update(uniform_scale=scale,axis_conversion='[x,z,y]',
        source_already_posed=True,correction='source normalized deform-weighted segment rotations',
        native_hip_lateral_alignment=align_hip_x,additional_stance_per_side_m=stance_extra,
        arm_rotation_fraction=arm_rotation_fraction,leg_rotation_fraction=leg_rotation_fraction,
        arm_lateral_extra_per_side_m=arm_lateral_extra,native_arm_pivot_alignment=align_arm_pivot,
        limb_fixtures=fixtures,vertices=int(len(points)),triangles=int(len(arrays['triangles'])),
        pose_changed_vertices=int(np.count_nonzero(np.linalg.norm(displacement,axis=1)>1e-12)),
        torso_uninfluenced_vertices=int(fixed.sum()),torso_uninfluenced_max_error=0.,
        maximum_pose_displacement=float(np.linalg.norm(displacement,axis=1).max()))
    report['native_joint_fit']={'basis':'rigid source segment fixture landmarks; not an animation/contact measurement',
        'exact_joint_bind_alignment':all(np.linalg.norm(f['pivot_native_offset_m'])<1e-6 and
            f['mid_native_offset_length_m']<1e-6 and f['end_native_offset_length_m']<1e-6 for f in fixtures),
        'partial_arm_fixture':arm_rotation_fraction!=1,'additional_stance_per_side_m':stance_extra,
        'hand_prop_contact':'unverified','animation_motion':'unverified',
        'native_skeleton_preservation_is_not_exact_donor_joint_alignment':True}
    return {'positions':posed,'scaled_source_positions':points,
            'triangles':arrays['triangles'][:,[0,2,1]].copy(),
            'source_vertex_ids':np.arange(len(points)), 'pose_displacement':displacement,
            'limb_influence':mask},weights,names,bones,report


def quantize_weights(weights, lanes=4):
    """Select strongest influences then quantize with stable largest remainder."""
    order=np.argsort(-weights,axis=1,kind='stable')[:,:lanes]
    selected=np.take_along_axis(weights,order,axis=1)
    retained=selected.sum(1)
    if np.any(retained<=0): raise ValueError('Unweighted export vertex')
    selected/=retained[:,None]
    raw=selected*255; byte=np.floor(raw).astype(np.int64)
    remainder=255-byte.sum(1)
    ranking=np.argsort(-(raw-byte),axis=1,kind='stable')
    for lane in range(lanes):
        rows=np.flatnonzero(remainder>lane)
        byte[rows,ranking[rows,lane]]+=1
    return order,byte,{'minimum_retained_weight':float(retained.min()),
        'maximum_dropped_weight':float((1-retained).max()),
        'maximum_quantization_error':float(np.max(abs(byte/255-selected)))}


def map_native_weights(weights,names,bones,native_names):
    """Reviewed Juno G9 semantic anchors, then actual known-parent fallback."""
    anchors={'DEF-spine':'Root_M','DEF-spine.001':'Spine1_M',
        'DEF-spine.002':'Spine2_M','DEF-spine.003':'Chest_M','DEF-spine.004':'Chest_M',
        'DEF-spine.005':'Neck_M','DEF-spine.006':'Neck_M','DEF-spine.007':'Head_M',
        'head':'Head_M','lowerjaw':'Head_M','upperteeth':'Head_M','lowerteeth':'Head_M'}
    for side in ('L','R'):
        for source,target in [('shoulder','Scapula'),('upper_arm','Shoulder'),
                ('forearm','Elbow'),('hand','Wrist'),('thigh','Hip'),('shin','Knee'),
                ('foot','Ankle'),('toe','Toes')]:
            for suffix in ('','.001'):
                anchors['DEF-'+source+'.'+side+suffix]=target+'_'+side
        for source,target in [('f_index','IndexFinger'),('f_middle','MiddleFinger'),
                              ('f_ring','RingFinger'),('f_pinky','PinkyFinger'),('thumb','ThumbFinger')]:
            for number in range(1,4):
                anchors['DEF-'+source+'.%02d.'%number+side]=target+str(number)+'_'+side
        for number in range(1,5):
            anchors['DEF-palm.%02d.'%number+side]=('RingFinger0_' if number==3 else
                'PinkyFinger0_' if number==4 else 'Wrist_')+side
    mapped=np.zeros((len(weights),len(native_names))); resolved={}; unresolved=[]
    for index,name in enumerate(names):
        if not np.any(weights[:,index]>0): continue
        at=name;seen=set()
        while at not in anchors:
            if not at or at in seen or at not in bones:
                unresolved.append(name);break
            seen.add(at);at=bones[at]['parent']
        else:
            target=anchors[at]
            if target not in native_names: raise ValueError('Missing native anchor '+target)
            mapped[:,native_names.index(target)]+=weights[:,index]
            resolved[name]={'anchor':at,'target':target,'direct':name==at}
    if unresolved: raise ValueError('Unmapped positive donor deform groups: '+', '.join(unresolved))
    if not np.allclose(mapped.sum(1),1,atol=1e-12):raise ValueError('Mapped donor weights lost mass')
    return mapped,{'semantic_anchors':anchors,'resolved_positive_groups':resolved,
                   'unknown_positive_groups':[]}


def vertex_normals(positions,triangles):
    p=np.asarray(positions);t=np.asarray(triangles)
    face=np.cross(p[t[:,1]]-p[t[:,0]],p[t[:,2]]-p[t[:,0]])
    normal=np.zeros_like(p)
    for corner in range(3):np.add.at(normal,t[:,corner],face)
    length=np.linalg.norm(normal,axis=1,keepdims=True)
    if np.any(length<=1e-14):raise ValueError('Degenerate or unused normal sample')
    return normal/length


def ordered_boundary(edges):
    neighbors={}
    for a,b in edges:
        neighbors.setdefault(int(a),[]).append(int(b));neighbors.setdefault(int(b),[]).append(int(a))
    if not neighbors or any(len(n)!=2 for n in neighbors.values()):
        raise ValueError('Cut is not one closed boundary')
    start=min(neighbors);result=[start];previous=None;current=start
    while True:
        following=next(v for v in neighbors[current] if v!=previous)
        if following==start:break
        if following in result:raise ValueError('Self intersecting boundary')
        result.append(following);previous,current=current,following
    if len(result)!=len(neighbors):raise ValueError('Cut has multiple boundary loops')
    return np.array(result,dtype=np.int64)


def _boundary_edges(triangles):
    t=np.asarray(triangles)
    edges=np.sort(np.concatenate([t[:,[0,1]],t[:,[1,2]],t[:,[2,0]]]),axis=1)
    edges,counts=np.unique(edges,axis=0,return_counts=True)
    if np.any(counts>2):raise ValueError('Nonmanifold input topology')
    return edges[counts==1]


def native_collar(native):
    # Weld only for topology analysis. Copied coordinates use exact originals.
    p=native['positions']; unique,first,inverse=np.unique(np.round(p,6),axis=0,
        return_index=True,return_inverse=True)
    edges=_boundary_edges(inverse[native['triangles']])
    edges=edges[np.all(unique[edges,1]>1.5,axis=1)]
    ring=ordered_boundary(edges)
    return first[ring]


def _smooth(value):
    value=np.clip(value,0,1);return value*value*(3-2*value)


def _cut_height(x,cut):
    return cut+4*x*x+.03*_smooth((abs(x)-.08)/.04)


def _parameter(points):
    distance=np.linalg.norm(np.roll(points,-1,axis=0)-points,axis=1)
    if distance.sum()<=0:raise ValueError('Collapsed neck boundary')
    return np.r_[0,np.cumsum(distance)]/distance.sum()


def _zipper(lower,upper,positions):
    a=_parameter(positions[lower]);b=_parameter(positions[upper]);i=j=0;faces=[]
    while i<len(lower) or j<len(upper):
        if i<len(lower) and (j==len(upper) or a[i+1]<=b[j+1]):
            faces.append([lower[i%len(lower)],lower[(i+1)%len(lower)],upper[j%len(upper)]]);i+=1
        else:
            faces.append([lower[i%len(lower)],upper[(j+1)%len(upper)],upper[j%len(upper)]]);j+=1
    return faces


def _orient_bridge_from_body(body_faces, bridge):
    """Keep zipper faces coherent and opposite the attached body boundary."""
    def directed_edges(faces):
        result={}
        for triangle in faces:
            for a,b in zip(triangle,np.roll(triangle,-1)):
                edge=tuple(sorted((int(a),int(b))))
                result.setdefault(edge,[]).append((int(a),int(b)))
        return result
    body_edges=directed_edges(body_faces);bridge_edges=directed_edges(bridge)
    orientation=[]
    for edge,values in bridge_edges.items():
        if len(values)==2:
            if values[0]==values[1]:raise ValueError('Zipper bridge has inconsistent internal winding')
        elif len(values)!=1:raise ValueError('Zipper bridge has a nonmanifold edge')
        if edge in body_edges:
            if len(values)!=1 or len(body_edges[edge])!=1:
                raise ValueError('Bridge does not attach to a single body boundary')
            orientation.append(values[0]==body_edges[edge][0])
    if not orientation or any(value!=orientation[0] for value in orientation):
        raise ValueError('Source body rim has inconsistent winding')
    return bridge[:,[0,2,1]] if orientation[0] else bridge


def validate_open_boundary_provenance(final_edges,source_ids,collar_ids,source_triangles,
                                      original_source_ids,*,allow_inherited=False):
    """Accept the exact collar and, optionally, only original source openings."""
    final={tuple(sorted(map(int,edge))) for edge in final_edges}
    collar={tuple(sorted((int(a),int(b)))) for a,b in zip(collar_ids,np.roll(collar_ids,-1))}
    if not collar<=final:raise ValueError('Native collar boundary is missing or closed')
    extra=final-collar
    if extra and not allow_inherited:
        raise ValueError('Unexpected open boundary after neck bridge: '+str(len(final)))
    t=np.asarray(source_triangles)
    raw=np.sort(np.concatenate([t[:,[0,1]],t[:,[1,2]],t[:,[2,0]]]),axis=1)
    edges,counts=np.unique(raw,axis=0,return_counts=True)
    original=np.asarray(original_source_ids)
    inherited={tuple(sorted(map(int,original[edge]))) for edge in edges[counts==1]}
    verified=[]
    for a,b in sorted(extra):
        ancestry=tuple(sorted((int(source_ids[a]),int(source_ids[b]))))
        if min(ancestry)<0 or ancestry not in inherited:
            raise ValueError('A new non-collar opening was introduced')
        verified.append(list(ancestry))
    return {'native_collar_open_edges':len(collar),'inherited_open_edges':len(verified),
            'inherited_source_edge_ids':verified,'introduced_noncollar_open_edges':0,
            'source_open_edges':int(np.count_nonzero(counts==1)),
            'source_nonmanifold_edges':int(np.count_nonzero(counts>2)),
            'inherited_openings_explicitly_allowed':allow_inherited}


def trim_and_bridge(posed,mapped,native,cut=1.52,band=.035,*,allow_inherited_openings=False,cut_height=None,
                    bridge_orientation='source-boundary'):
    """Clip the head locally and append an exact native collar plus neck bridge.

    Original triangles wholly below the curved cut keep their exact vertices.
    Edge intersections are shared by their original edge IDs. No welding,
    decimation, smoothing or general surface fitting is performed.
    The generated zipper inherits coherent winding from the original body
    boundary. ``bridge_orientation='radial'`` reproduces older archives only.
    """
    if bridge_orientation not in ('source-boundary','radial'):
        raise ValueError('Unknown neck bridge orientation mode')
    cut_function=_cut_height if cut_height is None else cut_height
    p=posed['positions'];t=posed['triangles'];points=p.tolist();weight=mapped.tolist()
    heights=np.asarray(cut_function(p[:,0],cut))
    if heights.shape!=(len(p),) or not np.isfinite(heights).all():
        raise ValueError('Invalid local neck cut height field')
    ids=posed['source_vertex_ids'].tolist();source_face=[];faces=[];cache={}
    scalar=p[:,1]-heights
    def intersection(a,b):
        edge=tuple(sorted((int(a),int(b))))
        if edge not in cache:
            q=float(scalar[a]/(scalar[a]-scalar[b]))
            cache[edge]=len(points);points.append(((1-q)*p[a]+q*p[b]).tolist())
            weight.append(((1-q)*mapped[a]+q*mapped[b]).tolist());ids.append(-1)
        return cache[edge]
    removed=[];clipped=[]
    for fi,tri in enumerate(t):
        keep=scalar[tri]<=1e-12
        if keep.all():faces.append(tri.tolist());source_face.append(fi);continue
        if not keep.any():removed.append(fi);continue
        polygon=[];clipped.append(fi)
        for c in range(3):
            a=int(tri[c]);b=int(tri[(c+1)%3])
            if scalar[a]<=1e-12:polygon.append(a)
            if (scalar[a]<0)!=(scalar[b]<0):polygon.append(intersection(a,b))
        for c in range(1,len(polygon)-1):
            faces.append([polygon[0],polygon[c],polygon[c+1]]);source_face.append(fi)
    points=np.asarray(points);weight=np.asarray(weight);faces=np.asarray(faces,dtype=np.int64)
    ids=np.asarray(ids);source_face=np.asarray(source_face)
    used=np.unique(faces);remap=np.full(len(points),-1,dtype=np.int64);remap[used]=np.arange(len(used))
    points=points[used];weight=weight[used];ids=ids[used];faces=remap[faces]
    edges=_boundary_edges(faces)
    cut_edges=edges[np.all(points[edges,1]>cut-.015,axis=1)]
    rim=ordered_boundary(cut_edges)
    collar_indices=native_collar(native);collar=native['positions'][collar_indices]
    # Compress only the existing narrow collar band; reject a folded mapping.
    shift=min(0.,float(collar[:,1].min())-.014-cut)
    if 1+1.5*shift/band<.1:raise ValueError('Neck transition would fold')
    point_heights=cut_function(points[:,0],cut)
    transition=(abs(points[:,0])<.12)&(points[:,1]>point_heights-band)
    neck_displacement=np.zeros_like(points)
    neck_displacement[transition,1]=shift*_smooth((points[transition,1]-(cut_function(points[transition,0],cut)-band))/band)
    pre_neck=points.copy();points+=neck_displacement
    normals=vertex_normals(points,faces)
    # Ring starts and winding agree by actual arc-length order around XZ.
    def rotate_ring(indices):
        q=points[indices] if np.max(indices)<len(points) else None
        return indices
    def orient(indices,coords):
        q=coords[indices];center=q[:,[0,2]].mean(0)
        start=int(np.argmin(np.arctan2(q[:,2]-center[1],q[:,0]-center[0])))
        indices=np.roll(indices,-start);q=coords[indices]
        area=np.sum(q[:,0]*np.roll(q[:,2],-1)-q[:,2]*np.roll(q[:,0],-1))
        return indices if area>0 else np.r_[indices[0],indices[:0:-1]]
    rim=orient(rim,points)
    collar_order=orient(np.arange(len(collar)),collar)
    collar_indices=collar_indices[collar_order];collar=collar[collar_order]
    native_n=np.zeros_like(native['positions']);count=np.zeros(len(native_n))
    for c in range(3):
        np.add.at(native_n,native['triangles'][:,c],native['corners']['NORMAL'][:,c,:3]);np.add.at(count,native['triangles'][:,c],1)
    native_n/=np.maximum(count[:,None],1);native_n/=np.maximum(np.linalg.norm(native_n,axis=1,keepdims=True),1e-12)
    query=np.linspace(0,1,64,endpoint=False)
    def sample(values,ring):
        parameter=_parameter(points[ring]);v=values[ring]
        return np.column_stack([np.interp(query,parameter,np.r_[v[:,c],v[0,c]]) for c in range(v.shape[1])])
    lower=sample(points,rim);lower_normal=sample(normals,rim);lower_weight=sample(weight,rim)
    parameter=_parameter(collar)
    def sample_top(v):
        return np.column_stack([np.interp(query,parameter,np.r_[v[:,c],v[0,c]]) for c in range(v.shape[1])])
    upper=sample_top(collar);upper_normal=sample_top(native_n[collar_indices]);upper_weight=sample_top(native['bone_weights'][collar_indices])
    delta=upper-lower
    def tangent(normal):
        normal/=np.maximum(np.linalg.norm(normal,axis=1,keepdims=True),1e-12)
        result=delta-normal*np.sum(delta*normal,axis=1,keepdims=True)
        result[:,1]=np.maximum(result[:,1],0);return result
    a=tangent(lower_normal);b=tangent(upper_normal)
    rings=[rim];append_p=[];append_w=[]
    for fraction in (.2,.4,.6,.8):
        f=fraction
        q=(2*f**3-3*f*f+1)*lower+(f**3-2*f*f+f)*a+(-2*f**3+3*f*f)*upper+(f**3-f*f)*b
        rings.append(np.arange(len(points)+len(append_p),len(points)+len(append_p)+len(q)))
        append_p.extend(q);append_w.extend((1-f)*lower_weight+f*upper_weight)
    top=np.arange(len(points)+len(append_p),len(points)+len(append_p)+len(collar));rings.append(top)
    append_p.extend(collar);append_w.extend(native['bone_weights'][collar_indices])
    original_count=len(points);points=np.concatenate([points,np.asarray(append_p)])
    weight=np.concatenate([weight,np.asarray(append_w)]);ids=np.r_[ids,np.full(len(append_p),-2)]
    bridge=np.array([f for lo,hi in zip(rings,rings[1:]) for f in _zipper(lo,hi,points)])
    if bridge_orientation=='source-boundary':
        bridge=_orient_bridge_from_body(faces,bridge)
    elif bridge_orientation=='radial':
        # Original behavior retained for existing reviewed donor stages.
        center=collar[:,[0,2]].mean(0);q=points[bridge]
        n=np.cross(q[:,1]-q[:,0],q[:,2]-q[:,0]);radial=q.mean(1);radial[:,[0,2]]-=center;radial[:,1]=0
        reverse=np.einsum('ij,ij->i',n,radial)<0;bridge[reverse]=bridge[reverse][:,[0,2,1]]
    else:raise ValueError('Unknown neck bridge orientation mode')
    faces=np.concatenate([faces,bridge]);source_face=np.r_[source_face,np.full(len(bridge),-1)]
    final_edges=_boundary_edges(faces)
    boundary_report=validate_open_boundary_provenance(final_edges,ids,top,t,posed['source_vertex_ids'],
                                                     allow_inherited=allow_inherited_openings)
    outside=(ids[:original_count]>=0)&~transition
    error=float(np.linalg.norm(points[:original_count][outside]-p[ids[:original_count][outside]],axis=1).max(initial=0))
    if error!=0:raise ValueError('Neck operation altered protected donor vertices')
    report={'head_cut_base_height':cut,'head_cut_curve':'cut + 4*x*x + .03*smooth((abs(x)-.08)/.04)',
        'removed_source_faces':len(removed),'clipped_source_faces':len(clipped),'retained_whole_source_faces':int(len(t)-len(removed)-len(clipped)),
        'edge_intersections':len(cache),'native_collar_samples':len(collar),'native_collar_original_indices':collar_indices.tolist(),
        'neck_shift':shift,'neck_band':band,'neck_changed_existing_vertices':int(np.count_nonzero(np.linalg.norm(neck_displacement,axis=1)>1e-12)),
        'bridge_added_vertices':len(append_p),'bridge_added_triangles':len(bridge),
        'outside_neck_position_error':error,'final_open_edges':len(final_edges),
        'boundary_provenance':boundary_report}
    if cut_height is not None:
        report['head_cut_curve']='explicit local cut-height callback; see donor profile parameters'
    if bridge_orientation!='radial':
        report.update(bridge_orientation=bridge_orientation,bridge_internal_winding_conflicts=0,
                      body_bridge_boundary_winding_conflicts=0)
    return {'positions':points,'triangles':faces,'bone_weights':weight,'source_vertex_ids':ids,
        'source_face_ids':source_face,'collar_vertex_indices':top,'collar_native_indices':collar_indices,
        'pre_neck_positions':np.concatenate([pre_neck,np.asarray(append_p)]),
        'removed_source_face_ids':np.array(removed),'clipped_source_face_ids':np.array(clipped)},report


def closest_triangles(query,triangles):
    """Exact closest point on each supplied triangle, with barycentric weights."""
    a,b,c=triangles[...,0,:],triangles[...,1,:],triangles[...,2,:]
    ab=b-a;ac=c-a;ap=query-a
    d00=np.sum(ab*ab,axis=-1);d01=np.sum(ab*ac,axis=-1);d11=np.sum(ac*ac,axis=-1)
    d20=np.sum(ap*ab,axis=-1);d21=np.sum(ap*ac,axis=-1)
    denominator=d00*d11-d01*d01
    good=abs(denominator)>1e-20;den=np.where(good,denominator,1)
    v=(d11*d20-d01*d21)/den;w=(d00*d21-d01*d20)/den
    inside=good&(v>=0)&(w>=0)&(v+w<=1)
    bary=np.stack([1-v-w,v,w],axis=-1)
    projected=a+ab*v[...,None]+ac*w[...,None]
    best=np.where(inside,np.sum((projected-query)**2,axis=-1),np.inf)
    for ia,ib in ((0,1),(1,2),(2,0)):
        start=triangles[...,ia,:];edge=triangles[...,ib,:]-start
        along=np.clip(np.sum((query-start)*edge,axis=-1)/np.maximum(np.sum(edge*edge,axis=-1),1e-30),0,1)
        candidate=start+along[...,None]*edge;distance=np.sum((candidate-query)**2,axis=-1)
        use=distance<best;best=np.minimum(best,distance)
        edge_bary=np.zeros_like(bary);edge_bary[...,ia]=1-along;edge_bary[...,ib]=along
        bary=np.where(use[...,None],edge_bary,bary)
    return bary,best


def plane_barycentric(query,triangles):
    """Unclamped tangent-plane coordinates for UV extrapolation only.

    Clamped geometry sampling can collapse a protruding donor patch onto one
    native edge or vertex. Extrapolating the selected face's UV chart preserves
    its local area; RGB paint and skin sampling still use clamped coordinates.
    """
    a,b,c=triangles[:,0],triangles[:,1],triangles[:,2]
    ab=b-a;ac=c-a;ap=query-a
    d00=np.sum(ab*ab,axis=1);d01=np.sum(ab*ac,axis=1);d11=np.sum(ac*ac,axis=1)
    d20=np.sum(ap*ab,axis=1);d21=np.sum(ap*ac,axis=1);den=d00*d11-d01*d01
    if np.any(abs(den)<1e-20):raise ValueError('Degenerate reference UV sampling face')
    v=(d11*d20-d01*d21)/den;w=(d00*d21-d01*d20)/den
    return np.column_stack([1-v-w,v,w])


def transport_corresponding_surface(query,query_normals,source,target,triangles):
    """Extend a donor-authored shape delta through local source-face charts.

    Source and target use exactly corresponding raw donor vertices/triangles.
    Each query selects a nearby agreeing source triangle, then receives its
    affine plane-chart shape delta. World-space offset from the chart is kept.
    Jacobians are analytic within the selected chart; face selection itself
    is piecewise and is separately checked by a full surface collision audit.
    """
    from scipy.spatial import cKDTree
    query=np.asarray(query,float);normal=np.asarray(query_normals,float)
    source=np.asarray(source,float);target=np.asarray(target,float);triangles=np.asarray(triangles,int)
    if source.shape!=target.shape:raise ValueError('Corresponding donor position counts differ')
    tri=source[triangles];cross=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0])
    lengths=np.linalg.norm(cross,axis=1);valid=lengths>1e-12
    if not valid.all():raise ValueError('Collapsed donor source triangle in proxy correspondence')
    tn=cross/lengths[:,None];tree=cKDTree(tri.mean(1))
    _,candidate=tree.query(query,k=min(64,len(tri)))
    if candidate.ndim==1:candidate=candidate[:,None]
    _,distance=closest_triangles(query[:,None,:],tri[candidate])
    agreement=1-np.einsum('ij,ikj->ik',normal,tn[candidate])
    score=distance+.0002*agreement
    side_wrong=(query[:,None,0]*tri[candidate].mean(2)[:,:,0]<0)&(abs(query[:,None,0])>.018)
    score=np.where(side_wrong,score+1,score)
    choice=np.argmin(score,axis=1);rows=np.arange(len(query));face=candidate[rows,choice]
    selected=tri[face];bary=plane_barycentric(query,selected)
    displacement=target[triangles[face]]-selected
    points=query+np.einsum('ni,nij->nj',bary,displacement)
    ab=selected[:,1]-selected[:,0];ac=selected[:,2]-selected[:,0]
    d00=np.sum(ab*ab,axis=1);d01=np.sum(ab*ac,axis=1);d11=np.sum(ac*ac,axis=1)
    den=d00*d11-d01*d01
    grad_v=(d11[:,None]*ab-d01[:,None]*ac)/den[:,None]
    grad_w=(d00[:,None]*ac-d01[:,None]*ab)/den[:,None]
    grad=np.stack([-grad_v-grad_w,grad_v,grad_w],axis=1)
    jacobian=np.eye(3)+np.einsum('nki,nkj->nij',displacement,grad)
    if not np.isfinite(points).all() or not np.isfinite(jacobian).all():
        raise ValueError('Nonfinite donor-correspondence transport')
    return points,jacobian,{'source_face_ids':face,'barycentrics':bary,
        'source_surface_distance':np.sqrt(distance[rows,choice])}


def _uv_islands(reference):
    triangles=reference['triangles'];uv=reference['corners']['TEXCOORD'][:,:,:2]
    parent=np.arange(len(triangles));edges={}
    def find(a):
        while parent[a]!=a:parent[a]=parent[parent[a]];a=parent[a]
        return a
    for fi,tri in enumerate(triangles):
        for ca,cb in ((0,1),(1,2),(2,0)):
            a,b=int(tri[ca]),int(tri[cb]);ua,ub=uv[fi,ca],uv[fi,cb]
            if a>b:a,b=b,a;ua,ub=ub,ua
            edge=(a,b)
            if edge in edges:
                other,va,vb=edges[edge]
                if np.allclose(ua,va,atol=1e-7,rtol=0) and np.allclose(ub,vb,atol=1e-7,rtol=0):
                    parent[find(fi)]=find(other)
            else:edges[edge]=(fi,ua,ub)
    roots=np.array([find(i) for i in range(len(triangles))])
    return np.unique(roots,return_inverse=True)[1]


def transfer_native_surface(body,reference,native):
    """Transfer corner UVs and RGB paint without changing donor coordinates.

    Native UV islands are selected per donor face. Each (donor vertex,island)
    is sampled exactly once, preventing per-face numerical UV cracks while
    keeping atlas seams split. The fitted native reference is lookup data only.
    """
    from scipy.spatial import cKDTree
    p=body['positions'];faces=body['triangles'];normal=vertex_normals(p,faces)
    rp=reference['positions'];rt=reference['triangles'];triangle=rp[rt]
    ref_normal=np.cross(triangle[:,1]-triangle[:,0],triangle[:,2]-triangle[:,0])
    ref_normal/=np.maximum(np.linalg.norm(ref_normal,axis=1,keepdims=True),1e-12)
    centers=triangle.mean(1);tree=cKDTree(centers);islands=_uv_islands(reference)
    face_points=p[faces].mean(1);face_normal=normal[faces].mean(1)
    selected=np.empty(len(faces),dtype=np.int64);distance=np.empty(len(faces))
    for start in range(0,len(faces),2048):
        stop=min(start+2048,len(faces));_,candidate=tree.query(face_points[start:stop],k=min(32,len(rt)))
        bary,d2=closest_triangles(face_points[start:stop,None,:],triangle[candidate])
        agreement=1-np.einsum('ij,ikj->ik',face_normal[start:stop],ref_normal[candidate])
        choice=np.argmin(d2+.0002*agreement,axis=1);rows=np.arange(stop-start)
        selected[start:stop]=candidate[rows,choice];distance[start:stop]=np.sqrt(d2[rows,choice])
    desired_island=islands[selected]
    pairs=np.column_stack([faces.reshape(-1),np.repeat(desired_island,3)])
    unique,inverse=np.unique(pairs,axis=0,return_inverse=True)
    uv=np.empty((len(unique),2));color=np.empty((len(unique),3));sample_distance=np.empty(len(unique))
    for island in np.unique(unique[:,1]):
        rows=np.flatnonzero(unique[:,1]==island);source=np.flatnonzero(islands==island)
        local_tree=cKDTree(centers[source])
        for start in range(0,len(rows),2048):
            batch=rows[start:start+2048];query=p[unique[batch,0]]
            _,candidate=local_tree.query(query,k=min(32,len(source)))
            if candidate.ndim==1:candidate=candidate[:,None]
            candidate=source[candidate]
            bary,d2=closest_triangles(query[:,None,:],triangle[candidate])
            agreement=1-np.einsum('ij,ikj->ik',normal[unique[batch,0]],ref_normal[candidate])
            choice=np.argmin(d2+.0002*agreement,axis=1);local=np.arange(len(batch))
            triangle_index=candidate[local,choice];bary=bary[local,choice]
            uv_bary=plane_barycentric(query,triangle[triangle_index])
            uv[batch]=np.einsum('ij,ijk->ik',uv_bary,reference['corners']['TEXCOORD'][triangle_index,:,:2])
            color[batch]=np.einsum('ij,ijk->ik',bary,reference['corners']['COLOR'][triangle_index,:,:3])
            sample_distance[batch]=np.sqrt(d2[local,choice])
    # Restore exact native collar UVs, choosing its original seam-side option.
    native_uv={}
    for vertex in body['collar_native_indices']:
        native_uv[int(vertex)]=native['corners']['TEXCOORD'][np.any(native['triangles']==vertex,axis=1)]
        options=[]
        for fi,tri in enumerate(native['triangles']):
            for c in np.flatnonzero(tri==vertex):options.append(native['corners']['TEXCOORD'][fi,c,:2])
        native_uv[int(vertex)]=np.unique(options,axis=0)
    for vertex,original in zip(body['collar_vertex_indices'],body['collar_native_indices']):
        rows=np.flatnonzero(unique[:,0]==vertex);options=native_uv[int(original)]
        for row in rows:uv[row]=options[np.argmin(np.linalg.norm(options-uv[row],axis=1))]
        candidates=np.argwhere(native['triangles']==original)
        native_normal=native['corners']['NORMAL'][candidates[0,0],candidates[0,1],:3]
        normal[vertex]=native_normal/np.linalg.norm(native_normal)
    rgba=np.column_stack([np.rint(np.clip(color,0,1)*255).astype(np.int64),np.full(len(color),255)])
    result={'positions':p[unique[:,0]],'normals':normal[unique[:,0]],'uvs':uv,
        'colors_rgba8':rgba,'bone_weights':body['bone_weights'][unique[:,0]],
        'triangles':inverse.reshape(-1,3),'source_vertex_ids':body['source_vertex_ids'][unique[:,0]],
        'geometry_vertex_ids':unique[:,0],'uv_island_ids':unique[:,1]}
    report={'method':'native face-chart UV extrapolation within face-selected UV island; clamped native RGB paint',
        'reference_uv_islands':int(islands.max()+1),'export_vertices':len(unique),
        'geometry_vertices':len(p),'uv_seam_copies':len(unique)-len(p),
        'reference_surface_distance_mean':float(sample_distance.mean()),
        'reference_surface_distance_p99':float(np.percentile(sample_distance,99)),
        'reference_surface_distance_max':float(sample_distance.max()),
        'positions_changed_for_uv_transfer':False,'paint_red_positive_vertices':int((rgba[:,0]>0).sum())}
    return result,report


def tangent_frames(positions,triangles,normals,uvs):
    p=positions[triangles];uv=uvs[triangles]
    e1=p[:,1]-p[:,0];e2=p[:,2]-p[:,0];a=uv[:,1]-uv[:,0];b=uv[:,2]-uv[:,0]
    det=a[:,0]*b[:,1]-a[:,1]*b[:,0];valid=abs(det)>1e-12
    factor=np.where(valid,1/np.where(valid,det,1),0)
    tangent=(e1*b[:,1,None]-e2*a[:,1,None])*factor[:,None]
    bitangent=(e2*a[:,0,None]-e1*b[:,0,None])*factor[:,None]
    t=np.zeros_like(positions);b=np.zeros_like(positions)
    for corner in range(3):np.add.at(t,triangles[:,corner],tangent);np.add.at(b,triangles[:,corner],bitangent)
    t-=normals*np.sum(t*normals,axis=1,keepdims=True)
    missing=np.linalg.norm(t,axis=1)<1e-10
    if np.any(missing):
        axis=np.tile([1.,0.,0.],(missing.sum(),1));n=normals[missing]
        axis[abs(n[:,0])>.9]=[0.,0.,1.];t[missing]=np.cross(axis,n)
    t/=np.maximum(np.linalg.norm(t,axis=1,keepdims=True),1e-12)
    sign=np.where(np.sum(np.cross(normals,t)*b,axis=1)<0,-1,1)
    return t,np.cross(normals,t)*sign[:,None],{'degenerate_uv_triangles':int((~valid).sum()),
                'fallback_tangent_vertices':int(missing.sum())}


def body_payload(body,native):
    if len(body['positions'])>65535:raise ValueError('Dense export exceeds the 16-bit vertex budget')
    ids,weights,report=quantize_weights(body['bone_weights'])
    tangent,binormal,tangent_report=tangent_frames(body['positions'],body['triangles'],body['normals'],body['uvs'])
    result={'name':BODY_NAME,'positions':body['positions'].tolist(),'normals':body['normals'].tolist(),
        'tangents':tangent.tolist(),'binormals':binormal.tolist(),'uvs':body['uvs'].tolist(),
        'colors_rgba8':body['colors_rgba8'].tolist(),'bone_palette':list(native['bone_palette']),
        'bone_indices':ids.tolist(),'bone_weights':weights.tolist(),'triangles':body['triangles'].tolist()}
    for name,array in result.items():
        if name not in ('name','bone_palette') and not np.isfinite(np.asarray(array)).all():
            raise ValueError('Nonfinite payload attribute: '+name)
    report['tangent_frames']=tangent_report
    report['minimum_byte_weight_sum']=int(weights.sum(1).min());report['maximum_byte_weight_sum']=int(weights.sum(1).max())
    return {'schema_version':1,'proxy_from_body':True,'meshes':[result]},report


JUNO_STRAY_FACIAL_SOURCE_IDS = (6030,6032,6033,8608,8609,15182,15204,15205,
    15206,15208,15209,15214,15216,15871,15923,15924,15928)


def repair_juno_stray_facial_weights(payload,prepared,source_bones):
    """Explicit reviewed repair of 17 surviving stray tongue-to-hip weights.

    The source tongue is spatially facial, not a repurposed pelvis control.
    Only the already exported positive Head_M byte lanes on the approved raw
    donor vertex IDs move to Root_M. Geometry and every other byte stay exact.
    """
    from copy import deepcopy
    bone=source_bones['DEF.Tongue.004']
    if min(bone['rest_head_world'][2],bone['posed_head_world'][2])<1.35:
        raise ValueError('Source tongue is not the reviewed facial bone')
    result=deepcopy(payload);mesh=result['meshes'][0];names=mesh['bone_palette']
    head=names.index('Head_M');root=names.index('Root_M')
    indices=np.array(mesh['bone_indices']);weights=np.array(mesh['bone_weights'])
    head_mass=np.where(indices==head,weights,0).sum(1)
    rows=np.flatnonzero(head_mass>0)
    actual=prepared['source_vertex_ids'][rows]
    if len(rows)!=17 or set(actual.tolist())!=set(JUNO_STRAY_FACIAL_SOURCE_IDS):
        raise ValueError('Positive facial-weight rows differ from the explicit 17-vertex review')
    changes=[];full=prepared['bone_weights'].copy()
    for row in rows:
        before_head=int(head_mass[row]);before_root=int(np.where(indices[row]==root,weights[row],0).sum())
        head_lanes=np.flatnonzero((indices[row]==head)&(weights[row]>0))
        root_lanes=np.flatnonzero(indices[row]==root)
        if len(root_lanes):
            weights[row,root_lanes[0]]+=before_head;weights[row,head_lanes]=0;indices[row,head_lanes]=0
        else:
            indices[row,head_lanes[0]]=root
        # Stable descending byte order; exact byte mass is otherwise unchanged.
        order=np.argsort(-weights[row],kind='stable');indices[row]=indices[row,order];weights[row]=weights[row,order]
        changes.append({'export_vertex':int(row),'source_vertex_id':int(prepared['source_vertex_ids'][row]),
            'head_byte_before':before_head,'head_byte_after':0,
            'root_byte_before':before_root,'root_byte_after':before_root+before_head,
            'head_normalized_before':float(full[row,head]),'root_normalized_before':float(full[row,root])})
        full[row,root]+=full[row,head];full[row,head]=0
    if np.any(weights.sum(1)!=255):raise ValueError('Facial repair changed byte weight totals')
    mesh['bone_indices']=indices.tolist();mesh['bone_weights']=weights.tolist()
    for key in payload['meshes'][0]:
        if key not in ('bone_indices','bone_weights') and mesh[key]!=payload['meshes'][0][key]:
            raise ValueError('Facial repair changed non-skin attribute '+key)
    report={'reason':'Original facial DEF.Tongue.004 has stray positive hip weights; never a pelvis control',
        'source_bone':{k:bone[k] for k in ('name','parent','rest_head_world','rest_tail_world','posed_head_world','posed_tail_world')},
        'explicit_source_vertex_ids':list(JUNO_STRAY_FACIAL_SOURCE_IDS),'changed_export_vertices':len(rows),
        'mapping':'positive exported Head_M bytes -> Root_M only',
        'total_byte_mass_moved':int(head_mass[rows].sum()),'changes':changes,
        'positions_normals_uvs_colors_triangles_bit_equal':True,
        'all_other_skin_rows_bit_equal':True,'positive_exported_head_weights_after':0,
        'microscopic_full_precision_weights_elsewhere':'preserved; none survive four-lane byte export'}
    return result,full,report


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
