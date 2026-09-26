# Vendor capability matrix — v0.3

*Last documentation review: 2026-09-26 (Tripo, Meshy, Hi3D/Hitem3D — via live web search; direct
site/doc fetch was blocked by this environment's egress policy, so findings below are corroborated
across multiple independent secondary sources rather than a single primary fetch. `last_reviewed`
is now a structured field on `ProviderProfile`, not just this doc's prose — see `app/providers/catalog.py`.)*

This project treats external 3D generators as **optional stage-specific accelerators**, not as the source of truth for the character pipeline. The canonical interchange/cleanup layer remains local Blender/USD tooling.

## Tripo3D

Best used for a stable end-to-end path: prompt/image/multiview generation, up to 2M faces in Ultra, PBR, 8K extreme textures, smart retopology/decimation, semantic segmentation, rigging and animation.

**Rigging detail (reviewed 2026-09-26):** the auto-rig endpoint documents support for
**7 creature types** — biped, quadruped, hexapod, octopod, avian, serpentine, aquatic —
with accurate joint placement and weight painting, plus a free "Rig Check" pre-flight
call that reports the recommended rig type before a paid rig is committed. This is
strictly more than the generic "rigging: yes/no" this repo previously tracked, and is
now structured data (`ProviderProfile.rig_creature_types`, `rig_precheck_endpoint`) so
the router can pick Tripo specifically for non-humanoid rig requests instead of
silently offering Meshy, whose documented rigging path is humanoid/biped-only.

Primary official references:
- https://developers.tripo3d.ai/en/models/v3-1
- https://developers.tripo3d.ai/en/docs/mesh-decimate
- https://developers.tripo3d.ai/en/docs/mesh-segment
- https://developers.tripo3d.ai/en/docs/models-texture
- https://developers.tripo3d.ai/en/models/rig
- https://developers.tripo3d.ai/en/docs/animations-rig

## Meshy

Adds explicit 4096^3 geometry generation passes, staged preview → refine, Smart Topology, UV/retexture/remesh endpoints, 8K texture resolution, and humanoid rig/animation paths. Remesh polycount is documented to 300k and Smart Topology to 100–15,000 (default 4,000), so Meshy is routed primarily for topology/post-processing/rig-ready production rather than absolute face-count leadership. Rigging is humanoid/biped-only in current docs — no creature-type taxonomy is documented, unlike Tripo's 7-type auto-rig.

Primary official references:
- https://docs.meshy.ai/en/api/text-to-3d
- https://docs.meshy.ai/en/api/image-to-3d
- https://docs.meshy.ai/en/api/remesh
- https://docs.meshy.ai/en/api/rigging

## Hi3D / Hitem3D

Adds the highest currently documented density target in this comparison: v3.0 `2048master`, with FAQ/parameter tables recommending 5M faces. It also adds portrait-specific generation, 3D model splitting, multicolor preparation, relief generation, 3MF and USDZ output.

**Contract warning:** the current create-task documentation contains an older/conflicting error line that says the valid face range ends at 2M while the same current docs/FAQ recommend 5M for 2048master. v0.3 therefore encodes a 5M → 2M retry ladder instead of treating 5M as guaranteed.

Primary official references:
- https://docs.hi3d.ai/en/api/api-reference/
- https://docs.hi3d.ai/en/api/api-reference/list/create-task
- https://docs.hi3d.ai/en/api/getting-started/faq
- https://docs.hi3d.ai/en/api/getting-started/changelog

## Routing policy

- **Non-biped creature rigging (quadruped/hexapod/octopod/avian/serpentine/aquatic):**
  Tripo only — Meshy is excluded by the router, not just by preference, since its
  rigging path has no documented support for these types (`ProviderId.MESHY not in
  providers_supporting_creature_rig(creature_type)`).
- **Extreme hero geometry >2M / portrait reconstruction:** Hi3D first, Tripo fallback.
- **Stable 2M interchange geometry:** Tripo first.
- **Smart topology, UV/remesh/retexture, rig-ready cleanup:** Meshy first, Tripo fallback.
- **8K PBR texturing:** Tripo and Meshy as independent routes for cross-checking.
- **Semantic part segmentation:** Tripo.
- **Print split / multicolor / 3MF / relief:** Hi3D.
- **Canonical deformation mesh, UDIM layout, baking, shading, grooming, export QA:** local pipeline, not delegated wholesale to a cloud generator.
