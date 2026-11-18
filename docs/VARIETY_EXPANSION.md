# Additive body collection

The original 0.2 collection is preserved as 35 unchanged meshes in
`build/collections/original-v0.2`. Its integrity ledger covers 82 files,
including sources, authoring meshes, GR2 exports, the old package, configuration
and comparison images. Check it with:

```powershell
python tools/freeze_collection.py --verify
```

The new collection uses separate configuration and output paths. Its five base
shapes are Curvy soft, Chubby, Soft pear, Defined abs and Fantasy bust. Normal
human/elf, githyanki and tiefling sources and larger human/elf and tiefling
sources remain separate families. The larger variants have their own hip,
thigh and chest balance; applying identical multipliers to both source frames
preserved the original proportional differences.

Broader overlapping fields connect the new waist, hips and thighs. The new
front-abdomen field extends lower than the old studies while protecting actual
mesh boundaries and the rear pelvic/tail region. A bounded paired fairing pass
smooths the normal-frame lower/medial attachment. The native larger-frame base
keeps its own contour. Tiefling raised back details have separate smoothing
protection. These changes apply only to the expansion collection.

New seam protection uses 12 mm of distance along the source surface, followed
by a smooth attachment feather. The previous two-ring default remains available
for the legacy pipeline; on a very coarse LOD those two rings reached all the
way into the breast apex. True open boundaries and the explicit neck, wrist and
pelvic attachment zones remain protected.

## Base shapes and independent size additions

The current package grid caps the separate breast growth control at
0, +50 and +100 build buckets. The latest source-preserving prototypes use these
as nominal growth strengths. Their initial
linear growth factor is the cube root of `1 + percentage / 100`; attachment
falloff and static drape then shape the result. The labels do not promise an
exact volume percentage, a doubled front projection or a cup size. Actual
width, height, projection and downward displacement are measured per mesh.
The values are not equivalent deformation settings for NudePunk's different rig.

The local relaxed-shape prototype preserves the source breast shape and broad
attachment through a continuous growth field with relaxed static drape.
Bounded lower-corner fairing smooths the normal-frame underside, while the
native larger-frame surface keeps its own contour. Source nipple and areolar
geometric relief and locked attachments are retained. The latest user review
still found the silhouette unnatural. Donor-model shape transfer is being
evaluated; the relaxed prototypes remain local and have not replaced the
experimental cage backend in `breast_sizes.py` / `breast_cage.py`.
Integration and full-grid export validation remain pending. The existing cage
backend uses an exact projection convention; it does not implement the nominal
growth/drape convention described above. An impossible combination raises an error
instead of being silently replaced by a smaller labelled size. The manifest
records the active backend's measurements, protected vertices and geometry checks.
The offline library retains +200 for experiments; current package validation
rejects those variants.

There is no finalized 0.3 variety package. The earlier 60-body smoke package and
report are quarantined under `dist/obsolete-60-body-smoke`; they predate the
attachment revisions and must not be treated as the current result.

Wall measurements use reviewed torso-surface landmarks, separately from the
base morph's internal pivot. A provenance-bound LOD0 calibration is reused by
lower LODs so a sparse simplification does not redefine the growth reference.

Only a completed requested grid is published as `body-build.json`. Checkpoints
and in-progress counts are separate, and resume validity includes source pins,
frame calibration, converter binaries and authoring/validation code. Completed
family batches can be joined with `tools/combine_body_batches.py`; it checks
their provenance and artifact hashes before publishing the full configured grid.

```powershell
python -m pip install -e ".[authoring]"
python tools/build_expansion.py --resume
python tools/preview_expansion.py --species tiefling --sheet variety
python tools/preview_expansion.py --species tiefling --sheet frames
python tools/preview_expansion.py --species tiefling --sheet chest
```

Authoring uses NumPy, Pillow and SciPy alongside the local model converter and
Blender preview renderer. Drape here means the authored resting mesh shape.
Runtime gravity, squeezing and new jiggle behavior are not implemented by this
collection; the generated game assets are static resources.

The source catalog fingerprints every admitted topology and position array.
Every exported body is imported again and checked for topology, skin weights,
bind matrices, corner UVs, positions and source-established smooth seams. The
larger families include all five native LODs and their original controllers.

The new collection also checks actual triangle intersections and collapsed
faces. A source-relative normal turn is reported separately: a rounded underside
can legitimately turn more than 90 degrees from its original direction. Source
normal direction alone is not used to accept or reject the new surface. The
intersection checker distinguishes expected shared-edge/vertex contact from
crossings and coplanar overlap, including crossings between adjacent faces.
It records exact preexisting source triangle pairs and rejects newly introduced
pairs. This is a floating point geometric check with explicit model-space
tolerances and adaptive exact predicates for ambiguous near-plane contacts,
not an animation or collision simulation. Proof hashes bind every
source and serialized authoring mesh, including each larger-frame LOD.

## Distribution and appearance

The package builder accepts multiple `--body-manifest` paths, merging matching
families without changing original variant IDs. With expansion bodies present,
deterministic identity hashes choose the base body and the chest bucket
separately, from the combinations actually present in the manifest. A legacy
collection used alone retains the previous selection behavior. This is a static
asset palette; runtime sliders are not implemented.

Pass both the frozen and completed expansion manifests when packaging:

```powershell
python tools/build.py --body-manifest build/collections/original-v0.2/body-build.json build/expansion/body-build.json --body-visual-bank "C:\path\to\combined-original-body-bank.lsx" --soft-material-banks "C:\path\to\native-material-bank.lsx" --skin-style-package build/expansion/skin-styles/package --skin-style-report build/expansion/skin-styles/skin-styles.json
```

Supply every native material bank needed by the selected families. Experimental
Tav creation additionally takes the native preset files with `--tav-presets`
and an exact body variant with `--tav-profile`.

New strong-frame bodies can use private SOFT or DEFINED texture styles. SOFT
reduces low-frequency abdominal normal detail inside a reviewed mesh-projected
mask. DEFINED retains native detail, with subtle geometry authored into the abs
base. See [skin styles](SKIN_STYLES.md) for the exact texture scope and validation.
The original collection keeps its previous private skin materials. Families
without a new texture style use the existing private material defaults and are
explicitly listed as fallbacks in the package report.

The optional new-Tav creation test accepts an exact variant ID, for example
`--tav-profile exp_curvy_b000`. It supports the reviewed smaller and larger
female sources through private roots. Existing-save and Magic Mirror behavior
remain unverified.

## Current limits

The clay comparison sheets show actual authored geometry with its exported
corner normals. Static triangle intersection and collapse checks are implemented
for every authored geometry. New jiggle, intersections during animated poses,
animation, attachment fit, clothing interaction, distance transitions and in-game
appearance still need acceptance work.

Adult root admission and child exclusions are unchanged. Compatible NPC body
assignment remains limited to reviewed Lae'zel and Minthara roots; this is not
yet game-wide NPC body distribution. Karlach's unique body is excluded from the
generic strong replacement.

The local 0.3 package and earlier alternatives share a module UUID; use one
Nudegate package at a time. Game-derived meshes, textures and packages remain
local and are excluded from Git.
