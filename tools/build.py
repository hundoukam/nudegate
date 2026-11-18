"""Build from locally owned BG3 packages. Never changes the game or saves."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from uuid import UUID

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from nudegate.core import Database, attrs, compile as compile_patch  # noqa: E402
from nudegate.body_resources import create_body_resources  # noqa: E402
from nudegate.skin_materials import create_soft_materials  # noqa: E402
from nudegate.tav_presets import create_tav_presets  # noqa: E402
from nudegate.collada import ColladaMesh  # noqa: E402
from nudegate.geometry_proofs import validate_geometry_proof, validate_wall_calibration  # noqa: E402
from nudegate.lod_authoring import enumerate_lods  # noqa: E402

LEGACY_BODY_WEIGHTS = {'lean':15, 'athletic':10, 'balanced':15, 'full':15, 'soft':20, 'voluptuous':10, 'plush':15}
EXPANSION_BASE_WEIGHTS = {'curvy':20, 'chubby':20, 'pear':20, 'defined':20, 'fantasy':20}
BREAST_PERCENT_WEIGHTS = {0:40, 50:30, 100:20}
VARIANT_METADATA = ('collection_id', 'base_body_id', 'breast_percent', 'skin_style', 'base_profile_sha256')


def validate_expansion_surfaces(family,variant,source_cache):
    """Require a geometry-bound intersection proof for every authored LOD."""
    lods = variant.get('lods') or [{'lod':0,'geometry_id':variant['geometry_id']}]
    if family.get('lod_count'):
        if (not isinstance(lods,list) or any(not isinstance(row,dict)
                or type(row.get('lod')) is not int or not isinstance(row.get('geometry_id'),str)
                for row in lods)):
            raise ValueError('Expansion surface proofs require explicit native LOD identities')
        declared = [(row['lod'],row['geometry_id']) for row in lods]
        native_key = ('native_lod_identities',family['source'],family['lod_count'])
        if native_key not in source_cache:
            source_cache[native_key] = [(row['lod'],row['geometry_id']) for row in
                enumerate_lods(Path(family['source']),expected_lods=family['lod_count'])]
        if len(declared)!=len(set(declared)) or sorted(declared)!=source_cache[native_key]:
            raise ValueError('Expansion surface proofs must cover every actual native LOD geometry exactly once')
    main_calibration = variant['sculpt'].get('breast_size',{}).get('wall_calibration')
    base_variants = [entry for entry in family['variants'] if entry.get('base_body_id')==variant.get('base_body_id')
                     and entry.get('breast_percent')==0 and entry['id'].startswith('exp_')]
    if len(base_variants)!=1:
        raise ValueError('Expansion size variants require one authored zero-size base as their calibration anchor')
    anchor = base_variants[0]
    anchor_key = (anchor['dae'],anchor['geometry_id'])
    if anchor_key not in source_cache:
        source_cache[anchor_key] = ColladaMesh.load(Path(anchor['dae']),geometry_id=anchor['geometry_id'])
    for lod in lods:
        geometry_id = lod['geometry_id']
        key = (family['source'],geometry_id)
        if key not in source_cache:
            source_cache[key] = ColladaMesh.load(Path(family['source']),geometry_id=geometry_id)
        authored = ColladaMesh.load(Path(variant['dae']),geometry_id=geometry_id)
        stats = variant['sculpt'] if lod['lod']==0 else variant['sculpt'].get('lods',{}).get(str(lod['lod']),{})
        validate_geometry_proof(source_cache[key],authored,stats.get('surface_intersections'))
        if stats.get('breast_size',{}).get('wall_calibration')!=main_calibration:
            raise ValueError('Native body LODs must share the same reviewed LOD0 wall calibration')
        if lod['lod']==0:
            validate_wall_calibration(main_calibration,source_cache[key],source_cache[anchor_key],
                family_id=family['id'],profile_sha256=variant.get('base_profile_sha256'),frame=family.get('frame',[1,1,1]))


def validate_expansion_request(manifest: dict) -> list[dict]:
    expansion = {family['id']:[variant for variant in family['variants'] if variant['id'].startswith('exp_')]
                 for family in manifest.get('families', [])}
    expansion = {family:variants for family,variants in expansion.items() if variants}
    if not expansion:
        return []
    if manifest.get('build_status') != 'complete':
        raise ValueError('Expansion manifests must complete their exact requested grid before packaging')
    grids = manifest.get('requested_grids') or [manifest.get('requested_grid')]
    expected = {}
    for grid in grids:
        if not isinstance(grid,dict):
            raise ValueError('Completed expansion manifest is missing its requested grid')
        families,profiles,percentages = (grid.get(key) for key in ('families','profile_ids','percentages'))
        if (any(not isinstance(values,list) or not values or len(values)!=len(set(values))
                for values in (families,profiles,percentages))
                or not set(families).issubset(expansion)
                or not set(profiles).issubset(EXPANSION_BASE_WEIGHTS)
                or any(type(percent) is not int or percent not in BREAST_PERCENT_WEIGHTS for percent in percentages)
                or grid.get('expected_variants') != len(families)*len(profiles)*len(percentages)):
            raise ValueError('Invalid completed expansion requested-grid declaration')
        for family in families:
            expected.setdefault(family,set()).update((profile,percent) for profile in profiles for percent in percentages)
    if set(expected)!=set(expansion):
        raise ValueError('Expansion requested grids do not cover their actual families')
    for family,variants in expansion.items():
        actual = [(variant.get('base_body_id'),variant.get('breast_percent')) for variant in variants]
        if len(actual)!=len(set(actual)) or set(actual)!=expected[family]:
            raise ValueError('Expansion manifest does not contain exactly its requested base/chest grid')
    if manifest.get('completed_variant_count') != sum(len(variants) for variants in expansion.values()):
        raise ValueError('Expansion completed-variant count does not match its grid')
    return copy.deepcopy(grids)


def merge_body_manifests(manifests: list[dict]) -> dict:
    """Combine collections without changing a source family or shadowing a variant."""
    if not manifests:
        raise ValueError('At least one body manifest is required')
    merged, families = {'schema_version':1, 'families':[], 'collections':[], 'requested_grids':[]}, {}
    for manifest in manifests:
        if manifest.get('schema_version', 1) != 1 or not isinstance(manifest.get('families'), list):
            raise ValueError('Unsupported or malformed body manifest')
        merged['requested_grids'].extend(validate_expansion_request(manifest))
        collection = manifest.get('collection_id', 'legacy')
        if collection not in merged['collections']:
            merged['collections'].append(collection)
        for raw in manifest['families']:
            family = copy.deepcopy(raw)
            identifier = family['id']
            for variant in family['variants']:
                variant.setdefault('collection_id', collection)
                variant.setdefault('base_body_id', variant['id'])
                variant.setdefault('breast_percent', 0)
            if identifier not in families:
                families[identifier] = family
                merged['families'].append(family)
                continue
            previous = families[identifier]
            if set(previous['original_visual_ids']) != set(family['original_visual_ids']):
                raise ValueError(f'Collections disagree on original body UUIDs: {identifier}')
            if not previous.get('source_sha256') or previous['source_sha256'] != family.get('source_sha256'):
                raise ValueError(f'Collections disagree on source pin source_sha256: {identifier}')
            for key in ('vertices', 'triangles', 'geometry_id', 'lod_count'):
                if key in previous and key in family and previous[key] != family[key]:
                    raise ValueError(f'Collections disagree on source pin {key}: {identifier}')
            for key in ('topology_id', 'position_sha256', 'controller_sha256', 'uv_sha256'):
                old, new = previous.get('source_snapshot', {}).get(key), family.get('source_snapshot', {}).get(key)
                if not old or old != new:
                    raise ValueError(f'Collections disagree on source snapshot {key}: {identifier}')
            known = {variant['id'] for variant in previous['variants']}
            if known.intersection(variant['id'] for variant in family['variants']):
                raise ValueError(f'Collections contain duplicate body variants: {identifier}')
            previous['variants'].extend(family['variants'])
    for family in merged['families']:
        identifiers = [variant['id'] for variant in family['variants']]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError(f'Duplicate body variants: {family["id"]}')
    if merged['requested_grids']:
        merged['build_status'] = 'complete'
        merged['completed_variant_count'] = sum(variant['id'].startswith('exp_')
                                                for family in merged['families'] for variant in family['variants'])
        validate_expansion_request(merged)
    return merged


def annotate_body_resources(resources: dict, manifest: dict) -> None:
    metadata = {(family['id'], variant['id']): {key:variant[key] for key in VARIANT_METADATA if key in variant}
                for family in manifest['families'] for variant in family['variants']}
    for entry in resources['variants']:
        entry.update(metadata[(entry['family_id'], entry['variant_id'])])
    for candidates in resources['resource_map'].values():
        for entry in candidates:
            entry.update(metadata[(entry['family_id'], entry['variant_id'])])


def _expansion(candidate: dict) -> bool:
    return candidate['variant_id'].startswith('exp_')


def _weighted_choice(items: list, weights: list[int], seed: str):
    total = sum(weights)
    if total <= 0:
        raise ValueError('Compatible palette has no supported weighted profiles')
    choice = int.from_bytes(hashlib.sha256(seed.encode()).digest()[:8], 'big') % total
    for item, weight in zip(items, weights):
        choice -= weight
        if choice < 0:
            return item
    raise ValueError('Invalid weighted palette')


def select_body_candidate(candidates: list[dict], seed: str) -> tuple[dict, dict]:
    """Keep legacy choices exact; independently choose mixed bases and chest sizes."""
    candidates = sorted(candidates, key=lambda candidate: candidate['variant_id'])
    if len({entry['variant_id'] for entry in candidates}) != len(candidates):
        raise ValueError('Ambiguous compatible body palette')
    if not isinstance(seed, str) or not seed.strip():
        raise ValueError('Body identity seed must be a nonempty string')
    if not any(_expansion(candidate) for candidate in candidates):
        selected = _weighted_choice(candidates, [LEGACY_BODY_WEIGHTS.get(c['variant_id'], 0) for c in candidates],
                                    'nudegate-body-v1:' + seed)
        return selected, {'algorithm':'legacy-v1'}
    bases = {}
    for candidate in candidates:
        if _expansion(candidate):
            base, percent = candidate.get('base_body_id'), candidate.get('breast_percent')
            if (base not in EXPANSION_BASE_WEIGHTS or type(percent) is not int or percent not in BREAST_PERCENT_WEIGHTS
                    or candidate['variant_id'] != f'exp_{base}_b{percent:03}'
                    or not isinstance(candidate.get('collection_id'), str) or not candidate['collection_id']):
                raise ValueError('Expansion profile metadata does not identify an actual supported base/chest combination')
            key = ('expansion', base)
        else:
            if candidate['variant_id'] not in LEGACY_BODY_WEIGHTS:
                raise ValueError('Unsupported legacy profile in compatible palette')
            key = ('legacy', candidate['variant_id'])
        bases.setdefault(key, []).append(candidate)
    keys = sorted(bases)
    base = _weighted_choice(keys, [EXPANSION_BASE_WEIGHTS[key[1]] if key[0] == 'expansion'
                                  else LEGACY_BODY_WEIGHTS[key[1]] for key in keys], 'nudegate-base-v2:' + seed)
    available = sorted(bases[base], key=lambda candidate: candidate.get('breast_percent', 0))
    percentages = [candidate.get('breast_percent', 0) for candidate in available]
    if len(percentages) != len(set(percentages)):
        raise ValueError('Ambiguous base/chest combination in compatible palette')
    selected = (_weighted_choice(available, [BREAST_PERCENT_WEIGHTS[percent] for percent in percentages],
                                 'nudegate-breast-v1:' + seed) if base[0] == 'expansion' else available[0])
    return selected, {'algorithm':'independent-base-and-chest-v2', 'base_bucket':base[1],
                      'breast_percent':selected.get('breast_percent', 0)}


def run(divine: Path, *args: str) -> str:
    result = subprocess.run([str(divine), "-g", "bg3", *map(str, args)],
                            capture_output=True, text=True)
    if result.returncode or "[ERROR]" in result.stdout + result.stderr:
        raise RuntimeError((result.stdout + result.stderr).strip())
    return result.stdout


def find_divine() -> Path | None:
    candidates = [
        Path.home() / ".cache/nudegate/lslib/Packed/Tools/Divine.exe",
        Path(os.environ.get("APPDATA", "")) / "Vortex/baldursgate3/mods/ExportTool-v1.20.4/tools/Divine.exe",
    ]
    return next((p for p in candidates if p.is_file()), None)


def package_order(data: Path) -> list[str]:
    names = [name for name in ("Shared", "Gustav", "GustavX")
             if (data / f"{name}.pak").is_file()]
    if len(names) != 3:
        raise ValueError("Expected Shared.pak, Gustav.pak and GustavX.pak in --game-data")
    patches = [p.stem for p in data.glob("Patch*.pak")
               if re.fullmatch(r"Patch\d+(?:_HotFix\d+)?", p.stem, re.I)]
    patches.sort(key=lambda name: tuple(map(int, re.findall(r"\d+", name))))
    return names + patches


def prepare(data: Path, divine: Path, cache: Path, packages: list[str]) -> Path:
    # Cache identity changes with the full source package set and file metadata.
    # Each new identity gets a fresh directory, so deleted/old files cannot leak in.
    identity = [{"name": p, "size": (data / f"{p}.pak").stat().st_size,
                 "mtime_ns": (data / f"{p}.pak").stat().st_mtime_ns} for p in packages]
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
    root = cache / key
    complete = root / "sources.json"
    if complete.is_file():
        return root
    root.mkdir(parents=True, exist_ok=True)
    for name in packages:
        print(f"Reading {name}.pak", flush=True)
        dest = root / name
        dest.mkdir(parents=True, exist_ok=True)
        for pattern in ("*RootTemplates*", "*CharacterVisual*"):
            run(divine, "-a", "extract-package", "-s", data / f"{name}.pak",
                "-d", dest, "-x", pattern)
        for source in sorted(dest.rglob("*.lsf")):
            run(divine, "-a", "convert-resource", "-s", source,
                "-d", source.with_suffix(source.suffix + ".lsx"))
    complete.write_text(json.dumps(identity, indent=2) + "\n", encoding="utf-8")
    return root


def write_inventory(db: Database, path: Path) -> None:
    rows = []
    for guid, node in sorted(db.templates.items()):
        if db.effective_attr(guid, "Type") != "character":
            continue
        rows.append({"template_id": guid, "name": attrs(node).get("Name"),
                     "visual_id": db.effective_attr(guid, "CharacterVisualResourceID"),
                     "parent": attrs(node).get("ParentTemplateId"),
                     "descendants": len(db.descendants(guid)),
                     "source": db.template_sources[guid]})
    path.write_text(json.dumps({"schema_version": 1, "characters": rows}, indent=2) + "\n", encoding="utf-8")


def assign_body_studies(generated: Path, report: dict, catalog: dict, resources: dict) -> None:
    """Choose a stable compatible study only for roots already admitted by core."""
    path = generated / 'Public/Nudegate/Content/[PAK]_CharacterVisuals/_merged.lsx'
    document = ET.parse(path)
    visuals = {attrs(node)['ID']: node for node in document.findall('./region/node/children/node')}
    seeds = {entry['template_id']: entry.get('body_seed', entry['template_id']) for entry in catalog['adults']}
    for entry in report['templates']:
        candidates = resources['resource_map'].get(entry['body_set_visual'], [])
        if not candidates:
            continue
        seed = seeds[entry['template_id']]
        selected, selection = select_body_candidate(candidates, seed)
        node = visuals[entry['private_visual_id']].find('attribute[@id="BodySetVisual"]')
        if node is None:
            raise ValueError('Compiled adult visual is missing its body set')
        entry['original_body_set_visual'] = entry['body_set_visual']
        entry['body_set_visual'] = selected['private_visual_id']
        entry['body_study'] = {'family': selected['family_id'], 'profile': selected['variant_id'],
                               'identity_seed': seed, 'physics': 'not included', 'in_game': 'not tested',
                               'selection':selection,
                               **{key:selected[key] for key in (*VARIANT_METADATA, 'skin_style_applied') if key in selected}}
        node.set('value', entry['body_set_visual'])
    document.write(path, encoding='utf-8', xml_declaration=True)
    report['body_resources'] = resources
    report['body_distribution'] = {'legacy_base_weights':LEGACY_BODY_WEIGHTS,
                                  'expansion_base_weights':EXPANSION_BASE_WEIGHTS,
                                  'breast_percent_weights':BREAST_PERCENT_WEIGHTS,
                                  'scope':'Only actually built compatible combinations are eligible'}


def soften_private_materials(resources: dict, source_banks: list[Path], generated: Path) -> dict:
    identifiers = sorted({identifier for entry in resources['variants'] for identifier in entry['material_ids']})
    skin = create_soft_materials(source_banks, identifiers, generated)
    path = Path(resources['outputs']['visuals'])
    document = ET.parse(path)
    for material in document.findall('.//node[@id="Objects"]/attribute[@id="MaterialID"]'):
        original = material.get('value')
        if original not in skin['material_map']:
            raise ValueError('A private body has an unresolved skin material')
        material.set('value', skin['material_map'][original])
    document.write(path, encoding='utf-8', xml_declaration=True)
    for entry in resources['variants']:
        entry['original_material_ids'] = entry['material_ids']
        entry['material_ids'] = [skin['material_map'][identifier] for identifier in entry['material_ids']]
        for lod in entry.get('lods', []):
            lod['original_material_id'] = lod['material_id']
            lod['material_id'] = skin['material_map'][lod['material_id']]
    return skin


def _uuid(value) -> str:
    try:
        parsed = UUID(value)
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError(f'Invalid skin material UUID: {value!r}') from error
    if not parsed.int:
        raise ValueError('Skin material UUID must not be zero')
    return str(parsed)


def load_skin_style_package(package: Path, report_path: Path) -> dict:
    """Bind a style report to exactly its validated, unchanged package files."""
    package = package.resolve()
    report = json.loads(report_path.read_text(encoding='utf-8'))
    if (report.get('schema_version') != 1
            or report.get('validation', {}).get('lslib_vt_validation') != 'passed'
            or report.get('validation', {}).get('resource_lsf_roundtrip') != 'passed'):
        raise ValueError('Skin styles require passed VT and resource round-trip checks')
    if not isinstance(report.get('material_map'), dict) or not report['material_map']:
        raise ValueError('Skin style material_map is empty')
    private_ids = set()
    for original, styles in report['material_map'].items():
        original_id = _uuid(original)
        if not isinstance(styles, dict) or set(styles) != {'soft', 'defined'}:
            raise ValueError('Each styled source material requires actual soft and defined resources')
        for identifier in styles.values():
            identifier = _uuid(identifier)
            if identifier == original_id or identifier in private_ids:
                raise ValueError('Skin style resources must have unique private material UUIDs')
            private_ids.add(identifier)
    files = report.get('files')
    if not isinstance(files, list) or not files:
        raise ValueError('Skin style report requires packaged file hashes')
    expected = set()
    for record in files:
        relative = Path(record['path'])
        source = package / relative
        if (relative.is_absolute() or '..' in relative.parts or not source.resolve().is_relative_to(package)
                or source.is_symlink() or not source.is_file()):
            raise ValueError('Skin style file path is not a regular file inside its package')
        key = relative.as_posix()
        if key in expected:
            raise ValueError('Duplicate file in skin style report')
        expected.add(key)
        if (source.stat().st_size != record['bytes']
                or hashlib.sha256(source.read_bytes()).hexdigest() != record['sha256']):
            raise ValueError(f'Skin style artifact changed after validation: {key}')
    actual = {path.relative_to(package).as_posix() for path in package.rglob('*') if path.is_file()}
    if actual != expected:
        raise ValueError('Skin style package file set differs from its validated report')
    result = copy.deepcopy(report)
    result['source_report_sha256'] = hashlib.sha256(report_path.read_bytes()).hexdigest()
    return result


def apply_skin_styles(resources: dict, generated: Path, styles: dict, legacy_skin: dict) -> dict:
    """Style only new variants; retain legacy clones and report texture fallbacks."""
    fallback = legacy_skin['material_map']
    reverse = {private:original for original, private in fallback.items()}
    if len(reverse) != len(fallback):
        raise ValueError('Ambiguous legacy soft material map')
    document = ET.parse(resources['outputs']['visuals'])
    nodes = {attrs(node)['ID']:node for node in document.findall('./region/node/children/node')}
    applied, legacy_count = [], 0
    for entry in resources['variants']:
        if not _expansion(entry):
            legacy_count += 1
            continue
        requested = entry.get('skin_style')
        if requested not in {'soft', 'defined'}:
            raise ValueError('Expansion variants require an explicit soft or defined skin style')
        choices = {}
        for original in entry.get('original_material_ids', entry['material_ids']):
            if original not in fallback:
                raise ValueError('New body has no validated legacy soft-material fallback')
            authored = styles['material_map'].get(original, {}).get(requested)
            choices[original] = authored or fallback[original]
        used = set()
        for material in nodes[entry['private_visual_id']].findall('.//node[@id="Objects"]/attribute[@id="MaterialID"]'):
            original = reverse.get(material.get('value'), material.get('value'))
            if original not in choices:
                raise ValueError('A body material does not match its validated resource report')
            material.set('value', choices[original])
            used.add(original)
        if used != set(choices):
            raise ValueError('Body material report contains unresolved original IDs')
        texture_count = sum(original in styles['material_map'] for original in choices)
        resolution = (requested if texture_count == len(choices) else
                      'legacy_soft_fallback' if texture_count == 0 else 'partial_style_with_legacy_soft_fallback')
        entry['material_ids'] = sorted(set(choices.values()))
        entry['skin_style_applied'] = resolution
        for lod in entry.get('lods', []):
            original = lod.get('original_material_id', reverse.get(lod['material_id'], lod['material_id']))
            lod['material_id'] = choices[original]
        applied.append({'private_visual_id':entry['private_visual_id'], 'family_id':entry['family_id'],
                        'variant_id':entry['variant_id'], 'requested':requested, 'applied':resolution,
                        'materials':[{'original_material_id':original, 'private_material_id':private,
                                      'normal_texture_style':requested if original in styles['material_map'] else 'legacy native normal map',
                                      'fallback':original not in styles['material_map']} for original, private in sorted(choices.items())]})
    document.write(resources['outputs']['visuals'], encoding='utf-8', xml_declaration=True)
    resolution = {entry['private_visual_id']:entry['skin_style_applied'] for entry in resources['variants'] if _expansion(entry)}
    for candidates in resources['resource_map'].values():
        for candidate in candidates:
            if candidate['private_visual_id'] in resolution:
                candidate['skin_style_applied'] = resolution[candidate['private_visual_id']]
    return {'variants':applied, 'legacy_resources_unchanged':legacy_count,
            'fallback_scope':'Families without authored style textures retain their legacy private soft material and native normal map'}


def _xml_identity(node: ET.Element):
    return [node.tag, sorted(node.attrib.items()), ' '.join((node.text or '').split()),
            [_xml_identity(child) for child in node]]


def merge_resource_documents(existing: ET.ElementTree, incoming: ET.ElementTree) -> ET.ElementTree:
    """Merge colliding resource banks while refusing UUID changes to old records."""
    result = copy.deepcopy(existing)
    root = result.getroot()
    for region in incoming.getroot().findall('region'):
        identifier = region.get('id')
        targets = root.findall(f'region[@id="{identifier}"]')
        if not targets:
            root.append(copy.deepcopy(region))
            continue
        if len(targets) != 1:
            raise ValueError('Ambiguous existing resource bank region')
        target = targets[0].find(f'node[@id="{identifier}"]/children')
        source = region.find(f'node[@id="{identifier}"]/children')
        if target is None or source is None:
            raise ValueError('Unsupported colliding resource bank structure')
        index = {attrs(node).get('ID'):node for node in target}
        if None in index or len(index) != len(target):
            raise ValueError('Ambiguous resource IDs in colliding bank')
        for node in source:
            key = attrs(node).get('ID')
            if not key:
                raise ValueError('Incoming resource has no UUID')
            if key in index:
                if _xml_identity(index[key]) != _xml_identity(node):
                    raise ValueError(f'Skin style would override an existing private resource: {key}')
            else:
                target.append(copy.deepcopy(node))
                index[key] = node
    return result


def copy_skin_style_package(package: Path, stage: Path, styles: dict, divine: Path) -> list[dict]:
    """Copy verified assets and merge SE settings or resource-bank collisions."""
    for record in styles['files']:
        relative = Path(record['path'])
        source, destination = package / relative, stage / relative
        if (source.stat().st_size != record['bytes']
                or hashlib.sha256(source.read_bytes()).hexdigest() != record['sha256']):
            raise ValueError('Skin style package changed between validation and packaging')
        destination.parent.mkdir(parents=True, exist_ok=True)
        if relative.as_posix() == 'Mods/Nudegate/ScriptExtender/Config.json':
            before = json.loads(destination.read_text()) if destination.exists() else {}
            incoming = json.loads(source.read_text())
            if any(value.get('ModTable', 'Nudegate') != 'Nudegate' for value in (before, incoming)):
                raise ValueError('Script Extender config must identify ModTable Nudegate')
            merged = {**incoming, **before, 'ModTable':'Nudegate',
                      'RequiredVersion':max(12, int(before.get('RequiredVersion', 0)), int(incoming.get('RequiredVersion', 0))),
                      'FeatureFlags':sorted(set(before.get('FeatureFlags', [])) | set(incoming.get('FeatureFlags', [])))}
            destination.write_text(json.dumps(merged, indent=2) + '\n', encoding='utf-8')
        elif relative.as_posix() == 'Mods/Nudegate/ScriptExtender/VirtualTextures.json':
            before = json.loads(destination.read_text()) if destination.exists() else {'Mappings':[]}
            incoming = json.loads(source.read_text())
            mappings = {}
            for mapping in before.get('Mappings', []) + incoming.get('Mappings', []):
                key = mapping['GTexName']
                if key in mappings and mappings[key] != mapping:
                    raise ValueError('Conflicting Script Extender virtual-texture mapping')
                mappings[key] = mapping
            destination.write_text(json.dumps({'Mappings':[mappings[key] for key in sorted(mappings)]}, indent=2) + '\n', encoding='utf-8')
        elif destination.exists() and destination.read_bytes() != source.read_bytes():
            if source.suffix.lower() != '.lsf':
                raise ValueError(f'Skin style asset collides with an existing file: {relative}')
            with tempfile.TemporaryDirectory(prefix='skin-bank-merge-', dir=stage.parent) as temp:
                work = Path(temp)
                old, new = work / 'old.lsx', work / 'new.lsx'
                run(divine, '-a', 'convert-resource', '-s', destination, '-d', old)
                run(divine, '-a', 'convert-resource', '-s', source, '-d', new)
                merged = merge_resource_documents(ET.parse(old), ET.parse(new))
                merged.write(work / 'merged.lsx', encoding='utf-8', xml_declaration=True)
                run(divine, '-a', 'convert-resource', '-s', work / 'merged.lsx', '-d', work / 'merged.lsf')
                shutil.copy2(work / 'merged.lsf', destination)
        else:
            shutil.copy2(source, destination)
            if hashlib.sha256(destination.read_bytes()).hexdigest() != record['sha256']:
                raise ValueError('Skin style asset changed while being copied')
    return [{'path':record['path'], 'sha256':hashlib.sha256((stage / record['path']).read_bytes()).hexdigest()}
            for record in styles['files']]


def verify_package(divine: Path, pak: Path, stage: Path, verification: Path, report: dict) -> None:
    run(divine, "-a", "extract-package", "-s", pak, "-d", verification)
    expected = {p.relative_to(stage).as_posix(): p for p in stage.rglob("*") if p.is_file()}
    actual = {p.relative_to(verification).as_posix(): p for p in verification.rglob("*") if p.is_file()}
    if expected.keys() != actual.keys():
        raise RuntimeError("Package round trip changed the file set")
    documents = {}
    for name, source in expected.items():
        if source.read_bytes() != actual[name].read_bytes():
            raise RuntimeError(f"Package round trip changed {name}")
        if source.suffix == ".lsf":
            converted = actual[name].with_suffix(".verified.lsx")
            run(divine, "-a", "convert-resource", "-s", actual[name], "-d", converted)
            documents[name] = ET.parse(converted)
    roots = documents["Public/Nudegate/RootTemplates/_merged.lsf"]
    visuals = documents["Public/Nudegate/Content/[PAK]_CharacterVisuals/_merged.lsf"]
    root_nodes = {attrs(n)["MapKey"]: n for n in roots.findall('./region/node/children/node')}
    visual_nodes = {attrs(n)["ID"]: n for n in visuals.findall('./region/node/children/node')}
    entries = report["templates"]
    if set(root_nodes) != {e["template_id"] for e in entries}:
        raise RuntimeError("Compiled package does not contain exactly the approved adult roots")
    if set(visual_nodes) != {e["private_visual_id"] for e in entries}:
        raise RuntimeError("Compiled package does not contain exactly the private visual resources")
    for entry in entries:
        root_values = attrs(root_nodes[entry["template_id"]])
        visual = visual_nodes[entry["private_visual_id"]]
        values = attrs(visual)
        if root_values.get("CharacterVisualResourceID") != entry["private_visual_id"]:
            raise RuntimeError(f"Compiled root lost its private visual: {entry['name']}")
        if (values.get("BodySetVisual") != entry["body_set_visual"]
                or values.get("BaseVisual") != entry["base_visual"]
                or values.get("ShowEquipmentVisuals", "").lower() != "false"):
            raise RuntimeError(f"Compiled visual lost its body or visibility setting: {entry['name']}")
        clothing = {"Body", "Underwear", "Gloves", "Footwear", "Cloak", "Headwear"}
        if any(attrs(n).get("Slot") in clothing for n in visual.findall('./children/node[@id="Slots"]')):
            raise RuntimeError(f"Compiled visual retained a garment slot: {entry['name']}")
    if 'body_resources' in report:
        bank = documents['Public/Nudegate/Content/[PAK]_BodyVisuals/_merged.lsf']
        body_nodes = {attrs(n)['ID']: n for n in bank.findall('./region/node/children/node')}
        for entry in report['body_resources']['variants']:
            values = attrs(body_nodes[entry['private_visual_id']])
            if values.get('SourceFile') != entry['sourcefile'] or not (verification / entry['sourcefile']).is_file():
                raise RuntimeError('A private body resource lost its packaged mesh')
    if 'tav_presets' in report:
        tav = report['tav_presets']
        template_nodes = {attrs(n)['MapKey']:n for n in documents['Public/Nudegate/RootTemplates/tav.lsf'].findall('./region/node/children/node')}
        visual_nodes = {attrs(n)['ID']:n for n in documents['Public/Nudegate/Content/[PAK]_CharacterVisuals/tav.lsf'].findall('./region/node/children/node')}
        for entry in tav['templates']:
            if (entry['private_template_id'] == entry['original_template_id']
                    or attrs(template_nodes[entry['private_template_id']]).get('CharacterVisualResourceID') != entry['private_visual_id']
                    or attrs(visual_nodes[entry['private_visual_id']]).get('BodySetVisual') != entry['private_body_set_visual']):
                raise RuntimeError('Private Tav template isolation did not survive packaging')
    if 'skin_styles' in report:
        styles = report['skin_styles']
        materials, virtual_textures = {}, {}
        for document in documents.values():
            for bank_name, index in (('MaterialBank', materials), ('VirtualTextureBank', virtual_textures)):
                for node in document.findall(f'./region[@id="{bank_name}"]/node[@id="{bank_name}"]/children/node[@id="Resource"]'):
                    identifier = attrs(node)['ID']
                    if identifier in index and _xml_identity(index[identifier]) != _xml_identity(node):
                        raise RuntimeError('Conflicting packaged skin resource UUID')
                    index[identifier] = node
        for choices in styles['material_map'].values():
            if not set(choices.values()).issubset(materials):
                raise RuntimeError('A requested skin style material was not packaged')
        config = json.loads((verification / 'Mods/Nudegate/ScriptExtender/Config.json').read_text())
        if config.get('ModTable') != 'Nudegate' or config.get('RequiredVersion', 0) < 12:
            raise RuntimeError('Skin styles lost their Script Extender registration')
        mappings = json.loads((verification / 'Mods/Nudegate/ScriptExtender/VirtualTextures.json').read_text())['Mappings']
        mappings = {entry['GTexName']:entry['GTS'] for entry in mappings}
        for style in styles['styles']:
            if style['private_virtual_texture_id'] not in virtual_textures:
                raise RuntimeError('A private style virtual texture was not packaged')
            material = materials[style['private_material_id']]
            parameters = [node for node in material.findall('./children/node[@id="VirtualTextureParameters"]')
                          if attrs(node).get('ParameterName') == 'virtualtexture']
            if (len(parameters) != 1 or attrs(parameters[0]).get('ID') != style['private_virtual_texture_id']
                    or attrs(parameters[0]).get('Enabled', '').lower() != 'true'
                    or attrs(virtual_textures[style['private_virtual_texture_id']]).get('GTexFileName') != style['gtex_name']):
                raise RuntimeError('A private skin style lost its material/VT/GTex reference chain')
            path = mappings.get(style['gtex_name'])
            if not path or not (verification / path).is_file():
                raise RuntimeError('A private style virtual texture lost its GTex/GTS mapping')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-data", type=Path,
                        default=Path(r"C:\Program Files (x86)\Steam\steamapps\common\Baldurs Gate 3\Data"))
    parser.add_argument("--divine", type=Path, default=find_divine())
    parser.add_argument("--source-root", type=Path, help="Use already converted package directories")
    parser.add_argument("--packages", nargs="+", help="Explicit ordered packages for --source-root")
    parser.add_argument("--cache", type=Path, default=Path.home() / ".cache/nudegate/sources")
    parser.add_argument("--catalog", type=Path, default=REPO / "config/adults.json")
    parser.add_argument("--inventory-only", action="store_true")
    parser.add_argument("--body-manifest", nargs='+', type=Path, help="One or more validated local body collections")
    parser.add_argument("--body-visual-bank", type=Path, help="Locally extracted BCB VisualBank LSX")
    parser.add_argument('--soft-material-banks', nargs='+', type=Path, help='Native skin banks for private vein/roughness defaults')
    parser.add_argument('--tav-presets', nargs='+', type=Path, help='Optional native generic CC preset files in load order')
    parser.add_argument('--tav-profile', default='plush', help='Fixed compatible body profile for new Tav creation')
    parser.add_argument('--skin-style-package', type=Path, help='Validated private skin-style package directory')
    parser.add_argument('--skin-style-report', type=Path, help='Matching skin-styles.json with file hashes')
    args = parser.parse_args()
    try:
        if args.divine is None or not args.divine.is_file():
            raise ValueError("Pass --divine with the path to LSLib Divine.exe")
        if bool(args.body_manifest) != bool(args.body_visual_bank):
            raise ValueError('Pass --body-manifest and --body-visual-bank together')
        if (args.soft_material_banks or args.tav_presets) and not args.body_manifest:
            raise ValueError('Private skin/Tav options require a validated body manifest')
        if bool(args.skin_style_package) != bool(args.skin_style_report):
            raise ValueError('Pass --skin-style-package and --skin-style-report together')
        if args.skin_style_package and (not args.body_manifest or not args.soft_material_banks):
            raise ValueError('Skin styles require body manifests and legacy private soft-material fallbacks')
        skin_styles = (load_skin_style_package(args.skin_style_package, args.skin_style_report)
                       if args.skin_style_package else None)
        packages = args.packages or package_order(args.game_data)
        root = args.source_root or prepare(args.game_data, args.divine, args.cache, packages)
        print("Indexing templates and character visuals", flush=True)
        db = Database.load(root, packages)
        build = REPO / "build"
        build.mkdir(exist_ok=True)
        write_inventory(db, build / "inventory.json")
        if args.inventory_only:
            print(f"Wrote {build / 'inventory.json'}")
            return 0
        catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(prefix="nudegate-", dir=build) as temp:
            work = Path(temp)
            generated, stage = work / "generated", work / "package"
            report = compile_patch(db, catalog, generated)
            variety = False
            if args.body_manifest:
                body_manifest = merge_body_manifests([json.loads(path.read_text(encoding='utf-8')) for path in args.body_manifest])
                variety = any(variant['id'].startswith('exp_') for family in body_manifest['families'] for variant in family['variants'])
                if variety and not args.soft_material_banks:
                    raise ValueError('Combined expansion collections require legacy private soft-material fallbacks')
                report['body_collections'] = [{'path':str(path.resolve()), 'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
                                              for path in args.body_manifest]
                geometry_source_cache = {}
                for family in body_manifest['families']:
                    if family.get('source_sha256') and hashlib.sha256(Path(family['source']).read_bytes()).hexdigest() != family['source_sha256']:
                        raise ValueError('Reviewed body source changed after its recorded validation')
                    for variant in family['variants']:
                        if (variant['verification'].get('skin_arrays') != 'passed'
                                or 'smooth_seams' not in variant['verification']
                                or variant['verification'].get('corner_uvs') != 'passed'
                                or variant['verification'].get('bind_shape') != 'passed'
                                or not variant['sculpt']['protected_vertices_unchanged']):
                            raise ValueError('Body studies must pass geometry and rig checks before packaging')
                        if variant['id'].startswith('exp_'):
                            validate_expansion_surfaces(family,variant,geometry_source_cache)
                        elif variant['sculpt'].get('surface_quality') != {'reversed_faces':0,'new_collapsed_faces':0}:
                            raise ValueError('Original body studies must retain their recorded geometry acceptance')
                        for kind in ('gr2', 'dae'):
                            if hashlib.sha256(Path(variant[kind]).read_bytes()).hexdigest() != variant[kind + '_sha256']:
                                raise ValueError('Body artifact changed after its recorded validation')
                resources = create_body_resources(body_manifest, args.body_visual_bank.resolve(), generated)
                annotate_body_resources(resources, body_manifest)
                if args.soft_material_banks:
                    report['skin_materials'] = soften_private_materials(resources, args.soft_material_banks, generated)
                if skin_styles:
                    report['skin_styles'] = copy.deepcopy(skin_styles)
                    report['skin_styles']['application'] = apply_skin_styles(resources, generated, skin_styles, report['skin_materials'])
                elif variety:
                    report['skin_style_application'] = apply_skin_styles(resources, generated, {'material_map':{}}, report['skin_materials'])
                assign_body_studies(generated, report, catalog, resources)
                if args.tav_presets:
                    tav = create_tav_presets(db, args.tav_presets, resources, generated, profile_id=args.tav_profile)
                    if not tav['counts']['presets']:
                        raise ValueError('No compatible reviewed new-Tav presets were generated')
                    report['tav_presets'] = tav
            shutil.copytree(REPO / "mod", stage)
            if args.body_manifest:
                metadata_path = stage / 'Mods/Nudegate/meta.lsx'
                metadata = ET.parse(metadata_path)
                metadata.find('.//node[@id="ModuleInfo"]/attribute[@id="Name"]').set('value',
                    'Nudegate (variety study)' if variety else 'Nudegate (plush Tav study)' if args.tav_presets else 'Nudegate (body study)')
                metadata.find('.//node[@id="ModuleInfo"]/attribute[@id="Description"]').set('value',
                    ('Experimental original and expansion adult body collections with independent base and chest-size choices. ' if variety
                     else 'Experimental soft and plush adult body shapes, with normal and strong female frames. ')
                    + ('Includes a new-Tav creation test option. ' if args.tav_presets else '')
                    + 'In-game acceptance is pending; no new jiggle physics are included.')
                metadata.find('.//node[@id="ModuleInfo"]/attribute[@id="Version64"]').set('value', '422212465065985' if variety else '281474976710658')
                metadata.write(metadata_path, encoding='utf-8', xml_declaration=True)
            for source in generated.rglob('*.GR2'):
                destination = stage / source.relative_to(generated)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            for source in generated.rglob("*.lsx"):
                destination = stage / source.relative_to(generated).with_suffix(".lsf")
                destination.parent.mkdir(parents=True, exist_ok=True)
                run(args.divine, "-a", "convert-resource", "-s", source, "-d", destination)
                if not destination.is_file():
                    raise RuntimeError(f"Conversion did not produce {destination.name}")
            if skin_styles:
                report['skin_styles']['packaged_files'] = copy_skin_style_package(args.skin_style_package, stage, skin_styles, args.divine)
            pak_name = ('Nudegate-0.3.0-variety-study.pak' if variety else
                        'Nudegate-0.2.0-plush-tav-study.pak' if args.tav_presets else
                        'Nudegate-0.2.0-body-study.pak' if args.body_manifest else 'Nudegate-0.1.0-alpha.pak')
            pak = work / pak_name
            run(args.divine, "-a", "create-package", "-s", stage, "-d", pak)
            if not pak.is_file():
                raise RuntimeError("Package creation produced no file")
            verify_package(args.divine, pak, stage, work / "verify", report)
            report["source_packages"] = packages
            report["package_sha256"] = hashlib.sha256(pak.read_bytes()).hexdigest()
            report["validation"] = {"package_round_trip": "passed", "in_game": "not tested"}
            report["outputs"] = {
                "templates": "build/generated/Public/Nudegate/RootTemplates/_merged.lsx",
                "visuals": "build/generated/Public/Nudegate/Content/[PAK]_CharacterVisuals/_merged.lsx",
            }
            if 'body_resources' in report:
                resources = report['body_resources']
                resources['outputs'] = {
                    'visuals': 'build/generated/Public/Nudegate/Content/[PAK]_BodyVisuals/_merged.lsx',
                    'meshes': ['build/generated/' + str(Path(p).relative_to(generated)).replace('\\', '/')
                               for p in resources['outputs']['meshes']],
                }
            for key in ('skin_materials', 'tav_presets'):
                if key in report:
                    section = report[key]
                    section['outputs'] = {kind:'build/generated/' + str(Path(p).relative_to(generated)).replace('\\','/')
                                          for kind,p in section['outputs'].items()}
                    if 'output' in section:
                        section['output'] = section['outputs']['materials']
            dist = REPO / "dist"
            dist.mkdir(exist_ok=True)
            # Publish local build outputs only after every check passes.
            shutil.copy2(pak, dist / pak.name)
            report_name = 'variety-study-report.json' if variety else 'body-study-report.json' if args.body_manifest else 'build-report.json'
            (dist / report_name).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            shutil.copytree(generated, build / "generated", dirs_exist_ok=True)
            print(f"Built {dist / pak.name}")
            print("Package round trip passed. In-game appearance is not tested.")
        return 0
    except (OSError, ValueError, RuntimeError, ET.ParseError) as error:
        print(f"Build stopped: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
