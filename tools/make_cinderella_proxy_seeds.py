"""Create source-specific search seeds for the shared native proxy fitter."""
from pathlib import Path
import argparse
import json
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from nudegate.cinderella_body import proxy_projection_seeds
from nudegate.donor_body import BODY_NAME, load_dae, sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target-pose', type=Path, required=True)
    parser.add_argument('--pose-audit', type=Path, required=True)
    parser.add_argument('--native', type=Path, default=ROOT / 'build/physics-probe/matched-v1/model-roundtrip/human_normal/source.dae')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.suffix.lower() != '.npz':
        raise ValueError('Cinderella search seeds require an explicit .npz output path')
    if output.exists() or output.with_suffix('.json').exists():
        raise ValueError('Refusing to overwrite existing Cinderella search seeds')
    paths = {'target_pose': args.target_pose.resolve(), 'pose_audit': args.pose_audit.resolve(),
             'native': args.native.resolve(), 'profile': ROOT / 'src/nudegate/cinderella_body.py'}
    hashes = {key: sha(path) for key, path in paths.items()}
    audit = json.loads(paths['pose_audit'].read_text())
    if audit['proof']['safe'] is not True or audit['posed_npz_sha256'] != hashes['target_pose']:
        raise ValueError('Cinderella search seeds require a passed matching pose audit')
    with np.load(paths['target_pose'], allow_pickle=False) as data:
        posed = {key: data[key] for key in data.files}
    proxy = load_dae(paths['native'], BODY_NAME + '_Cloth_Physics-geom')
    seeds, report = proxy_projection_seeds(proxy['positions'], posed)
    for key, path in paths.items():
        if sha(path) != hashes[key]:
            raise ValueError('Cinderella seed input changed: ' + key)
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output, positions=seeds)
    report.update(input_paths={key: str(path) for key, path in paths.items()}, input_sha256=hashes,
                  output=str(output), output_sha256=sha(output), accepted_geometry_or_physics=False)
    output.with_suffix('.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'output': str(output), 'sha256': report['output_sha256'], 'width_ratio': report['width_ratio']}))


if __name__ == '__main__':
    main()
