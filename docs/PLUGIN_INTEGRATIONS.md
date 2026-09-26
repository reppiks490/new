# Connected Visual/Design Integrations

## Figma / FigJam

The architecture diagram is now materialized in the connected FigJam workspace and mirrors the implemented control-plane boundaries: input/spec parsing, model-pack manager, GPU scheduler, geometry, retopo/UV/LOD, 8K/UDIM surfaces, human-realism stack, rig/morph, animation, realtime/offline rendering, export, policy gate and QA.

Implementation rule: Figma is the UX/system-architecture source for interface design, but executable contracts remain defined by versioned code schemas and tests.

## Runway

The connected workspace is authenticated. At this revision it exposes image-generation models but no enabled video-generation models and has no available credits. Accordingly, v0.3 treats Runway as an optional visual-reference/look-development adapter and never makes the core 3D pipeline depend on it.

Future adapter responsibilities:

- concept/lookdev reference frames;
- controlled turntable/reference-image preparation where supported;
- visual QA references;
- optional texture/reference enhancement subject to workspace capability and credits.

No Runway task is required for deterministic core operation.
