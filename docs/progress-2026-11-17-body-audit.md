# Body source audit, 2026-11-17

This audit creates cache exports only. It does not enable a body, modify active
mods, or establish in-game acceptance. Third-party meshes and derived test exports
remain outside this repository under `C:\Users\hundo\.cache\nudegate\bcb-analysis`.

## Additional BCB sources

| Family | Cache COLLADA | Position / skin vertices | Triangles |
| --- | --- | ---: | ---: |
| Human/elf, active high-poly | `HUM_F_NKD_HighPolyTest_KEL.dae` | 9,424 | 18,828 |
| Githyanki, normal female | `gith.dae` | 8,044 | 16,068 |
| Tiefling, normal female | `tiefling.dae` | 7,768 | 15,502 |

Each export contains one body mesh, one skin controller, 82 named skin joints and
no morph controllers. These are normal female sources, not strong female sources.

The githyanki resource is `b7bfa2d3-4dad-d8a3-8639-9e3dddb97a00`, material
`1c7022af-5d72-61b2-e49e-766148eb14c6`, source
`Generated/Public/BCBPak/Assets/Characters/_Models/Githyanki/_Female/Resources/GTY_F_NKD_Body_A.GR2`.
It exports an internally named `HUM_F_NKD_Body_A_Mesh`, despite the githyanki
resource's `GTY_F_NKD_Body_A_Mesh` object references. Verify and rewrite object
references against the newly exported GR2 rather than copying these references.

The tiefling resource is `820ddd41-7946-f026-099f-7034983d50d2`, material
`b3b205a0-3570-c06c-65a9-df9b95afc435`, source
`Generated/Public/BCBPak/Assets/Characters/_Models/Tieflings/_Female/Resources/TIF_F_NKD_Body_A.GR2`.
Its SkeletonResource is `3c9f7092-5cf2-4ec8-f974-1b81a70f47da`.

Githyanki and human inverse-bind matrices match within 0.000001, but their neck
positions differ. Tiefling inverse-bind matrices differ from human despite
identical joint names. Preserve each family's own mesh, materials, bind matrices,
body shape and character attachments; matching bone names alone is insufficient.
BCB resource metadata declares five LOD objects for githyanki/tiefling, while these
exports each contain one mesh. LOD coverage needs explicit authoring/verification.

## Numeric authoring observations

Coordinates below are the untransformed LSLib-exported mesh coordinates. Height
is +Y and the chest faces toward negative Z. Do not apply +Z-forward assumptions.

- Human high-poly bounds: X ±0.720558, Y -0.006811 to 1.573211,
  Z -0.182018 to 0.158465.
- Candidate chest authoring window: `0.02 < abs(X) < 0.165`,
  `1.26 < Y < 1.49`, `Z < -0.065`, with a smooth falloff and a Chest_M weight
  check. This is an inspection window, not an approved deformation mask.
- Frontmost BCB human chest samples are approximately X ±0.1048, Y 1.3662,
  Z -0.1820; tiefling samples are approximately X ±0.1033, Y 1.3662, Z -0.1814.
  Identifying a nipple region needs topology/visual review, not just a minimum-Z test.
- Preserve the neck and collar above Y 1.50. Vertices with Neck_M weight ≥0.5
  lie at Y 1.5473–1.5663; githyanki has its own neck coordinates.
- Wrist_L/R weight ≥0.5 lies at abs(X) 0.5563–0.6601,
  Y 1.1399–1.2154. Chest edits should remain far inside this region.
- BCB posterior extremities lie around X ±0.097, Y 0.953, Z +0.158.
  Hip edits need separate bounds and protection of genital, leg and tail seams.

## Matched jiggle sources

The installed The Jiggle Is Up supplied independently matched body/proxy sources:

| Family | Cache path | Body vertices / triangles | Proxy vertices / triangles |
| --- | --- | ---: | ---: |
| Human | `jiggle/HUM_F_matched_cloth.dae` | 8,044 / 16,068 | 773 / 1,494 |
| Githyanki | `jiggle/GTY_F_matched_cloth.dae` | 9,023 / 18,026 | 773 / 1,494 |
| Tiefling | `jiggle/TIF_F_matched_cloth.dae` | 7,768 / 15,502 | 773 / 1,494 |

The source GR2 paths are under
`Mods/The_Jiggle_Is_Up_7c842b2b-874a-0d28-aafc-1b55c106856d/Data/Blender Exports/`
with names `{HUM,GTY,TIF}_F_NKD_Body_A_one_cloth_mesh.GR2`.
Body and proxy exports preserve their own skin controllers, vertex colors and
scene-node LSTools extras: ExportOrder, `Cloth`, and proxy `ClothPhysics` flags.

The human matched GR2 -> DAE -> GR2 -> DAE round trip retained both mesh counts,
triangle counts, two skin controllers, color-array counts and these flags.
Output is `jiggle/HUM_F_matched_roundtrip.GR2` and `.dae`. A direct COLLADA edit
can preserve these extras; an arbitrary Blender export must not silently drop them.

Human, githyanki and tiefling matched chest tips reach approximately Z -0.1593,
-0.1485 and -0.1601 respectively, compared with BCB's -0.1820/-0.1820/-0.1814.
The matched body/proxy pair is a plausible local starting point for physics
variants; it is not BCB shape with physics already attached. Deform corresponding
body/proxy regions together, retain topology, and verify the mapping and constraints.
The LSF `NbClosestVertices=2400` is a mapping property, not the proxy vertex count.

Vanilla meshes were located in `Models.pak`, but the installed Divine build cannot
decode their compressed GR2 without `Granny2.dll`. No compatible DLL was found in
the inspected local tools, Blender, Desktop or Downloads directories. BCB and the
matched jiggle exports above do not encounter that decompression dependency.
