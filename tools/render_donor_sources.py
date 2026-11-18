"""Render raw donor NPZ exports without changing their geometry or sources.

Run inside Blender. A shared display scale retains relative world dimensions;
the body export may include a head or end at its original neck opening.
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from render_bodies import label, panel, BODY_COLOR, MUTED_COLOR

SELECTIONS = (
    ('mercy_c', 'Mercy / authored large'),
    ('juno_b', 'Juno / medium'),
    ('juno_e', 'Juno / Chubby 100%'),
    ('cinderella_a', 'Cinderella / default'),
    ('kiriko_2_0_c', 'Kiriko 2.0 / authored large'),
    ('jubilee_b', 'Jubilee / medium'),
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=Path, default=ROOT / 'build/donors/selected')
    parser.add_argument('--output', type=Path, default=ROOT / 'build/donors/previews/selected-donor-sources.png')
    parser.add_argument('--selection', nargs='+', choices=[row[0] for row in SELECTIONS])
    arguments = sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
    args = parser.parse_args(arguments)
    profiles = []
    for identifier, title in SELECTIONS:
        if args.selection and identifier not in args.selection:
            continue
        path = (args.sources / (identifier+'.npz')).resolve()
        metadata_path = path.with_suffix('.json')
        metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
        if metadata.get('load_warning'):
            raise ValueError('Donor load warning requires review before rendering: '+identifier)
        if metadata.get('source_saved') or metadata.get('geometry_regularization'):
            raise ValueError('Expected an unchanged raw donor export: '+identifier)
        before = digest(path)
        if before != metadata['npz_sha256']:
            raise ValueError('Raw donor export fingerprint differs: '+identifier)
        with np.load(path, allow_pickle=False) as arrays:
            positions = arrays['positions'].copy()
            triangles = arrays['triangles'].copy()
            normals = arrays['corner_normals'].copy()
        if normals.shape != (len(triangles), 3, 3):
            raise ValueError('Expected original per-corner normals')
        profiles.append({'id':identifier, 'label':title, 'path':path,
                         'metadata_path':metadata_path, 'metadata':metadata,
                         'npz_sha256':before, 'positions':positions,
                         'triangles':triangles, 'normals':normals})

    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.render.resolution_x = 2400
    scene.render.resolution_y = 1700
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGB'
    scene.render.film_transparent = False
    scene.render.use_border = False
    scene.display.render_aa = '16'
    shading = scene.display.shading
    shading.light = 'STUDIO'
    shading.color_type = 'OBJECT'
    shading.show_shadows = False
    shading.show_cavity = True
    shading.cavity_type = 'WORLD'
    shading.cavity_ridge_factor = .35
    shading.cavity_valley_factor = .35
    shading.show_specular_highlight = False
    shading.show_object_outline = False
    shading.background_type = 'WORLD'
    if scene.world is None:
        scene.world = bpy.data.worlds.new('Donor review background')
    scene.world.color = (.040, .049, .061)
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.look = 'None'

    max_height = max(float(np.ptp(p['positions'][:, 2])) for p in profiles)
    display_scale = min(1., 1.68 / max_height)
    front_min = min(float(p['positions'][:, 0].min())*display_scale for p in profiles)
    front_max = max(float(p['positions'][:, 0].max())*display_scale for p in profiles)
    side_min = min(float(-p['positions'][:, 1].max())*display_scale for p in profiles)
    side_max = max(float(-p['positions'][:, 1].min())*display_scale for p in profiles)
    cell_width = max(2.52, front_max-front_min+side_max-side_min+.55)
    cell_height = 2.16
    row_count = math.ceil(len(profiles)/3)
    front_offset = -cell_width/2+.20-front_min
    side_offset = front_offset+front_max+.16-side_min
    summaries = []
    for index, profile in enumerate(profiles):
        row, column = divmod(index, 3)
        x = (column-1)*cell_width
        floor = (row_count-1-row)*cell_height
        panel(x, floor, cell_width-.10, cell_height)
        vertices = profile['positions']*display_scale
        mesh = bpy.data.meshes.new(profile['id'])
        mesh.from_pydata(vertices.tolist(), [], profile['triangles'].tolist())
        mesh.update()
        stored = np.asarray([vertex.co[:] for vertex in mesh.vertices])
        preview_float_drift = float(np.max(np.abs(stored-vertices)))
        for polygon in mesh.polygons:
            polygon.use_smooth = True
        mesh.normals_split_custom_set(profile['normals'].reshape(-1,3).tolist())
        # Exact geometry is reused by both views. Only a shared uniform display
        # scale, scene translation and side-view rotation are applied.
        floor_offset = floor-float(vertices[:,2].min())
        for name, offset, angle in (('front',front_offset,0.), ('side',side_offset,math.pi/2)):
            obj = bpy.data.objects.new(profile['id']+' '+name, mesh)
            scene.collection.objects.link(obj)
            obj.location = (x+offset, 0, floor_offset)
            obj.rotation_euler.z = angle
            obj.color = BODY_COLOR
        label(profile['label'], x, floor+1.91, min(.11, 2.25/len(profile['label'])))
        label('FRONT', x+front_offset, floor-.04, .047, MUTED_COLOR)
        label('SIDE', x+side_offset, floor-.04, .047, MUTED_COLOR)
        summaries.append({'id':profile['id'], 'label':profile['label'],
            'npz':str(profile['path']), 'npz_sha256':profile['npz_sha256'],
            'metadata_sha256':digest(profile['metadata_path']),
            'source':profile['metadata']['source'],
            'source_sha256':profile['metadata']['source_sha256'],
            'source_saved':False, 'vertices':len(vertices),
            'triangles':len(profile['triangles']),
            'corner_normals':int(profile['normals'].shape[0]*3),
            'original_bounds':profile['metadata']['bounds'],
            'preview_float32_coordinate_drift':preview_float_drift,
            'geometry_operations':['shared uniform display scale only'],
            'display_object_operations':['floor translation','side view rotation']})

    upper = (row_count-1)*cell_height+2.18
    label('Nudegate / Selected donor source geometry', 0, upper+.27, .15)
    label('Authored shapes / original mesh detail / shared display scale', 0, upper+.05, .085, MUTED_COLOR)
    label('Not yet fitted to BG3 / physics not shown', 0, -.36, .10, MUTED_COLOR)
    label('Original Blender files remain unchanged', 0, -.53, .078, MUTED_COLOR)
    camera_data = bpy.data.cameras.new('Donor review camera')
    camera = bpy.data.objects.new('Donor review camera', camera_data)
    scene.collection.objects.link(camera)
    center_z = (upper+.47-.72)/2
    target = Vector((0,0,center_z))
    camera.location = (0,-12,center_z)
    camera.rotation_euler = (target-camera.location).to_track_quat('-Z','Y').to_euler()
    camera_data.type = 'ORTHO'
    aspect = scene.render.resolution_x/scene.render.resolution_y
    camera_data.ortho_scale = max(3*cell_width+.20, (upper+1.28)*aspect)
    scene.camera = camera
    output = args.output.resolve()
    output.parent.mkdir(parents=True,exist_ok=True)
    scene.render.filepath = str(output)
    bpy.ops.wm.save_as_mainfile(filepath=str(output.with_suffix('.blend')))
    bpy.ops.render.render(write_still=True)
    for profile in profiles:
        if digest(profile['path']) != profile['npz_sha256']:
            raise ValueError('Donor export changed during rendering')
    report = {'schema_version':1, 'purpose':'raw donor source comparison',
        'bg3_fitted':False, 'physics_shown':False, 'geometry_regularized':False,
        'source_files_saved':False, 'display_scale':display_scale,
        'image':str(output), 'blend':str(output.with_suffix('.blend')),
        'blender_version':bpy.app.version_string, 'profiles':summaries}
    output.with_suffix('.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print('DONOR_SOURCE_REVIEW '+str(output),flush=True)


if __name__ == '__main__':
    main()
