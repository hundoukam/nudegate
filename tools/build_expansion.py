"""Build an additive, fingerprinted base-body / chest-size study grid."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace

from build_bodies import (ROOT, FAMILIES, convert, validate_roundtrip,
                          measurements)
from nudegate.body_shapes import bake_shape
from nudegate.breast_sizes import apply_breast_size, author_breast_overlay_masks, calibrate_breast_wall
from nudegate.collada import ColladaMesh
from nudegate.expansion import effective_profile, apply_body_details, author_expansion_masks
from nudegate.lod_authoring import enumerate_lods, bake_lods, validate_lod_roundtrip
from nudegate.surface_intersections import SurfaceIntersectionChecker, geometry_fingerprint
from nudegate.geometry_proofs import validate_geometry_proof
from nudegate.base_attachment import round_base_attachments


PIPELINE_DEPENDENCIES = (
    Path(__file__), ROOT/'tools/build_bodies.py', ROOT/'src/nudegate/expansion.py',
    ROOT/'src/nudegate/breast_sizes.py', ROOT/'src/nudegate/body_shapes.py',
    ROOT/'src/nudegate/soften.py', ROOT/'src/nudegate/collada.py',
    ROOT/'src/nudegate/lod_authoring.py', ROOT/'src/nudegate/morphs.py',
    ROOT/'src/nudegate/surface_intersections.py', ROOT/'src/nudegate/geometry_proofs.py',
    ROOT/'src/nudegate/base_attachment.py',
    ROOT/'src/nudegate/breast_cage.py',
)
SURFACE_CHECKERS = {}
SOURCE_MASKS = {}
BASE_SCULPTS = {}
WALL_CALIBRATIONS = {}


def surface_checker(mesh):
    key = (geometry_fingerprint(mesh.positions,mesh.triangles),mesh.topology_id)
    if key not in SURFACE_CHECKERS:
        SURFACE_CHECKERS[key] = SurfaceIntersectionChecker(mesh.positions,mesh.triangles,topology_id=mesh.topology_id)
    return SURFACE_CHECKERS[key]


def pipeline_fingerprint():
    dependencies = {str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in PIPELINE_DEPENDENCIES}
    digest = hashlib.sha256(json.dumps(dependencies,sort_keys=True).encode()).hexdigest()
    return digest,dependencies


def tool_fingerprint(path):
    path = path.resolve()
    if not path.is_file():
        return None
    dependencies = {str(item.relative_to(path.parent)):hashlib.sha256(item.read_bytes()).hexdigest()
                    for item in [path, *sorted(path.parent.rglob('*.dll'))]}
    return hashlib.sha256(json.dumps(dependencies,sort_keys=True).encode()).hexdigest()


def checkpoint_fingerprint(profile,percent,source_sha,pipeline_sha,family,collection,source_pins,tool_sha):
    inputs = {'profile':profile,'percent':percent,'source':source_sha,'pipeline':pipeline_sha,
              'family_descriptor':family,'collection_id':collection,'reviewed_source_pins':source_pins,
              'converter':tool_sha}
    return hashlib.sha256(json.dumps(inputs,sort_keys=True,allow_nan=False).encode()).hexdigest()


def atomic_json(path,data):
    encoded = json.dumps(data,indent=2,allow_nan=False)+'\n'
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent,prefix=path.name+'.',suffix='.tmp',delete=False) as handle:
            temporary = Path(handle.name)
        temporary.write_text(encoded,encoding='utf-8')
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def sculpt(mesh, profile, percent, frame, *, family_id=None, body_lod=0):
    source_positions,triangles,topology_id = mesh.positions,mesh.triangles,mesh.topology_id
    source_view = SimpleNamespace(positions=source_positions,triangles=triangles,topology_id=topology_id)
    source_key = (geometry_fingerprint(source_positions,triangles),topology_id,tuple(frame or [1,1,1]),family_id)
    if source_key not in SOURCE_MASKS:
        masks, _ = author_expansion_masks(source_view,frame,preserve_back_ridges=family_id in {'tiefling_f','tiefling_fs'})
        SOURCE_MASKS[source_key] = (masks,author_breast_overlay_masks(masks))
    masks,overlay_masks = SOURCE_MASKS[source_key]
    base_key = (source_key,json.dumps(profile,sort_keys=True,allow_nan=False))
    if base_key not in BASE_SCULPTS:
        base, base_report = bake_shape(masks, profile)
        base, base_report['body_details'] = apply_body_details(masks, base, profile)
        if family_id in {'human_elf_f','gith_f','tiefling_f'}:
            corrected = round_base_attachments(masks,base)
            base,base_report['base_attachment'] = corrected['positions'],corrected['report']
        base_report['base_surface_intersections'] = surface_checker(source_view).validate(base)
        BASE_SCULPTS[base_key] = (base,base_report)
    base,cached_report = BASE_SCULPTS[base_key]
    report = copy.deepcopy(cached_report)
    profile_hash = hashlib.sha256(json.dumps(profile,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    calibration_key = (family_id,profile_hash)
    if calibration_key not in WALL_CALIBRATIONS:
        if body_lod!=0:
            raise ValueError('The native LOD0 base must establish wall calibration before lower LODs')
        WALL_CALIBRATIONS[calibration_key] = calibrate_breast_wall(overlay_masks,base,
            family_id=family_id,profile_fingerprint=profile_hash)
    overlay = apply_breast_size({**overlay_masks, 'positions':base,
                               'quality_reference_positions':source_positions,
                               'body_family_id':family_id,'base_profile_sha256':profile_hash,'body_lod':body_lod,
                               'wall_calibration':WALL_CALIBRATIONS[calibration_key]}, percent)
    report['breast_size'] = overlay['report']
    result = overlay['positions']
    report['surface_intersections'] = overlay['report']['quality']
    validate_geometry_proof(source_view,SimpleNamespace(positions=result,triangles=triangles,
                                                topology_id=topology_id),report['surface_intersections'])
    if any(result[index]!=source_positions[index] for index in masks['locked_vertices']):
        raise ValueError('Expansion moved a protected source attachment')
    displaced = [math.dist(a,b) for a,b in zip(source_positions,result)]
    report['moved_vertices'] = sum(distance>1e-10 for distance in displaced)
    report['max_displacement_metres'] = max(displaced,default=0.0)
    return result, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT/'config/expansion_bodies.json')
    parser.add_argument('--sources', type=Path, default=Path.home()/'.cache/nudegate/bcb-analysis')
    parser.add_argument('--strong-sources', type=Path, default=Path.home()/'.cache/nudegate/strong-analysis')
    parser.add_argument('--divine', type=Path, default=Path.home()/'.cache/nudegate/gr2-tools/Divine-1.20.4/Divine.exe')
    parser.add_argument('--output', type=Path, default=ROOT/'build/expansion')
    parser.add_argument('--families', nargs='+', choices=[f['id'] for f in FAMILIES])
    parser.add_argument('--profile-ids', nargs='+')
    parser.add_argument('--percentages', nargs='+', type=int)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--audit-all',action='store_true',help='With --dry-run, collect every profile/size/LOD result')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    if args.audit_all and not args.dry_run:
        raise ValueError('--audit-all requires --dry-run; it never publishes body assets')
    config = json.loads(args.config.read_text())
    if (config.get('schema_version')!=1 or not isinstance(config.get('collection_id'),str)
            or not re.fullmatch('[a-z][a-z0-9_.-]{0,63}',config['collection_id'])):
        raise ValueError('Invalid expansion collection identity')
    pins = json.loads((ROOT/'config/body_sources.json').read_text())['families']
    profiles = config['profiles']
    if (not isinstance(profiles,list) or not profiles
            or any(not isinstance(profile,dict) or not isinstance(profile.get('id'),str)
                   or not re.fullmatch('[a-z][a-z0-9_]{0,40}',profile['id']) for profile in profiles)
            or len({profile['id'] for profile in profiles}) != len(profiles)):
        raise ValueError('Expansion profiles must be nonempty and unique')
    if args.profile_ids:
        if set(args.profile_ids)-{p['id'] for p in profiles}:
            raise ValueError('Unknown expansion profile')
        profiles = [p for p in profiles if p['id'] in args.profile_ids]
    percentages = args.percentages or config['breast_percentages']
    if not percentages or len(percentages) != len(set(percentages)) or set(percentages)-set(config['breast_percentages']):
        raise ValueError('Unreviewed chest-size bucket')
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    pipeline_hash,dependencies = pipeline_fingerprint()
    converter_hash = tool_fingerprint(args.divine)
    if not args.dry_run and converter_hash is None:
        raise ValueError('Expected an existing GR2 converter')
    requested_families = [family['id'] for family in FAMILIES if not args.families or family['id'] in args.families]
    request = {'families':requested_families,'profile_ids':[profile['id'] for profile in profiles],
               'percentages':list(percentages), 'expected_variants':len(requested_families)*len(profiles)*len(percentages),
               'config_sha256':hashlib.sha256(args.config.read_bytes()).hexdigest(),
               'pipeline_sha256':pipeline_hash,'pipeline_dependencies':dependencies,'converter_sha256':converter_hash}
    manifest = {'schema_version':1, 'collection_id':config['collection_id'],
                'physics':'not included', 'in_game':'not tested', 'families':[],
                'build_status':'in_progress','requested_grid':request,'completed_variant_count':0}
    audit = []
    for family in FAMILIES:
        if args.families and family['id'] not in args.families:
            continue
        source = (args.strong_sources if family.get('lod_count') else args.sources)/family['file']
        mesh = ColladaMesh.load(source, geometry_id=family.get('geometry_id'))
        snapshot = mesh.snapshot()
        for key in ('topology_id','position_sha256'):
            if snapshot[key] != pins[family['id']][key]:
                raise ValueError('Unreviewed family source: '+family['id'])
        lods = enumerate_lods(source, expected_lods=5) if family.get('lod_count') else None
        if lods:
            for lod in lods:
                for key in ('topology_id','position_sha256'):
                    if lod['snapshot'][key] != pins[family['id']]['lods'][str(lod['lod'])][key]:
                        raise ValueError('Unreviewed source LOD')
        row = {**family,'source':str(source.resolve()),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
               'source_snapshot':snapshot,'variants':[]}
        manifest['families'].append(row)
        dest = args.output/family['id']
        dest.mkdir(exist_ok=True)
        for raw in profiles:
            profile = effective_profile(raw, strong=bool(lods))
            for percent in percentages:
                identifier = f"exp_{raw['id']}_b{percent:03}"
                print(f"Baking {family['id']} / {identifier}", flush=True)
                dae = dest/f'{family["id"]}_{identifier}.dae'
                gr2, check = dae.with_suffix('.GR2'), dae.with_suffix('.roundtrip.dae')
                checkpoint = dae.with_suffix('.json')
                config_hash = checkpoint_fingerprint(profile,percent,row['source_sha256'],pipeline_hash,
                                                     family,config['collection_id'],pins[family['id']],converter_hash)
                if args.resume and not args.dry_run and checkpoint.is_file():
                    try:
                        entry = json.loads(checkpoint.read_text())
                        if not isinstance(entry,dict):
                            entry = {}
                    except (OSError,ValueError):
                        entry = {}
                    if (entry.get('config_sha256') == config_hash and entry.get('id') == identifier
                            and entry.get('collection_id') == config['collection_id']
                            and entry.get('base_body_id') == raw['id'] and entry.get('breast_percent') == percent
                            and entry.get('skin_style') == raw['skin_style']
                            and entry.get('geometry_id') == snapshot['geometry_id']
                            and Path(entry.get('dae','')).resolve() == dae.resolve()
                            and Path(entry.get('gr2','')).resolve() == gr2.resolve()
                            and Path(entry.get('roundtrip_dae','')).resolve() == check.resolve()
                            and all(Path(entry.get(k,'')).is_file() and hashlib.sha256(Path(entry[k]).read_bytes()).hexdigest() == entry.get(k+'_sha256') for k in ('dae','gr2','roundtrip_dae'))):
                        row['variants'].append(entry)
                        print('  verified cached export',flush=True)
                        continue
                sculpt_rows = {}
                def transform(lod_mesh, lod):
                    positions, stats = sculpt(lod_mesh, profile, percent, family.get('frame'),family_id=family['id'],body_lod=lod)
                    sculpt_rows[lod] = (positions,stats)
                    return positions
                if args.dry_run:
                    for lod in lods or [{'lod':0,'geometry_id':snapshot['geometry_id']}]:
                        record = {'family_id':family['id'],'base_body_id':raw['id'],'breast_percent':percent,'lod':lod['lod']}
                        try:
                            transform(ColladaMesh.load(source,geometry_id=lod['geometry_id']),lod['lod'])
                            audit.append({**record,'status':'passed'})
                        except ValueError as error:
                            if not args.audit_all:
                                raise
                            audit.append({**record,'status':'rejected','reason':str(error),
                                          'details':getattr(error,'report',None)})
                    continue
                if lods:
                    bake_lods(source,dae,transform,expected_lods=5)
                else:
                    positions,stats = sculpt(mesh,profile,percent,None,family_id=family['id'])
                    sculpt_rows[0] = (positions,stats)
                    authored = ColladaMesh.load(source)
                    authored.set_positions(positions,recalculate_normals=True)
                    for key in ('topology_id','controller_sha256','uv_sha256','material_sha256'):
                        if authored.snapshot()[key] != snapshot[key]:
                            raise ValueError('Expansion changed protected source data: '+key)
                    authored.save(dae)
                positions,stats = sculpt_rows[0]
                stats = dict(stats)
                if lods:
                    stats['lods'] = {str(k):v for k,(_,v) in sculpt_rows.items()}
                # Bind the proof to coordinates as actually serialized in the
                # authoring DAE, before the separate GR2 round-trip checks.
                for lod in lods or [{'lod':0,'geometry_id':snapshot['geometry_id']}]:
                    reference = ColladaMesh.load(source,geometry_id=lod['geometry_id'])
                    authored = ColladaMesh.load(dae,geometry_id=lod['geometry_id'])
                    proof = surface_checker(reference).validate(authored.positions)
                    validate_geometry_proof(reference,authored,proof)
                    target_stats = stats if lod['lod']==0 else stats['lods'][str(lod['lod'])]
                    target_stats['surface_intersections'] = proof
                    if lods and lod['lod']==0:
                        stats['lods']['0']['surface_intersections'] = proof
                convert(args.divine,dae,gr2,'dae','gr2')
                convert(args.divine,gr2,check,'gr2','dae')
                if lods:
                    verification = validate_lod_roundtrip(source,dae,check,expected_lods=5)
                    verification.update({k:'passed' for k in ('topology','skin_arrays','corner_uvs','bind_shape')})
                    verification['smooth_seams'] = {'status':'passed','all_lods':True}
                else:
                    verification = validate_roundtrip(source,check,positions,mesh.triangles)
                verification['surface_intersections'] = 'passed'
                entry = {'id':identifier,'label':raw['label']+(f' +{percent}' if percent else ''),
                         'collection_id':config['collection_id'],'base_body_id':raw['id'],'breast_percent':percent,
                         'base_profile_sha256':hashlib.sha256(json.dumps(profile,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest(),
                         'skin_style':raw['skin_style'],'config_sha256':config_hash,
                         'dae':str(dae),'gr2':str(gr2),'geometry_id':snapshot['geometry_id'],
                         'roundtrip_dae':str(check),'roundtrip_dae_sha256':hashlib.sha256(check.read_bytes()).hexdigest(),
                         'mesh_name':snapshot['geometry_id'].removesuffix('-geom'),'model_name':'Dummy_Root',
                         'sculpt':stats,'verification':verification,'measurements':measurements(positions,family.get('frame')),
                         'dae_sha256':hashlib.sha256(dae.read_bytes()).hexdigest(),
                         'gr2_sha256':hashlib.sha256(gr2.read_bytes()).hexdigest()}
                if lods:
                    entry['lods'] = [{k:lod[k] for k in ('geometry_id','mesh_name','lod')} for lod in lods]
                atomic_json(checkpoint,entry)
                row['variants'].append(entry)
                manifest['completed_variant_count'] = sum(len(f['variants']) for f in manifest['families'])
                atomic_json(args.output/'body-build.progress.json',manifest)
    if not args.dry_run:
        completed = sum(len(f['variants']) for f in manifest['families'])
        if completed != request['expected_variants']:
            raise ValueError('Expansion build did not finish its exact requested grid')
        manifest['completed_variant_count'] = completed
        manifest['build_status'] = 'complete'
        atomic_json(args.output/'body-build.json',manifest)
    else:
        rejected = sum(row['status']=='rejected' for row in audit)
        atomic_json(args.output/'geometry-audit.json',{'schema_version':1,'requested_grid':request,
            'geometry_checks':len(audit),'rejected_checks':rejected,'checks':audit})
        if rejected:
            raise ValueError(f'{rejected} geometry checks rejected; see {args.output / "geometry-audit.json"}')
    print('All requested expansion combinations passed.',flush=True)


if __name__ == '__main__':
    main()
