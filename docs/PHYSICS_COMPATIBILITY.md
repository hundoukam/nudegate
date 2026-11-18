# Jiggle compatibility audit

The original static Nudegate body pipeline exports skinned meshes without a
matched cloth setup. Installing **The Jiggle Is Up** alongside those meshes does
not turn their private body resources into that mod's matched cloth assets.
The six later donor probes include fitted native cloth setups; their runtime
motion remains unverified, as described in the progress section below.

This read-only audit inspected the locally installed archives and already
extracted COLLADA/resource banks on 2026-11-17. No game files, active mods,
approved body exports, skeletons, or physics parameters were changed.

## Inspected sources

The installed `The Jiggle Is Up.pak` is 39,708,749 bytes, SHA-256
`96c5df5f028509b5bb5076ddd7c683b4b18ec6ed1783b69cf14cd4b16e4e8728`.
Its module UUID is `7c842b2b-874a-0d28-aafc-1b55c106856d`; its local metadata
names TitaniaMods as author and gives `Version64=36028797018964007`.

The installed `BCBPak.pak` is 263,885,277 bytes, SHA-256
`abb53996163b64c7621cdb3c809e71b3248f60be8ffc6240c632a005c0f55d1e`.
The audited normal-frame sources are the same BCB source families used by the
body pipeline. Strong-frame comparisons use the pristine native exports.

Machine-readable measurements, complete joint names, positive weight totals,
resource attributes, source hashes, and mapping-buffer hashes are in the local
authoring cache:

```text
C:\Users\hundo\.cache\nudegate\physics-study\compatibility-evidence.json
```

The cache also contains `inspect_physics.py` and `compare_sources.py` used for
these measurements. Extracted third-party/game assets are not added to the
repository.

## Skeleton and skin weights

None of the ten inspected source documents has joints named for breasts,
nipples, a bust, or jiggle. There are therefore no separate breast-joint weights
to enable in these sources. The body and proxy controllers use ordinary torso
and limb joints.

Counts below are COLLADA indexed position records and triangles, not necessarily
welded surface vertices. “Weighted joints” means a joint has at least one
strictly positive skin weight.

| Source | Scene/controller joints | Body weighted joints | LOD 0 positions / triangles |
| --- | ---: | ---: | ---: |
| BCB human/elf normal | 82 | 65 | 9,424 / 18,828 |
| BCB githyanki normal | 82 | 65 | 8,044 / 16,068 |
| BCB tiefling normal | 82 | 65 | 7,768 / 15,502 |
| TJiU human normal | 82 | 65 | 8,044 / 16,068 |
| TJiU githyanki normal | 82 | 65 | 9,023 / 18,026 |
| TJiU tiefling normal | 82 | 65 | 7,768 / 15,502 |
| Native and TJiU human strong | 80 | 65 | 8,044 / 16,068 |
| Native and TJiU tiefling strong | 80 | 65 | 7,770 / 15,504 |

The two additional names in the 82-joint sources are `Shoulder_Twist_L` and
`Shoulder_Twist_R`. Both have zero positive body weights. The 65 positively
weighted joint names agree between each compared source pair. This joint-name
agreement does not establish compatible bind transforms or cloth mapping.

The TJiU proxies all have 773 indexed positions and 1,494 triangles. Their
positive skin influences are:

| Proxy family | Positively weighted joint names |
| --- | --- |
| Human normal, tiefling normal, human strong | `Chest_M`, `Spine1_M`, `Spine2_M`, `Scapula_L`, `Scapula_R`, `Shoulder_L_Twist_01`, `Shoulder_R_Twist_01` |
| Githyanki normal | Same list with `Spine1_M` absent |
| Tiefling strong | Human list plus `Neck_M` |

For example, all 773 human-strong proxy records have a positive `Chest_M`
influence, with weights up to 1.0; 552 also have a positive `Spine2_M`
influence. These are attachment/animation weights on the proxy, not independent
left/right breast-bone weights. Each proxy also contains a COLOR source with
six or seven distinct RGB values. Preserve this data; its exact solver meaning
was not established by this audit.

## The matched TJiU asset set

The runtime source paths begin with:

```text
Mods/The_Jiggle_Is_Up_7c842b2b-874a-0d28-aafc-1b55c106856d/Data/Blender Exports/
```

