"""Reviewed Kiriko 2.0 C profile: authored shape and seven-spine source rig.

Kiriko's independently parented five-toe deform chains must receive the same
offline foot-pose correction. Her original active breast control and DEF bone
weights both contribute; neither family is silently discarded.
"""
from __future__ import annotations
import re
import numpy as np
from .donor_body import normalized_deform_weights,rotation_between,native_collar,fit_segment_endpoints


PROFILE='kiriko-2-rigify-seven-spine-v1'


def validate_rig(metadata):
    if metadata.get('id')!='kiriko_2_0_c' or metadata['vertex_group_validation']['active_vertex_group_rigs']!=['Kiriko Rig']:
        raise ValueError('Kiriko profile requires its exact reviewed active source rig')
    if metadata.get('key_overrides')!={'BreastSize':1}:
        raise ValueError('Kiriko profile requires selected C BreastSize=1')
    rigs=[r for r in metadata['rigs'] if r['name']=='Kiriko Rig']
    if len(rigs)!=1 or len(rigs[0]['bones'])!=1080:
        raise ValueError('Kiriko source rig count differs from the reviewed 1080 bones')
    bones={b['name']:b for b in rigs[0]['bones']}
    expected=['DEF-spine']+['DEF-spine.%03d'%i for i in range(1,7)]
    if sorted(n for n in bones if n.startswith('DEF-spine'))!=sorted(expected):
        raise ValueError('Kiriko requires its independently reviewed seven-spine chain')
    for name,parent in [('DEF-spine.004','DEF-spine.003'),('DEF-spine.005','DEF-spine.004'),
                        ('DEF-spine.006','DEF-spine.005'),('Vagina_Overall','tweak_spine'),('Anus_control','tweak_spine')]:
        if bones.get(name,{}).get('parent')!=parent:
            raise ValueError('Kiriko weighted neck/anatomy hierarchy changed: '+name)
    for side in ('L','R'):
        for number in ('','.001','.003','.004','.006','.007','.009','.010','.012','.013'):
            name='DEF-toes.'+side+number
            if name not in bones or not bones[name]['deform']:
                raise ValueError('Kiriko independent toe deform chain missing: '+name)
        if bones['DEF-toes.'+side]['parent']!='ORG-toe.'+side:
            raise ValueError('Kiriko independent toe-chain parent changed')
    return bones


def calibrate(arrays,metadata,native):
    bones=validate_rig(metadata);p=np.asarray(arrays['positions'],float)
    if p.ndim!=2 or p.shape[1]!=3 or not np.isfinite(p).all():raise ValueError('Invalid Kiriko source positions')
    ground=float(p[:,2].min());native_ground=float(native['positions'][:,1].min())
    shoulder=np.mean([bones['DEF-upper_arm.'+s]['posed_head_world']for s in ('L','R')],axis=0)[[0,2,1]]
    neck=np.asarray(bones['DEF-spine.005']['posed_head_world'])[[0,2,1]]
    target_shoulder=np.mean([native['bone_world']['Shoulder_'+s][:3,3]for s in ('L','R')],axis=0)
    target_neck=native['bone_world']['Neck_M'][:3,3]
    a=np.array([shoulder[1],neck[1]])-ground
    b=np.array([target_shoulder[1],target_neck[1]])-native_ground
    if np.any(a<=0):raise ValueError('Kiriko landmarks lie below its mesh ground')
    scale=float(a@b/(a@a))
    if not .5<scale<1.5:raise ValueError('Kiriko uniform calibration out of range')
    translation=np.array([target_shoulder[0]-scale*shoulder[0],native_ground-scale*ground,
        np.mean([target_shoulder[2]-scale*shoulder[2],target_neck[2]-scale*neck[2]])])
    collar=native['positions'][native_collar(native)]
    neck_interval=float(abs(native['bone_world']['Head_M'][1,3]-target_neck[1]))
    if not .05<neck_interval<.2:raise ValueError('Unexpected native neck interval')
    return {'profile':PROFILE,'uniform_scale':scale,'translation_bg3':translation.tolist(),
        'axis_order':[0,2,1],'reverse_winding':True,'source_ground_z':ground,'native_ground_y':native_ground,
        'source_neck_anchor':'DEF-spine.005','native_neck_anchor':'Neck_M',
        'source_shoulder':shoulder.tolist(),'native_shoulder':target_shoulder.tolist(),
        'source_neck':neck.tolist(),'native_neck':target_neck.tolist(),
        'placed_shoulder_residual':(shoulder*scale+translation-target_shoulder).tolist(),
        'placed_neck_residual':(neck*scale+translation-target_neck).tolist(),
        'scale_method':'own ground plus least-squares shoulder/lower-head-neck heights; one uniform scale',
        'neck_review':'DEF-spine.004 is lower neck/trapezius below .005; .005 is the weighted neck base; .006 is head',
        'head_cut_base_height':min(float(target_neck[1]-.35*neck_interval),float(collar[:,1].min()-.018)),
        'neck_transition_band':.3*neck_interval}


