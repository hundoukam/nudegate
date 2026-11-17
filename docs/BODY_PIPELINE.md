# Body variety and physics pipeline

Nudegate's initial appearance compiler preserves each approved adult's existing
body. The included offline morph authoring library is a foundation for making
variants; it is not a completed body pack, physics pack, or universal in-game slider.

## Reference sources

- User-linked [Enhanced Nude Bodies, Nexus 652](https://www.nexusmods.com/baldursgate3/mods/652?tab=files)
  is a different mod from the supplied BCB archive. Its files page was inaccessible
  through the research browser; no ENB mesh or current permissions were inspected.
- Supplied archive: `BCBPak 2351 3.17 2026-08-02T18-40Z AghPHzjQD.zip`, associated
  with [Nexus 2351](https://www.nexusmods.com/baldursgate3/mods/2351).
  Its metadata names author Sindae, module `BCBPak`, UUID
  `1d24059d-ff23-4a79-8892-57c85d512416`, description "A curvy body and clothes".
- The ZIP contains `BCBPak.pak` and `info.json`. The PAK has 717 files: 709 GR2,
  three LSF, one LSX, one LOCA, and three stats text files. It bundles no license
  or README; redistribution/modification terms were not established by this audit.

These are reference sources or optional locally installed dependencies. Nudegate
does not embed their meshes, textures, physics binaries, or extracted resource banks.
Keep analysis exports and third-party assets outside Git and release packages.

## Verified BCB geometry

The active normal female human/elf visual points to
`Generated/Public/BCBPak/Assets/HUM_F_NKD_HighPolyTest_KEL.GR2`, rather than the
older-looking `HUM_F_NKD_Body_A.GR2` also included in the archive.

LSLib 1.20.4 exported that active GR2 to COLLADA successfully. The export contained
one mesh, 9,424 position vertices, 18,828 triangles, one skin controller and 82
skin joints. It had no morph controllers and no breast or nipple joints.
An unedited GR2 -> DAE -> GR2 -> DAE round trip retained the triangle count,
skin controller and 9,424 weighted vertices. Export logs reported 10,800 internal
output vertices after seam splitting; that differs from COLLADA position count.
This checks file conversion, not rendering, animation, seams, or physics in BG3.

BCB also includes normal female githyanki and tiefling body meshes. No strong
female nude body mesh was found in this archive. Do not treat its normal female
body as a compatible replacement for Karlach's strong tiefling body.

## Authoring owned variants

1. Begin with an owned or otherwise permitted source mesh for one supported adult
   rig. Create explicit breast-volume, breast-shape and nipple-proportion targets
   in Blender or as validated offline displacement fields.
2. Keep shape keys as authoring data. Bake selected combinations to distinct GR2
   meshes; the inspected BCB mesh supplies no runtime morph/slider interface.
3. Preserve neck, wrist and ankle seams; UVs, materials and skin weights; skeleton
   names and bind transforms; vertex masks, LOD coverage and genital alignment.
4. Give every output mesh and VisualBank resource private Nudegate paths/UUIDs.
   Reference them from exact approved adult appearances. Do not override shared
   vanilla body UUIDs globally or infer adulthood from race, size or missing tags.
5. Catalog race, body shape, rig, material compatibility, source provenance and
   verification status. Choose only compatible verified variants using a stable
   per-character seed. An unknown or mismatched combination retains its original.

The authoring library can validate deformation inputs and preserve protected
regions. Finished variants still require mesh review, export checks and in-game
acceptance before entering the enabled body catalog.

## Physics is a matched asset set

BCB's inspected human VisualBank entry has no `ClothParams`; its
`ClothProxyMapping` contains empty `..0` through `..10` keys. Its existing
`SoftbodyResourceID` reference alone does not demonstrate functioning jiggle.

The locally installed **The Jiggle Is Up** uses a GR2 cloth proxy, LSF
`ClothParams`, and a compressed `ClothProxyMapping` correspondence. The inspected
human mapping specifies `NbClosestVertices=2400`. Damping, stiffness, solver
frequency and other parameters live in that LSF entry. The bundled `.xml` files
are exporter `SceneSettings`, not the runtime physics definition.

BCB and The Jiggle Is Up override 13 identical VisualBank UUIDs, including human
`db6e5918-8514-4dcc-8363-e8fd3c50cce5`, elf
`9e43f0e4-d063-d85c-87b4-470d569645db` and githyanki
`b7bfa2d3-4dad-d8a3-8639-9e3dddb97a00`. Effective load order selects competing
definitions; installing both does not combine BCB shape with Jiggle physics.

The installed **GreatTits** takes another route: item-mounted meshes, a remapped
custom skeleton, and `HUM_F_Breast_B_Spring.bin`. Skeleton UUID
`b6403b69-1277-104a-2087-51a5457b7ac2` references spring resource
`a87d78f5-d9ad-6820-2d55-33d8c5d155c2`. It is not a general NPC body slider.

Custom jiggle variants need their own matched geometry, proxy or spring setup,
mapping and colliders. Regenerate or verify correspondence after deformation;
copying an unrelated proxy map or exposing a strength number is insufficient.
Test walking, running, combat, dialogue, ragdolls, distance/LOD transitions and
save/reload behavior, including crowd performance, before claiming support.

## Current verification boundary

Archive inspection, resource conversion and the unedited mesh round trip were
performed in a separate cache. No game files or active mods were changed during
the audit. Custom shape variants, integrated physics and in-game body-variety
behavior remain unverified and are not supplied by the initial appearance pack.