The supported filenames and resource records actually found locally are:

| Family | GR2 filename | VisualBank UUID | `NbClosestVertices` | `AnimDriveSpringForce` |
| --- | --- | --- | ---: | ---: |
| Human normal | `HUM_F_NKD_Body_A_one_cloth_mesh.GR2` | `db6e5918-8514-4dcc-8363-e8fd3c50cce5` | 2,400 | 600 |
| Elf normal, same human GR2 | same | `9e43f0e4-d063-d85c-87b4-470d569645db` | 2,400 | 700 |
| Githyanki normal | `GTY_F_NKD_Body_A_one_cloth_mesh.GR2` | `b7bfa2d3-4dad-d8a3-8639-9e3dddb97a00` | 2,382 | 500 |
| Tiefling normal | `TIF_F_NKD_Body_A_one_cloth_mesh.GR2` | `820ddd41-7946-f026-099f-7034983d50d2` | 2,400 | 600 |
| Human strong | `HUM_FS_NKD_Body_A_one_cloth_mesh.GR2` | `9725b3db-6e40-054b-dc49-b8e479bc0cba` | 2,391 | 700 |
| Elf strong, same human GR2 | same | `edb26736-c3d5-72a7-b69a-16b5720ba664` | 2,391 | 750 |
| Tiefling strong | `TIF_FS_NKD_Body_A_one_cloth_mesh.GR2` | `a89dc12f-f2d2-f66b-cb25-eebbaa429a25` | 2,400 | 600 |

These parameters describe the installed mod; they are not validated recommended
values for new or enlarged bodies. Each listed entry has solver frequency 30,
stiffness frequency 100, linear stiffness 1, bending stiffness 0, compression
limit 0.95, and stretch limit 1.05. Githyanki damping is `0.07 0.07 0.07`;
the other listed entries use `0.1 0.1 0.1`.

Each matched GR2 exports two geometries:

1. `PREFIX_NKD_Body_A_Mesh`, export order 0, `DivModelType=Cloth`.
2. `PREFIX_NKD_Body_A_Mesh_Cloth_Physics`, export order 1,
   `DivModelType=Cloth` and `DivModelType=ClothPhysics`.

For the human-strong file, the resource connections are exactly:

```text
Template:        .../HUM_FS_NKD_Body_A_one_cloth_mesh.Dummy_Root.0
Objects.ObjectID:
  HUM_FS_NKD_Body_A_one_cloth_mesh.HUM_FS_NKD_Body_A_Mesh.0
ClothProxyMapping.Object.MapKey / ClothParams.UUID:
  HUM_FS_NKD_Body_A_one_cloth_mesh.HUM_FS_NKD_Body_A_Mesh_Cloth_Physics.1
ClothProxyMapping.MapValue.Object.Name:
  HUM_FS_NKD_Body_A_one_cloth_mesh.HUM_FS_NKD_Body_A_Mesh.0
```

`ClosestVertices` is a compressed ScratchBuffer. The human-strong buffer
decompresses to 4,782 bytes / 2,391 little-endian uint16 values; human-normal and
tiefling buffers to 4,800 bytes / 2,400 values; githyanki to 4,764 / 2,382.
The buffers contain `65535` as well as smaller values. The native-pair
correspondence and sentinel are now reproduced as described below; they are not
a simple one-index-per-raw-proxy-vertex array.

The listed TJiU entries have blank `SkeletonResource`,
`AttachmentSkeletonResource`, and `ClothColliderResourceID`, with
`NeedsSkeletonRemap=False`. They do not specify a replacement skeleton UUID.
Their `SoftbodyResourceID` values reference native resources:

| Families | `SoftbodyResourceID` |
| --- | --- |
| Human/elf/tiefling normal | `e96eed75-850b-4497-b077-a8f62f731bf3` |
| Githyanki normal | `15827dce-b0c0-c740-541b-03633a5a9c6d` |
| Human/elf/tiefling strong | `aad0d538-f1ce-e669-7728-ec54575c0076` |