def source_limb(name,bones):
    seen=set()
    while name and name not in seen:
        seen.add(name)
        toe=re.fullmatch(r'DEF-toes\.([LR])(?:\.\d{3})?',name)
        if toe:return 'toe',toe.group(1)
        for part in ('hand','forearm','upper_arm','toe','foot','shin','thigh'):
            for side in ('L','R'):
                if name in ('DEF-'+part+'.'+side,'DEF-'+part+'.'+side+'.001'):return part,side
        name=bones.get(name,{}).get('parent')
    return None


def protect_anatomical_source_pose(result,weights,names,bones,calibration,*,mode='axis'):
    """Preserve Kiriko's author-weighted central anatomy during neutral posing.

    Its active Vagina_Overall and Anus_control bones share tweak_spine rather
    than Mercy's DAZ pelvis chain. This mask uses only those source anatomical
    anchors and skin-support dimensions, never a contact pair or selected face.
    """
    for name in ('Vagina_Overall','Anus_control'):
        if bones.get(name,{}).get('parent')!='tweak_spine' or not bones[name]['deform']:
            raise ValueError('Kiriko source anatomy hierarchy changed')
    scale=calibration['uniform_scale'];shift=np.asarray(calibration['translation_bg3'])
    def point(name,end='head'):
        return np.asarray(bones[name]['posed_'+end+'_world'])[[0,2,1]]*scale+shift
    columns=[i for i,name in enumerate(names)if name=='Anus_control']
    if not columns:raise ValueError('Kiriko Anus_control skin support missing')
    support=weights[:,columns].sum(1)>1e-6
    if not support.any():raise ValueError('Kiriko anatomical control has no captured support')
    source=result['scaled_source_positions'];previous=result['positions']
    center=float(np.mean([point(name)[0]for name in ('Vagina_Overall','Anus_control')]))
    radius=float(np.max(abs(source[support,0]-center)))
    segment=float(np.mean([np.linalg.norm(point(name,'tail')-point(name))for name in ('Vagina_Overall','Anus_control')]))
    if not .001<radius<.05 or not .005<segment<.08:
        raise ValueError('Kiriko anatomy support dimensions differ from reviewed bounds')
    inner=.25*radius;outer=2*radius
    lower=min(point(name)[1]for name in ('Vagina_Overall','Anus_control'))-.5*segment
    upper=float(point('tweak_spine','tail')[1])
    if upper<=lower:raise ValueError('Kiriko anatomical vertical anchors reversed')
    def smooth(value):
        value=np.clip(value,0,1);return value*value*(3-2*value)
    if mode=='axis':
        protection=(1-smooth((abs(source[:,0]-center)-inner)/(outer-inner)))
        protection*=smooth((source[:,1]-(lower-segment))/segment)
        protection*=1-smooth((source[:,1]-upper)/segment)
        mask_parameters={'full_protection_half_width_m':inner,'zero_protection_half_width_m':outer,
            'full_protection_vertical_m':[float(lower),float(upper)],'vertical_fade_m':segment,
            'mask_definition':'separable C1 source-midline and source-anchor-height protection'}
    elif mode=='source-support':
        from scipy.spatial import cKDTree
        def anatomical(name):
            seen=set()
            while name and name not in seen:
                if name in ('Vagina_Overall','Anus_control'):return True
                seen.add(name);name=bones.get(name,{}).get('parent')
            return False
        anatomy_columns=[i for i,name in enumerate(names)if anatomical(name)]
        anatomy_support=weights[:,anatomy_columns].sum(1)>1e-6
        if not anatomy_support.any():raise ValueError('Kiriko complete anatomical skin support is empty')
        support_points=source[anatomy_support];low=support_points.min(0);high=support_points.max(0)
        if max(abs(low[0]),abs(high[0]))>.15 or low[1]<.8 or high[1]>1.25:
            raise ValueError('Kiriko anatomical source weights extend beyond the reviewed local pelvis')
        distance=cKDTree(support_points).query(source)[0]
        protection=1-smooth(distance/segment)
        mask_parameters={'full_anatomical_support_group_names':[names[i]for i in anatomy_columns],
            'full_anatomical_support_vertex_ids':np.flatnonzero(anatomy_support).tolist(),
            'full_anatomical_support_vertices':int(anatomy_support.sum()),
            'full_anatomical_source_bounds':[low.tolist(),high.tolist()],
            'source_support_distance_fade_m':segment,
            'mask_definition':'1-smooth(distance to original author-anatomy-supported vertices / mean anatomy control length)'}
    else:raise ValueError('Unknown Kiriko anatomical pose-mask mode')
    active=protection>0;full=protection>=1
    corrected=previous.copy()
    corrected[active]=source[active]+result['pose_displacement'][active]*(1-protection[active,None])
    corrected[full]=source[full]
    difference=corrected-previous;changed=np.linalg.norm(difference,axis=1)>1e-12
    breast=(result['source_breast_influence_left']+result['source_breast_influence_right'])>0
    if np.any(changed&breast):raise ValueError('Kiriko anatomical pose protection reached authored breast tissue')
    if not np.array_equal(corrected[~active],previous[~active]):raise ValueError('Kiriko mask changed outer donor geometry')
    result['positions']=corrected;result['pose_displacement']=corrected-source
    result['source_pelvic_pose_protection']=protection;result['pelvic_pose_restoration_displacement']=difference
    return {'method':'Kiriko source-anatomical central seam protection of offline leg pose','mask_mode':mode,
        'hierarchy':{name:bones[name]['parent']for name in ('Vagina_Overall','Anus_control','tweak_spine')},
        'support_group_names':[names[i]for i in columns],'author_support_vertices':int(support.sum()),
        'midline_x_m':center,'author_anus_support_radius_m':radius,
        **mask_parameters,
        'protected_source_vertex_ids':np.flatnonzero(full).tolist(),'changed_source_vertex_ids':np.flatnonzero(changed).tolist(),
        'changed_vertices':int(changed.sum()),'maximum_source_restoration_m':float(np.linalg.norm(difference,axis=1).max()),
        'rms_source_restoration_changed_m':float(np.sqrt(np.mean(np.sum(difference[changed]**2,axis=1))))if changed.any()else 0.,
        'all_outside_field_positions_bit_equal':True,'fully_protected_positions_bit_equal_to_scaled_source':True,
        'breast_vertices_changed':0,'exported_skin_weights_changed':False,'source_triangle_topology_changed':False,
        'collision_pair_ids_used_to_define_field':False,'game_animation_validation':'unverified'}


