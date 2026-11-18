"""Mercy's reviewed hybrid DAZ/Rigify profile with its original large sculpt.

Only generic weighted segment rotation is shared with the seven-spine authoring
math. Calibration and the weighted DAZ neck/pelvis aliases are reviewed here.
"""
from __future__ import annotations

import numpy as np
from .cinderella_body import active_bones, pose as rotate_segments
from .donor_body import native_collar


def validate_rig(metadata):
    if (metadata.get('id') != 'mercy_c'
            or metadata['vertex_group_validation']['active_vertex_group_rigs'] != ['Mercy_rig']):
        raise ValueError('Mercy profile requires its exact reviewed active hybrid rig')
    bones=active_bones(metadata)
    required={'neckLower','head neck middle','head neck upper','pelvis','hip',
              'abdomenLower','abdomenUpper','chestLower','chestUpper'}
    if not required<=set(bones):
        raise ValueError('Mercy weighted DAZ anchors are missing')
    return bones


def calibrate(arrays,metadata,native):
    bones=validate_rig(metadata)
    p=np.asarray(arrays['positions'],dtype=np.float64)
    if p.ndim!=2 or p.shape[1]!=3 or not np.isfinite(p).all():
        raise ValueError('Invalid Mercy source positions')
    ground=float(p[:,2].min());target_ground=float(native['positions'][:,1].min())
    shoulder=np.mean([bones['DEF-upper_arm.'+s]['posed_head_world'] for s in ('L','R')],axis=0)[[0,2,1]]
    # DEF-spine.005 is a controller segment above the actual weighted neck base.
    neck=np.asarray(bones['neckLower']['posed_head_world'])[[0,2,1]]
    native_shoulder=np.mean([native['bone_world']['Shoulder_'+s][:3,3] for s in ('L','R')],axis=0)
    native_neck=native['bone_world']['Neck_M'][:3,3]
    a=np.array([shoulder[1],neck[1]])-ground
    b=np.array([native_shoulder[1],native_neck[1]])-target_ground
    if np.any(a<=0):raise ValueError('Mercy landmarks are below the source ground')
    scale=float(a@b/(a@a))
    if not .5<=scale<=1.5:raise ValueError('Mercy uniform landmark scale outside reviewed range')
    shift=np.array([native_shoulder[0]-scale*shoulder[0],target_ground-scale*ground,
        np.mean([native_shoulder[2]-scale*shoulder[2],native_neck[2]-scale*neck[2]])])
    collar=native['positions'][native_collar(native)]
    interval=abs(float(native['bone_world']['Head_M'][1,3]-native_neck[1]))
    if not .05<interval<.2:raise ValueError('Unexpected native neck interval')
    return {'profile':'mercy-hybrid-daz-rigify-v1','uniform_scale':scale,
        'translation_bg3':shift.tolist(),'axis_order':[0,2,1],'reverse_winding':True,
        'source_ground_z':ground,'native_ground_y':target_ground,
        'source_neck_anchor':'neckLower','native_neck_anchor':'Neck_M',
        'source_shoulder':shoulder.tolist(),'native_shoulder':native_shoulder.tolist(),
        'source_neck':neck.tolist(),'native_neck':native_neck.tolist(),
        'placed_shoulder_residual':(shoulder*scale+shift-native_shoulder).tolist(),
        'placed_neck_residual':(neck*scale+shift-native_neck).tolist(),
        'scale_method':'one uniform least-squares scale from shoulder and weighted neck-base heights above source mesh ground',
        'head_cut_base_height':min(float(native_neck[1]-.35*interval),float(collar[:,1].min()-.018)),
        'neck_transition_band':.3*interval}