The last ID resolves in the native human-strong `PhysicsBank` to
`HUM_FS_Softbody`, source
`Public/Shared/Assets/Characters/_Anims/Humans/_FemaleStrong/HUM_FS_Softbody.bin`.
That 9,051-byte binary was subsequently extracted from `Models.pak` and decoded
with the isolated LSLib 1.20.4 `PhysicsTool.exe`. It contains one material and
12 `RigidDynamic` capsule actors, **all with `Kinematic=true`**: Root, both Hips,
Spine1, Spine2, Chest, both Scapulas, both Shoulders, Neck and Head. There is no
independent dynamic breast actor and no forearm/hand actor in this resource.
`DisableGravity=false` on these kinematic actors is not a breast-sag control;
cloth dynamics remain a separate part of the matched proxy setup. Blank explicit
cloth-collider fields do not prove absence of collisions.

The cached decoded XML is
`C:\Users\hundo\.cache\nudegate\physics-study\native-softbody\HUM_FS_Softbody.xml`.
The exact source BIN SHA-256 is
`ee47acf5490e575d0d7986805b21b7327f608bbce38eaea56c5a8334223338a2`;
the decoded XML SHA-256 is
`68f4df093af63a8f2a477fdb93e283f127f39229d01a88a5063de63146b0d1f5`.
An XML→BIN→XML cache-only test was readable, with two quaternion components
changing by at most `1.2e-7`; it was not byte/semantic identity. No collider
resource was changed in the game or in a generated mod package.

The complete local TJiU archive list has 164 entries: 94 GR2, 47 LSF, 21 XML,
one metadata LSX, and one image. It supplies no separate skeleton or physics BIN
file. The inspected XML sidecars contain exporter `SceneSettings`, not the
cloth solver parameters above.

## Why the current shapes are not a drop-in combination

The inspected BCB normal visual resources contain no `ClothParams`. Their
`ClothProxyMapping` entries are empty `..0` through `..10` keys; their existing
softbody/collider references alone do not provide TJiU's cloth implementation.
BCB and TJiU also redefine the same normal body VisualBank IDs in the table.
Load-order selection of one definition does not merge their geometry and
physics fields.

The three BCB normal body position multisets differ from their TJiU counterparts
at six-decimal source-coordinate precision. Human and githyanki also have
different position/triangle counts. A TJiU proxy/map cannot be declared matched
to these BCB shapes merely because the skeleton joint names agree.

Strong-frame TJiU LOD 0 and pristine native LOD 0 do have equal position
multisets and orientation-independent coordinate-triangle multisets at that
precision. This comparison ignores vertex ordering and is not an ordered
topology, UV, or skin-matrix equivalence proof. Their scene joint-local matrices
also differ, including weighted joints. For example, the largest single matrix
component difference is 1.964456. This is a matrix-component comparison, not a
world-space displacement. Equivalent posed skinning has not been demonstrated.

The native strong body exports retain five LODs. The inspected TJiU matched
GR2s contain one render body plus one physics proxy. There is no audited
five-LOD cloth setup to copy onto the current native five-LOD variants.

`src/nudegate/body_resources.py` deliberately rejects `Cloth`/`ClothPhysics`
geometry and source VisualBank records containing `ClothParams` or
`ClosestVertices`, with a matched-physics-builder error. It reports
`physics: not included`. That guard should remain in the static path.

## Next implementation boundary

An optional physics builder should first reproduce one **unmodified matched
TJiU body/proxy pair** under private resource IDs and paths. Preserve its entire
controller/skeleton hierarchy, inverse binds, vertex ordering, color data,
geometry flags, export orders, proxy mapping, and solver settings together.
Rewrite every model/object reference consistently for the private filename.
Do not replace an approved static variant to perform this experiment.

Before applying a plush or enlarged shape, verify posed skinning and bind/local
matrix conventions for that whole pair. Deform both its render body and proxy
into the new rest shape; regenerate or establish valid correspondence for the
resulting exported ordering, and verify collision coverage and LOD behavior.
A BCB or native-body graft needs these checks even when counts happen to match.
The existing source matching is strongest for strong-frame LOD 0, but it does
not remove the rig or LOD checks.

Acceptance remains unproven for walking, running, combat, dialogue, ragdolls,
save/reload, camera distance/LOD changes, and crowds. Extreme size variants need
their own collision and stability review. This audit did not implement, enable,
or game-test any physics variant.

## NudePunk comparison