def protect_author_breast_support(result,weights,names,bones,calibration):
    """Restore the source breast/torso support before fading into posed arms.

    True thoracic support uses semantic mass dominance, rather than tiny breast
    tails on arm skin. A C1 arm-mass gate is exactly zero at 50% arm support.
    No collision IDs or nearest target shape enter the source-derived field.
    """
    from scipy.spatial import cKDTree
    groups=['breast.'+side for side in ('L','R')]+['DEF-breast.'+side for side in ('L','R')]
    if any(name not in names or name not in bones for name in groups):
        raise ValueError('Kiriko author breast control/DEF support missing')
    columns=[names.index(name)for name in groups]
    arm_columns=[i for i,name in enumerate(names)if source_limb(name,bones) is not None
        and source_limb(name,bones)[0] in ('upper_arm','forearm','hand')]
    thorax_columns=[i for i,name in enumerate(names)if name in groups or
        name in ('DEF-spine.003','DEF-shoulder.L','DEF-shoulder.R')]
    arm_mass=weights[:,arm_columns].sum(1)
    thorax_mass=weights[:,thorax_columns].sum(1)
    support=(thorax_mass>=.5)&(arm_mass<=.25)
    if not support.any():raise ValueError('Kiriko dominant thoracic support is empty')
    source=result['scaled_source_positions'];previous=result['positions'];points=source[support]
    low=points.min(0);high=points.max(0)
    if max(abs(low[0]),abs(high[0]))>.25 or low[1]<1.1 or high[1]>1.65:
        raise ValueError('Kiriko breast support extends outside reviewed torso bounds')
    lengths=[np.linalg.norm(np.asarray(bones[name]['posed_tail_world'])-
        bones[name]['posed_head_world'])*calibration['uniform_scale']for name in groups]
    fade=float(np.mean(lengths)*.25)
    if not .01<fade<.05:raise ValueError('Kiriko breast-control fade differs from reviewed local scale')
    distance=cKDTree(points).query(source)[0]
    fraction=np.clip(distance/fade,0,1);protection=1-fraction*fraction*(3-2*fraction)
    arm_fraction=np.clip((arm_mass-.25)/.25,0,1)
    protection*=1-arm_fraction*arm_fraction*(3-2*arm_fraction)
    active=protection>0;full=protection>=1
    corrected=previous.copy()
    corrected[active]=source[active]+result['pose_displacement'][active]*(1-protection[active,None])
    corrected[full]=source[full]
    difference=corrected-previous;changed=np.linalg.norm(difference,axis=1)>1e-12
    breast_mass=weights[:,columns].sum(1);dominant_breast=breast_mass>=.5
    if not np.array_equal(corrected[dominant_breast],source[dominant_breast]):
        raise ValueError('Kiriko joint-fit source protection changed dominant authored breast tissue')
    distal=np.zeros(len(source),bool)
    for i,name in enumerate(names):
        limb=source_limb(name,bones)
        if limb is not None and limb[0] in ('hand','foot','toe'):distal|=weights[:,i]>0
    if np.any(changed&distal):raise ValueError('Kiriko breast protection reached hand/foot skin support')
    result['positions']=corrected;result['pose_displacement']=corrected-source
    result['source_breast_pose_protection']=protection
    result['breast_pose_restoration_displacement']=difference
    return {'method':'dominant source thoracic support plus C1 distance fade and C1 arm-mass gate',
        'source_group_names':groups,'source_support_vertices':int(support.sum()),
        'thoracic_semantic_group_names':[names[i]for i in thorax_columns],
        'full_support_minimum_thoracic_mass':.5,'full_support_maximum_arm_mass':.25,
        'zero_protection_minimum_arm_mass':.5,
        'full_support_source_vertex_ids':np.flatnonzero(support).tolist(),
        'source_support_bounds':[low.tolist(),high.tolist()],'source_control_lengths_m':lengths,
        'distance_fade_m':fade,'changed_source_vertex_ids':np.flatnonzero(changed).tolist(),
        'changed_vertices':int(changed.sum()),'maximum_restoration_m':float(np.linalg.norm(difference,axis=1).max()),
        'rms_restoration_changed_m':float(np.sqrt(np.mean(np.sum(difference[changed]**2,axis=1))))if changed.any()else 0.,
        'full_dominant_thoracic_support_bit_equal_to_scaled_source':bool(np.array_equal(corrected[support],source[support])),
        'arm_dominant_rows_changed_by_restoration':int((changed&(arm_mass>=.5)).sum()),
        'dominant_breast_vertices':int(dominant_breast.sum()),
        'dominant_breast_positions_bit_equal_to_scaled_source':True,
        'positive_breast_tail_vertices_moved_from_source':int(((breast_mass>0)&(np.linalg.norm(corrected-source,axis=1)>1e-12)).sum()),
        'outside_field_bit_equal_to_uncorrected_pose':bool(np.array_equal(corrected[~active],previous[~active])),
        'hands_and_feet_changed':0,'skin_weights_changed':False,'topology_changed':False,
        'collision_pair_ids_used_to_define_field':False}


