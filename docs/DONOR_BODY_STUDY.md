# Selected Blender body study

Six selected donor states now have individually validated **offline GR2 body,
native breast-cloth proxy and private new-Tav packages**. These prototypes target
the matched BG3 human-normal female rig. Other skeletons, broad NPC distribution
and successful physics in game remain outside this acceptance.

Original Blender files, frozen captures and earlier smaller-body collections
remain unchanged. Generated assets and packages stay local and outside Git.

## Selected states and packages

| Source | Selected authored state | Body vertices / triangles | Folder under `build/donors` |
| --- | --- | ---: | --- |
| Mercy C | Large, `TitsSkey = -1` | 14,933 / 26,168 | `mercy-cc-probe` |
| Juno B | Medium, `Big.Tits = 0.5` | 39,070 / 73,154 | `juno-b-coherent-cc-probe` |
| Juno E | `Chubby = 1`; reviewed breast-key defaults | 38,945 / 73,108 | `juno-e-cc-probe` |
| Cinderella A | Reviewed default, including recorded reset keys | 34,170 / 64,390 | `cinderella-cc-probe` |
| Kiriko 2.0 C | Large, `BreastSize = 1` | 34,271 / 63,364 | `kiriko-cc-probe` |
| Jubilee, Marvel Rivals B | `PBMBreastsSize = 0.5`, `FBMHeavy = 0` | 55,693 / 103,386 | `jubilee-cc-probe` |

Each folder contains a `.pak` and `probe-report.json` binding the model, mapping,
surface proofs and compiled resources. The local consolidated index is
`build/donors/accepted-six-donor-validation-index.json`; it records all six
accepted stage paths, fingerprints and individual body/proxy/winding results.
Earlier failed or superseded studies remain separate.

Each package creates five private roots and five private visuals for five
explicitly reviewed adult normal-human female creation presets, with **zero
original NPC root overrides**. Test **one donor package at a time**: these
alternatives use the same probe folder and character-creation records. They are
not six simultaneously selectable bodies in one package. Existing saves are
not supported by this new-character probe.

Detailed source exports are frozen in `build/donors/selected`. The older shaded
gallery used regularized mannequins, which are not conversion inputs. Kiriko
requires the verified Blender 5.2 loader; invalid older-loader outputs remain
quarantined.

## Preserved shape and explicit changes

The pipeline retains the selected author's dense sculpt and shape settings.
It applies one uniform placement, explicit neutral limb posing, a local head
cut and a bridge to BG3's exact 18-point collar. Sources already include their
saved pose, so rest-to-pose skinning is not applied twice. Reports disclose
the additional operations:

- **Source-support fields:** Mercy, Juno E and Kiriko use their own anatomical
  bone hierarchy and smooth fields to retain original central anatomy during
  posing. E also restores its original proximal shoulder/axilla surface while
  actual elbow, wrist, knee and ankle neighborhoods, hands and feet remain exact
  to its reviewed limb-pose baseline. Weak breast-weight tails on arms are
  distinguished from the breast surface.
- **Cinderella:** a separate, fingerprinted pelvic pose correction moves 17
  source vertices by less than 0.8 mm, with breast, silhouette, hand/foot and
  neck protection checked. It is a local pose repair, not a new chubby sculpt.
- **Kiriko:** her seven-spine rig and independent toe chains are mapped
  explicitly. Native segment endpoints are fitted through longitudinal limb
  adjustments that preserve cross-sections, followed by source-support guards.
  This does not prove animation or hand/prop contact in game.
- **Float32 conditioning:** explicitly enumerated nanometre-scale changes on
  Jubilee's hand and Kiriko's toenail copies preserve microscopic clearance in
  the serialized format. Configurations under `config/float32_conditioning` pin
  the data; unrelated fields stay exact. Fresh complete audits follow, with no
  relaxed predicates or pair exceptions.
- **Neck winding:** coherent bridge orientation fixes Juno B/E shading defects
  without moving accepted neck vertices or changing source body triangles.
  Coherent winding is now the preparation default. Explicit
  `--legacy-radial-neck-winding` reproduces old archives; original B models and
  packages remain preserved separately.

Skin captures retain complete frozen geometry and UV arrays byte-for-byte.
Separate recorded skin repairs handle Mercy's unused orphan vertex and Kiriko's
four tiny negative weight residuals. The Juno profiles also reassign the same
17 reviewed stray tongue influences on the hips to the native root. These skin
repairs do not change positions. The native skeleton, joint transforms and
binding order remain intact; per-bone bounds are rebuilt for the actual body.