def protect_pelvic_source_pose(result,weights,names,bones,calibration):
    """Retain the authored central anatomy instead of rotating thigh bleed.

    The Genitals/Anus hierarchy and the author's Anus skin support define the
    region. No collision face IDs, candidate intersections or edited skin
    weights participate in the mask. It attenuates only the offline neutral
    pose displacement, and is not a claim about subsequent game animation.
    """
    for name in ('Genitals','Anus'):
        if name not in bones or bones[name]['parent']!='pelvis' or not bones[name]['deform']:
            raise ValueError('Expected the reviewed anatomical Genitals/Anus to pelvis hierarchy')
    scale=calibration['uniform_scale'];shift=np.asarray(calibration['translation_bg3'])
    def point(name,end='head'):
        return np.asarray(bones[name]['posed_'+end+'_world'])[[0,2,1]]*scale+shift
    def is_descendant(name,ancestor):
        seen=set()
        while name and name not in seen:
            if name==ancestor:return True
            seen.add(name);name=bones.get(name,{}).get('parent')
        return False
    columns=[i for i,name in enumerate(names) if is_descendant(name,'Anus')]
    support=weights[:,columns].sum(1)>1e-6
    if not support.any():raise ValueError('Anus has no captured author skin support')
    source=result['scaled_source_positions'];previous=result['positions']
    center=float(np.mean([point(name)[0] for name in ('Genitals','Anus')]))
    radius=float(np.max(abs(source[support,0]-center)))
    if not .001<radius<.05:raise ValueError('Unexpected anatomical midline support radius')
    segment=float(np.mean([np.linalg.norm(point(name,'tail')-point(name)) for name in ('Genitals','Anus')]))
    if not .005<segment<.08:raise ValueError('Unexpected source anatomy segment length')
    inner=.25*radius;outer=2*radius
    lower=min(point(name)[1] for name in ('Genitals','Anus'))-.5*segment
    upper=float(point('pelvis','tail')[1])
    if upper<=lower:raise ValueError('Anatomical protection vertical limits are reversed')
    def smooth(value):
        value=np.clip(value,0,1);return value*value*(3-2*value)
    protection=(1-smooth((abs(source[:,0]-center)-inner)/(outer-inner)))
    protection*=smooth((source[:,1]-(lower-segment))/segment)
    protection*=1-smooth((source[:,1]-upper)/segment)
    active=protection>0;full=protection>=1
    corrected=previous.copy()
    corrected[active]=source[active]+result['pose_displacement'][active]*(1-protection[active,None])
    corrected[full]=source[full]
    if not np.array_equal(corrected[~active],previous[~active]):
        raise ValueError('Pelvic mask changed points outside its declared anatomy field')
    difference=corrected-previous;changed=np.linalg.norm(difference,axis=1)>1e-12
    breast=(result['source_breast_influence_left']+result['source_breast_influence_right'])>0
    if np.any(changed&breast):raise ValueError('Anatomical pose protection reached authored breasts')
    result['positions']=corrected;result['pose_displacement']=corrected-source
    result['source_pelvic_pose_protection']=protection
    result['pelvic_pose_restoration_displacement']=difference
    return {'method':'source-anatomical central seam protection of offline neutral leg pose',
        'hierarchy':{'Genitals':bones['Genitals']['parent'],'Anus':bones['Anus']['parent'],'pelvis':bones['pelvis']['parent']},
        'support_group_names':[names[i] for i in columns],'author_support_vertices':int(support.sum()),
        'midline_x_m':center,'author_anus_support_radius_m':radius,
        'full_protection_half_width_m':inner,'zero_protection_half_width_m':outer,
        'full_protection_vertical_m':[float(lower),float(upper)],'vertical_fade_m':segment,
        'mask_definition':'(1-smooth lateral distance) * smooth lower height * (1-smooth upper height), using scaled-source coordinates',
        'protected_source_vertex_ids':np.flatnonzero(full).tolist(),'changed_source_vertex_ids':np.flatnonzero(changed).tolist(),
        'changed_vertices':int(changed.sum()),'maximum_source_restoration_m':float(np.linalg.norm(difference,axis=1).max()),
        'rms_source_restoration_changed_m':float(np.sqrt(np.mean(np.sum(difference[changed]**2,axis=1)))) if changed.any() else 0.,
        'all_outside_field_positions_bit_equal':True,'fully_protected_positions_bit_equal_to_scaled_source':True,
        'breast_vertices_changed':0,'exported_skin_weights_changed':False,'source_triangle_topology_changed':False,
        'collision_pair_ids_used_to_define_field':False,'game_animation_validation':'unverified'}


