"""Read-only source-identity review of native cloth paint on an actual donor."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from nudegate.donor_body import sha


def load(stage):
    with np.load(stage/'posed_dense.npz') as d:source={k:d[k] for k in d.files}
    with np.load(stage/'body_prepared.npz') as d:prepared={k:d[k] for k in d.files}
    ids=prepared['source_vertex_ids'];valid=ids>=0;n=len(source['positions'])
    seen=np.zeros(n,int);np.add.at(seen,ids[valid],1)
    minimum=np.full((n,4),255,int);maximum=np.zeros((n,4),int)
    for c in range(4):
        np.minimum.at(minimum[:,c],ids[valid],prepared['colors_rgba8'][valid,c])
        np.maximum.at(maximum[:,c],ids[valid],prepared['colors_rgba8'][valid,c])
    return source,prepared,seen,minimum,maximum


def review(stage):
    source,prepared,seen,minimum,maximum=load(stage)
    rgba=prepared['colors_rgba8'];sid=prepared['source_vertex_ids'];r=rgba[:,0]
    support=(source['source_breast_influence_left']+source['source_breast_influence_right'])>0
    record={'stage':str(stage.resolve()),'posed_npz_sha256':sha(stage/'posed_dense.npz'),
        'prepared_npz_sha256':sha(stage/'body_prepared.npz'),
        'export_vertices':len(r),'Rpositive_export_vertices':int((r>0).sum()),
        'Rpositive_unique_source_vertices':int(((seen>0)&(maximum[:,0]>0)).sum()),
        'Rpositive_outside_author_pectoral_support_source_ids':np.flatnonzero((seen>0)&(maximum[:,0]>0)&~support).tolist(),
        'Bbytes_unique':np.unique(rgba[:,2]).tolist(),
        'Rbytes_histogram':{str(int(value)):int((r==value).sum())for value in np.unique(r)},
        'semantics':'Values are verified native byte paint. Author pectoral skin influence is a comparison field, not an obligation to paint every supported point.',
        'sides':{}}
    for side in ('left','right'):
        w=source['source_breast_influence_'+side];positive=w>0;retained=positive&(seen>0)
        # Microscopic cross-side skin tails are captured faithfully, but do
        # not define the opposite side's authored breast pole.
        sign=1 if side=='left' else -1
        ids=np.flatnonzero(retained&(w>.05)&(source['positions'][:,0]*sign>0))
        if not len(ids):raise ValueError('Missing same-side anatomical breast pole: '+side)
        tip=int(ids[np.argmin(source['positions'][ids,2])])
        rows=np.flatnonzero(sid==tip)
        stats={'author_positive_vertices':int(positive.sum()),'retained_positive_vertices':int(retained.sum()),
            'Rpositive_author_vertices':int((retained&(maximum[:,0]>0)).sum()),
            'mixed_static_dynamic_UV_copies':int((retained&(minimum[:,0]==0)&(maximum[:,0]>0)).sum()),
            'author_influence_mass_covered_by_any_R_fraction':float(w[retained&(maximum[:,0]>0)].sum()/w[retained].sum()),
            'tip_definition':'forwardmost same-lateral-side retained author-breast source vertex with normalized support >.05; BG3 forward -Z',
            'tip_source_id':tip,'tip_position_bg3':source['positions'][tip].tolist(),
            'tip_author_influence':float(w[tip]),'tip_RGBA8':rgba[rows].tolist(),'influence_tiers':[],'tip_caps':[]}
        for lo,hi in ((0,.1),(.1,.5),(.5,.8),(.8,1.01)):
            selected=retained&(w>lo)&(w<=hi);painted=selected&(maximum[:,0]>0)
            stats['influence_tiers'].append({'interval':[lo,hi],'source_vertices':int(selected.sum()),
                'Rpositive_vertices':int(painted.sum()),'Rzero_vertices':int((selected&(maximum[:,0]==0)).sum()),
                'Rrange':[int(minimum[selected,0].min()),int(maximum[selected,0].max())]if selected.any()else [],
                'Brange':[int(minimum[selected,2].min()),int(maximum[selected,2].max())]if selected.any()else []})
        for radius in (.01,.02,.03,.05):
            selected=retained&(np.linalg.norm(source['positions']-source['positions'][tip],axis=1)<=radius)
            stats['tip_caps'].append({'radius_m':radius,'source_vertices':int(selected.sum()),
                'Rzero_vertices':int((selected&(maximum[:,0]==0)).sum()),
                'Rrange':[int(minimum[selected,0].min()),int(maximum[selected,0].max())]})
        record['sides'][side]=stats
    return record


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage',type=Path,required=True)
    parser.add_argument('--before',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();record={'schema_version':1,'current':review(args.stage)}
    if args.before:
        record['before']=review(args.before)
        a,_,sa,mna,mxa=load(args.before);b,_,sb,mnb,mxb=load(args.stage)
        if not np.array_equal(a['positions'],b['positions']):raise ValueError('Paint comparison source geometry differs')
        retained=(sa>0)&(sb>0);changed=retained&np.any((mna!=mnb)|(mxa!=mxb),axis=1)
        new=retained&(mxa[:,0]==0)&(mxb[:,0]>0);removed=retained&(mxa[:,0]>0)&(mxb[:,0]==0)
        record['comparison']={'source_positions_bit_equal':True,'changed_RGBA_source_vertices':int(changed.sum()),
            'new_Rpositive_source_vertices':np.flatnonzero(new).tolist(),
            'removed_Rpositive_source_vertices':np.flatnonzero(removed).tolist(),
            'changes':[{'source_vertex_id':int(i),'position':b['positions'][i].tolist(),
                'old_min_RGBA':mna[i].tolist(),'old_max_RGBA':mxa[i].tolist(),
                'new_min_RGBA':mnb[i].tolist(),'new_max_RGBA':mxb[i].tolist(),
                'author_left_influence':float(b['source_breast_influence_left'][i]),
                'author_right_influence':float(b['source_breast_influence_right'][i])}
                for i in np.flatnonzero(changed)]}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(record,indent=2))
    print(json.dumps({'report':str(args.output.resolve()),'Rpositive':record['current']['Rpositive_export_vertices'],
        'side_summary':{s:{k:v for k,v in d.items()if k not in ('tip_caps','influence_tiers')}
            for s,d in record['current']['sides'].items()}},indent=2))


if __name__=='__main__':main()
