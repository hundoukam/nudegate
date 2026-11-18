"""Create source-bound authored-pole query seeds for fit_native_donor_proxy.py."""
import argparse,hashlib,json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from nudegate.donor_body import load_dae,BODY_NAME
from nudegate.native_proxy_fit import anterior_pole_seeds
from fit_native_donor_proxy import NATIVE_SHA256

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target-pose',type=Path,required=True)
    parser.add_argument('--pose-audit',type=Path,required=True)
    parser.add_argument('--native',type=Path,default=ROOT/'build/physics-probe/matched-v1/model-roundtrip/human_normal/source.dae')
    parser.add_argument('--expected-native-sha256',default=NATIVE_SHA256)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    output=args.output.resolve();provenance=output.with_suffix('.json')
    if output.exists() or provenance.exists():raise ValueError('Refusing to overwrite authored seeds')
    paths={'target_pose':args.target_pose.resolve(),'pose_audit':args.pose_audit.resolve(),
        'native':args.native.resolve(),'tool':Path(__file__).resolve(),
        'implementation':ROOT/'src/nudegate/native_proxy_fit.py'}
    hashes={key:sha(path) for key,path in paths.items()}
    if hashes['native']!=args.expected_native_sha256:raise ValueError('Native source pin differs')
    audit=json.loads(paths['pose_audit'].read_text())
    if audit['proof']['safe'] is not True or audit['posed_npz_sha256']!=hashes['target_pose']:
        raise ValueError('Projection seeds require their own passed pose proof')
    with np.load(paths['target_pose'],allow_pickle=False) as archive:pose=dict(archive)
    native=load_dae(paths['native'],BODY_NAME+'_Cloth_Physics-geom')
    seeds,report=anterior_pole_seeds(native['positions'],pose['positions'],
        pose['source_breast_influence_left'],pose['source_breast_influence_right'])
    for key,path in paths.items():
        if sha(path)!=hashes[key]:raise ValueError('Input changed during seed generation: '+key)
    output.parent.mkdir(parents=True,exist_ok=True);np.savez_compressed(output,positions=seeds)
    report.update(input_paths={key:str(path) for key,path in paths.items()},input_sha256=hashes,
        output=str(output),output_sha256=sha(output),input_hashes_stable=True)
    provenance.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'output':str(output),'maximum_seed_offset_m':report['maximum_seed_offset_m']},indent=2))

if __name__=='__main__':main()
