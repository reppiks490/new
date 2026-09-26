# Production Architecture

## 1. Control plane

A local API converts natural-language/image/multiview input into a typed `CharacterSpec`. Jobs are immutable plans with stage hashes so generation can be reproduced and resumed.

## 2. Geometry stack

Three representations should coexist:

- **Deformation base:** animation-friendly topology and facial/body edge loops.
- **Interchange/high-detail mesh:** up to the compatibility target (~2M triangles).
- **Hero source:** hardware-aware dense sculpt/reconstruction representation used for close-up lookdev, displacement baking and archival source detail. It may exceed 2M substantially, but is not forced through every realtime stage.

Multires/subdivision keeps detail nondestructive. Dense source -> displacement/normal baking is a first-class operation.

## 3. Surface stack

- UDIM-aware texture sets.
- 4K production and 8K hero tiles.
- Base color, roughness, specular/metallic where relevant, normal, micro-normal, displacement, SSS/skin masks.
- 16/32-bit displacement for high-quality surface relief.
- Streaming/page residency for 8K tile sets.

## 4. Human realism stack

- Layered physically based skin with epidermal/dermal response.
- Separate eye cornea/aqueous/iris/sclera geometry and shaders.
- Strand/groom hair rather than alpha-card-only hero hair.
- Morph targets + pose-space corrective shapes.
- High-frequency pore/wrinkle response separated from macro forms.

## 5. Rigging and animation

- Standard humanoid skeleton plus face rig/blendshapes.
- Corrective morphs for shoulders, hips, elbows, knees, jaw and facial extremes.
- Export through USD/UsdSkel as the canonical rich interchange path, with FBX/GLB fallbacks.

## 6. Rendering

- Interactive preview path: raster/ray-traced renderer or Unreal.
- Offline hero path: Cycles/OptiX where available.
- Geometry and material residency budgets are separate.
- Renderer validates texture color spaces, tangent basis, displacement scale and SSS units before final output.

## 7. Capability packs

Heavyweight model checkpoints and libraries are installed as optional packs. Multi-gigabyte size must correspond to real functionality: generation/reconstruction models, texture models, upscalers, groom libraries, motions, HDR environments, material scans and caches.

## 8. Adult fictional mode

The engine may expose broad fictional-adult anatomy and mature-content workflows. Hard exclusions are enforced before any downstream generation call: sexual minors/minor-appearing characters, non-consensual sexual material, and explicit sexual deepfakes/impersonation of real people.

## 9. Runtime/job substrate (v0.3)

Every generation request compiles into a versioned `JobManifest`. The plan is canonically serialized and hashed; stage state is tracked independently so failed work can later be resumed without changing the input contract. Volatile timestamps/status fields are excluded from reproducibility hashing.

The Blender worker is invoked in background mode through a generated command line. Embedded auto-execution is disabled by default and the trusted Character3D worker script receives the manifest after Blender's `--` separator.

## 10. Pack registry and storage scaling

Capability packs form a dependency DAG. The reference maximum-quality pack set models approximately 100+ GB of genuinely useful optional data/checkpoints before project-local caches and generated 8K assets. The registry supports dependency deduplication, cycle rejection and optional SHA-256 file verification.

Disk size is not a quality metric by itself. A pack is admitted only when its bytes correspond to a defined runtime capability, model/checkpoint, source asset library, rig/motion data, render/lookdev resource, or cache required to accelerate deterministic work.
