# Soft normal and strong female bodies

Version 0.2 adds the larger female frame as its own supported asset family.
The normal female frame (commonly called Body Type 1) and the strong female
frame (Body Type 3) retain their own geometry, skin weights, bind matrices,
materials and scale. The larger body is not replaced by the smaller model.

Seven shapes now include a masked surface-softening pass, with an additional
Plush profile for a fuller waist, hips, thighs and torso. Softening rounds local
contours; it does not provide runtime jiggle. Protected attachment zones have
smooth falloff into the editable surface. Local triangle-safety limits prevent
fine ridges from folding without unnecessarily limiting the whole torso.

Normal human/elf, githyanki and tiefling sources come from the supplied BCB
archive. Strong human/elf and tiefling sources were decoded from the user's
installed vanilla game using an isolated LSLib tool copy. Human and elf strong
visuals reference the same original human model with different skin materials.
Strong tieflings use their own source, not the human or normal female rig.

All five native strong-body LODs are authored and exported together. Their
controllers and other XML remain unchanged. GR2 export may reorder vertices;
validation requires a complete bijection that preserves every ordered face
corner, then checks mapped positions, skin influences, all UV sets, bind
matrices and smooth normals. Welding, splitting or changed connectivity fail.

## Skin presentation

Optional private skin-material copies change existing `VeinAmount` defaults
to 0.15 and `TMP_BODY_ROUGH` defaults to 0.62. Colour, tattoos, virtual-texture
references and other material properties are retained. These controls reduce
vein/specular emphasis; **they do not edit the muscular normal-map artwork**.
Tiefling racial texture details and unique companion textures remain separate
from generic shape authoring. Skin appearance still requires in-game review.

## Experimental new Tav creation

`tools/build.py --tav-presets ... --tav-profile plush` builds a new-character
creation option using the compatible normal and strong bodies. It copies each
supported generic female preset's root and character visual under new private
UUIDs, then changes that CC preset's root reference. It preserves clothing
visibility, gameplay fields, camera data and skin settings. Original NPC roots
are not overwritten by this option. Child evidence and unknown families remain
vetoes.

This is a new-creation test path. Existing saves, Magic Mirror transitions,
clothing fit, animation, distance transitions and character appearance have not
been accepted in game. Special bodies such as Karlach's scarred/glowing model
are not replaced with the generic strong mesh.

## Local outputs

- `build/plush-final/body-build.json`: all current exports and checks.
- `build/plush/tiefling-soft-comparison.png`: smaller/larger baseline, softened
  and plush geometry, drawn with a common scale.
- `build/plush/human-soft-comparison.png`: human/elf comparison.
- `dist/Nudegate-0.2.0-plush-tav-study.pak`: local experimental package.
- `dist/body-study-report.json`: exact adult assignments, private skin materials
  and CC preset/root mappings for the last body build.

Use one Nudegate package at a time: the basic alpha and body-study alternatives
share a module UUID. Source/derived mesh assets remain outside Git.
