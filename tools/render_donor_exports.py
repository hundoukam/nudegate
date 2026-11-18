"""Render verified serialized GR2 body geometry; run inside Blender.

The visible triangles/positions come from the lossless readback, not an imagined
result. Prepared shading normals are used only after exporter basis checks.
No source file, package, body state or physics setting is modified.
"""
from __future__ import annotations
import argparse,base64,hashlib,json,math,sys
from pathlib import Path
import bpy
import numpy as np
from mathutils import Vector

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from render_bodies import label,panel,BODY_COLOR,MUTED_COLOR

sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()


def read_profile(entry):
    dump_path=Path(entry['dump']);dump=json.loads(dump_path.read_text())
    export_path=Path(entry['export_report']);export=json.loads(export_path.read_text())
    package_path=Path(entry['package_report']);package=json.loads(package_path.read_text())
    prepared_path=Path(entry['prepared'])
    model=Path(dump['source_gr2']);model_sha=sha(model)
    if (model_sha!=dump['source_sha256'] or model_sha!=export['output_sha256']
            or export.get('validation_status')!='passed'
            or model_sha not in package['files'].values()
            or sha(package['package'])!=package['package_sha256']):
        raise ValueError('Actual model, dump, export or package hash binding failed')
    mesh=next(m for m in dump['meshes'] if m['name']=='HUM_F_NKD_Body_A_Mesh')
    raw_positions=base64.b64decode(mesh['positions_f32_le_base64'],validate=True)
    raw_triangles=base64.b64decode(mesh['triangle_indices_i32_le_base64'],validate=True)
    if (hashlib.sha256(raw_positions).hexdigest()!=mesh['positions_f32_le_sha256']
            or hashlib.sha256(raw_triangles).hexdigest()!=mesh['triangle_indices_i32_le_sha256']):
        raise ValueError('Actual serialized geometry buffer changed')
    positions=np.frombuffer(raw_positions,dtype='<f4').reshape(-1,3)
    triangles=np.frombuffer(raw_triangles,dtype='<i4').reshape(-1,3)
    with np.load(prepared_path,allow_pickle=False) as prepared:
        if (not np.array_equal(positions,prepared['positions'].astype('<f4'))
                or not np.array_equal(triangles,prepared['triangles'])):
            raise ValueError('Prepared shading attributes do not belong to the actual model')
        normals=prepared['normals'].copy()
    if len(positions)!=mesh['raw_vertices'] or len(triangles)!=mesh['triangles']:
        raise ValueError('Actual model geometry count differs from readback')
    record={'label':entry['label'],'model':str(model.resolve()),'model_sha256':model_sha,
        'readback':str(dump_path.resolve()),'readback_sha256':sha(dump_path),
        'export_report_sha256':sha(export_path),'prepared_sha256':sha(prepared_path),
        'package_sha256':package['package_sha256'],'actual_vertices':len(positions),
        'actual_triangles':len(triangles),'runtime_physics_shown':False,
        'normal_basis':'prepared normals, validated against serialized exporter basis'}
    return positions[:,[0,2,1]],triangles[:,[0,2,1]],normals[:,[0,2,1]],record


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--percentage',type=int,default=100,help='Render scale for a smaller inspection copy')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    if not 10<=args.percentage<=100:raise ValueError('Render percentage must be between 10 and 100')
    output=args.output.resolve()
    if output.exists() or output.with_suffix('.blend').exists():
        raise ValueError('Export reviews are write-once; choose a new output filename')
    manifest=json.loads(args.manifest.read_text());entries=manifest['profiles']
    if not entries or len(entries)>6:raise ValueError('Review requires one to six actual exported profiles')
    profiles=[read_profile(entry) for entry in entries]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene=bpy.context.scene;scene.render.engine='BLENDER_WORKBENCH'
    columns=2 if len(profiles)>1 else 1;rows=math.ceil(len(profiles)/columns)
    scene.render.resolution_x=2400 if columns==2 else 1600
    scene.render.resolution_y=int(scene.render.resolution_x*(rows*2.10+.92)/(columns*2.8+.15))
    scene.render.resolution_percentage=args.percentage;scene.render.image_settings.file_format='PNG'
    scene.render.image_settings.color_mode='RGB';scene.render.film_transparent=False
    scene.display.render_aa='16'
    shading=scene.display.shading;shading.light='STUDIO';shading.color_type='OBJECT'
    shading.show_shadows=False;shading.show_cavity=True;shading.cavity_type='WORLD'
    shading.cavity_ridge_factor=.35;shading.cavity_valley_factor=.35
    shading.show_specular_highlight=False;shading.show_object_outline=False;shading.background_type='WORLD'
    scene.world=bpy.data.worlds.new('Export review background');scene.world.color=(.04,.049,.061)
    scene.view_settings.view_transform='Standard';scene.view_settings.look='None'
    records=[]
    for index,(vertices,triangles,normals,record) in enumerate(profiles):
        row,column=divmod(index,columns);x=(column-(columns-1)/2)*2.8;floor=(rows-1-row)*2.1
        panel(x,floor,2.68,2.0)
        mesh=bpy.data.meshes.new(record['label']);mesh.from_pydata(vertices.tolist(),[],triangles.tolist());mesh.update()
        for polygon in mesh.polygons:polygon.use_smooth=True
        mesh.normals_split_custom_set(normals[triangles].reshape(-1,3).tolist())
        for view,offset,angle in [('FRONT',-.48,0.),('SIDE',.67,math.pi/2)]:
            obj=bpy.data.objects.new(record['label']+' '+view,mesh);scene.collection.objects.link(obj)
            obj.location=(x+offset,0,floor);obj.rotation_euler.z=angle;obj.color=BODY_COLOR
            label(view,x+offset,floor-.055,.045,MUTED_COLOR)
        label(record['label'],x,floor+1.88,min(.088,2.5/max(1,len(record['label']))))
        records.append(record)
    top=(rows-1)*2.1+2.0
    label('Nudegate / preserved donor bodies',0,top+.34,.14)
    label('Actual exported game geometry / source body shapes with rig fitting',0,top+.15,.075,MUTED_COLOR)
    label('Same display scale / static preview / in-game skin and jiggle untested',0,-.32,.075,MUTED_COLOR)
    camera_data=bpy.data.cameras.new('Export review camera');camera=bpy.data.objects.new('Export review camera',camera_data)
    scene.collection.objects.link(camera)
    center=(top+.48-.46)/2;camera.location=(0,-14,center)
    camera.rotation_euler=(Vector((0,0,center))-camera.location).to_track_quat('-Z','Y').to_euler()
    camera_data.type='ORTHO';aspect=scene.render.resolution_x/scene.render.resolution_y
    # Blender's orthographic scale is the vertical span. Fit both dimensions;
    # using a horizontal span here crops portrait contact sheets.
    camera_data.ortho_scale=max((columns*2.8+.15)/aspect,top+.94);scene.camera=camera
    output.parent.mkdir(parents=True,exist_ok=True);scene.render.filepath=str(output)
    bpy.ops.wm.save_as_mainfile(filepath=str(output.with_suffix('.blend')))
    bpy.ops.render.render(write_still=True)
    output.with_suffix('.json').write_text(json.dumps({'schema_version':1,
        'kind':'actual serialized donor geometry review','manifest_sha256':sha(args.manifest),
        'image_sha256':sha(output),
        'source_files_modified':False,'runtime_physics_shown':False,
        'render_percentage':args.percentage,'profiles':records},indent=2))
    print('EXPORTED_DONOR_REVIEW '+str(output),flush=True)


if __name__=='__main__':main()