def joint_neighborhood_preservation(result,weights,names,bones,fixtures):
    """Measure restoration after limb fitting on actual endpoint skin rows."""
    source=result['scaled_source_positions'];baseline=result['joint_fit_positions_before_source_support']
    final=result['positions'];rows=[]
    for fixture in fixtures:
        side=fixture['side'];chain=fixture['source_chain'];segment=fixture['lower_segment_fit']
        radius=.25*min(fixture['upper_segment_fit']['source_length_m'],segment['source_length_m'])
        columns=[i for i,name in enumerate(names)if source_limb(name,bones) is not None and
            source_limb(name,bones)[1]==side and source_limb(name,bones)[0]in chain]
        mass=weights[:,columns].sum(1)
        for endpoint,source_point,target in [('mid',segment['source_start'],segment['target_start']),
                                             ('distal',segment['source_end'],segment['target_end'])]:
            point=np.asarray(source_point);distance=np.linalg.norm(source-point,axis=1)
            selected=(distance<=radius)&(mass>=.5)
            if selected.sum()<4:raise ValueError('Kiriko endpoint skin neighborhood is undersampled')
            delta=final[selected]-baseline[selected]
            max_delta=float(np.linalg.norm(delta,axis=1).max())
            if max_delta>1e-12:raise ValueError('Kiriko source protection undid native endpoint skin fitting')
            # A local least-squares skin-field estimate is disclosed separately
            # from the exact segment-matrix endpoint fixture.
            design=np.column_stack((source[selected]-point,np.ones(int(selected.sum()))))
            affine=np.linalg.lstsq(design,final[selected],rcond=None)[0]
            estimate=affine[3];residual=estimate-np.asarray(target)
            rows.append({'side':side,'source_chain':chain,'endpoint':endpoint,'source_joint':source_point,
                'target_joint':target,'skin_neighborhood_radius_m':radius,'skin_vertex_count':int(selected.sum()),
                'source_vertex_ids':np.flatnonzero(selected).tolist(),'source_restoration_max_delta_m':max_delta,
                'local_affine_skin_estimated_joint':estimate.tolist(),
                'local_affine_skin_estimated_joint_residual_m':residual.tolist(),
                'local_affine_skin_estimated_joint_residual_length_m':float(np.linalg.norm(residual))})
    return {'method':'actual source dominant-limb skin rows near elbow/wrist and knee/ankle; compare after all source protection',
        'all_endpoint_neighborhoods_bit_equal_to_joint_fit_baseline':True,
        'local_affine_skin_joint_estimate_is_not_runtime_contact_measurement':True,'neighborhoods':rows}


