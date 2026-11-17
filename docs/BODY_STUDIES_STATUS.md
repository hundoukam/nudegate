# Body study progress, 2026-11-17

**0.2 update:** the current build has 35 body files across five normal/strong
female families and seven profiles, containing 91 LOD geometries. The larger
female sources retain all five native LODs. Experimental new-Tav support covers
27 compatible presets using 25 private roots; optional skin presentation uses
six private materials. See [soft female frames](PLUSH_FRAMES.md) for current
scope and limitations. The first-batch results below are retained as history.

There are now **18 actual exported GR2 body studies**, not placeholder body names.
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

These studies contain one exported LOD each. In-game appearance, heads/anatomy
attachments, animations, distance transitions, performance and save reloads
still need acceptance testing. No new jiggle physics are included. The matched
body/proxy sources located during this work provide a separate next step for
physics authoring; they are not silently applied to these BCB-derived shapes.

Meshes and local study packages derive from the user's supplied BCB archive and
stay outside the public source repository. The committed files are authoring
code, source fingerprints, parameter profiles, tests and documentation.
