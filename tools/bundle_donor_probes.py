"""Collect hash-checked offline donor probes and an actual-export review.

Creates local review artifacts only. Nothing is installed or activated.
"""
from __future__ import annotations
import argparse,hashlib,json,zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
STATES=(
    ('juno_b','donor_juno_b','juno-b-coherent-cc-probe','Juno B / authored medium'),
    ('mercy_c','donor_mercy_c','mercy-cc-probe','Mercy C / authored size limit'),
    ('cinderella_a','donor_cinderella_a','cinderella-cc-probe','Cinderella A / original sculpt'),
    ('jubilee_b','donor_jubilee_b','jubilee-cc-probe','Jubilee B / authored medium'),
    ('kiriko_2_0_c','donor_kiriko_c','kiriko-cc-probe','Kiriko 2.0 C / authored large'),
    ('juno_e','donor_juno_e','juno-e-cc-probe','Juno E / authored Chubby 100%'),
)
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()

README='''Nudegate - selected donor offline probes

Six separate experimental new-Tav body packages, with each author's selected
body shape and its own fitted native breast-cloth proxy and mapping.

USE ONE PAK AT A TIME when testing later. These probes share the same module
folder and five compatible adult female normal-body creation presets. They are
not a combined NPC variety release. Existing saves are not supported by these
creation-preset probes. No installation or load-order changes are performed by
this bundle tool.

The preview uses actual serialized game geometry. It is a static shape review,
not an in-game screenshot or a demonstration of simulated motion. Skin materials,
heads/anatomy attachments, animation/hand props, distance behavior and performance
still require game testing. Each body currently has one authored render LOD.
Kiriko has a separate native limb-proportion fit; source originals remain intact.
Some distal hand/foot and other source-proportion offsets remain documented in
the per-body reports. Native solver settings are retained; new gravity/squeeze
controls and additional +100/+200 donor growth sliders are not implemented.

Cinderella A retains the original sculpt, including its authored compression
creases. A separate uncompressed three-key study exists in the authoring folder;
it does not replace A in this bundle.

Original Blender files, selected source captures and the earlier smaller-body
collections are preserved. Generated model assets remain outside the source repo.

Checksums and exact model/proof references are in package-manifest.json.
The geometry index compares each actual model to its own original-state Float32
source baseline. Existing authored source contacts are reported, not hidden.
No new contact exceptions or combined state-specific allowlists are used.
'''


def write_immutable(path,data):
    if path.exists():
        if path.read_bytes()!=data:raise ValueError('Review artifact exists with different contents: '+str(path))
    else:path.write_bytes(data)


