# Nudegate

An experimental Baldur's Gate 3 project for adult NPC nudity, body variety and
compatible body physics, inspired by NudePunk2077.

**Current source version: 0.3.0 experimental. This is a development prototype, not an
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
The basic static alpha does not require Script Extender. The optional private
texture styles require Script Extender 12 or later.

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

The [selected Blender donor study](docs/DONOR_BODY_STUDY.md) now has a local
Juno medium new-Tav prototype using the actual dense donor surface and rebuilt
native cloth mappings. Authored large and chubby states are separate source
exports. Runtime motion and skin appearance remain unverified; this is not the
all-NPC distribution package.

The additive 0.3 authoring pipeline keeps the original 35 body meshes and adds
five new base shapes with separate nominal breast-growth buckets through +100.
It includes frame-specific curve balancing and optional private strong-frame
skin textures. See [the variety expansion](docs/VARIETY_EXPANSION.md) for build,
preview, integrity-check and scope details. The new texture option requires
Script Extender 12 or later; the earlier static packages do not.

Local source-preserving prototypes explore continuous growth, broad attachments
and static drape. Their +50/+100 labels are nominal growth strengths rather than
exact projection or volume percentages. The latest visual review still found
the shape unnatural, so donor-model shape transfer is being evaluated before
further batch exports. These prototypes have not replaced the experimental
cage backend in the authoring code. Integration and full-grid export validation
remain pending. Runtime gravity,
squeezing and new jiggle behavior are not yet implemented. The +100 cap applies
to the current package grid; larger offline experiments remain separate.

The basic alpha retains each character's original body family, so it also references
compatible installed body replacers. The optional local body-study build now bakes
**seven profiles across normal and strong female families**. It includes
lean, athletic, soft balanced, full, soft, voluptuous and plush studies, with
separate local surface-proportion controls. A shared body replacer alone gives all users of that resource
the same replacement; multiple shapes need private body resources and stable
selection within compatible skeleton/skin families.

The provided BCB 3.17 archive is useful as a local compatibility reference.
It and the installed `The Jiggle Is Up` mod overlap on body resource IDs, so
loading both does not establish that both effects survive. The planned custom
pipeline and verified findings are in [docs/BODY_PIPELINE.md](docs/BODY_PIPELINE.md).
The latest mesh counts, export results and artifact paths are in
[body study progress](docs/BODY_STUDIES_STATUS.md).

`tools/build_bodies.py` now edits actual COLLADA geometry, recalculates shading,
exports GR2 and imports it again to check topology, skinning and position drift.
The source catalog pins the reviewed source topology and positions. Neck,
wrist, ankle and central pelvic/tail attachment zones stay fixed.
Private resource registration preserves each family's skeleton and materials;
BCB's stale LOD object names are replaced with actual exported object names.

```powershell
python tools/build_bodies.py --sources "C:\path\to\reviewed\DAE\sources" --divine "C:\path\to\Divine.exe"
python tools/build.py --body-manifest build/bodies/body-build.json --body-visual-bank "C:\path\to\BCB\VisualBank\_merged.lsx"
& "C:\path\to\blender.exe" --background --python tools/render_bodies.py -- --manifest build/bodies/body-build.json --output build/bodies/body-comparison.png
```

These local prototypes derive from the supplied BCB 3.17 archive and the user's vanilla game. Meshes,
source banks, generated packages and renders remain outside Git. The ordinary
build still works without body assets. The optional package is
`dist/Nudegate-0.2.0-body-study.pak`; it shares the basic alpha's module UUID, so
use one package at a time.

The larger human/elf and tiefling female bodies retain their own native frame
and all five LODs. An optional experimental new-Tav preset path chooses the
Plush shape for both supported frame sizes without replacing original NPC
roots. See [soft female frames and Tav testing](docs/PLUSH_FRAMES.md), including
the private skin-material option and remaining normal-map/physics work.

The body-study build currently finds compatible body-set IDs on Lae'zel's root
and Minthara's normal/vanity roots. Minthara's two roots share a stable selection
seed. Unsupported bodies retain their existing body. This is not broad NPC
distribution, runtime sliders or a physics release. Full-body and private
anatomy attachment alignment still need in-game inspection.

`src/nudegate/morphs.py` and `tools/morph.py` also support explicit masked JSON
mesh snapshots for offline authoring. Texture-based areola variation and matched
jiggle assets remain future work.
The [local physics audit](docs/PHYSICS_COMPATIBILITY.md) records the separate
cloth proxy, mapping and rig requirements that a jiggle prototype must preserve.

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

1. Verify the current private body studies in game, including heads, attachments and distance transitions.
2. Cover reviewed global and level-local NPC instances and additional body families.
3. Author compatible LODs, texture variation and broader deterministic distribution.
4. Match physics to the bodies, then test animation, collision and performance.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the data model and sources.
