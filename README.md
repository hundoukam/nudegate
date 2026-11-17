# Nudegate

An experimental Baldur's Gate 3 project for adult NPC nudity, body variety and
compatible body physics, inspired by NudePunk2077.

**Current version: 0.1.0 alpha. This is a development prototype, not an
all-NPC release.** The builder produces an appearance-only `.pak` from a local
BG3 installation. It changes twelve explicitly reviewed adult root templates,
creates private character visuals, removes embedded garment slots and disables
equipment rendering. Equipment, armor class, inventory, loot, dialogue and
combat data are retained. Original head, hair, skin materials, anatomy,
body family and censorship leaves are retained.

## Current coverage

The catalog includes the main adult roots for Lae'zel, Karlach, Wyll (human and
transformed), Minthara (normal and vanity), Jaheira, Minsc, Shadowheart,
Astarion, Gale and Halsin. These are **template patches**, not confirmation
that every story instance of those characters changes. Lae'zel and human
Wyll's gameplay globals inherit their roots. Karlach, Jaheira and Minsc have
explicit instance visuals and can bypass these root patches. Level-local NPCs,
cinematic variants, transformations and saved appearance overrides need separate
coverage. Origin player avatars using these roots may also be affected.

Children and unknown characters are excluded. The compiler requires an exact
UUID/name adult review, resolves the entire parent chain, and refuses child
tags, child ancestry, minor name/stat evidence and missing data. A root with
descendants is admitted only when every immediate child has an existing,
explicit visual that prevents inheriting the patch. Child visual resources
and shared body resources are never edited by this alpha.

## Build

Requires Python 3.10+, an installed PC copy of BG3, and
[LSLib / Divine](https://github.com/Norbyte/lslib/releases).
Script Extender is not required for the current static alpha.

```powershell
python tools/build.py --divine "C:\path\to\Divine.exe" --game-data "C:\path\to\Baldurs Gate 3\Data"
```

The builder reads `Shared`, `Gustav`, `GustavX` and installed numbered hotfix
packages in order. Within packages it resolves the built-in module order.
It extracts only root templates and character visual metadata, caches converted
sources outside the repository, validates the catalog, compiles LSX to LSF and
checks the resulting package by extracting it again. It does not edit the game
installation, mod load order, or saves.

Outputs:

- `dist/Nudegate-0.1.0-alpha.pak`: local experimental package.
- `dist/build-report.json`: exact patched IDs, body families and validation.
- `build/inventory.json`: candidate template inventory for further review.
- `build/generated/`: generated XML for inspection.

Use `--inventory-only` to inspect candidates without building a mod.
Game-derived outputs and third-party assets are excluded from Git.

## Body variety and jiggle

The alpha retains each character's original body family, so it also references
compatible installed body replacers. **It does not yet distribute custom shapes
or add jiggle.** A shared body replacer alone gives all users of that resource
the same replacement; multiple shapes need private body resources and stable
selection within compatible skeleton/skin families.

The provided BCB 3.17 archive is useful as a local compatibility reference.
It and the installed `The Jiggle Is Up` mod overlap on body resource IDs, so
loading both does not establish that both effects survive. The planned custom
pipeline and verified findings are in [docs/BODY_PIPELINE.md](docs/BODY_PIPELINE.md).

`src/nudegate/morphs.py` and `tools/morph.py` provide an offline authoring
foundation: explicit region masks, topology checks, bounded scale changes,
locked seam vertices and displacement reports. They process JSON vertex
snapshots, not game-ready meshes. Mesh import/export, authored masks, private
body resource registration and physics still need integration.

## Validation

```powershell
python tools/test.py
```

Tests cover admission, child ancestry/tags, inheritance isolation, source
precedence, deterministic private IDs, and preservation of gameplay and visual
identity. A successful package round trip proves file integrity and conversion,
not in-game appearance, save compatibility or performance.

Test the alpha on a separate test save through your mod manager. Inspect the
exact characters listed in the report, ordinary and strong body types,
conversations, movement, equipment changes, reloads and the game's nudity
settings. Verify children such as Mol and childhood Shadowheart keep their
original appearances. Existing mods that edit the same adult roots can conflict.

## Development priorities

1. Cover reviewed global and level-local NPC instances, and verify results in game.
2. Author private adult body meshes with preserved skin weights, UVs and locked seams.
3. Add compatible body profiles and deterministic weighted assignment.
4. Match physics to those bodies, then test animation, collision, LOD and performance.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the data model and sources.
