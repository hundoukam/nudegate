# Selected Blender body study

The donor path preserves the author's selected body surface and authored shape
keys. Original Blender files and earlier smaller-body collections stay unchanged.
Generated meshes, packages, scenes, textures and source exports remain local and
are excluded from Git.

## Selected states

| Source | Selected state | Authored key setting |
| --- | --- | --- |
| Mercy | C, large | `TitsSkey = -1` |
| Juno | B, medium | `Big.Tits = 0.5` |
| Juno | E, chubby | `Chubby = 1`; breast size keys at their reviewed defaults |
| Cinderella | A, default | Reviewed default, including the recorded reset keys |
| Kiriko 2.0 | C, large | `BreastSize = 1` |
| Jubilee, Marvel Rivals | B, medium | `PBMBreastsSize = 0.5`, `FBMHeavy = 0` |

All six states have detailed, unsmoothed source exports in
`build/donors/selected`. The older shaded gallery used regularized mannequins;
those are not conversion inputs. The export manifest pins the originals and
exact presets. Kiriko requires the verified Blender 5.2 loader; invalid
older-loader outputs are quarantined.

All six also have skin-group captures whose complete frozen geometry and UV
arrays match byte-for-byte. Captures are write-once. Enumerated skin-only repairs
are separate outputs from `tools/repair_donor_skin_capture.py`: Mercy's one
unreferenced orphan vertex receives a placeholder that is removed during mesh
compaction; Kiriko's four tiny negative weight residuals become zero. No body
positions or UVs change in these repairs.

Mercy C and Cinderella A now have dense fitted geometry studies with their own
calibration and native collars. Each uses its original authored body surface.
Juno E's chubby study and fitted proxy remain held because its neutral-pose
adaptation introduces new contacts. These later bodies do not yet have accepted
physics packages; their local audit reports determine each candidate's status.

## First packaged body: Juno B

The experimental new-Tav package is
`build/donors/juno-cc-probe/Nudegate-donor_juno_b-creation-probe.pak`.
Its report records private IDs and source fingerprints. It covers five compatible
adult normal-human female creation presets and emits no NPC patches.

The body contains **39,070 vertices and 73,154 triangles**. Preparation uses a
uniform scale and source-weighted limb pose correction. The dense donor surface
and authored breast shape are retained. Only the head cut and local neck bridge
change topology; the collar uses BG3's exact 18-point native connection.

The source is already posed, so rest-to-pose skinning is not applied twice.
Deform weights are normalized separately from unrelated wardrobe masks.
Seventeen reviewed stray tongue influences on the hips are reassigned to the
native root, with geometry and other weights unchanged. The model retains the
native skeleton, binding order and rig matrices. Bone bounds are rebuilt for
the actual body. Source limb lengths remain unchanged; the resulting wrist and
ankle anchors differ by about 2 cm from native joints. Hand/prop contact and
animation fit therefore still require review.

### Jiggle

The package includes the fitted native cloth proxy and a new dense-body map.
The mapping implementation was checked byte-for-byte against all five original
matched native models. Original solver settings are retained. This establishes
the serialized setup, not successful motion in game.

New gravity controls, hand contact and squeeze behavior have not been ported.
Each later body needs its own fitted proxy and mapping. Static renders do not
demonstrate physics.

### Verification and limits

Checks bind the actual prepared arrays to serialized GR2 buffers and the final
package. Float32 positions match the intended conversion byte-for-byte.
Topology, skin bytes, proxy records, material groups and rig data are checked
after serialization. Package extraction reproduces every staged file exactly;
compiled visual resources are read back.

The original source already contains intersecting surfaces. A complete search
of that source represented in the game's Float32 format provides the baseline
before pose correction or the neck cut. The final body has zero introduced
intersection pairs, zero bridge contacts and zero collapsed faces relative to
that baseline. The unquantized-source comparison is also retained: Float32
conversion itself creates two submicron contacts. These checks do not establish
collision-free animation.

Skin mapping is provisional. Original Juno texture files are missing locally,
and projected native UVs show checker distortion. In-game skin appearance,
head/neck shading, motion, distance behavior and performance are unverified.
There is currently one authored render LOD.

A reversible character-creation test was attempted on 2026-11-17. Both installed
game executables exited before exposing a game window; Steam exposed its sign-in
screen. No authentication was automated. Original mod settings were restored
byte-for-byte and only the exact temporary probe package was removed. No saved
game was loaded or written. Test records are in `build/donors/runtime-juno-b`.

## Tools

`tools/export_blender_donors.py` captures a reviewed state with scripts disabled
and checks the source before and after. Optional sparse skin groups are added
only after proving all frozen geometry arrays are bit-identical.
Duplicate source group labels retain their distinct indices, matching
[Blender's per-index pose-channel mapping](https://github.com/blender/blender/blob/v4.5.0/source/blender/blenkernel/intern/armature_deform.cc#L504).
Finite out-of-range source weights are recorded verbatim and block skin
normalization until explicitly repaired. Kiriko has four tiny negative weights
in the evaluated source. Jubilee's repeated subdivision evaluation changes a
few UV values by at most `2.3842e-7`; its explicit frozen-UV option retains the
original UV bytes after exact geometry and loop-order checks.
`tools/prepare_donor_body.py` currently implements the Juno rig's pose, neck and
attribute preparation. Other rigs require their own semantic joint review.

`tools/donor_mesh_export` writes the actual dense render mesh while retaining
the matched native rig and fitted proxy. `tools/build_donor_probe.py` requires
hash-bound export, mapping and accepted surface-audit reports before creating
private character-creation resources.

```powershell
python tools/build_donor_probe.py `
  --export-report build/donors/juno_actual_nativehips_v2/export-f64roundtrip/HUM_F_NKD_Body_A_one_cloth_mesh.GR2.report.json `
  --mapping-report build/donors/juno_actual_nativehips_v2/export-f64roundtrip/HUM_F_NKD_Body_A_one_cloth_mesh.GR2.mapping.json `
  --surface-audit build/donors/juno_actual_nativehips_v2/global-serialized-float32source-surface-audit.json
```

This builds local artifacts without installing them. Future large variants use
the authors' own shape-key states; the earlier procedural +200 chest deformation
is not promoted into this path.