The relevant newer local source is
`C:\Users\hundo\Desktop\NudePunk2077-vsquish`, also represented in the installed
copy. The main `NudePunk2077` folder contains an earlier jiggle-only revision.
Inspection establishes implemented source paths and parameter meanings; it
does not certify the current in-game acceptance of every experimental option.

`scripts/tools/breast_squish/build.py` edits actual REDengine dangle graphs.
Its `apply_gravity` sets each `animDyngParticlesContainer.gravityWS`, multiplies
particle `pullForceFactor` and `damping`, and enlarges the C_top travel ellipsoid:

| Graph level | `gravityWS` | Pull multiplier | Damping multiplier | C_top travel radius |
| --- | ---: | ---: | ---: | ---: |
| grav | 18 | 0.68 | 0.88 | 0.100 m |
| grav2 | 24 | 0.52 | 0.78 | 0.115 m |
| grav3 / Pendulum | 30 | 0.40 | 0.68 | 0.130 m |

These values are engine graph controls, not verified SI acceleration values or
portable BG3 parameters. The older Gentle/Strong/Extra choices change travel
range; the added gravity choices also change downward acceleration and return
behavior. `r6/scripts/NudePunk/F80Sizes.reds` selects graph resources at spawn.
It preserves the breast component's own rig; replacing that rig with the body
size rig previously broke the graph's bone indices.

NudePunk contact is also concrete graph work: `patch_graph` installs arm/hand
capsules in `collisionRoundedShapes` and sets particle
`collisionCapsuleRadius`. **Firm 95 / Medium 90 / Soft 80 means collision radius
as a percentage of measured breast reach**, not a tissue-compression percentage.
The Saggy style combines clamp multiplier 1.5 and pull multiplier 0.55 with a
torso-fixed bar that pushes the particle down by up to 50 mm; the less-drop
variant targets 35 mm. Settled visible height depends on body and pose. The
separate experimental squash-bone test adds six deform bones per breast and
requires its matching test meshes/rig; moving the original breast particle is
not equivalent to local surface denting.

BG3 has no verified direct equivalent of these REDengine graph inputs. The
closest available route is TJiU's cloth proxy, `ClothParams` and native capsule
collision resource. Its damping/animation drive are related concepts, with
different units and behavior. Hand contact would additionally need verified
hand/forearm collider binding and collision masks; those actors are absent from
the inspected native strong resource. Cloth contact does not by itself prove
volume-preserving squeeze. The first runtime experiment remains the unmodified
matched TJiU pair on one reviewed adult, followed by gait, settling and arm
contact checks before reshaping or retargeting it to BCB.

NudePunk's percentage size rigs are **bone-scale controls**, not guaranteed cup,
volume, or forward-projection percentages. `build_xl_sizes.py` extends the
authored +0/+50 rig scale-float changes linearly (+100 can turn neutral scale
1.42 into 2.84); `build_xxxl_sizes.py` extends that scheme through +200. Vertex
weights, transforms and body shape determine the resulting dimensions.

