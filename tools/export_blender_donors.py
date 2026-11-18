"""Export selected authored body states without saving or sculpting their sources.

Run with Blender --background --disable-autoexec --python this_file -- ... .
The outputs are local source references, not BG3-ready assets or physics meshes.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import sys


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def selected_presets(plans, selections, pins):
    """Resolve exact review states and bind them to reviewed original files."""
    identifiers = [plan.get('id') for plan in plans]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError('Duplicate donor plan IDs')
    if not selections or len(set(selections)) != len(selections):
        raise ValueError('Selections must be nonempty and unique')
    lookup = {plan['id']: plan for plan in plans}
    pin_ids = [pin.get('id') for pin in pins]
    if len(set(pin_ids)) != len(pin_ids):
        raise ValueError('Duplicate original source pins')
    pin_lookup = {pin['id']: pin for pin in pins}
    result = []
    for selection in selections:
        pieces = selection.split(':')
        if len(pieces) != 2 or pieces[0] not in lookup:
            raise ValueError('Unknown donor selection: ' + selection)
        plan = lookup[pieces[0]]
        if plan.get('adult_model') is not True:
            raise ValueError('An explicitly reviewed adult body plan is required')
        matching = [preset for preset in plan['presets'] if preset['id'] == pieces[1]]
        if len(matching) != 1:
            raise ValueError('Unknown or duplicate preset: ' + selection)
        if plan['id'] not in pin_lookup:
            raise ValueError('Missing original source pin: ' + plan['id'])
        pin = pin_lookup[plan['id']]
        if Path(plan['source']).resolve() != Path(pin['source']).resolve():
            raise ValueError('Donor plan and original source pin differ')
        if not re.fullmatch(r'[a-f0-9]{64}', pin.get('source_sha256', '')):
            raise ValueError('Invalid original source fingerprint')
        name = re.sub(r'[^a-z0-9_]', '_', plan['id'].lower()) + '_' + pieces[1].lower()
        result.append((copy.deepcopy(plan), copy.deepcopy(matching[0]), copy.deepcopy(pin), name))
    if len({row[3] for row in result}) != len(result):
        raise ValueError('Selections collide on an output filename')
    return result


def authored_states(saved, resets, overrides):
    """Restore saved values/mutes, then apply only review resets and overrides."""
    states = copy.deepcopy(saved)
    for name in resets:
        for match in (name, name + '_SDF'):
            if match in states:
                states[match]['value'], states[match]['mute'] = 0.0, False
    for name, value in overrides.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError('A selected key value is not finite')
        matched = [key for key in (name, name + '_SDF') if key in states]
        if not matched:
            raise ValueError('Selected key missing from body: ' + name)
        for key in matched:
            if not states[key]['min'] <= value <= states[key]['max']:
                raise ValueError('Selected key exceeds its authored range: ' + key)
            states[key]['value'], states[key]['mute'] = float(value), False
    return states


def matrix_list(matrix):
    return [[float(value) for value in row] for row in matrix]


def sparse_vertex_groups(rows, names, deform_names=()):
    """Preserve evaluated group assignments as CSR without normalizing weights."""
    import numpy as np
    if any(not isinstance(name,str) or not name for name in names):
        raise ValueError('Vertex group names must be nonempty strings')
    # Blender maps each group INDEX to its named pose channel, so two source
    # groups with the same label may both contribute. Preserve both columns.
    # v4.5.0 blenkernel/intern/armature_deform.cc:504-505, 314-332.
    repeated={name:[i for i,value in enumerate(names) if value==name]
              for name in set(names) if names.count(name)>1}
    deform=set(deform_names)
    deform_indices={index for index,name in enumerate(names) if name in deform}
    offsets,indices,weights,deform_sums=[0],[],[],[]
    for row in rows:
        seen=set();total=0.0
        for index,weight in row:
            if (isinstance(index,(bool,np.bool_)) or not isinstance(index,(int,np.integer))
                    or not 0<=index<len(names)):
                raise ValueError('Evaluated vertex group index is invalid')
            if index in seen:
                raise ValueError('A vertex contains a duplicate group assignment')
            if (isinstance(weight,(bool,np.bool_)) or not isinstance(weight,(int,float,np.integer,np.floating))
                    or not math.isfinite(weight)):
                raise ValueError('Evaluated vertex group weight is invalid: '+repr(weight))
            seen.add(index);indices.append(int(index));weights.append(float(weight))
            if index in deform_indices:total+=float(weight)
        offsets.append(len(indices));deform_sums.append(total)
    sums=np.asarray(deform_sums,dtype=np.float64)
    raw_weights=np.asarray(weights,dtype=np.float64)
    negative=int(np.count_nonzero(raw_weights<0))
    above_one=int(np.count_nonzero(raw_weights>1))
    positive=sums[sums>1e-12]
    arrays={'group_offsets':np.asarray(offsets,dtype=np.int64),
            'group_indices':np.asarray(indices,dtype=np.int32),
            'group_weights':np.asarray(weights,dtype=np.float64)}
    report={'vertices':len(sums),'group_count':len(names),'assignments':len(indices),
            'duplicate_name_group_indices':dict(sorted(repeated.items())),
            'group_binding':'each source group index binds its named deform bone; duplicate labels stay separate',
            'deform_group_names':[name for name in names if name in deform],
            'weighted_vertex_count':int(len(positive)),'unweighted_vertex_count':int(len(sums)-len(positive)),
            'minimum_deform_sum':float(sums.min()) if len(sums) else None,
            'maximum_deform_sum':float(sums.max()) if len(sums) else None,
            'median_positive_deform_sum':float(np.median(positive)) if len(positive) else None,
            'maximum_positive_deform_sum_deviation_from_one':float(np.abs(positive-1).max()) if len(positive) else None,
            'positive_deform_sums_within_1e_3_of_one':bool(np.all(np.abs(positive-1)<=1e-3)) if len(positive) else False,
            'minimum_raw_weight':float(raw_weights.min()) if len(raw_weights) else None,
            'maximum_raw_weight':float(raw_weights.max()) if len(raw_weights) else None,
            'negative_weight_assignments':negative,'above_one_weight_assignments':above_one,
            'weights_within_unit_interval':not (negative or above_one),
            'normalization_applied':False,'indices_and_weights_valid':not (negative or above_one)}
    return arrays,report


def verify_reference_arrays(reference, candidate):
    """Reject even one-bit changes in previously captured geometry arrays."""
    import numpy as np
    if not reference:
        raise ValueError('Geometry reference must contain arrays')
    verified={}
    for name,original in reference.items():
        if name not in candidate:
            raise ValueError('Geometry reference array is missing: '+name)
        before,after=np.asarray(original),np.asarray(candidate[name])
        if (before.dtype!=after.dtype or before.shape!=after.shape
                or before.tobytes(order='C')!=after.tobytes(order='C')):
            raise ValueError('Geometry reference array changed: '+name)
        verified[name]=hashlib.sha256(before.tobytes(order='C')).hexdigest()
    return {'bit_equal':True,'verified_arrays':verified,
            'extra_arrays':sorted(set(candidate)-set(reference))}


def retain_reference_uvs(reference, candidate):
    """Keep frozen UVs when repeated subdivision changes only their rounding.

    Skin groups use evaluated vertex indices. All non-UV arrays must still be
    bit-identical before accepting those groups; fresh UVs are never consumed.
    """
    core={name:value for name,value in reference.items() if not re.fullmatch(r'uv\d+',name)}
    if not {'positions','triangles','corner_loop_indices'} <= set(core):
        raise ValueError('Frozen UV reuse requires complete evaluated geometry and loop order')
    verify_reference_arrays(core,candidate)
    result=dict(candidate);restored={}
    import numpy as np
    for name,original in reference.items():
        if not re.fullmatch(r'uv\d+',name):continue
        fresh=np.asarray(candidate[name]);old=np.asarray(original)
        if fresh.shape!=old.shape or fresh.dtype!=old.dtype:
            raise ValueError('Frozen UV layout changed: '+name)
        if fresh.tobytes()!=old.tobytes():
            restored[name]={'different_values':int(np.count_nonzero(fresh!=old)),
                'maximum_capture_difference':float(np.max(np.abs(fresh-old))),
                'fresh_capture_sha256':hashlib.sha256(fresh.tobytes()).hexdigest(),
                'retained_frozen_sha256':hashlib.sha256(old.tobytes()).hexdigest()}
        result[name]=old.copy()
    verify_reference_arrays(reference,result)
    return result,{'policy':'retain exact frozen UVs after bit-identical geometry/loop-order check',
                   'fresh_uvs_consumed':False,'restored':restored}


def modifier_record(modifier):
    result = {key: getattr(modifier, key) for key in ('name', 'type', 'show_viewport', 'show_render')}
    for key in ('levels', 'render_levels', 'sculpt_levels', 'thickness', 'offset', 'vertex_group'):
        if hasattr(modifier, key):
            result[key] = getattr(modifier, key)
    if modifier.type == 'ARMATURE':
        result['object'] = modifier.object.name if modifier.object else None
        for key in ('use_vertex_groups','use_bone_envelopes','use_deform_preserve_volume','use_multi_modifier'):
            result[key]=getattr(modifier,key)
    if modifier.type == 'NODES':
        result['node_group'] = modifier.node_group.name if modifier.node_group else None
    return result


def export_one(plan, preset, pin, identifier, output, max_subdivision, *,
               vertex_groups=False, geometry_reference=None, reuse_reference_uvs=False):
    import bpy
    import numpy as np

    source = Path(plan['source']).resolve()
    destination = output / (identifier + '.npz')
    if destination.exists() or destination.with_suffix('.json').exists():
        raise ValueError('Donor captures are write-once; choose a new output directory')
    reference_path=Path(geometry_reference).resolve() if geometry_reference else None
    if reuse_reference_uvs and reference_path is None:
        raise ValueError('Frozen UV reuse requires an explicit geometry reference')
    if reference_path is not None and reference_path==(output/(identifier+'.npz')).resolve():
        raise ValueError('Output must not replace the frozen geometry reference')
    reference_sha=file_sha256(reference_path) if reference_path is not None else None
    before_sha = file_sha256(source)
    if before_sha != pin['source_sha256']:
        raise ValueError('Original source changed after review: ' + str(source))
    # A partially loaded newer file can still contain a plausible named mesh.
    # That is insufficient evidence of intact source geometry or rig state.
    # Require the matching Blender version rather than accepting load errors.
    bpy.ops.wm.open_mainfile(filepath=str(source), use_scripts=False)
    scene = bpy.context.scene
    body = bpy.data.objects.get(plan['body_mesh'])
    if body is None or body.type != 'MESH':
        raise ValueError('Expected the exact selected body mesh')
    original_counts = {'vertices':len(body.data.vertices), 'polygons':len(body.data.polygons)}
    original_modifiers = [modifier_record(modifier) for modifier in body.modifiers]
    original_units = {name:getattr(scene.unit_settings, name) for name in ('system','scale_length','length_unit')}
    source_pose = {'scene':scene.name, 'frame':scene.frame_current}
    source_simplify = {name:getattr(scene.render,name) for name in
                       ('use_simplify','simplify_subdivision','simplify_subdivision_render')}
    muted_drivers = []
    # Visibility and shape drivers must not overwrite the exact authored preset.
    # Bone controls and constraints continue to evaluate in the saved pose.
    for obj in bpy.data.objects:
        if obj.animation_data:
            for driver in obj.animation_data.drivers:
                if driver.data_path.startswith(('hide_', 'show_')) or driver.data_path.endswith(('.show_render', '.show_viewport')):
                    muted_drivers.append({'owner':obj.name, 'path':driver.data_path, 'previous_mute':driver.mute})
                    driver.mute = True
    for collection in bpy.data.collections:
        collection.hide_render = collection.hide_viewport = False
    def expose(layer):
        layer.exclude = layer.hide_viewport = False
        for child in layer.children:
            expose(child)
    expose(bpy.context.view_layer.layer_collection)
    body.hide_viewport = body.hide_render = False
    if body.name in bpy.context.view_layer.objects:
        body.hide_set(False)
    keys = body.data.shape_keys
    saved = {}
    if keys:
        saved = {key.name:{'value':float(key.value), 'mute':bool(key.mute),
                          'min':float(key.slider_min), 'max':float(key.slider_max),
                          'relative_key':key.relative_key.name, 'vertex_group':key.vertex_group}
                 for key in keys.key_blocks}
        if keys.animation_data:
            for driver in keys.animation_data.drivers:
                muted_drivers.append({'owner':keys.name, 'path':driver.data_path, 'previous_mute':driver.mute})
                driver.mute = True
    states = authored_states(saved, plan.get('reset_keys') or [], preset.get('keys', {}))
    for name, state in states.items():
        keys.key_blocks[name].value = state['value']
        keys.key_blocks[name].mute = state['mute']
    for modifier in body.modifiers:
        if modifier.type == 'MASK':
            modifier.show_viewport = modifier.show_render = False
        if modifier.type == 'SUBSURF':
            modifier.levels = min(modifier.levels, max_subdivision)
            modifier.render_levels = min(modifier.render_levels, max_subdivision)
    bpy.context.view_layer.update()
    graph = bpy.context.evaluated_depsgraph_get()
    evaluated = body.evaluated_get(graph)
    mesh = evaluated.to_mesh(preserve_all_data_layers=True, depsgraph=graph)
    try:
        mesh.calc_loop_triangles()
        transform = np.asarray(evaluated.matrix_world, dtype=np.float64)
        local = np.asarray([vertex.co[:] for vertex in mesh.vertices], dtype=np.float64)
        positions = local @ transform[:3,:3].T + transform[:3,3]
        triangles = np.asarray([triangle.vertices[:] for triangle in mesh.loop_triangles], dtype=np.int32)
        loops = np.asarray([triangle.loops[:] for triangle in mesh.loop_triangles], dtype=np.int32)
        normal_transform = np.linalg.inv(transform[:3,:3])
        normals = np.asarray([vertex.normal[:] for vertex in mesh.vertices], dtype=np.float64) @ normal_transform
        normals /= np.maximum(np.linalg.norm(normals, axis=1)[:,None], 1e-30)
        split = np.asarray([normal.vector[:] for normal in mesh.corner_normals], dtype=np.float64) @ normal_transform
        split /= np.maximum(np.linalg.norm(split, axis=1)[:,None], 1e-30)
        arrays = {'positions':positions, 'triangles':triangles, 'normals':normals,
                  'corner_normals':split[loops], 'corner_loop_indices':loops,
                  'triangle_material_indices':np.asarray([mesh.polygons[t.polygon_index].material_index for t in mesh.loop_triangles], dtype=np.int32)}
        uv_layers = []
        for index, layer in enumerate(mesh.uv_layers):
            uv = np.asarray([loop.uv[:] for loop in layer.data], dtype=np.float64)
            arrays[f'uv{index}'] = uv[loops]
            uv_layers.append({'name':layer.name,'array':f'uv{index}','active':layer == mesh.uv_layers.active})
        for name, array in arrays.items():
            if not np.isfinite(array).all():
                raise ValueError('Nonfinite evaluated donor data: ' + name)
        if not len(positions) or not len(triangles) or triangles.min() < 0 or triangles.max() >= len(positions):
            raise ValueError('Invalid evaluated donor topology')
        rig_objects = {modifier.object.name:modifier.object for modifier in body.modifiers
                       if modifier.type == 'ARMATURE' and modifier.object is not None}
        if body.parent is not None and body.parent.type == 'ARMATURE':
            rig_objects[body.parent.name] = body.parent
        rigs = []
        for rig in rig_objects.values():
            posed = rig.evaluated_get(graph)
            bones = []
            for bone in rig.data.bones:
                pose_bone = posed.pose.bones.get(bone.name)
                bones.append({'name':bone.name,'parent':bone.parent.name if bone.parent else None,
                    'deform':bone.use_deform,
                    'rest_head_world':list(rig.matrix_world @ bone.head_local),
                    'rest_tail_world':list(rig.matrix_world @ bone.tail_local),
                    'posed_head_world':list(posed.matrix_world @ pose_bone.head) if pose_bone else None,
                    'posed_tail_world':list(posed.matrix_world @ pose_bone.tail) if pose_bone else None,
                    'rest_matrix_local':matrix_list(bone.matrix_local),
                    'posed_matrix':matrix_list(pose_bone.matrix) if pose_bone else None})
            rigs.append({'name':rig.name,'matrix_world':matrix_list(rig.matrix_world),'bones':bones})
        group_names=[];group_report=None
        if vertex_groups:
            source_groups=list(body.vertex_groups)
            if [group.index for group in source_groups]!=list(range(len(source_groups))):
                raise ValueError('Source vertex group indices are not a contiguous name table')
            group_names=[group.name for group in source_groups]
            active_rigs={modifier.object.name for modifier in body.modifiers
                         if modifier.type=='ARMATURE' and modifier.object is not None
                         and modifier.show_viewport and modifier.use_vertex_groups}
            deform_names={bone['name'] for rig in rigs if rig['name'] in active_rigs
                          for bone in rig['bones'] if bone['deform']}
            group_arrays,group_report=sparse_vertex_groups(
                ([(assignment.group,assignment.weight) for assignment in vertex.groups]
                 for vertex in mesh.vertices),group_names,deform_names)
            if group_report['deform_group_names'] and group_report['weighted_vertex_count']==0:
                raise ValueError('Evaluated mesh lost all active deform-bone weights')
            group_report['active_vertex_group_rigs']=sorted(active_rigs)
            arrays.update(group_arrays)
        reference_report=None;uv_retention=None
        if reference_path is not None:
            with np.load(reference_path,allow_pickle=False) as frozen:
                if reuse_reference_uvs:
                    arrays,uv_retention=retain_reference_uvs(dict(frozen),arrays)
                reference_report=verify_reference_arrays(dict(frozen),arrays)
            if file_sha256(reference_path)!=reference_sha:
                raise ValueError('Frozen geometry reference changed during extraction')
            reference_report.update(path=str(reference_path),sha256=reference_sha)
        output.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(destination, **arrays)
        metadata = {'schema_version':1,'id':identifier,'donor_id':plan['id'],'preset':preset,
            'source':str(source),'source_sha256':before_sha,'source_saved':False,
            'body_mesh':body.name,'original_counts':original_counts,
            'evaluated_counts':{'vertices':len(positions),'triangles':len(triangles)},
            'bounds':[positions.min(axis=0).tolist(),positions.max(axis=0).tolist()],
            'coordinates':{'space':'evaluated Blender world','unit':'Blender world units',
                           'scene_unit_settings':original_units,'body_matrix_world':transform.tolist()},
            'source_pose':source_pose,'rigs':rigs,'saved_shape_keys':saved,'applied_shape_keys':states,
            'source_scene_simplify':source_simplify,
            'review_reset_keys':plan.get('reset_keys') or [],'key_overrides':preset.get('keys',{}),
            'muted_drivers':muted_drivers,'original_modifiers':original_modifiers,
            'evaluated_modifiers':[modifier_record(modifier) for modifier in body.modifiers],
            'evaluation':'viewport dependency graph with saved pose; wardrobe MASK disabled; SUBSURF capped, never enabled when originally disabled',
            'max_subdivision':max_subdivision,'geometry_regularization':False,
            'body_only':True,'anatomy_keys_reset':False,'uv_layers':uv_layers,
            'materials':[material.name if material else None for material in mesh.materials],
            'vertex_groups_exported':vertex_groups,'vertex_group_names':group_names,
            'vertex_group_validation':group_report,'geometry_reference':reference_report,
            'reference_uv_retention':uv_retention,
            'blender_version':bpy.app.version_string,'load_warning':None,
            'exporter_sha256':file_sha256(Path(__file__)),
            'npz':str(destination.resolve()),'npz_sha256':file_sha256(destination)}
    finally:
        evaluated.to_mesh_clear()
    after_sha = file_sha256(source)
    if after_sha != before_sha:
        raise ValueError('Original source changed during extraction')
    metadata['source_sha256_after'] = after_sha
    destination.with_suffix('.json').write_text(json.dumps(metadata,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('DONOR_EXPORT ' + json.dumps({'id':identifier,'npz':str(destination),'counts':metadata['evaluated_counts']}),flush=True)
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plans',nargs='+',type=Path,required=True)
    parser.add_argument('--selection',nargs='+',required=True,help='Exact donor:preset IDs')
    parser.add_argument('--pins',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--max-subdivision',type=int,default=1,choices=(0,1,2))
    parser.add_argument('--vertex-groups',action='store_true',help='Include evaluated sparse vertex group assignments')
    parser.add_argument('--geometry-reference',type=Path,help='Require every existing array to match one frozen NPZ exactly')
    parser.add_argument('--reuse-reference-uvs',action='store_true',help='Keep frozen UV arrays after exact evaluated geometry/loop-order parity')
    arguments = sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else sys.argv[1:]
    args = parser.parse_args(arguments)
    plans = [plan for path in args.plans for plan in json.loads(path.read_text(encoding='utf-8'))]
    pins = json.loads(args.pins.read_text(encoding='utf-8'))['donors']
    requested = selected_presets(plans,args.selection,pins)
    if args.geometry_reference is not None and len(requested)!=1:
        raise ValueError('A geometry reference applies to exactly one selected state')
    for plan,preset,pin,identifier in requested:
        export_one(plan,preset,pin,identifier,args.output.resolve(),args.max_subdivision,
                   vertex_groups=args.vertex_groups,geometry_reference=args.geometry_reference,
                   reuse_reference_uvs=args.reuse_reference_uvs)


if __name__ == '__main__':
    main()
