"""Render a raw donor, matched BG3 source and preliminary authored fits.

Run inside Blender. This tool only creates a display scene; all authoring mesh
files and raw donor arrays remain unchanged. Head trim is a recorded face mask.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import bpy
import numpy as np
from mathutils import Vector

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tools')]
from nudegate.collada import ColladaMesh
from render_bodies import label,panel,split_normals,BODY_COLOR,MUTED_COLOR

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def dae_profile(path,geometry,title):
    mesh=ColladaMesh.load(path,geometry_id=geometry)
    positions,triangles=mesh.positions,mesh.triangles
    return {'label':title,'id':path.stem,'vertices':np.asarray([(x,z,y)for x,y,z in positions]),
            'triangles':np.asarray([(a,c,b)for a,b,c in triangles],dtype=np.int32),
            'normals':np.asarray(split_normals(path,geometry)).reshape(-1,3,3),
            'source':str(path),'source_sha256':sha(path),'geometry_id':geometry,
            'display_face_mask':'all input faces'}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--donor',type=Path,default=ROOT/'build/donors/selected/juno_b.npz')
    parser.add_argument('--donor-scale',type=float,default=1.165)
    parser.add_argument('--donor-cut-height',type=float,default=1.57)
    parser.add_argument('--source',type=Path,default=ROOT/'build/physics-probe/matched-v1/model-roundtrip/human_normal/source.dae')
    parser.add_argument('--candidate',type=Path,nargs='+',required=True)
    parser.add_argument('--geometry-id',default='HUM_F_NKD_Body_A_Mesh-geom')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--omit-native',action='store_true',help='Compare the donor with multiple fits in one row')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    donor_path=args.donor.resolve()
    donor_metadata=json.loads(donor_path.with_suffix('.json').read_text())
    if donor_metadata.get('load_warning') or sha(donor_path)!=donor_metadata['npz_sha256']:
        raise ValueError('Unreviewed or changed raw donor export')
    with np.load(donor_path,allow_pickle=False) as arrays:
        vertices=arrays['positions'].copy()*args.donor_scale
        triangles=arrays['triangles'].copy()
        normals=arrays['corner_normals'].copy()
    # Original donor is Blender Z-up. BG3 normalization [x,z,y] followed by its
    # display conversion [x,z,y] returns these coordinates, with no reflection.
    indices=np.flatnonzero(np.all(vertices[triangles,2]<=args.donor_cut_height,axis=1))
    profiles=[{'id':donor_metadata['id'],'label':'Original Juno / normalized reference',
        'vertices':vertices,'triangles':triangles[indices],'normals':normals[indices],
        'source':str(donor_path),'source_sha256':sha(donor_path),
        'display_face_mask':{'height_max':args.donor_cut_height,'source_face_indices':indices.tolist(),
            'source_face_indices_sha256':hashlib.sha256(indices.astype('<i8').tobytes()).hexdigest()},
        'donor_normalization':{'bg3_axes':'[x,z,y]','scale':args.donor_scale,'offset':[0,0,0]},
        'original_triangle_count':len(triangles)}]
    if not args.omit_native:
        profiles.append(dae_profile(args.source.resolve(),args.geometry_id,'Native matched BG3 / original'))
    for path in args.candidate:
        profiles.append(dae_profile(path.resolve(),args.geometry_id,'Preliminary BG3 fit / '+path.stem.split('_')[-1]))

    bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
    scene=bpy.context.scene
    scene.render.engine='BLENDER_WORKBENCH'
    scene.render.resolution_x=2400
    scene.render.resolution_y=1050 if len(profiles)<=3 else 1800
    scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG';scene.render.image_settings.color_mode='RGB'
    scene.render.film_transparent=False;scene.render.use_border=False
    scene.display.render_aa='16'
    shading=scene.display.shading
    shading.light='STUDIO';shading.color_type='OBJECT';shading.show_shadows=False
    shading.show_cavity=True;shading.cavity_type='WORLD'
    shading.cavity_ridge_factor=.35;shading.cavity_valley_factor=.35
    shading.show_specular_highlight=False;shading.show_object_outline=False
    shading.background_type='WORLD'
    if scene.world is None:scene.world=bpy.data.worlds.new('Fit review background')
    scene.world.color=(.040,.049,.061)
    scene.view_settings.view_transform='Standard';scene.view_settings.look='None'
    visible=[p['vertices'][np.unique(p['triangles'])] for p in profiles]
    max_height=max(float(np.ptp(v[:,2]))for v in visible)
    scale=min(1.,1.68/max_height)
    front_min=min(float(v[:,0].min())*scale for v in visible)
    front_max=max(float(v[:,0].max())*scale for v in visible)
    side_min=min(float(-v[:,1].max())*scale for v in visible)
    side_max=max(float(-v[:,1].min())*scale for v in visible)
    cell_width=max(2.52,front_max-front_min+side_max-side_min+.55)
    cell_height=2.15
    front_offset=-cell_width/2+.20-front_min
    side_offset=front_offset+front_max+.16-side_min
    columns=min(3,len(profiles));rows=math.ceil(len(profiles)/columns)
    reports=[]
    for index,(p,v) in enumerate(zip(profiles,visible)):
        row,column=divmod(index,columns)
        x=(column-(columns-1)/2)*cell_width
        floor=(rows-1-row)*cell_height
        panel(x,floor,cell_width-.10,cell_height)
        vertices=p['vertices']*scale
        mesh=bpy.data.meshes.new(p['id'])
        mesh.from_pydata(vertices.tolist(),[],p['triangles'].tolist());mesh.update()
        for poly in mesh.polygons:poly.use_smooth=True
        mesh.normals_split_custom_set(p['normals'].reshape(-1,3).tolist())
        floor_offset=floor-float(v[:,2].min())*scale
        for name,offset,angle in [('front',front_offset,0.),('side',side_offset,math.pi/2)]:
            obj=bpy.data.objects.new(p['id']+' '+name,mesh);scene.collection.objects.link(obj)
            obj.location=(x+offset,0,floor_offset);obj.rotation_euler.z=angle;obj.color=BODY_COLOR
        label(p['label'],x,floor+1.91,min(.10,2.25/len(p['label'])))
        label('FRONT',x+front_offset,floor-.04,.047,MUTED_COLOR)
        label('SIDE',x+side_offset,floor-.04,.047,MUTED_COLOR)
        record={k:value for k,value in p.items() if k not in {'vertices','triangles','normals'}}
        record.update(vertices=len(vertices),rendered_triangles=len(p['triangles']),
                      visible_bounds=[v.min(0).tolist(),v.max(0).tolist()])
        reports.append(record)
    upper=(rows-1)*cell_height+2.18
    label('Nudegate / Donor to BG3 / first fit',0,upper+.25,.15)
    label('Original donor / native matched body / fitted render body',0,upper+.04,.085,MUTED_COLOR)
    label('Preliminary geometry study / runtime physics not shown',0,-.35,.09,MUTED_COLOR)
    label('Same view angles and display scale / original source files unchanged',0,-.53,.073,MUTED_COLOR)
    camera_data=bpy.data.cameras.new('Fit review camera');camera=bpy.data.objects.new('Fit review camera',camera_data)
    scene.collection.objects.link(camera)
    center=(upper+.45-.71)/2;target=Vector((0,0,center))
    camera.location=(0,-12,center);camera.rotation_euler=(target-camera.location).to_track_quat('-Z','Y').to_euler()
    camera_data.type='ORTHO';aspect=scene.render.resolution_x/scene.render.resolution_y
    camera_data.ortho_scale=max(columns*cell_width+.20,(upper+1.28)*aspect)
    scene.camera=camera
    output=args.output.resolve();output.parent.mkdir(parents=True,exist_ok=True)
    scene.render.filepath=str(output)
    bpy.ops.wm.save_as_mainfile(filepath=str(output.with_suffix('.blend')))
    bpy.ops.render.render(write_still=True)
    report={'schema_version':1,'purpose':'preliminary donor-to-BG3 fit review',
            'runtime_physics_shown':False,'display_scale':scale,
            'source_files_saved':False,'proxy_overlay':False,
            'image':str(output),'profiles':reports}
    output.with_suffix('.json').write_text(json.dumps(report,indent=2)+'\n')
    print('DONOR_FIT_REVIEW '+str(output),flush=True)

if __name__=='__main__':main()