There is also a separate static solution in `scripts/tools/np_hanging_size.py`:
`HangingSizeField` adds lower-pole fullness and downward shear after its size
field, with a 100 mm C1 root transition, broad support and protected attachments.
Its docstring explicitly distinguishes this offline bending from gravity
simulation. `np_size_bake.py` samples one continuous field across LODs. BG3 can
follow that broad-attachment/static-drape approach independently of runtime
physics, with actual width/height/projection measurements; NudePunk's axes must
not be copied directly (its front/up axes differ from BG3's).

Reproduction pins (SHA-256, under the source root above):

| Source file | SHA-256 |
| --- | --- |
| `scripts/tools/breast_squish/build.py` | `9cb473e5f8f3ff6233e6142caa44b5e413fe135e6c07de296ceeb44992e8f5ad` |
| `r6/scripts/NudePunk/F80Sizes.reds` | `6d42d61ecff00491d5edd77d4803e0b46711da1b55e1f6142958b8a806e24ec7` |
| `scripts/tools/build_xl_sizes.py` | `b5871c0785abaf81f94ca2eabc396382335302e935a6e47ac29dddad0d10baa6` |
| `scripts/tools/np_hanging_size.py` | `1dc3c9c141a7f672c00a7592361aefdf3258f388e68e8d3b25f23ad481e0f72f` |

The ignored report `build/physics-review/runtime-comparison.json` records full
source paths/hashes, the additional inspected source files, and decoded native
actor metadata. None of this work implements or enables BG3 physics.

## Reproduced cloth mapping

The primary [Nicoco007 cloth-mapping implementation](https://github.com/nicoco007/lslib/blob/9ce136678ade9a14d57b05897cfa47e6d6622803/LSLib/Granny/ClothUtils.cs)
reproduced the decompressed mapping bytes exactly for all five inspected TJiU
families. Its source is pinned locally at that commit; it is separate from the
official 1.20.4 exporter dependency.

R is the cloth weight byte and B the compatibility mask. Starting at positive
weights, the selection expands through overlaps, neighbors, overlaps, neighbors
and overlaps, using a 1e-7 position overlap radius. Physics indices follow first
position encounter while traversing fully selected triangles. Target selection
uses raw-index ordering with its defined hole-packing rule.

| Family | Marked target vertices | Selected unique physics positions | uint16 count |
| --- | ---: | ---: | ---: |
| Human normal | 800 | 772 | 2400 |
| Human strong | 797 | 769 | 2391 |
| Githyanki normal | 794 | 772 | 2382 |
| Tiefling normal | 800 | 772 | 2400 |
| Tiefling strong | 800 | 772 | 2400 |

Every native target position coincides with a compatible physics position.
Each triplet is its physics index followed by two `-1` values (`65535` as uint16).
This explains the counts differing from raw proxy/position counts. The report
`build/physics-probe/matched-v1/cloth-mapping-reproduction.json` contains all five
matching buffer hashes. The dense exporter below now exercises the primary
source's noncoincident nearest-three algorithm, including controlled one/two/
three-neighbor and mask cases. Its approximate distance rules and new topology
simulation still require in-game acceptance.

## Experimental matched-data exporter

`tools/physics_export` is a separate .NET 8 authoring helper for one complete
matched cloth render/proxy pair. It does not loosen the static body builder's
cloth guard or assign a resource to an NPC. The official Windows LSLib 1.20.4
DLLs stay outside Git; `toolchain-pins.json` pins all 28 DLL hashes. Build with:

```powershell
dotnet build tools/physics_export/PhysicsExport.csproj
# Override the external tool directory when necessary:
dotnet build tools/physics_export/PhysicsExport.csproj -p:LSLibDir="C:\path\to\Divine-1.20.4"
```

Two arguments perform an unmodified serialization check; five author the shape:

```powershell
dotnet tools/physics_export/bin/Debug/net8.0/PhysicsExport.dll source.GR2 output.GR2
dotnet tools/physics_export/bin/Debug/net8.0/PhysicsExport.dll source.GR2 output.GR2 reference.dae authored.dae jacobians.json
```

The reference must come from that exact original GR2. Both render and proxy
geometries must retain their source indexed triangles. The authored DAE supplies
positions; the JSON supplies one 3-by-3 Jacobian per reference position under
`geometries.<geometry-id>.jacobians`. Matrices are stored as rows and act on
column vectors. Both inputs must come from the same continuous deformation.
The helper transports the original normal with the inverse transpose and the
original tangent frame with the Jacobian, retaining source UV/hard splits.

Generic DAE import changed cloth color bytes and introduced bind/local transform
rounding. The new helper instead uses LSLib's resolved `NodeSerializer` metadata
to capture original vertex records and replace only named Position/QTangent
fields. It preserves original topology storage, raw RGBA, skin arrays, rig
transforms, flags and all unrelated vertex-record bytes. It rereads the result
and requires exact protected state and source schema, zero position serialization
error, and basis error below 0.05 degrees before publishing atomically. Version
pins are mandatory because this uses narrowly scoped internal metadata access.

Local normal/strong zero-change checks preserved every known object-state float
bit and every raw vertex-record byte. Translation, nonuniform scale and rotation
checks preserved every nongeometry field, with basis error below 0.009 degrees.
Inverted Jacobians, omitted proxies, changed topology and malformed position
counts were rejected without an output file. Reports are under the ignored
`build/physics-probe/matched-v1` directory.

The resource-only baseline probe there packages two unmodified matched GR2s
under private paths/UUIDs and verifies LSX/LSF semantics and PAK file hashes. It
contains no NPC assignment and has not been installed. Neither serialization
proof establishes global intersection safety, consistency of an arbitrary
field/Jacobian pair, collision coverage, useful simulation or working squeeze.
New visual bounds and runtime movement/LOD/culling acceptance still require
review after a donor shape is fitted.

## Dense donor export experiment

`tools/donor_mesh_export` is a separate .NET 8 helper. It replaces the render
mesh of a matched native cloth pair without resampling the donor onto the native
render topology. It does not modify the static builder or the frozen
`tools/physics_export` helper, and does not install or assign a game resource.
It references the frozen helper only for metadata-resolved raw proxy capture.

```powershell
dotnet restore tools/donor_mesh_export/DonorMeshExport.csproj --locked-mode
dotnet build tools/donor_mesh_export/DonorMeshExport.csproj --no-restore
dotnet tools/donor_mesh_export/bin/Debug/net8.0/DonorMeshExport.dll template.GR2 body_payload.json output.GR2 --preserve-template-proxy --allow-nearest --rebuild-mesh-bounds
```

The schema-1 JSON contains `meshes`, each with an exact native mesh `name` and
equally sized `positions`, `normals`, `tangents`, `binormals`, `uvs`,
`colors_rgba8`, `bone_indices`, and `bone_weights` arrays. `bone_palette` names
the native skeleton joints; `triangles` contains raw vertex index triples.
Coordinates and basis vectors are already BG3 Y-up. All components must be
finite; N/T/B must be normalized and orthogonal; four weight bytes must sum to
255. Pre-split raw vertices and triangle order are retained, with at most
65,535 vertices per mesh. Skin indices are remapped by joint name independently
for render and proxy palettes. Unknown joints or positive use of joints absent
from the original mesh palette fail closed. Unused whole-skeleton palette
entries do not create new bindings. An explicit `--allow-head-binding` option
can append the already existing native `Head_M` joint; this is not used for the
reviewed Juno body, whose erroneous source facial weights were repaired in the
preparation stage.

`--preserve-template-proxy` takes a body-only payload and retains the fitted
native proxy's raw position/basis/UV/color/skin bytes and topology. A two-mesh
payload is also supported. `proxy_from_body: true` can extract a painted donor
patch plus a guard ring, but that mode is unsuitable for the current donor's
disconnected anatomical islands without a separate connectivity review. The
preserved native proxy avoids introducing those islands into the simulation
mesh; collision behavior remains untested.

The default mapping mode requires exact coincident physics counterparts.
`--allow-nearest` explicitly enables the unmodified primary `ClothUtils.cs`,
pinned at commit `9ce136678ade9a14d57b05897cfa47e6d6622803`. The copied source
hash is `830507720200577e51664cb40e4c47e7a1c103b593d3b9df50b7f665306dcf8f`.
Its MIT license and attribution accompany the helper. Its KDTree dependency
is pinned to exact NuGet version 1.0.5, package-lock content hashes, and a runtime
DLL SHA256, in addition to the 28 official DLL pins. An independent selection
audit must exactly match the primary source's target packing, cooked physics
point order, and masks. Mapping is generated only after the final GR2 is
serialized and read back. No arbitrary nearest-three substitute is used.

The writer preserves the complete native skeleton, model bindings and
transforms, material and cloth flags, and original mesh bone names/order.
With no bounds option, every original bone-binding record remains exact.
`--rebuild-mesh-bounds` intentionally replaces only binding OBBMin/OBBMax using
official LSLib `VertexHelpers.UpdateOBBs`: each positively weighted position is
transformed by that native bone's inverse world matrix. Readback must contain
every weighted position in its corresponding box; unused boxes become zero.
This updates geometry bounds without changing the skeleton or bind matrices.
The report distinguishes this intentional bounds change from exact rig state.

Publication requires identical authored Float32 render positions, raw triangle order, remapped
skin and RGBA bytes, protected mesh metadata and rig state, full material-group
coverage, basis error below 0.05 degrees, and UV half-precision error below
0.002. A retained proxy additionally requires identical captured raw records.
The `.report.json` records those checks, bounds containment, hashes, and mapping
distance/neighbor statistics. `.mapping.json` supplies actual readback rest
bounds, the little-endian uint16 buffer and SHA256, and its LSX-ready
zlib/Base64 value. A passed report establishes serialization and source-algorithm
mapping only; independent geometry acceptance and runtime tests are separate.
An authoring NPZ may contain Float64 positions, so its intersection proof alone
does not establish the final Float32 mesh's surface result. The read-only
`geometry input.GR2 output.json` command supplies the actual serialized position
and triangle arrays as lossless little-endian Base64 (`<f4` and `<i4`, both
reshaped to rows of three), their SHA256 hashes, the GR2 hash, material-group
coverage and cloth flags. Final rest acceptance should audit these actual
coordinates with the verified source-face ancestry.
Payload numbers are first read as Float64 and then narrowed to Float32, matching
the author NPZ's conversion and round-to-even midpoint behavior. Direct JSON
Float32 parsing selected an adjacent odd-mantissa value at 98 midpoint cases in
the first V2 export; that artifact is superseded by the corrected
`export-f64roundtrip` output. The self-test includes two of those concrete
midpoint values. Exact Float32 array correspondence is a prerequisite for,
rather than a replacement for, the final serialized surface audit.

The first dense Juno tooling-only check retained 38,964 render vertices and
73,154 triangles with zero position error, maximum basis error 0.0084 degrees,
and maximum UV quantization error 0.000523. Its fitted 795-vertex proxy records
and skeleton/model state remained exact. Rebuilt boxes contained all 60,930
render and 2,280 proxy weighted-point memberships. Those artifacts are explicitly
not geometry accepted: the pose preparation still needed an inner-thigh repair.
The unchanged original buffers reproduce byte-for-byte for all five native
families. The `selftest template.GR2 output.json` command additionally verifies
known one/two/three-neighbor results, mask filtering, strict noncoincident
rejection, and failure when no compatible physics neighbor exists. Neither
proof establishes runtime gravity, collision, squeeze, jiggle quality, LOD
behavior or animated culling.

`tools/build_donor_probe.py` requires model, export, mapping and rest-audit
hashes to agree before creating a private new-character probe. The Float32
source-baseline branch requires an explicitly unposed, uncut source, verifies
the hashed original NPZ transformed only by the declared axis order and uniform
scale, and recomputes both its geometry fingerprint and the recorded canonical
pair-set hash/count. It does not merge source, pose and target exception sets.
The separate unquantized comparison remains in the audit trail.

The reviewed original human-normal VisualBank is pinned to SHA256
`301b79e3215173032f0e7e8f2c4660a7a3768847a50c3829e75230c097d3882c`.
Its private clone retains native solver parameters, ObjectIDs, materials and
skeleton references. Besides the body resource, all three compiled creation
documents are decoded and compared with their generated LSX game records;
the separate LSX region alias is normalized to the stored root-node name, as
official LSFReader does. The decoded root/visual/body/preset chain must contain
only the expected private roots and visuals and the selected generic presets.
The offline B package review independently regenerated these records and
verified another LSX/LSF cycle: five private roots, five private visuals and
five selected generic presets, with no original root override. These checks
do not establish successful loading, materials or physics in the game.

## Cinderella source profile

`tools/prepare_cinderella_body.py` uses the separate
`nudegate.cinderella_body` profile. Its seven-spine Rigify map treats .004/.005
as neck and .006 as head; it does not reuse Juno's eight-spine indices or facial
weight repair. One uniform scale and placement are calibrated from Cinderella's
own mesh ground, shoulder and neck landmarks. The reviewed capture yields scale
1.080275650999603 and BG3 translation
[-0.0003133757568234296, 0.06453125388236142, -0.03693711456559791].
The strict package loader supports this explicit scale-then-translation-then-
Float32 representation and verifies its original-source geometry hash; the
older scalar-only representation is unchanged.

The first complete limb pose introduced four central pelvic seam contacts.
Reducing the leg rotation fraction retained them until the whole correction was
removed, moving feet by 103 mm. A separate explicit local pose-coherence step
instead moves 17 central seam vertices by at most 0.783653 mm. Its small inner
patch follows one translation of the original sculpt, with a C1 one-millimeter
fade to the existing pose. Original skin weights and topology remain intact.
The source capture and uncorrected pose geometry hashes are required before the
versioned configuration can apply:

```powershell
python tools/prepare_cinderella_body.py --pelvic-pose-corrective config/donor_profiles/cinderella_a_pelvic_pose_corrective_v1.json --output build/donors/cinderella-new-stage
```

Independent pose review retained exactly the original 537 source intersection
pairs, with no new or resolved pairs and no collapse. Prepared-body review found
283 pairs, all source-inherited, and no new neck/bridge contacts or collapse.
The source configuration reproduced the reviewed prepared payload byte-for-byte.
Breast, hands/feet, upper neck and sampled outer pelvic contours remain exact
outside the tiny central support. This remains body preparation: Cinderella's
own proxy fit, actual serialized rest proof, materials and runtime acceptance
are separate requirements.

Cinderella's own matched-proxy authoring is reproduced by
`tools/make_cinderella_proxy_seeds.py` and the shared
`tools/fit_native_donor_proxy.py`. Search seeds use her actual source breast
poles and strong-support height/width spans; they guide correspondence only.
The shared fitter selects actual same-side, agreeing-normal triangle points on
her connected donor surface and samples one analytic compact velocity flow on
the original proxy and disposable native lookup. The actual dense sculpt never
passes through that deformation. The selected 75 mm support has no new proxy or
lookup intersections/collapse, proxy Jacobian minimum 1.1038 and lookup minimum
0.1588. An 89-sample central-difference check agrees within 5.51e-9.

```powershell
python tools/make_cinderella_proxy_seeds.py --target-pose build/donors/cinderella_actual_posefix_v2/posed_dense.npz --pose-audit build/donors/cinderella_actual_posefix_v2/global-pose-surface-audit.json --output build/donors/cinderella-proxy-run/seeds.npz
python tools/fit_native_donor_proxy.py --source-id cinderella_a --target-pose build/donors/cinderella_actual_posefix_v2/posed_dense.npz --pose-audit build/donors/cinderella_actual_posefix_v2/global-pose-surface-audit.json --target-body build/donors/cinderella_actual_posefix_v2/body_prepared.npz --radius .075 --moving-centres --projection-seeds build/donors/cinderella-proxy-run/seeds.npz --output build/donors/cinderella-proxy-run/fit
```

The same-field UV/paint transfer preserves every reviewed body corner position,
normal, skin weight and source ID. Its native-derived breast poles and 10 mm
caps retain R127, with no manual paint override. The repainted dynamic region's
exact all-proxy-triangle distances have median 3.47 mm, 95th percentile 13.22 mm,
and maximum 21.90 mm. The subsequent raw serialized mapping and final body/proxy
surface audits remain distinct proof steps; none establishes runtime movement.

The selected A sculpt and original file remain intact. A separate optional
uncompressed study releases only three measured authored wardrobe controls:
`Boba marcas bikini parche`, `Boobpress`, and `thihhs`. Evaluated per-key fields
and comparison renders identify their breast compression and narrow thigh-band
effects; other body-volume and face settings are retained exactly. The optional
capture is admitted only with `--optional-uncompressed-study` and a complete
key-state check against selected A. It is not a replacement selection and needs
its own source baseline and geometry review. Neither study uses source smoothing
or sculpting, and neither saves the original Blender file.

## Primary implementation evidence

- Norbyte's [COLLADA exporter](https://github.com/Norbyte/lslib/blob/master/LSLib/Granny/Model/ColladaExporter.cs)
  and [importer](https://github.com/Norbyte/lslib/blob/master/LSLib/Granny/Model/ColladaImporter.cs)
  round-trip the `Cloth` and `ClothPhysics` LSTools flags.
- Norbyte's [mesh definitions](https://github.com/Norbyte/lslib/blob/master/LSLib/Granny/Model/DivinityMesh.cs)
  distinguish mesh cloth flags from `ClothPhysics` (`0x100`).
- Script Extender's [resource definitions](https://github.com/Norbyte/bg3se/blob/main/BG3Extender/GameDefinitions/Resources.h)
  expose separate `ClothParam`, uint16 `ClothHighResInfo.ClosestVertices`, cloth
  mapping data, skeleton references, and `SoftbodyResourceID` on visual resources.

The local mod/game files supply the filenames, counts, UUIDs, and parameter
values in this document. Tool support for serializing these fields is not proof
that a newly authored asset set simulates correctly in BG3.