Cinderella A retains its saved wardrobe-compression settings. An **optional,
separate uncompressed study** disables only the three verified authored controls
`Boobpress`, `Boba marcas bikini parche` and `thihhs`. It is not the selected A
default and is not one of the final six physics probes.

The original 35-body collection and smaller-body archives under
`build/collections/classic-small-v0.1` and
`build/collections/pictured-normal-v0.1` remain intact.

## Physics setup and verification

Each donor has its own fitted native breast-cloth simulation patch and rebuilt
render-to-proxy map. The same verified field fits the disposable native UV/paint
lookup where needed; it does not replace the dense donor sculpt. Native solver
settings and paint semantics are retained. Mapping behavior was reproduced
byte-for-byte against all five original matched native models.

All six actual serialized bodies pass their own complete source comparison:
**zero introduced intersection pairs, zero bridge contacts, zero collapsed
faces and zero bridge winding conflicts**. Each actual serialized proxy has
zero absolute intersections and collapsed faces; its authoring field has
positive sampled flow Jacobians. Actual GR2 buffers, skin/paint bytes, rig,
material groups and bounds are read back and checked. Package extraction and
compiled resource readback verify integrity and private UUID isolation.

The authored sources contain existing intersecting surfaces. Each accepted
state uses **one independently searched baseline of that same original state**
after uniform placement and Float32 conversion, before pose correction or neck
operations. Existing authored and format-created contacts remain reported.
Unquantized comparisons are retained separately; their pair sets are never
unioned into a larger exception list. The index and per-stage
`global-serialized-*-audit.json` reports contain exact counts and evidence.
These are rest-mesh checks, not collision-free animation proofs.

## Remaining work

The user chose to continue offline. These six packages are built and verified
locally, not installed for a successful game test. Runtime jiggle, materials,
head/neck appearance, anatomy attachments, animation and prop contact,
performance and distance/LOD behavior remain unverified. Each dense body has
one authored render LOD. Projected native UVs and missing local donor textures
also leave skin presentation provisional.

This is the native breast-cloth setup only. New gravity or squeeze controls and
donor `+100`/`+200` breast sliders are **not implemented**. Larger variants should
use reviewed authored states; the earlier procedural `+200` shape is not
promoted into this path. Further body-family support and adult NPC rollout
remain future work.

An earlier reversible Juno B creation test exited before a game window appeared;
Steam showed its sign-in screen. No authentication was automated. Original mod
settings were restored byte-for-byte and the temporary package was removed;
no save was loaded or written. Records remain in `build/donors/runtime-juno-b`.

## Reproduction tools

`tools/export_blender_donors.py` captures reviewed states with scripts disabled
and checks original files before and after. Skin-group capture requires frozen
geometry parity. Duplicate group labels retain separate indices, matching
[Blender's per-index armature mapping](https://github.com/blender/blender/blob/v4.5.0/source/blender/blenkernel/intern/armature_deform.cc#L504).
Out-of-range weights block normalization until explicit repair. Jubilee's
frozen-UV option retains original UV bytes after geometry/loop-order checks.

Donor-specific preparation tools record calibration, semantic skin mapping,
pose guards and local neck operations. `tools/fit_native_donor_proxy.py` authors
the matched proxy/lookup field. `tools/donor_mesh_export` writes the dense render
mesh while preserving the native rig and fitted proxy.
`tools/build_donor_probe.py` requires accepted, hash-bound model, mapping and
surface reports before creating private character-creation resources. Example:

```powershell
python tools/build_donor_probe.py `
  --export-report build/donors/juno_b_coherent_neck_v3/export/HUM_F_NKD_Body_A_one_cloth_mesh.GR2.report.json `
  --mapping-report build/donors/juno_b_coherent_neck_v3/export/HUM_F_NKD_Body_A_one_cloth_mesh.GR2.mapping.json `
  --surface-audit build/donors/juno_b_coherent_neck_v3/global-serialized-float32source-surface-audit.json `
  --output build/donors/juno-b-coherent-cc-probe
```

This builds local artifacts without installing them. See
[the physics audit](PHYSICS_COMPATIBILITY.md) for native format and rig details.
