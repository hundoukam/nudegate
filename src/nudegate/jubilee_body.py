"""Reviewed modern Marvel Rivals Jubilee body, using its own eight-spine rig."""
from __future__ import annotations
import copy
import numpy as np
from .donor_body import native_collar,pose_donor
from .mercy_body import semantic_anchors as common_rigify_anchors


def validate_rig(metadata):
    if metadata.get('id')!='jubilee_b' or metadata['vertex_group_validation']['active_vertex_group_rigs']!=['Rig']:
        raise ValueError('Jubilee profile requires the exact selected Marvel Rivals capture')
    bones={b['name']:b for r in metadata['rigs'] if r['name']=='Rig' for b in r['bones']}
    expected={'DEF-spine'}|{'DEF-spine.%03d'%i for i in range(1,8)}
    if {name for name in bones if name.startswith('DEF-spine')}!=expected:
        raise ValueError('Jubilee requires its reviewed eight-spine anatomy')
    if not {'pectoral.L','pectoral.R','Butt.L','Butt.R'}<=set(bones):
        raise ValueError('Missing reviewed Jubilee body anchors')
    return bones


def calibrate(arrays,metadata,native):
    bones=validate_rig(metadata);p=np.asarray(arrays['positions'],dtype=np.float64)
    if p.ndim!=2 or p.shape[1]!=3 or not np.isfinite(p).all():raise ValueError('Invalid Jubilee source positions')
    ground=float(p[:,2].min());target_ground=float(native['positions'][:,1].min())
    shoulder=np.mean([bones['DEF-upper_arm.'+s]['posed_head_world'] for s in ('L','R')],axis=0)[[0,2,1]]
    neck=np.asarray(bones['DEF-spine.005']['posed_head_world'])[[0,2,1]]
    target_shoulder=np.mean([native['bone_world']['Shoulder_'+s][:3,3] for s in ('L','R')],axis=0)
    target_neck=native['bone_world']['Neck_M'][:3,3]
    a=np.array([shoulder[1],neck[1]])-ground;b=np.array([target_shoulder[1],target_neck[1]])-target_ground
    if np.any(a<=0):raise ValueError('Jubilee landmarks are below ground')
    scale=float(a@b/(a@a))
    if not .5<=scale<=1.5:raise ValueError('Jubilee uniform placement scale outside reviewed range')
    translation=np.array([target_shoulder[0]-scale*shoulder[0],target_ground-scale*ground,
        np.mean([target_shoulder[2]-scale*shoulder[2],target_neck[2]-scale*neck[2]])])
    interval=abs(float(native['bone_world']['Head_M'][1,3]-target_neck[1]))
    if not .05<interval<.2:raise ValueError('Unexpected native neck interval')
    collar=native['positions'][native_collar(native)]
    return {'profile':'jubilee-marvel-rivals-eight-spine-v1','uniform_scale':scale,
        'translation_bg3':translation.tolist(),'axis_order':[0,2,1],'reverse_winding':True,
        'source_ground_z':ground,'native_ground_y':target_ground,
        'source_neck_anchor':'DEF-spine.005','native_neck_anchor':'Neck_M',
        'source_shoulder':shoulder.tolist(),'native_shoulder':target_shoulder.tolist(),
        'source_neck':neck.tolist(),'native_neck':target_neck.tolist(),
        'placed_shoulder_residual':(shoulder*scale+translation-target_shoulder).tolist(),
        'placed_neck_residual':(neck*scale+translation-target_neck).tolist(),
        'scale_method':'independent uniform least-squares shoulder/neck height fit above exact source ground',
        'head_cut_base_height':min(float(target_neck[1]-.35*interval),float(collar[:,1].min()-.018)),
        'neck_transition_band':.3*interval}


def pose(arrays,metadata,native,calibration,*,align_hip_x=True):
    validate_rig(metadata)
    scale=calibration['uniform_scale'];shift=np.asarray(calibration['translation_bg3'])
    placed=dict(arrays);placed['positions']=np.asarray(arrays['positions'],dtype=np.float64)*scale+shift[[0,2,1]]
    transformed=copy.deepcopy(metadata)
    for rig in transformed['rigs']:
        for bone in rig['bones']:
            for field in ('posed_head_world','posed_tail_world'):
                if bone.get(field) is not None:bone[field]=(np.asarray(bone[field])*scale+shift[[0,2,1]]).tolist()
    result,weights,names,bones,report=pose_donor(placed,transformed,native,1.,align_hip_x=align_hip_x)
    expected=np.asarray(arrays['positions'],dtype=np.float64)[:,[0,2,1]]*scale+shift
    if not np.array_equal(result['scaled_source_positions'],expected):
        raise ValueError('Jubilee placement does not match the declared source representation')
    for label,side in [('left','L'),('right','R')]:
        result['source_breast_influence_'+label]=weights[:,names.index('pectoral.'+side)]
    report.update(profile=calibration['profile'],calibration=calibration,uniform_scale=scale,
        translation_bg3=shift.tolist(),source_already_posed=True,
        source_pose_policy='only limb corrections after evaluated source capture; source armature is never applied twice')
    return result,weights,names,bones,report


def semantic_anchors():
    anchors=common_rigify_anchors()
    anchors.update({'DEF-spine.004':'Chest_M','DEF-spine.005':'Neck_M',
        'DEF-spine.006':'Neck_M','DEF-spine.007':'Head_M','ORG-spine':'Root_M',
        'pectoral.L':'Chest_M','pectoral.R':'Chest_M','Butt.L':'Root_M','Butt.R':'Root_M'})
    return anchors


def map_weights(weights,names,bones,native_names):
    anchors=semantic_anchors();mapped=np.zeros((len(weights),len(native_names)));resolved={}
    for index,name in enumerate(names):
        if not np.any(weights[:,index]>0):continue
        at=name;seen=set()
        while at not in anchors:
            if not at or at in seen or at not in bones:raise ValueError('Unmapped positive Jubilee group: '+name)
            seen.add(at);at=bones[at]['parent']
        target=anchors[at]
        if target not in native_names:raise ValueError('Missing native Jubilee joint '+target)
        mapped[:,native_names.index(target)]+=weights[:,index]
        resolved[name]={'anchor':at,'target':target,'direct':name==at}
    if not np.allclose(mapped.sum(1),1,atol=1e-12):raise ValueError('Jubilee mapping lost normalized mass')
    return mapped,{'profile':'jubilee-marvel-rivals-eight-spine-v1','semantic_anchors':anchors,
                   'resolved_positive_groups':resolved,'unknown_positive_groups':[]}
