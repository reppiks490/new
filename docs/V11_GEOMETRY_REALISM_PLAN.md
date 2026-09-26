# v1.1 Geometry + Realism Plan

## Benchmark delta
Current Tripo H3.1 documentation advertises text/image/multiview generation, PBR, quad output, smart low-poly, and up to 2,000,000 triangles in Ultra mode. Therefore 2M triangles is treated as the **interchange compatibility tier**, not the hero ceiling.

## Geometry tiers
- Preview: <=100k triangles for interactive authoring.
- Interchange: <=2M triangles for provider round-trip, validation, and export compatibility.
- Hero: uncapped policy-wise; actual density is hardware-budgeted and nondestructive. Preserve a deformation-friendly base cage and store detail in Multires levels, 16/32-bit displacement, micro-normal maps, and UDIM texture sets.

## Why this beats naive triangle escalation
Raw triangle count is not the quality objective. Facial silhouette, anatomical landmarks, deformation topology, texel density, displacement bandwidth, groom strand density, and shading fidelity are separately budgeted. Hero density may exceed 2M when hardware permits, but canonical interchange remains bounded.

## Reference-view pipeline
A visual-reference adapter is reserved for connected image generators. It must emit identity-consistent orthographic-ish front/3-quarter/profile/back views plus material closeups, each with camera metadata and a consistency score. Generated references are evidence inputs, not ground truth.

## Capability packs (useful bytes only)
Future multi-GB packs must declare license, hash, version, disk footprint, VRAM/RAM requirement, and task role. Eligible content: reconstruction/checkpoint weights, segmentation/normal/depth models, texture/material upscalers, skin/eye/groom libraries, motion/rig assets, render kernels, and derived caches. Padding is forbidden.

## Acceptance gates
1. Base topology/deformation gate.
2. Landmark/identity preservation gate.
3. 2M interchange export gate.
4. Hero detail projection/bake gate.
5. 4K/8K UDIM PBR and displacement gate.
6. Groom collision/density gate.
7. Rig/morph deformation stress gate.
8. Render multiview consistency gate.
