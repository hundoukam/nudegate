# Private skin styles

`skin_styles.py` builds optional **SOFT** and **DEFINED** native skin materials
for new body variants. It does not repoint original materials or the frozen
legacy body resources. The verified build covers these larger female materials:

| Material | Original material UUID |
| --- | --- |
| HUM_FS_NKD_Body_A | `9106a412-4963-2147-914b-838fd337cf43` |
| TIF_FS_NKD_Body_A | `6d46fd76-b821-9d89-78e5-52674d7a0416` |
| ELF_FS_NKD_Body_A | `a4aca4bd-08f7-000d-a124-34a900af1401` |

SOFT changes real normal-map data in a restricted front abdomen region and
applies the existing softer vein/roughness presentation defaults described
below. DEFINED keeps the source normal DDS and material scalars unchanged; its additional shape definition
can come from the separately generated body geometry. Neither style invents a
`NormalStrength` material parameter. The inspected native shader exposes no such
main-normal control.

## Native packing and layer evidence

The source materials use
`Public/Shared/Assets/Materials/Characters/CHAR_Skin_Body.lsf`. Its native DX11
deferred pixel shader was extracted from `Materials.pak` and inspected with
Microsoft's `D3DDisassemble` API. The tested binary is
`CHAR_Skin_Body_ST_DEF_DX11.bshd`, SHA-256:

```text
84e4bf00254a587226a2a991459b8ff586d6c58ee2955c1343cfd4b6180e5745
```

The Cache1 sample selects `.yzwx` (G, B, A), then `.zyx` reverses those selected
components before the `2*x-1` conversion. The following instructions reorder
them for the shader's tangent basis. Together with the native map data, this
confirms the source normal packing:

| DDS channel | Meaning |
| --- | --- |
| R | Unused, zero |
| G | Tangent normal Y |
| B | Tangent normal Z |
| A | Tangent normal X |

The shader also applies `frac(UV)` when sampling. Native body meshes contain
U coordinates in both `[0,1]` and `[1,2]`. Mask projection removes a triangle's
common integer tile without
modifying the source mesh UVs. Triangles crossing a wrapped boundary in the
reviewed mask are rejected for explicit review.

The implementation checks R=0 and the decoded A/G/B unit-vector distribution
before editing. Reading the same data as ordinary RGB fails that check.

Actual native GTS/GTP extraction established the skin layer order below. Layer
names alone are insufficient to infer the packed character map type:

| VT layer | Native source map | GTS layer type |
| --- | --- | --- |
| 0: Albedo | CLEA | `R8G8B8A8_SRGB` |
| 1: Normal | NM | `X8Y8Z8W8` |
| 2: Physical | HMVY | `X8Y8Z8W8` |

