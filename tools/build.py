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
    args = parser.parse_args()
    try:
        if args.divine is None or not args.divine.is_file():
            raise ValueError("Pass --divine with the path to LSLib Divine.exe")
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
            shutil.copytree(REPO / "mod", stage)
            for source in generated.rglob("*.lsx"):
                destination = stage / source.relative_to(generated).with_suffix(".lsf")
                destination.parent.mkdir(parents=True, exist_ok=True)
                run(args.divine, "-a", "convert-resource", "-s", source, "-d", destination)
                if not destination.is_file():
                    raise RuntimeError(f"Conversion did not produce {destination.name}")
            pak = work / "Nudegate-0.1.0-alpha.pak"
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
            dist = REPO / "dist"
            dist.mkdir(exist_ok=True)
            # Publish local build outputs only after every check passes.
            shutil.copy2(pak, dist / pak.name)
            (dist / "build-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            shutil.copytree(generated, build / "generated", dirs_exist_ok=True)
            print(f"Built {dist / pak.name}")
            print("Package round trip passed. In-game appearance is not tested.")
        return 0
    except (OSError, ValueError, RuntimeError, ET.ParseError) as error:
        print(f"Build stopped: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
