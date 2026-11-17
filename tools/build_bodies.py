"""Bake reviewed local BCB family shape studies and round-trip GR2 exports."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from nudegate.body_shapes import author_masks, bake_shape, surface_quality  # noqa: E402
from nudegate.collada import ColladaMesh, validate_smooth_seams  # noqa: E402

FAMILIES = (
    {"id": "human_elf_f", "label": "Human / elf, normal female", "file": "HUM_F_NKD_HighPolyTest_KEL.dae",
     "vertices": 9424, "triangles": 18828,
     "original_visual_ids": ["db6e5918-8514-4dcc-8363-e8fd3c50cce5", "9e43f0e4-d063-d85c-87b4-470d569645db"]},
    {"id": "gith_f", "label": "Githyanki, normal female", "file": "gith.dae",
     "vertices": 8044, "triangles": 16068,
     "original_visual_ids": ["b7bfa2d3-4dad-d8a3-8639-9e3dddb97a00"]},
    {"id": "tiefling_f", "label": "Tiefling, normal female", "file": "tiefling.dae",
     "vertices": 7768, "triangles": 15502,
     "original_visual_ids": ["820ddd41-7946-f026-099f-7034983d50d2"]},
)


def convert(divine: Path, source: Path, output: Path, input_format: str, output_format: str) -> None:
    cmd = [str(divine), "--loglevel", "all", "-g", "bg3", "-a", "convert-model",
           "-s", str(source), "-d", str(output), "-i", input_format, "-o", output_format]
    if output_format == "gr2":
        cmd += ["-e", "recalculate-tangents"]
    result = subprocess.run(cmd, text=True, capture_output=True)
    if result.returncode or not output.is_file():
        raise RuntimeError(f"Mesh conversion failed: {source.name}\n{result.stdout}\n{result.stderr}")


def skin_arrays(path: Path) -> dict:
    root = ET.parse(path).getroot()
    ns = {"c": root.tag.split("}")[0][1:]}
    controllers = root.findall('./c:library_controllers/c:controller', ns)
    out = {}
    for controller in controllers:
        skin = controller.find('c:skin', ns)
        if skin is None:
            raise ValueError("Expected skinned source geometry")
        sources = {n.get('id'): n for n in skin.findall('c:source', ns)}
        for item in skin.findall('c:joints/c:input', ns):
            source = sources[item.get('source').lstrip('#')]
            array = next((n for n in source if n.tag.endswith('array')), None)
            text = array.text.split()
            semantic = item.get('semantic')
            out[controller.get('id') + ':' + semantic] = text if semantic == 'JOINT' else list(map(float, text))
        weights = skin.find('c:vertex_weights', ns)
        bind_shape = skin.find('c:bind_shape_matrix', ns)
        out[controller.get('id') + ':BIND_SHAPE_MATRIX'] = (list(map(float, bind_shape.text.split()))
            if bind_shape is not None else [1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1])
        for key in ('vcount', 'v'):
            out[controller.get('id') + ':' + key] = list(map(int, weights.find('c:' + key, ns).text.split()))
        weight_input = next(n for n in weights.findall('c:input', ns) if n.get('semantic') == 'WEIGHT')
        array = sources[weight_input.get('source').lstrip('#')].find('c:float_array', ns)
        out[controller.get('id') + ':WEIGHT'] = list(map(float, array.text.split()))
    return out


def corner_uvs(path: Path) -> list:
    root = ET.parse(path).getroot()
    ns = {'c': root.tag.split('}')[0][1:]}
    geometry = root.find('./c:library_geometries/c:geometry/c:mesh', ns)
    sources = {n.get('id'): n for n in geometry.findall('c:source', ns)}
    result = []
    for primitive in geometry.findall('c:triangles', ns):
        inputs = primitive.findall('c:input', ns)
        stride = max(int(n.get('offset', '0')) for n in inputs) + 1
        indices = list(map(int, primitive.find('c:p', ns).text.split()))
        for item in sorted((n for n in inputs if n.get('semantic') == 'TEXCOORD'), key=lambda n: n.get('set','0')):
            source = sources[item.get('source').lstrip('#')]
            accessor = source.find('c:technique_common/c:accessor', ns)
            values = list(map(float, source.find('c:float_array', ns).text.split()))
            width, start = int(accessor.get('stride', '1')), int(accessor.get('offset', '0'))
            offset = int(item.get('offset', '0'))
            coordinates = [tuple(values[start + indices[i+offset]*width:start + indices[i+offset]*width + 2])
                           for i in range(0, len(indices), stride)]
            result.append((item.get('set','0'), coordinates))
    if not result:
        raise ValueError('Reviewed body source has no explicit corner UVs')
    return result


def validate_roundtrip(source: Path, exported: Path, expected_positions: list, triangles: list) -> dict:
    mesh = ColladaMesh.load(exported)
    shading = validate_smooth_seams(ColladaMesh.load(source), mesh)
    if mesh.triangles != triangles or len(mesh.positions) != len(expected_positions):
        raise ValueError("GR2 export changed indexed source topology")
    delta = max(math.dist(a, b) for a, b in zip(mesh.positions, expected_positions))
    if delta > 3e-6:
        raise ValueError(f"GR2 position drift exceeds tolerance: {delta}")
    before, after = skin_arrays(source), skin_arrays(exported)
    uv_before, uv_after = corner_uvs(source), corner_uvs(exported)
    if len(uv_before) != len(uv_after):
        raise ValueError('GR2 export changed UV layer or primitive count')
    max_uv_drift = 0
    for (layer, original_uvs), (new_layer, new_uvs) in zip(uv_before, uv_after):
        if layer != new_layer or len(original_uvs) != len(new_uvs):
            raise ValueError('GR2 export changed indexed UV layout')
        max_uv_drift = max(max_uv_drift, max((abs(a-b) for old, new in zip(original_uvs, new_uvs)
                                             for a,b in zip(old,new)), default=0))
    if max_uv_drift > 1e-6:
        raise ValueError('GR2 export altered corner UV coordinates')
    if before.keys() != after.keys():
        raise ValueError("GR2 export changed controller structure")
    max_bind_drift = 0
    for key in before:
        if len(before[key]) != len(after[key]):
            raise ValueError(f"GR2 export changed skin array size: {key}")
        if key.endswith((':JOINT', ':v', ':vcount')):
            if before[key] != after[key]:
                raise ValueError(f"GR2 export changed joint order or influence indices: {key}")
        else:
            error = max((abs(a - b) for a, b in zip(before[key], after[key])), default=0)
            if error > (5e-5 if key.endswith((':INV_BIND_MATRIX', ':BIND_SHAPE_MATRIX')) else 1e-6):
                raise ValueError(f"GR2 export changed skin weights or bind matrices: {key} ({error})")
            if key.endswith(':INV_BIND_MATRIX'):
                max_bind_drift = max(max_bind_drift, error)
    return {"topology": "passed", "skin_arrays": "passed", "max_position_drift": delta,
            "max_inverse_bind_drift": max_bind_drift, "smooth_seams": shading,
            "corner_uvs": 'passed', 'max_corner_uv_drift': max_uv_drift, 'bind_shape': 'passed'}


def measurements(positions: list) -> dict:
    chest = [p for p in positions if 1.27 < p[1] < 1.43 and .025 < abs(p[0]) < .21]
    hips = [p for p in positions if .86 < p[1] < 1.04 and abs(p[0]) < .28]
    return {"chest_front_z": min(p[2] for p in chest),
            "hip_width": max(p[0] for p in hips) - min(p[0] for p in hips)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=Path, default=Path.home() / '.cache/nudegate/bcb-analysis')
    parser.add_argument('--divine', type=Path, default=Path.home() / '.cache/nudegate/lslib/Packed/Tools/Divine.exe')
    parser.add_argument('--profiles', type=Path, default=ROOT / 'config/body_studies.json')
    parser.add_argument('--source-catalog', type=Path, default=ROOT / 'config/body_sources.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'build/bodies')
    parser.add_argument('--families', nargs='+', choices=[f['id'] for f in FAMILIES])
    args = parser.parse_args()
    try:
        profiles = json.loads(args.profiles.read_text())['profiles']
        source_catalog = json.loads(args.source_catalog.read_text())['families']
        if len({p['id'] for p in profiles}) != len(profiles):
            raise ValueError('Duplicate study IDs')
        if any(not re.fullmatch(r'[a-z][a-z0-9_]{0,40}', p['id']) for p in profiles):
            raise ValueError('Study IDs must be simple lowercase file-safe names')
        args.output.mkdir(parents=True, exist_ok=True)
        manifest = {"schema_version": 1, "source_kind": "local BCB 3.17 archive",
                    "physics": "not included in these geometry studies", "in_game": "not tested", "families": []}
        for family in FAMILIES:
            if args.families and family['id'] not in args.families:
                continue
            source = args.sources / family['file']
            mesh = ColladaMesh.load(source)
            snapshot = mesh.snapshot()
            if snapshot['vertex_count'] != family['vertices'] or snapshot['triangle_count'] != family['triangles']:
                raise ValueError(f"Source topology does not match reviewed family: {family['id']}")
            for key in ('topology_id', 'position_sha256'):
                if snapshot[key] != source_catalog[family['id']][key]:
                    raise ValueError(f"Source {key} does not match reviewed family: {family['id']}")
            masks, mask_report = author_masks(mesh.positions, mesh.triangles, mesh.topology_id)
            row = {**family, 'source': str(source.resolve()), 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                   'source_snapshot': snapshot, 'masks': mask_report, 'variants': []}
            destination = args.output / family['id']
            destination.mkdir(exist_ok=True)
            for profile in profiles:
                print(f"Baking {family['id']} / {profile['id']}", flush=True)
                new_positions, sculpt = bake_shape(masks, profile)
                sculpt['surface_quality'] = surface_quality(masks['positions'], new_positions, mesh.triangles)
                variant = ColladaMesh.load(source)
                variant.set_positions(new_positions, recalculate_normals=sculpt['moved_vertices'] > 0)
                after = variant.snapshot()
                for key in ('topology_id', 'controller_sha256', 'uv_sha256', 'material_sha256'):
                    if snapshot[key] != after[key]:
                        raise ValueError(f"Sculpt altered protected data: {key}")
                dae = destination / (family['id'] + '_' + profile['id'] + '.dae')
                gr2 = dae.with_suffix('.GR2')
                check = dae.with_suffix('.roundtrip.dae')
                variant.save(dae)
                convert(args.divine, dae, gr2, 'dae', 'gr2')
                convert(args.divine, gr2, check, 'gr2', 'dae')
                verification = validate_roundtrip(source, check, new_positions, variant.triangles)
                row['variants'].append({'id': profile['id'], 'label': profile['label'],
                    'dae': str(dae.resolve()), 'gr2': str(gr2.resolve()), 'mesh_name': snapshot['geometry_id'].removesuffix('-geom'),
                    'model_name': 'Dummy_Root', 'sculpt': sculpt, 'verification': verification,
                    'measurements': measurements(new_positions), 'gr2_sha256': hashlib.sha256(gr2.read_bytes()).hexdigest(),
                    'dae_sha256': hashlib.sha256(dae.read_bytes()).hexdigest()})
            manifest['families'].append(row)
            target = args.output / 'body-build.json'
            tmp = target.with_suffix('.tmp')
            tmp.write_text(json.dumps(manifest, indent=2) + '\n')
            tmp.replace(target)
        print(f"Wrote {args.output / 'body-build.json'}", flush=True)
        return 0
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print(f"Body build stopped: {error}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
