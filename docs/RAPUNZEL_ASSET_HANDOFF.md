# Character replacement: paused during asset selection

The user asked to stop after researching replacement assets. Do not resume
development or sourcing until they ask to continue.

## Confirmed direction

- Replace the low-quality character with one finished, fully clothed benchmark
  before expanding the wardrobe or controls.
- User selected **Rapunzel from Disney's Tangled animated movie**.
- Asset budget is **$0**. No purchases or paid generation authorized.
- No replacement model was acquired or integrated during this research pass.
  Existing application code and assets remain at checkpoint `5d7808a` on
  `codex/browser-studio-customization`.
- Blender 4.3.2 is now available in the workspace. Source inspection/conversion
  is possible once a usable character file is available.

## Sources checked

### Paid Blender Rapunzel — excluded by budget

https://www.artstation.com/marketplace/p/ADz2X/rapunzel-from-tangled-rig-animated-low-poly-3d-model

The listing advertises a $29 model by Black Cat, Blender/FBX files, an IK rig,
and facial/body shape keys. These are seller claims, not verified mesh or rig
quality. The page describes a Standard Use License; permission for an editor
that exports the character was not established. Nothing purchased, downloaded,
or recommended as a verified production asset. Generic page text suggesting
an existing purchase is not evidence that this user owns it.

### Free BlendSwap Rapunzel V1.0 — incomplete

https://blendswap.com/blend/19828

Creator: davidlopez1231. Listed Blender 2.7x/Cycles, 51.4 MB, CC-BY-NC-SA.
The creator explicitly describes an early textured/UV-mapped version and says
the body and rigs are future work. This does not satisfy the finished character
requirement. No source file downloaded or visual quality verified.

### Free Maya television-series rig — wrong target

https://www.deviantart.com/939163156/art/3D-Model-TTS-Rapunzel-Rigged-Model-Download-690611752

The creator describes a Maya 2014 2.5D rig based on Tangled: The Series.
It is not a suitable replacement for the requested fully three-dimensional
movie-style character. Download requires login; no source acquired.

### Rain v3 — possible free base, not Rapunzel

https://studio.blender.org/characters/rain/v3/

Blender Studio lists a free 64.4 MB rig, Blender 4.1+, licensed CC-BY 4.0,
with the required credit: “Rain Rig (CC) Blender Foundation | studio.blender.org”.
Listed source archive:
https://studio.blender.org/download-source/files/ee/a7/eea73e55dba1cea31c09848df6a794b2-4.zip

Rain could supply an authored starting mesh/rig, but making a convincing
Rapunzel would require new character-specific sculpting, long golden hair,
purple dress construction, materials, and fitting. Do not represent Rain as
Rapunzel or claim this adaptation already exists. Nothing downloaded/integrated.

Other search results included Sketchfab fan models, Roblox-oriented first
models, generated-model galleries, and static models. No complete free,
movie-faithful Rapunzel asset was verified. This is a bounded search result,
not a claim that no suitable free model exists anywhere.

## Outstanding decision when resuming

The last question was whether the user would accept a custom Rapunzel
interpretation built from a free rigged base, or only an existing model closely
matching the movie. The user paused before answering. Do not interpret the
pause as selecting either option.

The existing MakeHuman morph targets are topology-specific and cannot be
promised to work on a replacement mesh. Inspect source geometry, rig,
materials, hair, clothing and supported shape keys before defining controls.
Quality must be judged in actual close-up and full-body renders, with export
appearance and fit checked, rather than by asset counts or seller previews.

## Operational state

- Research used the Firecrawl skill and connected web tools.
- Native external preview-image downloads did not complete; no candidate
  image or source model was actually inspected locally.
- No new product code, model, deployment, or external message was created.
- The existing build remains unfinished; see `WORK_CHECKPOINT_2026-10-09.md`.
