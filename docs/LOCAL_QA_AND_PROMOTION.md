# Local QA and provider-neutral promotion

Provider brand is not a quality metric. v0.5 introduces local inspection before a remote asset can become the canonical character source.

## Geometry checks

- face and vertex counts
- geometry/body count
- watertightness
- winding consistency
- degenerate-face ratio
- measured UV availability
- bounds/extents and surface area

These checks are deliberately separate from generation. A 5M-face output that has worse topology can lose to a cleaner 2M-face candidate.

## Texture checks

Texture QA records actual pixel dimensions and flags whether a map reaches 2K, 4K, or 8K. A provider's requested setting is not accepted as proof of delivered resolution.

## Promotion gate

Candidate score combines local mesh metrics, actual texture resolution, PBR channel completeness, source/reference similarity (when a future vision QA module supplies it), rig readiness, and optional portrait specialization. Hard blockers can reject a high score—for example, >=2% degenerate faces or inconsistent winding.

## 8K UDIM strategy

Eight 8K tiles across six raw maps represent a large staging-memory footprint. The planner therefore treats mip/virtual-texture streaming and region-by-region baking as mandatory for hero configurations rather than assuming every map can remain GPU-resident simultaneously.

## Cycles

The render preset generator maps NVIDIA/AMD/Intel/Apple devices to OPTIX/HIP/ONEAPI/METAL and scales samples, dicing rate, and tile size with VRAM. It is a starting point, not a guarantee that a given displaced/groomed scene fits memory.
