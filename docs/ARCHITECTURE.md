# Implementation notes

## Why private character visuals

BG3 characters can have clothing in equipped item visuals and in character
visual `Slots`. Setting `ShowEquipmentVisuals=False` alone misses embedded
garments. The local authored `TEMP_Minthara_Naked` visual provides a useful
comparison: it has the same base and body set as adult Minthara, retains identity
and censorship slots, and omits embedded Body/Footwear/Underwear slots.

For each exact reviewed adult root the compiler copies the complete original
node, then changes only `CharacterVisualResourceID`. It copies the corresponding
CharacterVisualBank resource under a deterministic private UUID, turns off
equipment visuals, and removes Body/Underwear/Gloves/Footwear/Cloak/Headwear slots.
Materials and every other slot are preserved. The original visual resource IDs,
mesh files, body sets, skeletons, equipment and stats are not edited.

The generated regions are `Templates/Templates/GameObjects` and
`CharacterVisualBank/CharacterVisualBank/Resource`.
Files live under `Public/Nudegate/RootTemplates` and
`Public/Nudegate/Content/[PAK]_CharacterVisuals`.

## Admission and inheritance

The source catalog contains exact template UUIDs, expected names and explicit
adult review evidence. Missing tags never count as proof of adulthood.
The full inheritance chain must resolve without cycles. The compiler rejects:

- `BASE_Children` (`1ccae813-70c3-4be7-843c-0ddf1b6fe5c3`).
- Inherited `KID` (`ee978587-6c68-4186-9bfc-3b3cc719a835`) or
  `GOBLIN_KID` (`88730ec2-439e-4172-95f4-b7f1875169fa`).
- Minor evidence in ancestor names/stats or the character visual name.
- Missing body/base resources, head slot, or positive catalog review.
- Descendants that would inherit the changed visual ID.

Every direct child must explicitly declare an existing visual before a parent
root can be patched. The child and its descendants therefore retain that
original visual. A future mod or game update introducing an inheriting child
causes a fresh build to fail instead of expanding coverage automatically.

## Limits

Root-template overrides are insufficient for many NPCs: the game's global and
level-local actor records can specify their own character visual ID. Those
actors need exact reviewed instance support or a complete reverse-reference
audit before replacing an existing visual ID. Do not solve this by globally
editing shared clothing or generic racial templates.

A nonzero body resource ID does not prove its geometry has complete visible
coverage. In-game inspection is still required. Unknown slots are retained;
their appearance needs review rather than speculative removal.

## Sources

- [Norbyte's indexed BG3 data: child base](https://bg3.norbyte.dev/search?id=1ccae813-70c3-4be7-843c-0ddf1b6fe5c3)
- [Adult Shadowheart character visual](https://bg3.norbyte.dev/search?id=9ab62da4-a028-c237-b5b9-ca897f62b771)
- [Kagha visual with embedded garments](https://bg3.norbyte.dev/search?id=0774cbd6-d405-bfbf-4b75-0d4681f83f69)
- [Karlach gameplay global](https://bg3.norbyte.dev/search?id=2c76687d-93a2-477b-8b18-8a14b549304c)
- [Official AddCustomVisualOverride API](https://docs.baldursgate3.game/index.php?title=AddCustomVisualOverride)
- [BG3SE API and component definitions](https://github.com/Norbyte/bg3se)

Schemas were also checked against locally installed BG3 4.1.1.7631656 converted
using LSLib 1.20.4. No external document's instructions are part of the build.
