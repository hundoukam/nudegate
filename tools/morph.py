"""Apply an explicit, seam-locked authoring recipe to a JSON mesh snapshot."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from nudegate.morphs import apply_morph  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mesh", type=Path)
    parser.add_argument("--recipe", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.output.resolve() in {args.mesh.resolve(), args.recipe.resolve()}:
            raise ValueError("Output must be separate from the source mesh and recipe")
        source = args.mesh.read_bytes()
        recipe = args.recipe.read_bytes()
        mesh = json.loads(source)
        result = apply_morph(mesh, json.loads(recipe))
        mesh["positions"] = result["positions"]
        mesh["morph_report"] = {**result["report"],
                                "source_sha256": hashlib.sha256(source).hexdigest(),
                                "recipe_sha256": hashlib.sha256(recipe).hexdigest(),
                                "in_game": "not tested"}
        serialized = json.dumps(mesh, indent=2, allow_nan=False) + "\n"
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
        print(json.dumps(mesh["morph_report"], indent=2))
        return 0
    except (OSError, ValueError, TypeError) as error:
        print(f"Morph stopped: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
