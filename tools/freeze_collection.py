"""Copy an approved body collection into a verified, non-overwriting archive."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def write_once(path,encoded):
    path = Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if path.read_text(encoding='utf-8') != encoded:
            raise ValueError('Refusing to replace an existing archive record: '+str(path))
        return
    with path.open('x',encoding='utf-8',newline='') as handle:
        handle.write(encoded)


def bind_manifest(output,expected_sha256):
    """Add one new hash sidecar without rewriting any existing archive file."""
    output = Path(output).resolve()
    if not isinstance(expected_sha256,str) or not re.fullmatch(r'[0-9a-f]{64}',expected_sha256):
        raise ValueError('Expected an explicitly approved lowercase SHA-256')
    manifest = output/'body-build.json'
    if hashlib.sha256(manifest.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError('Frozen manifest differs from its approved external fingerprint')
    write_once(output/'manifest.sha256',expected_sha256+'  body-build.json\n')
    return expected_sha256


def checked_copy(source, destination, expected=None):
    source, destination = Path(source), Path(destination)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if expected and digest != expected:
        raise ValueError(f'Approved artifact changed before freezing: {source}')
    if destination.exists():
        if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
            raise ValueError(f'Refusing to replace an archived artifact: {destination}')
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
        raise ValueError('Archived copy failed integrity verification')
    return digest


def freeze(manifest_path, output):
    manifest_path, output = Path(manifest_path).resolve(), Path(output).resolve()
    data = json.loads(manifest_path.read_text())
    original_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    hashes = {}
    for family in data['families']:
        if Path(family['id']).name != family['id']:
            raise ValueError('Invalid family archive path')
        source = Path(family['source'])
        destination = output / 'sources' / family['id'] / source.name
        hashes[destination.relative_to(output).as_posix()] = checked_copy(source, destination, family['source_sha256'])
        family['source'] = str(destination)
        for variant in family['variants']:
            if Path(variant['id']).name != variant['id']:
                raise ValueError('Invalid variant archive path')
            for kind in ('dae','gr2'):
                source = Path(variant[kind])
                destination = output / 'bodies' / family['id'] / variant['id'] / source.name
                hashes[destination.relative_to(output).as_posix()] = checked_copy(source, destination, variant[kind + '_sha256'])
                variant[kind] = str(destination)
            variant['collection_id'] = 'original-v0.2'
            variant['base_body_id'] = variant['id']
            variant['breast_percent'] = 0
    for relative in ('config/body_studies.json','config/body_sources.json','config/adults.json',
                     'dist/Nudegate-0.2.0-plush-tav-study.pak','dist/body-study-report.json',
                     'build/plush/tiefling-soft-comparison.png','build/plush/human-soft-comparison.png'):
        source = ROOT / relative
        if source.is_file():
            destination = output / 'snapshot' / relative
            hashes[destination.relative_to(output).as_posix()] = checked_copy(source, destination)
    commit = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    data['collection_id'] = 'original-v0.2'
    data['approved_source_commit'] = commit
    data['original_manifest_sha256'] = original_sha
    encoded = json.dumps(data,indent=2)+'\n'
    path = output / 'body-build.json'
    write_once(path,encoded)
    ledger = {'collection_id':'original-v0.2','source_commit':commit,'original_manifest_sha256':original_sha,
              'body_files':sum(len(f['variants']) for f in data['families']),'sha256':hashes}
    write_once(output/'integrity.json',json.dumps(ledger,indent=2)+'\n')
    bind_manifest(output,hashlib.sha256(path.read_bytes()).hexdigest())
    return ledger


def verify(output):
    output = output.resolve()
    sidecar = output/'manifest.sha256'
    if not sidecar.is_file():
        raise ValueError('Frozen manifest requires a write-once manifest.sha256 bound to its approved external hash')
    fields = sidecar.read_text(encoding='utf-8').split()
    if (len(fields)!=2 or fields[1]!='body-build.json' or not re.fullmatch(r'[0-9a-f]{64}',fields[0])
            or hashlib.sha256((output/'body-build.json').read_bytes()).hexdigest()!=fields[0]):
        raise ValueError('Frozen collection manifest fingerprint changed')
    ledger = json.loads((output/'integrity.json').read_text())
    for name,expected in ledger['sha256'].items():
        path = (output/name).resolve()
        if not path.is_relative_to(output) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Frozen collection integrity check failed: '+name)
    manifest = json.loads((output/'body-build.json').read_text())
    variants = [v for f in manifest['families'] for v in f['variants']]
    if len(variants) != ledger['body_files']:
        raise ValueError('Frozen collection body count changed')
    for variant in variants:
        for kind in ('dae','gr2'):
            path = Path(variant[kind]).resolve()
            if not path.is_relative_to(output) or ledger['sha256'].get(path.relative_to(output).as_posix()) != variant[kind+'_sha256']:
                raise ValueError('Frozen manifest does not match its file ledger')
    return ledger


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,default=ROOT/'build/plush-final/body-build.json')
    parser.add_argument('--output',type=Path,default=ROOT/'build/collections/original-v0.2')
    parser.add_argument('--verify',action='store_true',help='Check the frozen collection without rebuilding it')
    parser.add_argument('--bind-manifest-sha256',help='Add a write-once sidecar from an independently approved frozen manifest hash')
    args=parser.parse_args()
    if args.bind_manifest_sha256:
        bind_manifest(args.output,args.bind_manifest_sha256)
        result=verify(args.output)
    else:
        result=verify(args.output) if args.verify else freeze(args.manifest,args.output)
    print(json.dumps({'collection_id':result['collection_id'],'body_files':result['body_files'],
                      'verified_files':len(result['sha256']),'output':str(args.output.resolve())},indent=2))
