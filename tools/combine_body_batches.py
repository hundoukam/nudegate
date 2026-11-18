"""Publish a complete expansion grid from independently completed family batches."""
import argparse
import hashlib
import json
from pathlib import Path

from build import merge_body_manifests
from build_expansion import ROOT, FAMILIES, atomic_json, pipeline_fingerprint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifests',nargs='+',type=Path,required=True)
    parser.add_argument('--config',type=Path,default=ROOT/'config/expansion_bodies.json')
    parser.add_argument('--output',type=Path,default=ROOT/'build/expansion/body-build.json')
    args = parser.parse_args()
    if args.output.resolve() in {path.resolve() for path in args.manifests}:
        raise ValueError('Combined output must be separate from every batch input')
    documents = [json.loads(path.read_text()) for path in args.manifests]
    config = json.loads(args.config.read_text())
    if any(document.get('collection_id')!=config['collection_id'] for document in documents):
        raise ValueError('Batch collection IDs do not match the requested collection')
    result = merge_body_manifests(documents)
    result['collection_id'] = config['collection_id']
    result['physics'],result['in_game'] = 'not included','not tested'
    grids = result['requested_grids']
    for key in ('config_sha256','pipeline_sha256','converter_sha256'):
        values = {grid.get(key) for grid in grids}
        if len(values)!=1 or None in values:
            raise ValueError('Batch provenance differs: '+key)
    if grids[0]['pipeline_sha256'] != pipeline_fingerprint()[0]:
        raise ValueError('Authoring or validation code changed after the batches were built')
    if grids[0]['config_sha256'] != hashlib.sha256(args.config.read_bytes()).hexdigest():
        raise ValueError('Expansion configuration changed after the batches were authored')
    if {family['id'] for family in result['families']} != {family['id'] for family in FAMILIES}:
        raise ValueError('The combined expansion must contain all reviewed families')
    expected = {(profile['id'],percent) for profile in config['profiles'] for percent in config['breast_percentages']}
    for family in result['families']:
        if {(variant['base_body_id'],variant['breast_percent']) for variant in family['variants']} != expected:
            raise ValueError('The combined expansion must contain the full configured grid for '+family['id'])
        for variant in family['variants']:
            for kind in ('dae','gr2','roundtrip_dae'):
                if hashlib.sha256(Path(variant[kind]).read_bytes()).hexdigest()!=variant[kind+'_sha256']:
                    raise ValueError('A batch artifact changed after validation')
    result['batch_inputs'] = [{'path':str(path.resolve()),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
                              for path in args.manifests]
    atomic_json(args.output,result)
    print(f"Published {result['completed_variant_count']} verified expansion variants to {args.output}")


if __name__ == '__main__':
    main()