The HUM and TIF standalone source DDS files are 2048² BC3/DXT5 with twelve mip
levels. Their layer assignment was confirmed against the actual native GTex
images, rather than guessed from the map names. Official tooling and loading
contracts are documented in [Norbyte's virtual texture notes](https://github.com/Norbyte/bg3se/blob/main/Docs/VirtualTextures.md).

## SOFT mask and preservation rules

The mask is rasterized through the selected source geometry's actual indexed
UV0 coordinates. Source positions are divided by the reviewed frame scales to
obtain canonical smaller-frame metres. Its exact support is:

- `1.02 < Y < 1.26`;
- `abs(X) < 0.13`;
- front-facing body depth, `Z < -0.015`.

Smooth transitions occur inside those bounds. Back, clavicle, groin, hands,
feet, tail and unrelated atlas regions are excluded. This is a front abdomen
pass, not a claim that every muscular feature has been removed.

Within the mask, the code separates broad A/G normal slopes with a 12-pixel
Gaussian blur and attenuates that broad component. It retains the fine-detail
residual. A local ridge guard further reduces editing around strong fine
features, including tiefling scale detail. The resulting normals are normalized
and repacked into A/G/B; R stays zero.

The edited map is compressed with Microsoft DirectXTex using data alpha, not
transparency alpha. Only affected BC3 blocks are copied back into the original
DDS at each mip. Original header bytes and all blocks outside that footprint
remain byte identical. A touched 4×4 boundary block may still have ordinary BC3
quantization differences in neighboring pixels; the method does not promise
pixel identity inside those touched blocks.

CLEA and HMVY inputs are copied unchanged. Colour, tattoo, CancelMSK,
detail-normal and other parameter records are retained. Both styles use private
resource UUIDs and `virtualtexture` references. SOFT additionally changes only
the existing `Enabled` and `Value` attributes of these two scalar records:

| Scalar | Inspected native Enabled / Value | SOFT Enabled / Value |
| --- | --- | --- |
| `VeinAmount` | `True` / `0.5` | `True` / `0.15` |
| `TMP_BODY_ROUGH` | `False` / `0.56` | `True` / `0.62` |

Their `BaseValue` attributes remain `1` and `0.56`, respectively. These are the
same supported presentation values used by the optional scalar-only soft
materials. DEFINED retains the native scalar defaults. Missing, duplicated,
or invalid supported scalar records cause SOFT authoring to fail; no new shader
parameter is invented. These two settings affect vein/specular presentation,
separately from the restricted abdomen normal-map edit.

SOFT material UUIDs include `soft-vein-roughness-v1` and the scalar settings in
their deterministic identity. Virtual texture UUIDs, GTex names, DDS content,
and DEFINED material identities are unaffected by this scalar presentation
revision. Frozen legacy material resources are not rewritten.

## ELF source handling

ELF_FS uses a different CancelMSK and a separate native GTex:
`539e48c343581124d79182d7fae3deda`. Comparing its extracted native layers with
HUM_FS found small but real differences; some local CLEA differences were large.
It is therefore built as a separate family rather than replacing elf textures
with human textures.

The ELF inputs preserve the extracted native top-mip BC3 blocks exactly. The
LSLib extraction API emits a single-mip DDS, so lower mip levels were regenerated
with DirectXTex BOX filtering, separate alpha, and linear data handling. The
ELF source provenance record states that caveat explicitly. DEFINED preserves
this prepared source DDS byte for byte; it does not claim byte identity with
all original native ELF mip levels.

## Build and resource contract

Authoring requires Python with NumPy and Pillow, Norbyte LSLib/Divine with
`build-vt` support, and Microsoft's `texconv.exe`. The tested tool versions are
LSLib 1.20.4 and DirectXTex May 2026. Runtime loading requires Script Extender
v12 or later; NumPy, Pillow and the authoring tools are not game dependencies.

```powershell
python -m pip install numpy Pillow
python tools/build_skin_styles.py --config C:\path\skin-styles-inputs.json --output build/expansion/skin-styles --divine C:\path\Divine.exe --texconv C:\path\texconv.exe
```

The JSON config contains `source_banks` and `families`. A family has `id`,
`material_id`, `dae`, `geometry_id`, optional `frame: [x,y,z]`, and `textures`:

```json
{
  "id": "human_elf_fs",
  "material_id": "9106a412-4963-2147-914b-838fd337cf43",
  "dae": "HUM_FS_pristine.dae",
  "geometry_id": "HUM_FS_NKD_Body_A_Mesh-geom",
  "frame": [1.217716, 1.12049, 1.15],
  "textures": {
    "Albedo": "HUM_FS_NKD_Body_A_CLEA.DDS",
    "Normal": "HUM_FS_NKD_Body_A_NM.DDS",
    "Physical": "HUM_FS_NKD_Body_A_HMVY.DDS"
  }
}
```

Paths are resolved relative to the config file. The current workspace config
is `.cache/nudegate/skin-study/skin-styles-inputs.json` under the user's home.
It includes all three verified families and source provenance.

The library API is:

```python
create_skin_styles(
    source_banks, families, output,
    divine=divine_path, texconv=texconv_path, module_folder="Nudegate",
)
```

`skin-styles.json` returns this integration map:

```text
material_map[original_material_uuid]["soft" or "defined"] = private_material_uuid
```

Only the new variants should consume this map. Unsupported material IDs retain
their existing material references.

`output/package/` contains only runtime assets:

```text
Public/Nudegate/Content/[PAK]_SkinStyles/_merged.lsf
Public/Nudegate/Assets/VirtualTextures/NudegateSkinStyles.gts
Public/Nudegate/Assets/VirtualTextures/NudegateSkinStyles.gtp
Mods/Nudegate/ScriptExtender/VirtualTextures.json
Mods/Nudegate/ScriptExtender/Config.json
```

The bank includes MaterialBank and VirtualTextureBank regions. The material's
`VirtualTextureParameters` entry with `ParameterName="virtualtexture"` holds
the private VT UUID in `ID`. That VT resource holds its private `GTexFileName`.
The SE mapping connects that GTex name to the packaged GTS path. None of these
private UUIDs or GTex names replace an original resource.

The generated SE config declares `RequiredVersion: 12`, `ModTable: "Nudegate"`
and empty `FeatureFlags`. When merging it into a mod with an existing SE config,
retain the higher required version and existing feature flags. Lua scripts are
not needed merely to register these virtual textures.

## Completed validation

The three-family build produced six private materials and six private GTex
resources. LSLib's `--vt-validate` passed, the resource bank passed LSX → LSF →
LSX conversion, and all six Material → VT → GTex → SE/GTS reference chains
resolved.

All six private GTex resources were extracted again through LSLib. **All eighteen
top-mip layer images were pixel identical to their authoring DDS inputs**, with
zero mean and maximum error. All three DEFINED normal DDS files were byte
identical to their prepared source inputs.

The scalar presentation revision was rebuilt and checked against its prior
output: all eighteen authoring DDS files remain byte identical, and all eighteen
decoded layer images remain pixel identical both to those inputs and to the
prior extraction. All six runtime material chains resolve. SOFT changes only
the two permitted scalar defaults; DEFINED retains native scalars. Existing
`BaseValue` and every other material parameter were verified after LSF roundtrip.

The GTS/GTP container hashes change on rebuild because LSLib assigns a fresh
GTS GUID and GTP checksums with `Guid.NewGuid`; this does not change the private
VT IDs, GTex names, or decoded image content. The current report records the
new runtime file hashes. See the builder's [GTS headers](https://github.com/Norbyte/lslib/blob/master/LSLib/VirtualTextures/Build.cs)
and [GTP page-file writer](https://github.com/Norbyte/lslib/blob/master/LSLib/VirtualTextures/PageFileBuild.cs).

Nine focused tests cover A/G/B validation, protected pixels, ridge guards,
compressed-block preservation, UV projection/frame/tile handling, SOFT-only
scalar isolation, source immutability, unsupported scalars and UUID binding. The
current build report is `build/expansion/skin-styles/skin-styles.json`; its
`authoring/private-vt-parity.json` records the eighteen layer comparisons, while
`authoring/soft-presentation-validation.json` includes material comparisons,
reference chains, prior-content parity, and runtime file hashes.
In-game appearance and acceptance remain untested.

Primary tool references:

- [Norbyte VT building and registration](https://github.com/Norbyte/bg3se/blob/main/Docs/VirtualTextures.md)
- [LSLib VT extraction implementation](https://github.com/Norbyte/lslib/blob/master/LSLib/VirtualTextures/VirtualTexture.cs)
- [LSLib VT builder](https://github.com/Norbyte/lslib/blob/master/LSLib/VirtualTextures/Build.cs)
- [Microsoft DirectXTex texconv flags](https://github.com/microsoft/DirectXTex/wiki/Texconv)