def pose(arrays,metadata,native,calibration,*,align_hip_x=False,protect_pelvic_seam=False):
    validate_rig(metadata)
    result,weights,names,bones,report=rotate_segments(arrays,metadata,native,calibration,align_hip_x=align_hip_x)
    for label,prefix in [('left','l'),('right','r')]:
        groups=[i for i,name in enumerate(names) if name==prefix+'_Pectoral']
        if not groups:raise ValueError('Mercy source pectoral group missing')
        result['source_breast_influence_'+label]=weights[:,groups].sum(1)
    if protect_pelvic_seam:
        report['source_pelvic_pose_protection']=protect_pelvic_source_pose(result,weights,names,bones,calibration)
        report['pose_changed_vertices']=int(np.count_nonzero(np.linalg.norm(result['pose_displacement'],axis=1)>1e-12))
        report['maximum_pose_displacement']=float(np.linalg.norm(result['pose_displacement'],axis=1).max())
    report['profile']='mercy-hybrid-daz-rigify-v1'
    return result,weights,names,bones,report


def semantic_anchors():
    anchors={'root':'Root_M','hip':'Root_M','pelvis':'Root_M',
        'DEF-spine':'Root_M','DEF-spine.001':'Spine1_M','DEF-spine.002':'Spine2_M',
        'DEF-spine.003':'Chest_M','DEF-spine.004':'Neck_M','DEF-spine.005':'Neck_M','DEF-spine.006':'Head_M',
        'abdomenLower':'Spine1_M','abdomenUpper':'Spine2_M','chestLower':'Chest_M','chestUpper':'Chest_M',
        'neckLower':'Neck_M','head neck middle':'Neck_M','head neck upper':'Head_M','head':'Head_M'}
    for side,prefix in [('L','l'),('R','r')]:
        for source,target in [('shoulder','Scapula'),('upper_arm','Shoulder'),('forearm','Elbow'),
            ('hand','Wrist'),('thigh','Hip'),('shin','Knee'),('foot','Ankle'),('toe','Toes')]:
            for suffix in ('','.001'):anchors['DEF-'+source+'.'+side+suffix]=target+'_'+side
        for source,target in [('f_index','IndexFinger'),('f_middle','MiddleFinger'),
            ('f_ring','RingFinger'),('f_pinky','PinkyFinger'),('thumb','ThumbFinger')]:
            for i in range(1,4):anchors['DEF-'+source+'.%02d.'%i+side]=target+str(i)+'_'+side
        for i in range(1,5):
            anchors['DEF-palm.%02d.'%i+side]=('RingFinger0_' if i==3 else 'PinkyFinger0_' if i==4 else 'Wrist_')+side
        anchors[prefix+'_Pectoral']='Chest_M'
        anchors[prefix+'Metatarsals']='Toes_'+side
    return anchors


def map_weights(weights,names,bones,native_names):
    anchors=semantic_anchors();mapped=np.zeros((len(weights),len(native_names)));resolved={}
    for index,name in enumerate(names):
        if not np.any(weights[:,index]>0):continue
        at=name;seen=set()
        while at not in anchors:
            if not at or at in seen or at not in bones:
                raise ValueError('Unmapped positive Mercy group: '+name)
            seen.add(at);at=bones[at]['parent']
        target=anchors[at]
        if target not in native_names:raise ValueError('Missing native Mercy joint '+target)
        mapped[:,native_names.index(target)]+=weights[:,index]
        resolved[name]={'anchor':at,'target':target,'direct':name==at}
    if not np.allclose(mapped.sum(1),1,atol=1e-12):raise ValueError('Mercy mapping lost normalized mass')
    return mapped,{'profile':'mercy-hybrid-daz-rigify-v1','semantic_anchors':anchors,
                   'resolved_positive_groups':resolved,'unknown_positive_groups':[]}
