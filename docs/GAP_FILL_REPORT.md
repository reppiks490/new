# Gap-fill report: Tripo → Meshy + Hi3D

The normalized provider layer only treats a feature as a gap-fill when the current Tripo profile does not expose the equivalent capability in the project catalog.

## Meshy gap-fill

- `geometry_4k_pass` — single-image/text generation can use a 4096³ generation pass.
- `uv_unwrap` — dedicated auto-UV endpoint for meshes up to 40k faces; route after remesh.

Meshy also provides useful overlapping alternatives for 8K PBR texturing, smart topology, remesh/retexture, rigging and animation. These are retained as independent fallback/cross-validation routes even where Tripo has analogous functionality.

## Hi3D / Hitem3D gap-fill

- `high_density_5m` — current FAQ/parameter docs recommend 5M faces for v3.0 2048master; encoded with a 5M→2M fallback because of an inconsistent validation line in the same documentation.
- `portrait_specialist` — dedicated portrait model family.
- `print_split` — dedicated 3D model splitting pipeline.
- `multicolor_3d` — dedicated multicolor preparation.
- `relief` — image-to-3D relief/depth workflow.
- `print_3mf` — 3MF export/print path.
- `usdz` — USDZ generation/export path.

## Non-delegated core

Regardless of provider, the masterbuild keeps these responsibilities local/canonical where possible: deformation topology QA, UDIM strategy, displacement/micro-normal baking, skin/eye/hair shading, groom systems, rig correctives, export verification, provenance, deterministic job manifests, caching and offline render orchestration.
