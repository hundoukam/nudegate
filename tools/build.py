"""Build from locally owned BG3 packages. Never changes the game or saves."""
from __future__ import annotations

import argparse
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

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from nudegate.core import Database, attrs, compile as compile_patch  # noqa: E402
from nudegate.body_resources import create_body_resources  # noqa: E402
from nudegate.skin_materials import create_soft_materials  # noqa: E402
from nudegate.tav_presets import create_tav_presets  # noqa: E402


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
    weights = {'lean':15, 'athletic':10, 'balanced':15, 'full':15, 'soft':20, 'voluptuous':10, 'plush':15}
    for entry in report['templates']:
        candidates = resources['resource_map'].get(entry['body_set_visual'], [])
        if not candidates:
            continue
        candidates = sorted(candidates, key=lambda c: c['variant_id'])
        if len({c['variant_id'] for c in candidates}) != len(candidates):
            raise ValueError('Ambiguous compatible body palette')
        total = sum(weights.get(c['variant_id'], 0) for c in candidates)
        if total <= 0:
            raise ValueError('Compatible palette has no supported weighted profiles')
        seed = seeds[entry['template_id']]
        if not isinstance(seed, str) or not seed.strip():
            raise ValueError('Body identity seed must be a nonempty string')
        choice = int.from_bytes(hashlib.sha256(('nudegate-body-v1:' + seed).encode()).digest()[:8], 'big') % total
        selected = None
        for candidate in candidates:
            choice -= weights.get(candidate['variant_id'], 0)
            if choice < 0:
                selected = candidate
                break
        node = visuals[entry['private_visual_id']].find('attribute[@id="BodySetVisual"]')
        if node is None:
            raise ValueError('Compiled adult visual is missing its body set')
        entry['original_body_set_visual'] = entry['body_set_visual']
        entry['body_set_visual'] = selected['private_visual_id']
        entry['body_study'] = {'family': selected['family_id'], 'profile': selected['variant_id'],
                               'identity_seed': seed, 'physics': 'not included', 'in_game': 'not tested'}
        node.set('value', entry['body_set_visual'])
    document.write(path, encoding='utf-8', xml_declaration=True)
    report['body_resources'] = resources


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
    parser.add_argument("--body-manifest", type=Path, help="Optional validated local body study build")
    parser.add_argument("--body-visual-bank", type=Path, help="Locally extracted BCB VisualBank LSX")
    parser.add_argument('--soft-material-banks', nargs='+', type=Path, help='Native skin banks for private vein/roughness defaults')
    parser.add_argument('--tav-presets', nargs='+', type=Path, help='Optional native generic CC preset files in load order')
    parser.add_argument('--tav-profile', default='plush', help='Fixed compatible body profile for new Tav creation')
    args = parser.parse_args()
    try:
        if args.divine is None or not args.divine.is_file():
            raise ValueError("Pass --divine with the path to LSLib Divine.exe")
        if bool(args.body_manifest) != bool(args.body_visual_bank):
            raise ValueError('Pass --body-manifest and --body-visual-bank together')
        if (args.soft_material_banks or args.tav_presets) and not args.body_manifest:
            raise ValueError('Private skin/Tav options require a validated body manifest')
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
            if args.body_manifest:
                body_manifest = json.loads(args.body_manifest.read_text(encoding='utf-8'))
                for family in body_manifest['families']:
                    for variant in family['variants']:
                        if (variant['verification'].get('skin_arrays') != 'passed'
                                or 'smooth_seams' not in variant['verification']
                                or variant['verification'].get('corner_uvs') != 'passed'
                                or variant['verification'].get('bind_shape') != 'passed'
                                or variant['sculpt']['surface_quality'] != {'reversed_faces':0,'new_collapsed_faces':0}
                                or not variant['sculpt']['protected_vertices_unchanged']):
                            raise ValueError('Body studies must pass geometry and rig checks before packaging')
                        for kind in ('gr2', 'dae'):
                            if hashlib.sha256(Path(variant[kind]).read_bytes()).hexdigest() != variant[kind + '_sha256']:
                                raise ValueError('Body artifact changed after its recorded validation')
                resources = create_body_resources(body_manifest, args.body_visual_bank.resolve(), generated)
                if args.soft_material_banks:
                    report['skin_materials'] = soften_private_materials(resources, args.soft_material_banks, generated)
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
                metadata.find('.//node[@id="ModuleInfo"]/attribute[@id="Name"]').set('value', 'Nudegate (plush Tav study)' if args.tav_presets else 'Nudegate (body study)')
                metadata.find('.//node[@id="ModuleInfo"]/attribute[@id="Description"]').set('value',
                    'Experimental soft and plush adult body shapes, with normal and strong female frames. '
                    + ('Includes a new-Tav creation test option. ' if args.tav_presets else '')
                    + 'In-game acceptance is pending; no new jiggle physics are included.')
                metadata.find('.//node[@id="ModuleInfo"]/attribute[@id="Version64"]').set('value', '281474976710658')
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
            pak_name = ('Nudegate-0.2.0-plush-tav-study.pak' if args.tav_presets else
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
            report_name = 'body-study-report.json' if args.body_manifest else 'build-report.json'
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
