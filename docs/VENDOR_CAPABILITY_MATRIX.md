# Vendor capability matrix — v0.3

This project treats external 3D generators as **optional stage-specific accelerators**, not as the source of truth for the character pipeline. The canonical interchange/cleanup layer remains local Blender/USD tooling.

## Tripo3D

Best used for a stable end-to-end path: prompt/image/multiview generation, up to 2M faces in Ultra, PBR, 8K extreme textures, smart retopology/decimation, semantic segmentation, rigging and animation.

Primary official references:
- https://developers.tripo3d.ai/en/models/v3-1
- https://developers.tripo3d.ai/en/docs/mesh-decimate
- https://developers.tripo3d.ai/en/docs/mesh-segment
- https://developers.tripo3d.ai/en/docs/models-texture

## Meshy

Adds explicit 4096^3 geometry generation passes, staged preview → refine, Smart Topology, UV/retexture/remesh endpoints, 8K texture resolution, and humanoid rig/animation paths. Remesh polycount is documented to 300k and Smart Topology to 15k, so Meshy is routed primarily for topology/post-processing/rig-ready production rather than absolute face-count leadership.

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

- **Extreme hero geometry >2M / portrait reconstruction:** Hi3D first, Tripo fallback.
- **Stable 2M interchange geometry:** Tripo first.
- **Smart topology, UV/remesh/retexture, rig-ready cleanup:** Meshy first, Tripo fallback.
- **8K PBR texturing:** Tripo and Meshy as independent routes for cross-checking.
- **Semantic part segmentation:** Tripo.
- **Print split / multicolor / 3MF / relief:** Hi3D.
- **Canonical deformation mesh, UDIM layout, baking, shading, grooming, export QA:** local pipeline, not delegated wholesale to a cloud generator.