def pose(arrays,metadata,native,calibration,*,align_hip_x=False,protect_pelvic_seam=False,pelvic_mask_mode='source-support',
         fit_native_joints=False):
    validate_rig(metadata);weights,names,bones,report=normalized_deform_weights(arrays,metadata)
    scale=calibration['uniform_scale'];translation=np.asarray(calibration['translation_bg3'])
    points=arrays['positions'][:,[0,2,1]]*scale+translation
    transforms={};fixtures=[]
    for side in ('L','R'):
        for chain,targets in [(('upper_arm','forearm','hand'),('Shoulder','Elbow','Wrist')),
                              (('thigh','shin','foot'),('Hip','Knee','Ankle'))]:
            a,b,c=[np.asarray(bones['DEF-'+p+'.'+side]['posed_head_world'])[[0,2,1]]*scale+translation for p in chain]
            ta,tb,tc=[native['bone_world'][p+'_'+side][:3,3]for p in targets]
            upper=rotation_between(b-a,tb-ta);lower=rotation_between(c-b,tc-tb)
            offset=np.zeros(3)
            if chain[0]=='thigh' and align_hip_x:offset[0]=ta[0]-a[0]
            segment_fit={}
            if fit_native_joints:
                upper_matrix,upper_offset,upper_fit=fit_segment_endpoints(a,b,ta,tb)
                lower_matrix,lower_offset,lower_fit=fit_segment_endpoints(b,c,tb,tc)
                if not all(.5<=fit['longitudinal_scale']<=1.5 for fit in (upper_fit,lower_fit)):
                    raise ValueError('Kiriko segment length fit exceeds reviewed profile bounds')
                # Hands/feet receive the proper lower-segment rotation and
                # exact distal-pivot translation, without stretching digits.
                transforms[(chain[0],side)]=upper_matrix,upper_offset
                transforms[(chain[1],side)]=lower_matrix,lower_offset
                transforms[(chain[2],side)]=lower,tc-lower@c
                pivot=upper_matrix@a+upper_offset;middle=upper_matrix@b+upper_offset;end=lower_matrix@c+lower_offset
                offset=ta-a;segment_fit={'upper_segment_fit':upper_fit,'lower_segment_fit':lower_fit}
            else:
                pivot=a+offset;middle=pivot+upper@(b-a);end=middle+lower@(c-b)
                transforms[(chain[0],side)]=upper,pivot-upper@a
                transforms[(chain[1],side)]=lower,middle-lower@b
                transforms[(chain[2],side)]=transforms[(chain[1],side)]
            if chain[2]=='foot':transforms[('toe',side)]=transforms[('foot',side)]
            fixtures.append({'source_chain':list(chain),'native_chain':list(targets),'side':side,
                'source_pivot':a.tolist(),'native_pivot':ta.tolist(),'corrected_pivot':pivot.tolist(),
                'pivot_translation':offset.tolist(),'upper_rotation':upper.tolist(),'lower_rotation':lower.tolist(),
                'mid_native_offset_m':(middle-tb).tolist(),'end_native_offset_m':(end-tc).tolist(),
                'mid_native_offset_length_m':float(np.linalg.norm(middle-tb)),
                'end_native_offset_length_m':float(np.linalg.norm(end-tc)),**segment_fit})
    displacement=np.zeros_like(points);influence=np.zeros(len(points));toe_groups=[]
    for i,name in enumerate(names):
        limb=source_limb(name,bones)
        if limb not in transforms:continue
        rotation,offset=transforms[limb]
        displacement+=(points@rotation.T+offset-points)*weights[:,i,None]
        influence+=weights[:,i]
        if name.startswith('DEF-toes.') and np.any(weights[:,i]>0):toe_groups.append(name)
    candidate=points+displacement;fixed=influence==0
    if not np.array_equal(candidate[fixed],points[fixed]):raise ValueError('Kiriko pose changed zero-limb donor core')
    result={'positions':candidate,'scaled_source_positions':points,'triangles':arrays['triangles'][:,[0,2,1]].copy(),
        'source_vertex_ids':np.arange(len(points)),'pose_displacement':displacement,'limb_influence':influence}
    for label,side in [('left','L'),('right','R')]:
        columns=[i for i,name in enumerate(names)if name in ('DEF-breast.'+side,'breast.'+side)]
        if len(columns)!=2:raise ValueError('Kiriko active breast DEF/control pair missing')
        result['source_breast_influence_'+label]=weights[:,columns].sum(1)
    if fit_native_joints:
        result['joint_fit_positions_before_source_support']=candidate.copy()
        report['source_breast_pose_protection']=protect_author_breast_support(result,weights,names,bones,calibration)
    if protect_pelvic_seam:
        report['source_pelvic_pose_protection']=protect_anatomical_source_pose(result,weights,names,bones,calibration,mode=pelvic_mask_mode)
    if fit_native_joints:
        report['post_restoration_endpoint_skin_check']=joint_neighborhood_preservation(result,weights,names,bones,fixtures)
    report.update(profile=PROFILE,calibration=calibration,uniform_scale=scale,translation_bg3=translation.tolist(),
        axis_conversion='[x,z,y]',native_hip_lateral_alignment=align_hip_x,limb_fixtures=fixtures,
        source_extra_toe_groups_posed=toe_groups,torso_uninfluenced_vertices=int(fixed.sum()),
        torso_uninfluenced_max_error=0.,pose_changed_vertices=int((np.linalg.norm(result['pose_displacement'],axis=1)>1e-12).sum()),
        maximum_pose_displacement=float(np.linalg.norm(result['pose_displacement'],axis=1).max()),
        game_motion_and_hand_prop_contact='unverified; copied native rig is not a joint-position fit proof')
    report['native_joint_fit']={'enabled':fit_native_joints,
        'method':'source-weighted affine segment fit: native XYZ pivots, proper rotation, longitudinal-only length scale'if fit_native_joints else 'rigid directions; source lengths and partial source pivots',
        'fixture_landmark_max_residual_m':max(max(np.linalg.norm(np.asarray(f['corrected_pivot'])-np.asarray(f['native_pivot'])),
            f['mid_native_offset_length_m'],f['end_native_offset_length_m'])for f in fixtures),
        'fixture_landmarks_are_not_deformed_surface_or_runtime_contact':True,
        'individual_segment_cross_section_scale':1.,'blended_joint_cross_sections':'not an isometry under weighted affine blending',
        'hands_feet':'proper lower-segment rotation with exact distal-pivot translation; no digit length scaling',
        'hand_foot_orientation_and_motion':'unverified'}
    return result,weights,names,bones,report


