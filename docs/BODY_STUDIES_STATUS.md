# Body study progress, 2026-11-17

**0.3 work:** an additive collection preserves the original 35 meshes and adds
Curvy soft, Chubby, Soft pear, Defined abs and Fantasy bust bases. Independent
size additions and native strong-frame SOFT/DEFINED texture styles use separate
private resources. See [the variety expansion](VARIETY_EXPANSION.md) and
[skin validation](SKIN_STYLES.md) for current scope. Earlier counts below refer
to their original batches.

The skin-style build and expanded validation tooling are implemented. New body
geometry remains under visual review: source-preserving static-drape prototypes
are local studies, with donor-model transfer now being evaluated. No complete
new capped grid or finalized 0.3 package has been published. The original 35
meshes remain unchanged.

The [selected Blender donor path](DONOR_BODY_STUDY.md) has now produced its first
dense Juno medium new-Tav package with a native cloth proxy and rebuilt mapping.
It preserves the authored body surface and uses a local native neck bridge.
In-game appearance and motion remain unverified. The six selected source states
and the exact preserved smaller-body archives are separate from this prototype.

**Preserved smaller-body catalog:** all six earlier profiles for normal
human/elf, githyanki and tiefling bodies are retained for initial in-game review.
The user's clarification applies to the whole smaller-body range; enlarged
proportions are the current visual concern. Exact DAE/GR2 files, sources and
preview scenes/images are frozen under `build/collections/classic-small-v0.1`
(18 bodies, 49 hash-checked files). Its manifest SHA-256 is
`66a091094990d399333a4fe0eca2ccfcbe95b183633c68bad2f31b3928186458`.
The earlier pictured human/elf-only snapshot remains unchanged under
`build/collections/pictured-normal-v0.1` (six bodies, 18 hash-checked files).
Both archives preserve the original exports directly; the current configuration
contains later recipes and must not be used to recreate these exact versions.
The separate 0.2 archive also retains its 21 normal-frame bodies within the
unchanged 35-body collection. This is visual feedback, not in-game acceptance.
Future Blender donor work uses separate outputs. Verify the complete earlier
small-body archive with
`python tools/freeze_collection.py --verify --output build/collections/classic-small-v0.1`.

**0.2 update:** that build has 35 body files across five normal/strong
female families and seven profiles, containing 91 LOD geometries. The larger
female sources retain all five native LODs. Experimental new-Tav support covers
27 compatible presets using 25 private roots; optional skin presentation uses
six private materials. See [soft female frames](PLUSH_FRAMES.md) for current
scope and limitations. The first-batch results below are retained as history.

The initial batch produced **18 actual exported GR2 body studies**.
Six profiles were baked separately for human/elf, githyanki and tiefling normal
female sources. Each retains its own source geometry, materials and bind data.

| Profile | Chest projection scale | Local surface diameter scale | Main silhouette change |
| --- | ---: | ---: | --- |
| Lean | 0.65 | 0.85 | Smaller chest, narrower hip/waist |
| Athletic | 0.82 | 0.90 | Reduced chest, fuller upper legs |
| Source proportions | 1.00 | 1.00 | Unchanged source positions |
| Full | 1.22 | 1.10 | Fuller chest, mild hip/thigh increase |
| Soft | 1.12 | 1.25 | Fuller waist, hips and thighs |
| Voluptuous | 1.48 | 1.35 | Largest chest projection with fuller hips |

Scales control bounded local geometric fields; falloff and locked regions keep
attachments fixed. Projection, diameter and local tip-depth controls are separate.
Texture-based areola color/diameter variants are not included.

## Export acceptance

All 18 meshes passed the following checks on the local source build:

- Original indexed topology and skin influence indices retained.
- Joint names/order, skin weights, bind-shape and inverse-bind matrices checked.
- Original corner UV coordinates retained exactly after GR2 export/import.
- Maximum round-trip position drift: `0.000000864` metres.
- Neck, wrist, ankle, outer-arm and central pelvic protected positions unchanged.
- No introduced reversed or collapsed faces; an independent stricter scan also
  found no face shrinking below 10% of its source area.
- Smooth UV seam normal disagreement below `0.019` degrees after GR2 export.
- Private VisualBank resource package extracted and verified after packing.

A normal rebuild originally introduced visible UV seams. This was corrected by
sharing normals only across source-established smooth splits and retaining
original normals in untouched neighborhoods. Hard edges remain distinct.

## Local artifacts

- `build/bodies/body-build.json`: per-source/per-variant measurements and checks.
- `build/bodies/body-comparison.png`: six human/elf front and side studies.
- `build/bodies/gith_f/body-comparison.png`: corresponding gith studies.
- `build/bodies/tiefling_f/body-comparison.png`: corresponding tiefling studies.
- Matching `.blend` comparison scenes beside each PNG.
- `dist/Nudegate-0.1.0-body-study.pak`: optional local appearance test package.
- `dist/body-study-report.json`: exact private resources and adult assignments.

The package contains 18 meshes and 24 private body visual resources (human/elf
material aliases have separate resources). Current compatible adult assignment
is limited to Lae'zel and Minthara's normal/vanity roots. Minthara's two roots use
one identity seed to avoid changing body when her outfit mode changes. Children
and unsupported body families retain their existing resources.

These initial studies contain one exported LOD each. In-game appearance, heads/anatomy
attachments, animations, distance transitions, performance and save reloads
still need acceptance testing. No new jiggle physics are included. The matched
body/proxy sources located during this work provide a separate next step for
physics authoring; they are not silently applied to these BCB-derived shapes.

Meshes and local study packages derive from the user's supplied BCB archive and
stay outside the public source repository. The committed files are authoring
code, source fingerprints, parameter profiles, tests and documentation.