def collect(index_path):
    index=json.loads(index_path.read_text());rows=index['states']
    if index.get('all_six_passed') is not True or len(rows)!=6:
        raise ValueError('Requires the complete independently accepted six-state index')
    states={row['id']:row for row in rows}
    packages=[];render=[]
    for identifier,profile,folder,label in STATES:
        state=states[identifier];model=Path(state['model'])
        if (state.get('passed_offline_serialized_geometry') is not True
                or any(state.get(key)!=0 for key in ('introduced_body_pairs','body_bridge_pairs',
                    'body_collapsed_faces','proxy_absolute_intersections','proxy_collapsed_faces',
                    'bridge_winding_conflict_edges'))
                or sha(model)!=state['model_sha256']
                or sha(state['surface_proof'])!=state['surface_proof_sha256']
                or sha(state['proxy_proof'])!=state['proxy_proof_sha256']):
            raise ValueError('Accepted model/proof binding failed: '+identifier)
        package_dir=ROOT/'build/donors'/folder;report_path=package_dir/'probe-report.json'
        report=json.loads(report_path.read_text())
        surface=json.loads(Path(state['surface_proof']).read_text())
        proxy=json.loads(Path(state['proxy_proof']).read_text())
        if any(proof.get('passed') is not True
                or proof.get('input_hashes_stable') is not True
                or proof.get('actual_model_sha256')!=state['model_sha256']
                for proof in (surface,proxy)):
            raise ValueError('Actual model is not bound to passing proofs: '+identifier)
        export_path=Path(report['export_report']['path'])
        if (Path(report['surface_audit']['path']).resolve()!=Path(state['surface_proof']).resolve()
                or report['surface_audit']['sha256']!=state['surface_proof_sha256']
                or sha(export_path)!=report['export_report']['sha256']):
            raise ValueError('Package proof/export binding failed: '+identifier)
        pak=package_dir/f'Nudegate-{profile}-creation-probe.pak'
        if (Path(report['package']).resolve()!=pak.resolve() or report['profile']!=profile
                or sha(pak)!=report['package_sha256'] or state['model_sha256'] not in report['files'].values()
                or report['validation']['creation_uuid_isolation']!={'private_roots':5,'private_visuals':5,
                    'selected_generic_presets':5,'original_root_overrides':0}
                or report['validation']['npc_overrides']!='none'):
            raise ValueError('Private package integrity/scope failed: '+identifier)
        packages.append({'id':identifier,'label':label,'profile':profile,'package':str(pak.resolve()),
            'package_sha256':report['package_sha256'],'package_bytes':pak.stat().st_size,
            'report':str(report_path.resolve()),'report_sha256':sha(report_path),
            'model_sha256':state['model_sha256'],'module_id':report['module_id'],
            'private_body_id':report['private_body_id'],'vertices':state['actual_body_vertices'],
            'triangles':state['actual_body_triangles'],'source_format_contacts':state['source_format_pair_count'],
            'introduced_contacts':0,'proxy_contacts':0,'bridge_winding_conflicts':0})
        for key in ('dump','prepared_npz'):
            if sha(surface['input_paths'][key])!=surface['input_sha256'][key]:
                raise ValueError('Audited render input changed: '+identifier+'/'+key)
        render.append({'label':label,'dump':surface['input_paths']['dump'],
            'export_report':str(export_path.resolve()),'prepared':surface['input_paths']['prepared_npz'],
            'package_report':str(report_path.resolve())})
    if len({p['module_id'] for p in packages})!=6 or len({p['private_body_id'] for p in packages})!=6:
        raise ValueError('Probe private IDs collided across donor profiles')
    return {'schema_version':1,'kind':'six separate offline new-Tav body probes',
        'scope':'five compatible adult female normal-body creation presets per package; one package at a time',
        'gameplay_tested':False,'installed':False,'npc_distribution_included':False,
        'native_breast_cloth_setup':True,'new_gravity_squeeze_or_growth_sliders':False,
        'validation_index':str(index_path.resolve()),'validation_index_sha256':sha(index_path),
        'packages':packages}, {'profiles':render}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index',type=Path,default=ROOT/'build/donors/accepted-six-donor-validation-index.json')
    parser.add_argument('--review',type=Path,default=ROOT/'build/donors/final-export-review')
    parser.add_argument('--zip',type=Path,help='After rendering actual-exports.png, write a new ZIP inside dist/')
    args=parser.parse_args();review=args.review.resolve()
    if not review.is_relative_to((ROOT/'build').resolve()):raise ValueError('Review must stay inside build/')
    manifest,render=collect(args.index)
    review.mkdir(parents=True,exist_ok=True)
    for name,data in [('package-manifest.json',manifest),('render-manifest.json',render)]:
        write_immutable(review/name,(json.dumps(data,indent=2)+'\n').encode())
    write_immutable(review/'README.txt',README.encode())
    if args.zip:
        output=args.zip.resolve()
        if not output.is_relative_to((ROOT/'dist').resolve()) or output.exists():
            raise ValueError('ZIP needs a new path inside dist/')
        image=review/'actual-exports.png';image_report=review/'actual-exports.json'
        rendered=json.loads(image_report.read_text())
        if (not image.is_file() or rendered.get('image_sha256')!=sha(image)
                or rendered['manifest_sha256']!=sha(review/'render-manifest.json')
                or [(p['model_sha256'],p['package_sha256']) for p in rendered['profiles']]
                    !=[(p['model_sha256'],p['package_sha256']) for p in manifest['packages']]):
            raise ValueError('Render the complete verified six-body review first')
        files={f'probes/{Path(p["package"]).name}':Path(p['package']) for p in manifest['packages']}
        files.update({name:review/name for name in ('package-manifest.json','README.txt','actual-exports.png','actual-exports.json')})
        files['accepted-six-donor-validation-index.json']=args.index
        output.parent.mkdir(parents=True,exist_ok=True);temp=output.with_suffix('.tmp')
        if temp.exists():raise ValueError('Temporary bundle already exists')
        with zipfile.ZipFile(temp,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
            for name,path in files.items():archive.write(path,name)
        with zipfile.ZipFile(temp) as archive:
            if archive.testzip() is not None or set(archive.namelist())!=set(files):
                raise ValueError('ZIP file-list/CRC verification failed')
            for name,path in files.items():
                if hashlib.sha256(archive.read(name)).hexdigest()!=sha(path):
                    raise ValueError('ZIP content mismatch: '+name)
        temp.rename(output)
        print(json.dumps({'bundle':str(output),'bytes':output.stat().st_size,'sha256':sha(output),'entries':len(files)}))
    print(json.dumps({'review':str(review),'profiles':len(manifest['packages']),
        'all_package_and_model_hashes_verified':True,'game_files_changed':False}))


if __name__=='__main__':main()
