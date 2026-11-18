"""Make reproducible comparison sheets from verified local mesh manifests."""
import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,default=ROOT/'build/expansion/body-build.json')
    parser.add_argument('--original',type=Path,default=ROOT/'build/collections/original-v0.2/body-build.json')
    parser.add_argument('--output',type=Path,default=ROOT/'build/expansion/previews')
    parser.add_argument('--blender',type=Path,default=Path('C:/Program Files/Blender Foundation/Blender 4.5/blender.exe'))
    parser.add_argument('--sheet',choices=['variety','frames','chest'],default='variety')
    parser.add_argument('--species',choices=['human','tiefling'],default='tiefling')
    args = parser.parse_args()
    families = {f['id']:f for f in json.loads(args.manifest.read_text())['families']}
    originals = {f['id']:f for f in json.loads(args.original.read_text())['families']}
    normal,strong = ('human_elf_f','human_elf_fs') if args.species == 'human' else ('tiefling_f','tiefling_fs')
    def variant(family,identifier,label=None,legacy=False):
        row = dict(next(v for v in (originals if legacy else families)[family]['variants'] if v['id']==identifier))
        if label:
            row['label'] = label
        return row
    if args.sheet == 'variety':
        rows = [variant(strong,'plush','Original plush / retained',True)]
        rows += [variant(strong,f'exp_{name}_b000') for name in ('curvy','chubby','pear','defined','fantasy')]
        title = f'{args.species.title()} / larger female frame / original + new base bodies'
    elif args.sheet == 'frames':
        rows = [variant(f,f'exp_{name}_b000',f'{label} / {name.title()}')
                for f,label in ((normal,'Smaller'),(strong,'Larger')) for name in ('curvy','chubby','pear')]
        title = f'{args.species.title()} / smaller and larger female frames'
    else:
        rows = [variant(f,f'exp_curvy_b{percent:03}',f'{label} / Curvy +{percent}')
                for f,label in ((normal,'Smaller'),(strong,'Larger')) for percent in (0,50,100)]
        title = f'{args.species.title()} / independent chest projection control'
    args.output.mkdir(parents=True,exist_ok=True)
    manifest = args.output/f'{args.species}-{args.sheet}.json'
    image = manifest.with_suffix('.png')
    manifest.write_text(json.dumps({'families':[{'id':'comparison','label':title,'variants':rows}]},indent=2)+'\n')
    subprocess.run([str(args.blender),'--background','--python',str(ROOT/'tools/render_bodies.py'),'--',
                    '--manifest',str(manifest.resolve()),'--output',str(image.resolve()),'--fit-width'],check=True)


if __name__ == '__main__':
    main()