def semantic_anchors():
    anchors={'DEF-spine':'Root_M','DEF-spine.001':'Spine1_M','DEF-spine.002':'Spine2_M',
        'DEF-spine.003':'Chest_M','DEF-spine.004':'Neck_M','DEF-spine.005':'Neck_M','DEF-spine.006':'Head_M',
        'ORG-spine':'Root_M','tweak_spine':'Root_M','ORG-spine.003':'Chest_M',
        'ORG-spine.004':'Neck_M','ORG-spine.005':'Neck_M','ORG-spine.006':'Head_M','ORG-face':'Head_M'}
    for side in ('L','R'):
        for source,target in [('shoulder','Scapula'),('upper_arm','Shoulder'),('forearm','Elbow'),
                              ('hand','Wrist'),('thigh','Hip'),('shin','Knee'),('foot','Ankle'),('toe','Toes')]:
            for suffix in ('','.001'):anchors['DEF-'+source+'.'+side+suffix]=target+'_'+side
        for number in ('','.001','.003','.004','.006','.007','.009','.010','.012','.013'):
            anchors['DEF-toes.'+side+number]='Toes_'+side
        anchors['DEF-butt.'+side]='Root_M'
        anchors['DEF-breast.'+side]=anchors['breast.'+side]='Chest_M'
        for source,target in [('f_index','IndexFinger'),('f_middle','MiddleFinger'),
                              ('f_ring','RingFinger'),('f_pinky','PinkyFinger'),('thumb','ThumbFinger')]:
            for number in range(1,4):anchors['DEF-'+source+'.%02d.'%number+side]=target+str(number)+'_'+side
        for number in range(1,5):
            anchors['DEF-palm.%02d.'%number+side]=('RingFinger0_'if number==3 else 'PinkyFinger0_'if number==4 else 'Wrist_')+side
    return anchors


def map_weights(weights,names,bones,native_names):
    anchors=semantic_anchors();mapped=np.zeros((len(weights),len(native_names)));resolved={}
    for i,name in enumerate(names):
        if not np.any(weights[:,i]>0):continue
        at=name;seen=set()
        while at not in anchors:
            if not at or at in seen or at not in bones:raise ValueError('Unmapped positive Kiriko group: '+name)
            seen.add(at);at=bones[at]['parent']
        target=anchors[at]
        if target not in native_names:raise ValueError('Missing native Kiriko joint '+target)
        mapped[:,native_names.index(target)]+=weights[:,i]
        resolved[name]={'anchor':at,'target':target,'direct':name==at}
    if not np.allclose(mapped.sum(1),1,atol=1e-12):raise ValueError('Kiriko mapping lost normalized skin mass')
    return mapped,{'profile':PROFILE,'semantic_anchors':anchors,'resolved_positive_groups':resolved,'unknown_positive_groups':[]}
