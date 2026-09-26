# v1.3 Worlds, Rendering, and Topology Expansion

## Scope

v1.2 was character-only. v1.3 adds scene/world composition and animation
as first-class outputs alongside characters, plus deeper mesh-topology and
render-output tracking. This document records what shipped, what was
deliberately left out, and why — consistent with this project's existing
execution-truth discipline (`docs/V10_EXECUTION_TRUTH.md`).

## Scenes and worlds

A `SceneSpec` composes already-canonical, already-policy-gated character
and prop assets by SHA-256 reference. Scene assembly is a placement
concern — it does not itself generate character content, and does not
re-run `app/core/policy.py`'s generation-time gate. Scene/world prompts
(environment descriptions, asset display names) go through their own gate
instead (`app/core/scene_policy.py`), using the same shared filter as
characters (`app/core/content_filters.py`).

World terrain is generated locally and deterministically: a diamond-square
fractal heightmap (seeded, no external model or network dependency),
classified into biomes by elevation and slope, tiled with exact
shared-edge continuity (adjacent tiles slice from one master array rather
than being generated independently and approximately stitched), and
streamed with distance-based LOD and cache eviction. Visible tiles export
as real files with real SHA-256 provenance into a validated combined
scene — this is a genuinely connected pipeline, not isolated modules.

## Body-proportion morphing

Scoped deliberately to general body-build/proportion controls — the same
category of slider present in any mainstream, general-audience character
creator (height, limb proportions, waist, hips, bust, glutes, muscularity,
body fat). Regional scaling uses continuous per-vertex weight maps about a
pivot, not a hard vertex-group boundary or a crude whole-mesh scale, per
`docs/ARCHITECTURE.md`'s own standing guidance against the latter.

This is explicitly **not** the place for anatomical/sexual-feature
controls. See `docs/SECURITY_AND_TRUST.md`'s content-filtering section:
that boundary is intentional, permanent, and independent of any other
instruction given to an agent working on this repository.

## Rendering: two different "8K"s

The goal of "8K rendering" conflates two genuinely separate capabilities,
and v1.3 treats them separately:

- **8K texture/bake resolution** (`app/qa/textures.py`, `app/materials/`,
  `app/qa/bake_output_verification.py`): real file-level verification —
  existence, exact dimensions, non-empty, SHA-256 — against a bake
  contract's declared channels and UDIM tiles.
- **8K+ render *output* resolution** (`app/render/output_resolution.py`,
  `app/render/output_verification.py`): a previously entirely-missing
  capability. Tiers run HD/2K/4K/8K/16K, doubling the same way existing
  texture tiers already do. `render_fits_hardware()` mirrors the
  hardware-aware capping already used for geometry
  (`app/pipeline/planner.py::_hardware_hero_cap`) and world tiling
  (`app/pipeline/scene_planner.py::_hardware_scene_cap`), applied to
  render buffers. `verify_render_output()` opens a real file and checks
  its actual dimensions — proven in tests against a genuine 15360×8640
  file, not a stub.

`app/render/job.py::compile_render_job()` ties the pre-existing sampling/
denoise quality system (`CyclesPreset` — "how good") together with the new
resolution system (`RenderOutputSpec` — "how big"), which previously
existed as two disconnected modules with no combined entry point.

Building a genuine 16K-class fixture required raising PIL's default
decompression-bomb guard (`Image.MAX_IMAGE_PIXELS`, ~89.5M pixels by
default) — this project's own defined ceiling (132.7M pixels at 16K)
exceeds it. Rather than disabling the guard, `app/qa/textures.py` raises
it to a fixed, still-bounded 200M-pixel cap, comfortably above the known
ceiling and nowhere near unlimited, with a test confirming the cap is
raised but not removed.

## Polygon topology

`app/qa/topology.py` tracks triangle/quad/n-gon counts and the *exact*
fan-triangulation effective-triangle-count (not just raw face count) —
directly addressing the "do not advertise only raw vertex count" guidance.

This is scoped to OBJ specifically, not GLB: confirmed against the Khronos
glTF 2.0 specification (not assumed from memory) that glTF has no native
quad primitive mode — only point/line/triangle variants — so any quad/
n-gon geometry is necessarily already triangulated by the time it's in a
GLB, and there is no original polygon structure left to recover. trimesh
itself also triangulates on load regardless of source format, which is
why the analyzer reads raw OBJ `f` face lines directly rather than going
through trimesh at all.

## Explicitly out of scope for v1.3

- **FBX quad/n-gon preservation.** FBX can store non-triangulated polygon
  data, but FBX SDK-level parsing is substantially more complex than OBJ's
  plain-text format and was not attempted this cycle.
- **Multi-tile bake-receipt output verification.** The receipt schema
  (`HighLowBakeReceipt`/`BakeChannelReceipt`) records one filepath per
  channel with no per-UDIM-tile breakdown. `validate_bake_receipt_and_output()`
  handles single-tile contracts correctly and explicitly returns no output
  report for multi-tile contracts, rather than silently misattributing one
  channel's file to every declared tile. Extending the receipt schema
  itself to carry per-tile paths is a larger, separate change.
- **An interactive viewport, mesh-sculpt tools, a UV editor, or a
  shader/material editor.** This remains a headless, text-only Python
  library and pipeline; it has no GUI toolkit dependency and this
  packaging environment has no means to build or test one. "Advanced
  editing" here means the programmatic surfaces above (body morphs, scene
  placement QA, topology analysis) — not a rendered interactive tool.
- **Image-to-prompt as natural-language captioning.** `app/pipeline/image_analysis.py`
  performs real local pixel computation (palette, contrast, edge density)
  and is explicit in its own docstring that it is not a captioner — that
  would require a vision-language model this environment does not have.
- **Explicit sexual/anatomical content generation of any kind.** Not a
  gap; a permanent, deliberate exclusion. See `docs/SECURITY_AND_TRUST.md`.

## Regression

**235/235 tests passing, warnings treated as errors**, verified from a
clean install (not just the working development environment).
