"""Render actual torso attachment geometry for source/legacy/new-base review.

Run with Blender --background --python tools/render_attachment_review.py --
    --manifest build/attachment-review/human_elf_f.json --output ...png
Only render meshes are created; source geometry, rigs, and game files are read.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO/'src'),str(REPO/'tools')]
from nudegate.collada import ColladaMesh


def source_face_indices(triangles,reference_positions,frame):
    """Select once from the undeformed source, never from grown coordinates."""
    return [index for index,triangle in enumerate(triangles)
            if all(1.13<reference_positions[vertex][1]/frame[1]<1.49
                   and abs(reference_positions[vertex][0]/frame[0])<.30 for vertex in triangle)]


def rotate_display(point,angle_x,angle_z):
    x,y,z=point
    y,z=math.cos(angle_x)*y-math.sin(angle_x)*z,math.sin(angle_x)*y+math.cos(angle_x)*z
    return (math.cos(angle_z)*x-math.sin(angle_z)*y,
            math.sin(angle_z)*x+math.cos(angle_z)*y,z)


def selected_view_bounds(vertices,triangles,indices,angle_x,angle_z):
    used={vertex for index in indices for vertex in triangles[index]}
    if not used:raise ValueError('Review face selection is empty')
    projected=[rotate_display(vertices[vertex],angle_x,angle_z) for vertex in used]
    return [min(point[0] for point in projected),max(point[0] for point in projected),
            min(point[2] for point in projected),max(point[2] for point in projected)]


def geometric_normals(vertices,triangles):
    keys = [tuple(round(value,8) for value in vertex) for vertex in vertices]
    sums = defaultdict(lambda:[0.,0.,0.])
    face_normals = []
    for triangle in triangles:
        a,b,c = (Vector(vertices[index]) for index in triangle)
        normal = (b-a).cross(c-a)
        face_normals.append(normal)
        for key in {keys[index] for index in triangle}:
            for axis in range(3):sums[key][axis] += normal[axis]
    normals = {key:Vector(values).normalized() for key,values in sums.items()}
    return [tuple(normals[keys[index]]) for triangle in triangles for index in triangle],face_normals,keys


def local_metrics(vertices,triangles,face_normals,keys):
    edges = defaultdict(list)
    for face,triangle in enumerate(triangles):
        for a,b in zip(triangle,triangle[1:]+triangle[:1]):
            edges[tuple(sorted((keys[a],keys[b])))].append(face)
    values = []
    worst = []
    for (a,b),faces in edges.items():
        if len(faces)!=2:continue
        x,depth,y = ((a[index]+b[index])/2 for index in range(3))
        if not (1.19<y<1.335 and .025<abs(x)<.22 and depth<-.025):continue
        first,second = (face_normals[face] for face in faces)
        if first.length==0 or second.length==0:continue
        angle = math.degrees(first.angle(second))
        values.append(angle)
        worst.append((angle,[x,y,depth]))
    values.sort()
    return {'underbust_edges':len(values),'underbust_max_edge_angle_degrees':max(values,default=0),
            'underbust_p95_edge_angle_degrees':values[min(len(values)-1,int(len(values)*.95))] if values else 0,
            'underbust_edges_over_45_degrees':sum(value>45 for value in values),
            'worst_edges':sorted(worst,reverse=True)[:8]}


def text(value,x,z,size=.045):
    curve = bpy.data.curves.new('Review label','FONT')
    curve.body=value;curve.size=size;curve.align_x='CENTER';curve.align_y='CENTER'
    obj=bpy.data.objects.new(value,curve);bpy.context.scene.collection.objects.link(obj)
    obj.rotation_euler.x=math.pi/2;obj.location=(x,-1.0,z);obj.color=(.85,.9,.95,1)


def main():
    global bpy,Vector
    import bpy
    from mathutils import Vector
    from render_bodies import split_normals
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--normal-mode',choices=('authored','welded'),default='authored')
    parser.add_argument('--crop',choices=('none','source'),default='none',
                        help='Default renders every face. source requires source_dae per row and uses static original face indices.')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    manifest=json.loads(args.manifest.read_text())
    bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
    scene=bpy.context.scene;scene.render.engine='BLENDER_WORKBENCH'
    scene.render.resolution_x=2200
    scene.render.resolution_percentage=100;scene.render.image_settings.file_format='PNG'
    shading=scene.display.shading;shading.light='STUDIO';shading.color_type='OBJECT'
    shading.show_shadows=False;shading.show_cavity=False;shading.show_specular_highlight=False
    shading.show_object_outline=False;shading.background_type='WORLD'
    if scene.world is None:scene.world=bpy.data.worlds.new('Review background')
    scene.world.color=(.035,.045,.06);scene.view_settings.view_transform='Standard'
    columns=[('FRONT',0.,0.),('SIDE',0.,math.pi/2),('UNDERSIDE',math.radians(-38),0.)]
    loaded=[];column_bounds=[[math.inf,-math.inf,math.inf,-math.inf] for _ in columns]
    for row in manifest['rows']:
        path=Path(row['dae']);source=ColladaMesh.load(path,geometry_id=row.get('geometry_id'))
        frame=row.get('frame',[1,1,1])
        vertices=[(x/frame[0],z/frame[2],y/frame[1]) for x,y,z in source.positions]
        triangles=[(a,c,b) for a,b,c in source.triangles]
        reference_path=None
        if args.crop=='source':
            if not row.get('source_dae'):raise ValueError('Static source cropping requires an explicit source_dae for every row')
            reference_path=Path(row['source_dae'])
            reference=ColladaMesh.load(reference_path,geometry_id=row.get('source_geometry_id',source.geometry_id))
            if reference.triangles!=source.triangles or len(reference.positions)!=len(vertices):
                raise ValueError('Static source crop requires identical indexed source topology')
            indices=source_face_indices(source.triangles,reference.positions,frame)
        else:indices=list(range(len(triangles)))
        pivot=1.315 if args.crop=='source' else .80
        display=[(x,y+.075,z-pivot) for x,y,z in vertices]
        for column,(_,angle_x,angle_z) in enumerate(columns):
            bounds=selected_view_bounds(display,triangles,indices,angle_x,angle_z)
            current=column_bounds[column]
            current[:]=[min(current[0],bounds[0]),max(current[1],bounds[1]),min(current[2],bounds[2]),max(current[3],bounds[3])]
        loaded.append((row,path,source,frame,vertices,triangles,display,indices,reference_path))
    widths=[bounds[1]-bounds[0]+.20 for bounds in column_bounds]
    total_width=sum(widths)+.12
    centers=[];cursor=-sum(widths)/2
    for width,bounds in zip(widths,column_bounds):
        centers.append(cursor+width/2-(bounds[0]+bounds[1])/2);cursor+=width
    geometry_min=min(bounds[2] for bounds in column_bounds)
    geometry_max=max(bounds[3] for bounds in column_bounds)
    geometry_height=geometry_max-geometry_min;height=geometry_height+.24
    reports=[]
    for row_index,(row,path,source,frame,vertices,triangles,display,indices,reference_path) in enumerate(loaded):
        welded,face_normals,keys=geometric_normals(vertices,triangles)
        authored=split_normals(path,source.geometry_id)
        authored=[tuple(Vector((normal[0]*frame[0],normal[1]*frame[2],normal[2]*frame[1])).normalized()) for normal in authored]
        chosen=authored if args.normal_mode=='authored' else welded
        faces=[triangles[index] for index in indices]
        normals=[normal for index in indices for normal in chosen[index*3:index*3+3]]
        mesh=bpy.data.meshes.new(row['id'])
        mesh.from_pydata(display,[],faces);mesh.update()
        for polygon in mesh.polygons:polygon.use_smooth=True
        mesh.normals_split_custom_set(normals)
        floor=(len(manifest['rows'])-row_index-1)*height
        for column_index,(_,angle_x,angle_z) in enumerate(columns):
            obj=bpy.data.objects.new(row['id']+' review',mesh);scene.collection.objects.link(obj)
            obj.location=(centers[column_index],0,floor-geometry_min);obj.rotation_euler=(angle_x,0,angle_z)
            obj.color=(.63,.69,.74,1)
        text(row['label'],0,floor+geometry_height+.10,.044)
        reports.append({**row,'dae_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                        'geometry_id':source.geometry_id,'normal_mode':args.normal_mode,
                        'vertices':len(vertices),'triangles':len(triangles),
                        'rendered_triangles':len(faces),'crop_mode':args.crop,
                        'source_crop_reference':str(reference_path) if reference_path else None,
                        'source_face_indices_sha256':hashlib.sha256(json.dumps(indices).encode()).hexdigest(),
                        **local_metrics(vertices,triangles,face_normals,keys)})
    upper=(len(manifest['rows'])-1)*height+geometry_height+.38
    text('UNDERBUST ATTACHMENT / '+manifest['family'],0,upper,.060)
    text('Actual geometry / '+args.normal_mode+' normals / '+('static source face set' if args.crop=='source' else 'every input face'),0,upper-.075,.037)
    for index,(label,_,__) in enumerate(columns):text(label,centers[index]+(column_bounds[index][0]+column_bounds[index][1])/2,upper-.16,.034)
    camera_data=bpy.data.cameras.new('Attachment review camera');camera=bpy.data.objects.new('Attachment review camera',camera_data)
    scene.collection.objects.link(camera);bottom,top=-.08,upper+.13;center=(bottom+top)/2
    camera.location=(0,-10,center);camera.rotation_euler=(Vector((0,0,center))-camera.location).to_track_quat('-Z','Y').to_euler()
    total_height=top-bottom;scene.render.resolution_y=max(800,round(scene.render.resolution_x*total_height/total_width))
    camera_data.type='ORTHO';aspect=scene.render.resolution_x/scene.render.resolution_y
    camera_data.ortho_scale=(max(total_width,total_height*aspect) if aspect>=1
                             else max(total_height,total_width/aspect));scene.camera=camera
    # Store labels as meshes in the saved diagnostic scene.
    for obj in list(scene.objects):
        if obj.type=='FONT':
            bpy.ops.object.select_all(action='DESELECT');obj.select_set(True)
            bpy.context.view_layer.objects.active=obj;bpy.ops.object.convert(target='MESH')
    output=args.output.resolve();output.parent.mkdir(parents=True,exist_ok=True)
    scene.render.filepath=str(output)
    bpy.ops.wm.save_as_mainfile(filepath=str(output.with_suffix('.blend')))
    bpy.ops.render.render(write_still=True)
    output.with_name(output.stem+'.review.json').write_text(json.dumps({'family':manifest['family'],'rows':reports},indent=2)+'\n')
    print('ATTACHMENT_REVIEW '+str(output))


if __name__=='__main__':main()
