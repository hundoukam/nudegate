"""Build optional private SOFT/DEFINED skin VTs from reviewed native source maps.

The JSON config contains source_banks and families. Each family has id,
material_id, dae, geometry_id, optional frame=[x,y,z], and textures with keys
Albedo (CLEA), Normal (NM), Physical (HMVY). Paths are relative to the config.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from nudegate.skin_styles import create_skin_styles  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--divine", type=Path, default=Path.home() / ".cache/nudegate/gr2-tools/Divine-1.20.4/Divine.exe")
    parser.add_argument("--texconv", type=Path, default=Path.home() / ".cache/nudegate/gr2-tools/directxtex/texconv.exe")
    parser.add_argument("--module-folder", default="Nudegate")
    args = parser.parse_args()
    config_path = args.config.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    def resolved(value):
        path = Path(value)
        return path if path.is_absolute() else config_path.parent / path
    banks = [resolved(value) for value in config["source_banks"]]
    for family in config["families"]:
        family["dae"] = resolved(family["dae"])
        family["textures"] = {name: resolved(value) for name, value in family["textures"].items()}
    report = create_skin_styles(banks, config["families"], args.output, divine=args.divine,
                                texconv=args.texconv, module_folder=args.module_folder)
    print(json.dumps({"report": str(args.output.resolve() / "skin-styles.json"),
                      "material_map": report["material_map"], "validation": report["validation"]}, indent=2))


if __name__ == "__main__":
    main()
