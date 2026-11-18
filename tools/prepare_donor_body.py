"""Prepare an explicitly selected dense Juno state in private staging."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from nudegate.donor_body import (load_dae,pose_donor,sha,map_native_weights,
    trim_and_bridge,transfer_native_surface,body_payload,repair_juno_stray_facial_weights,
    normalized_deform_weights)


def preview(output, native_path):
    """Render exact prepared arrays in Blender, with a shared display scale."""
    output=output.resolve();native_path=native_path.resolve()
    import bpy
    import math
    from mathutils import Vector
    sys.path.insert(0,str(ROOT/'tools'))
    from render_bodies import label,panel,BODY_COLOR,MUTED_COLOR
    from nudegate.collada import ColladaMesh
    with np.load(output/'posed_dense.npz') as data:
        posed=data['positions'][:,[0,2,1]]
        source=data['scaled_source_positions'][:,[0,2,1]]
        faces=data['triangles'][:,[0,2,1]]
    native=ColladaMesh.load(native_path,geometry_id='HUM_F_NKD_Body_A_Mesh-geom')
    profiles=[('Original Juno / uniform scale',source,faces),
              ('Actual Juno / limb pose corrected',posed,faces),
              ('Native BG3 / comparison',np.array(native.positions)[:,[0,2,1]],np.array(native.triangles)[:,[0,2,1]])]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene=bpy.context.scene;scene.render.engine='BLENDER_WORKBENCH'
    scene.render.resolution_x=2400;scene.render.resolution_y=1050
    scene.render.resolution_percentage=100;scene.render.image_settings.file_format='PNG'
    shading=scene.display.shading;shading.light='STUDIO';shading.color_type='OBJECT'
    shading.show_shadows=False;shading.show_cavity=True;shading.cavity_type='WORLD'
    shading.cavity_ridge_factor=.4;shading.cavity_valley_factor=.4
    shading.background_type='WORLD';shading.show_object_outline=False
    scene.world=bpy.data.worlds.new('Background');scene.world.color=(.04,.049,.061)
    scene.view_settings.view_transform='Standard';scene.view_settings.look='None'
    for i,(title,points,triangles) in enumerate(profiles):
        x=(i-1)*2.4;panel(x,0,2.3,2.1)
        # Only the original head is hidden in this body review, never edited.
        triangles=triangles[np.all(points[triangles,2]<1.58,axis=1)]
        mesh=bpy.data.meshes.new(title);mesh.from_pydata(points.tolist(),[],triangles.tolist());mesh.update()
        for p in mesh.polygons:p.use_smooth=True
        for suffix,offset,angle in [('front',-.38,0),('side',.62,math.pi/2)]:
            ob=bpy.data.objects.new(title+suffix,mesh);scene.collection.objects.link(ob)
            ob.location=(x+offset,0,0);ob.rotation_euler.z=angle;ob.color=BODY_COLOR
        label(title,x,1.96,.075);label('FRONT',x-.38,-.04,.048,MUTED_COLOR);label('SIDE',x+.62,-.04,.048,MUTED_COLOR)
    report=json.loads((output/'report.json').read_text())
    heading='Actual dense donor / source-weighted pose correction'
    for audit_name in ('global-pose-surface-audit.json','corrective-global-audit.json'):
        audit_path=output/audit_name
        if audit_path.exists():
            audit=json.loads(audit_path.read_text());proof=audit.get('proof',audit)
            if not proof.get('safe',False):heading=f"HELD geometry study / {proof['introduced_intersection_count']} new contacts"
    label(heading,0,2.3,.13)
    annotation='Original topology and torso / scale '+str(report['uniform_scale'])
    if report.get('native_hip_lateral_alignment'):annotation+=' / native lateral hip alignment'
    if report.get('arm_rotation_fraction',1)!=1:annotation+=f" / arm correction {report['arm_rotation_fraction']*100:g}%"
    if report.get('additional_stance_per_side_m',0):annotation+=f" / stance +{report['additional_stance_per_side_m']*1000:g}mm per side"
    label(annotation,0,2.15,.075,MUTED_COLOR)
    if report.get('native_joint_fit'):
        label('Rest-pose study / animation and hand-prop contact unverified',0,-.20,.065,MUTED_COLOR)
    camera_data=bpy.data.cameras.new('Camera');camera=bpy.data.objects.new('Camera',camera_data)
    scene.collection.objects.link(camera);camera.location=(0,-12,1.0)
    camera.rotation_euler=(Vector((0,0,1.0))-camera.location).to_track_quat('-Z','Y').to_euler()
    camera_data.type='ORTHO';camera_data.ortho_scale=7.45;scene.camera=camera
    scene.render.filepath=str(output/'posed_preview.png')
    bpy.ops.wm.save_as_mainfile(filepath=str(output/'posed_preview.blend'))
    bpy.ops.render.render(write_still=True)


def preview_final(output):
    output=output.resolve()
    import bpy
    import math
    from mathutils import Vector
    sys.path.insert(0,str(ROOT/'tools'))
    from render_bodies import label,panel,BODY_COLOR,MUTED_COLOR
    with np.load(output/'body_prepared.npz') as data:
        vertices=data['positions'][:,[0,2,1]];faces=data['triangles'][:,[0,2,1]]
        normals=data['normals'][:,[0,2,1]];uvs=data['uvs'];colors=data['colors_rgba8']/255
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene=bpy.context.scene;scene.render.engine='BLENDER_WORKBENCH'
    scene.render.resolution_x=2200;scene.render.resolution_y=1150;scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG';scene.view_settings.view_transform='Standard';scene.view_settings.look='None'
    shading=scene.display.shading;shading.light='STUDIO';shading.color_type='OBJECT'
    shading.show_shadows=False;shading.show_cavity=True;shading.cavity_type='WORLD'
    shading.cavity_ridge_factor=.45;shading.cavity_valley_factor=.45;shading.background_type='WORLD'
    shading.show_object_outline=False;scene.world=bpy.data.worlds.new('Background');scene.world.color=(.04,.049,.061)
    mesh=bpy.data.meshes.new('Final dense donor');mesh.from_pydata(vertices.tolist(),[],faces.tolist());mesh.update()
    for polygon in mesh.polygons:polygon.use_smooth=True
    mesh.normals_split_custom_set(normals[faces].reshape(-1,3).tolist())
    layer=mesh.uv_layers.new(name='Native BG3 UV');layer.data.foreach_set('uv',uvs[faces].reshape(-1))
    color=mesh.color_attributes.new(name='Native physics paint',type='FLOAT_COLOR',domain='POINT')
    color.data.foreach_set('color',colors.reshape(-1))
    for i,(title,angle) in enumerate([('Front',0),('Side',math.pi/2),('Back',math.pi)]):
        x=(i-1)*1.8;panel(x,0,1.7,2.05)
        ob=bpy.data.objects.new(title,mesh);scene.collection.objects.link(ob)
        ob.location=(x,0,0);ob.rotation_euler.z=angle;ob.color=BODY_COLOR
        label(title,x,1.92,.09)
    report=json.loads((output/'report.json').read_text())
    label('Actual '+report.get('display_label','Juno')+' / dense geometry + exact native collar',0,2.25,.115)
    label(f'{len(vertices):,} UV-split vertices / {len(faces):,} triangles / original body surface retained',0,2.10,.065,MUTED_COLOR)
    cd=bpy.data.cameras.new('Camera');camera=bpy.data.objects.new('Camera',cd);scene.collection.objects.link(camera)
    camera.location=(0,-12,1.0);camera.rotation_euler=(Vector((0,0,1.0))-camera.location).to_track_quat('-Z','Y').to_euler()
    cd.type='ORTHO';cd.ortho_scale=5.7;scene.camera=camera
    scene.render.filepath=str(output/'body_preview.png');bpy.ops.render.render(write_still=True)
    shading.color_type='VERTEX';scene.render.filepath=str(output/'paint_preview.png');bpy.ops.render.render(write_still=True)
    image=bpy.data.images.new('Native UV checker',width=1024,height=1024);image.generated_type='COLOR_GRID'
    material=bpy.data.materials.new('Native UV checker');material.use_nodes=True
    tex=material.node_tree.nodes.new('ShaderNodeTexImage');tex.image=image
    material.node_tree.nodes.active=tex;mesh.materials.append(material)
    shading.color_type='TEXTURE';scene.render.filepath=str(output/'uv_preview.png');bpy.ops.render.render(write_still=True)
    # The saved scene provides the same exact mesh for interactive review.
    shading.color_type='OBJECT';bpy.ops.wm.save_as_mainfile(filepath=str(output/'body_preview.blend'))
    for ob in list(scene.objects):
        if ob is not camera:bpy.data.objects.remove(ob,do_unlink=True)
    neck_faces=faces[np.any(vertices[faces,2]>1.43,axis=1)]
    neck_mesh=bpy.data.meshes.new('Exact collar detail');neck_mesh.from_pydata(vertices.tolist(),[],neck_faces.tolist());neck_mesh.update()
    for p in neck_mesh.polygons:p.use_smooth=True
    neck_mesh.normals_split_custom_set(normals[neck_faces].reshape(-1,3).tolist())
    for i,(title,angle) in enumerate([('Front',0),('Side',math.pi/2),('Back',math.pi),('Oblique',math.pi/4)]):
        x=(i-1.5)*.72
        ob=bpy.data.objects.new(title,neck_mesh);scene.collection.objects.link(ob);ob.location=(x,0,-1.40)
        ob.rotation_euler.z=angle;ob.color=BODY_COLOR;label(title,x,.31,.042)
    label('Local neck bridge / exact native 18-point collar',0,.47,.065)
    camera.location=(0,-8,.19);camera.rotation_euler=(Vector((0,0,.19))-camera.location).to_track_quat('-Z','Y').to_euler()
    cd.ortho_scale=3.0;scene.render.resolution_x=2200;scene.render.resolution_y=650
    scene.render.filepath=str(output/'neck_preview.png');bpy.ops.render.render(write_still=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--donor',type=Path,default=ROOT/'build/donors/skinned/juno_b.npz')
    parser.add_argument('--native',type=Path,default=ROOT/'build/physics-probe/matched-v1/model-roundtrip/human_normal/source.dae')
    parser.add_argument('--reference',type=Path,default=ROOT/'build/donors/juno_fit_study/landmark-moving-v4/juno_b_flow_r075.dae')
    parser.add_argument('--output',type=Path,default=ROOT/'build/donors/juno_actual')
    parser.add_argument('--scale',type=float,default=1.165)
    parser.add_argument('--align-hip-x',action='store_true',help='Translate source-weighted legs to native lateral hip pivots')
    parser.add_argument('--stance-extra',type=float,default=0.,help='Additional outward pose translation per leg in metres')
    parser.add_argument('--arm-rotation-fraction',type=float,default=1.)
    parser.add_argument('--leg-rotation-fraction',type=float,default=1.)
    parser.add_argument('--arm-lateral-extra',type=float,default=0.,help='Additional outward source-weighted arm pivot translation per side in metres')
    parser.add_argument('--align-arm-pivot',action='store_true',help='Translate source-weighted arms to native shoulder joint XYZ')
    parser.add_argument('--posed-input',type=Path,help='Use a separately reviewed full-topology pose/corrective NPZ without recomputing its coordinates')
    parser.add_argument('--pose-only',action='store_true')
    parser.add_argument('--blender-preview',action='store_true')
    parser.add_argument('--blender-preview-final',action='store_true')
    parser.add_argument('--repair-skin-payload',type=Path,
        help='Explicit reviewed shared-Juno facial-weight repair; copy prior staging into a new output')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else None)
    if args.blender_preview:
        preview(args.output,args.native);return
    if args.blender_preview_final:
        preview_final(args.output);return
    if args.repair_skin_payload:
        import shutil
        source=args.repair_skin_payload.resolve();destination=args.output.resolve()
        if destination.exists():raise ValueError('Skin repair requires a new output directory')
        if destination==source or source in destination.parents:raise ValueError('Skin repair destination must be separate')
        metadata=json.loads(args.donor.with_suffix('.json').read_text())
        bones={b['name']:b for r in metadata['rigs'] for b in r['bones']}
        payload=json.loads((source/'body_payload.json').read_text())
        with np.load(source/'body_prepared.npz') as loaded:prepared={k:loaded[k] for k in loaded.files}
        updated,full,repair=repair_juno_stray_facial_weights(payload,prepared,bones)
        destination.mkdir(parents=True)
        for path in source.iterdir():
            if path.is_file():shutil.copy2(path,destination/path.name)
        prepared['bone_weights']=full
        np.savez_compressed(destination/'body_prepared.npz',**prepared)
        (destination/'body_payload.json').write_text(json.dumps(updated,separators=(',',':'),allow_nan=False))
        report=json.loads((source/'report.json').read_text());report['explicit_skin_repair']=repair
        report['payload']=str(destination/'body_payload.json');report['payload_sha256']=sha(destination/'body_payload.json')
        report['skin_repair_input_payload_sha256']=sha(source/'body_payload.json')
        (destination/'report.json').write_text(json.dumps(report,indent=2))
        print(json.dumps({'payload':report['payload'],'sha256':report['payload_sha256'],'repair':repair},indent=2));return
    metadata=json.loads(args.donor.with_suffix('.json').read_text())
    if sha(args.donor)!=metadata['npz_sha256']:
        raise ValueError('Donor capture fingerprint changed')
    with np.load(args.donor,allow_pickle=False) as source:
        arrays={k:source[k] for k in source.files}
    native=load_dae(args.native)
    if args.posed_input:
        if args.posed_input.resolve().parent==args.output.resolve():
            raise ValueError('Reviewed pose inputs must remain in separate staging')
        report=json.loads(args.posed_input.with_name('report.json').read_text())
        if report['source_npz_sha256']!=sha(args.donor):raise ValueError('Reviewed pose belongs to a different source state')
        if 'local_pose_corrective' in report and not report['local_pose_corrective']['passed']:
            raise ValueError('Local corrective has not passed its global source comparison')
        with np.load(args.posed_input) as data:posed={k:data[k] for k in data.files}
        if not np.array_equal(posed['triangles'],arrays['triangles'][:,[0,2,1]]):
            raise ValueError('Reviewed pose changed original source topology')
        if not np.array_equal(posed['source_vertex_ids'],np.arange(len(arrays['positions']))):
            raise ValueError('Reviewed pose changed original source vertex identity')
        if not np.array_equal(posed['scaled_source_positions'],arrays['positions'][:,[0,2,1]]*report['uniform_scale']):
            raise ValueError('Reviewed pose source normalization differs')
        weights,names,bones,_=normalized_deform_weights(arrays,metadata)
        report['reviewed_posed_input']={'path':str(args.posed_input.resolve()),'sha256':sha(args.posed_input)}
    else:
        posed,weights,names,bones,report=pose_donor(arrays,metadata,native,args.scale,
            align_hip_x=args.align_hip_x,stance_extra=args.stance_extra,
            arm_rotation_fraction=args.arm_rotation_fraction,leg_rotation_fraction=args.leg_rotation_fraction,
            arm_lateral_extra=args.arm_lateral_extra,align_arm_pivot=args.align_arm_pivot)
    for side,groups in [('left',['l_breast','l_breast2']),('right',['r_breast','r_breast2'])]:
        values=weights[:,[names.index(n) for n in groups]].sum(1)
        posed['source_breast_influence_'+side]=values
        report['source_breast_influence_'+side]={'groups':groups,'positive_vertices':int((values>0).sum()),
            'maximum':float(values.max()),'sum':float(values.sum())}
    args.output.mkdir(parents=True,exist_ok=True)
    np.savez_compressed(args.output/'posed_dense.npz',**posed)
    report.update(donor_state_id=metadata['id'],display_label=metadata['donor_id']+' '+metadata['preset']['id'],
                  reviewed_preset=metadata['preset'],source_key_values={name:metadata['applied_shape_keys'][name]['value']
                    for name in ('Chubby','Big.Tits','Small.Tits','Hyper.Tits') if name in metadata['applied_shape_keys']},
                  source_npz=str(args.donor.resolve()),source_npz_sha256=sha(args.donor),
                  source_metadata_sha256=sha(args.donor.with_suffix('.json')),
                  frozen_geometry_parity=metadata.get('geometry_reference'),
                  native=str(args.native.resolve()),native_sha256=sha(args.native),
                  complete=False)
    if not args.pose_only:
        mapped,report['skin_mapping']=map_native_weights(weights,names,bones,native['bone_palette'])
        body,report['neck']=trim_and_bridge(posed,mapped,native)
        np.savez_compressed(args.output/'neck_geometry.npz',**body)
        reference=load_dae(args.reference)
        final,report['surface_transfer']=transfer_native_surface(body,reference,native)
        final['source_face_ids']=body['source_face_ids']
        payload,report['export_quantization']=body_payload(final,native)
        np.savez_compressed(args.output/'body_prepared.npz',**final)
        (args.output/'body_payload.json').write_text(json.dumps(payload,separators=(',',':'),allow_nan=False))
        report.update(complete=True,payload=str((args.output/'body_payload.json').resolve()),
            payload_sha256=sha(args.output/'body_payload.json'),reference=str(args.reference.resolve()),
            reference_sha256=sha(args.reference),surface_audit_status='not yet audited; source contains known preexisting intersections')
    (args.output/'report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({'posed':str(args.output/'posed_dense.npz'),'complete':report['complete'],
                      'payload':report.get('payload'),'report':str(args.output/'report.json')},indent=2))


if __name__=='__main__':main()
