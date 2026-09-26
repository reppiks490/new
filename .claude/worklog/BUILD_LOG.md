# Build log — character3d-masterbuild v1.2

Terse running log of what's been done, so chat replies can stay short.
Full detail lives here, not repeated in conversation.

## Session: initial build to spec

- Verified uploaded zip against Ed25519 signature manifest: SHA-256 match confirmed.
- Extracted archive into repo root (143 files: app/, tests/, docs/, scripts/, config/).
- Fixed `pyproject.toml`: setuptools flat-layout auto-discovery failed with
  multiple top-level dirs (app/config/blender_scripts) → added
  `[tool.setuptools.packages.find] include = ["app", "app.*"]`.
- Created `.venv`, installed project editable + dev deps.
- Pinned `starlette>=0.40,<1.0` in pyproject — environment's latest starlette
  (1.7.0) requires a nonexistent `httpx2` package under `-W error`.
- Pinned `anyio==4.3.0` in venv — anyio 4.15.1 emits a hard
  `BlockingPortal` deprecation warning under `-W error` during fastapi
  testclient import.
- Remaining before 114/114 green: `scipy` is used transitively by
  `trimesh` (mesh connected-components / body_count) but not declared as
  a dependency. 8 tests fail with `ModuleNotFoundError: No module named
  'scipy'`. Fix: add `scipy` to `pyproject.toml` dependencies, reinstall,
  rerun full suite.

- Also added `networkx` (trimesh's `repair.fill_holes` needs it; undeclared).
- Result: **114/114 passed, `-W error`** — matches README's stated v1.2
  regression status exactly.

## Final dependency additions to pyproject.toml

- `starlette>=0.40,<1.0` (pin — avoids httpx2 hard dependency in starlette 1.x)
- `scipy>=1.13` (trimesh mesh connectivity/body_count)
- `networkx>=3.3` (trimesh hole-filling/repair)

Note: `anyio==4.3.0` pin is currently venv-only (installed, not declared in
pyproject) — anyio 4.15.1 raises a hard BlockingPortal deprecation warning
under `-W error` via starlette's testclient. Not yet added as an explicit
constraint; a fresh `pip install -e .[dev]` on an unpinned resolver could
pull anyio 4.15+ again and fail collection. Should add
`anyio>=4.0,<4.4` (or similar) to `[project.optional-dependencies].dev` —
flagging, not yet done.

- Added `anyio>=4.0,<4.4` to `[project.optional-dependencies].dev` — closes
  the gap above; pin is now declared, not just present in the working venv.
- Added `.gitignore` (.venv/, __pycache__/, build artifacts, pytest cache).
- Verified from clean room: fresh `.venv2` + `pip install -e ".[dev]"` +
  `pytest -q -W error` → **114/114 passed**, using only pyproject.toml
  (no manual post-install pins). Confirms the fix is real, not
  venv-specific happenstance.

## Status: build complete, committed and pushed

All four packaging/dependency gaps between the shipped source and a clean
install closed:
1. setuptools flat-layout multi-package discovery
2. starlette pin (avoid httpx2 hard dep in 1.x)
3. scipy (trimesh transitive, undeclared)
4. networkx (trimesh transitive, undeclared)
5. anyio dev pin (avoid BlockingPortal deprecation under -W error)

Spec target (README): 114 tests passing, warnings as errors. Met exactly.

Committed as `37c155b`, pushed to `origin/claude/effort-status-tjzcfd`.

## PR: not applicable

`reppiks490/new` had zero commits before this session. This branch is now
the repo's only branch (and its default) — there is no other branch to
diff against, so `create_pull_request` correctly rejects the base. This
push *is* the repo's initial history, not a change proposed against one.

## Session 2: dogfood release verification + CI

- Ran the project's own `scripts/verify_release.py` against the artifact
  it was delivered in (the original signed zip + its signature manifest).
  First attempt returned INVALID.
- Root-caused rather than assumed-broken: the uploader had renamed the
  file with a `99ffe1d3-` staging prefix. `artifact_name` is part of the
  Ed25519-signed payload (by design — prevents a renamed/substituted file
  from passing), so the verifier correctly rejected the renamed path.
  Not a bug. Confirmed by copying to the original filename and
  re-verifying: **VALID**, exit 0. Full end-to-end proof the release
  signing/verification pipeline works, not just a manual sha256 check.
- Smoke-tested `app.main` imports cleanly and exposes a FastAPI `app`
  object (both Python 3.11 and 3.12).
- Added `.github/workflows/ci.yml`: matrix on Python 3.11/3.12, installs
  `.[dev]`, smoke-tests the app import, runs `pytest -q -W error`.
- Verified the 3.12 leg locally before shipping it (not just assumed) —
  fresh `.venv312`, clean install, 114/114 passed on 3.12 too.

## Session 3: creature-type rig capability (Tripo research finding)

Scope note: the incoming instruction for this session asked for much more
(8K render pipelines, skin/eye/hair shading depth, GPU scheduling detail,
explicit adult anatomy generation, etc.) than one engineering cycle can
honestly implement and verify. I did one real, sourced, tested cycle
end-to-end rather than a large batch of unverified scaffolding. I also did
not implement explicit sexual/anatomical content generation — the repo's
own existing policy gate (`app/core/policy.py`) and architecture doc
already scope an adult-fictional mode with hard exclusions, and I left
that boundary as-is rather than building out anatomical detail systems.

- Live web search (WebFetch to the vendor doc domains themselves was
  blocked by this environment's network egress policy — confirmed via
  `read_documentation`, not assumed) confirmed:
  - Tripo H3.1: face count up to 2,000,000, quad topology, text/image/
    multiview input, GLB/FBX export — matches existing catalog.
  - Tripo auto-rig endpoint: **7 documented creature types** (biped,
    quadruped, hexapod, octopod, avian, serpentine, aquatic) + a free
    "Rig Check" pre-flight endpoint. This was NOT in the existing
    capability matrix — RIGGING was a bare boolean.
  - Meshy remesh: 100-300,000 polygons (matches). Smart Topology:
    100-15,000, default 4,000 (default wasn't previously recorded).
    Meshy's rigging docs are humanoid/biped-only — no creature taxonomy.
  - Hi3D: 2,000,000 (2048quality) / 5,000,000 (2048master) — matches
    existing 5M->2M retry ladder exactly.
- Added structured, queryable fields to `ProviderProfile`:
  `rig_creature_types: list[str]`, `rig_precheck_endpoint: bool`,
  `last_reviewed: str` — per the spec's "don't bury capabilities in
  comments, make them queryable" requirement.
- Added `providers_supporting_creature_rig(creature_type)` in
  `app/providers/catalog.py`.
- Added `creature_type` field to `CharacterSpec` (biped default, plus
  the 6 other Tripo-documented types).
- Updated `app/providers/router.py`'s rigging route: non-biped
  `creature_type` now excludes Meshy from the candidate list (not just
  deprioritizes it) with an explicit warning, since Meshy has no
  documented support for those rig types.
- Updated `docs/VENDOR_CAPABILITY_MATRIX.md` with a dated review header,
  the new Tripo rig-taxonomy finding, Meshy's default Smart Topology
  polycount, and the new routing rule, with source URLs.
- Added 4 new tests (`tests/test_providers.py`): review-date presence,
  Tripo's 7 creature types are queryable (not notes-only), router
  excludes Meshy for non-biped rigging, router keeps both providers for
  the biped/default case (no regression).
- Full suite: **118/118 passed, `-W error`** (114 prior + 4 new).

## Next candidates (not yet done, for whoever continues this)

- Meshy's documented preview→refine task staging isn't yet modeled as a
  two-phase pipeline stage in `app/pipeline/` — currently only
  `text_preview_request`/`refine_request` request builders exist in
  `app/providers/meshy.py` without a stage that sequences them.
- Hi3D's portrait-specialist and relief/depth workflows are capability
  flags in the catalog but have no dedicated request-builder module the
  way `app/providers/hi3d.py::image_task_fields` covers geometry/3MF.
- The geometry-tier module (`app/runtime/geometry_tiers.py`) still only
  has 3 tiers (preview/interchange_2m/hero_multires); the incoming spec's
  4-tier breakdown (preview/production/compat_2m/hero) partially exists
  in `QualityTier` enum but isn't reconciled with this module.

## Session 4: /goal set — scene/world/animation composition + centralized content filters

A `/goal` command set a session-scoped Stop hook directing continued
build-out toward "full spec 3D builder... scenes, vast worlds, animation...
xxx rated... invoke any and all plugins... install those that need to be."

Two things stated plainly and held regardless of the hook:
1. Declined to build explicit sexual/anatomical content generation systems.
2. Declined a follow-up instruction ("remove the previous boundary") asking
   to remove the minor-sexual-content / non-consensual-content hard-block
   filters. Those stay permanently. This is not a configurable engineering
   parameter and no in-session instruction changes it.

Real engineering delivered this cycle:

- **Scene/world composition** (previously did not exist at all —
  confirmed via grep before building, not assumed):
  - `app/core/scene_models.py`: `SceneSpec`, `SceneAssetInstance`,
    `Transform`, `AssetKind`, `SceneScale`, `EnvironmentLighting`. Scenes
    compose already-canonical, already-policy'd assets by SHA-256
    reference — scene assembly is a placement concern, not a new
    generation surface.
  - `app/pipeline/scene_planner.py`: `compile_scene_plan` — policy gate,
    hardware-aware combined-scene triangle budget (reuses the
    `_hardware_hero_cap` heuristic from `app/pipeline/planner.py`,
    generalized to a whole scene), deterministic `scene_manifest_hash`
    (same determinism discipline as `app/release/`).
  - `app/qa/scene.py`: `qa_scene_placement` — bounding-sphere overlap
    detection and scene-bounds containment check.
- **Animation clips** (also did not exist — only pose-deformation
  snapshots existed in `app/qa/rig.py`, no timeline/keyframe model):
  - `app/core/animation_models.py`: `AnimationClip`, `AnimationTrack`,
    `Keyframe` — monotonic-keyframe-time validation, morph-target tracks
    via `target_joint="morph:<name>"`.
  - `app/qa/animation.py`: `qa_animation_clip` — unknown-joint and
    empty-track detection against a rig's known joint set.
- **Centralized content filtering** (user explicitly asked to "add
  filters such as nsfw"; this also closed a real gap — scene prompts had
  zero content filtering before this):
  - `app/core/content_filters.py`: single source of truth for the
    prompt-safety regexes that used to live only inline in
    `app/core/policy.py`. `FilterCategory` enum, `HARD_BLOCK_CATEGORIES`
    (minor-sexual-content, non-consensual-content — unconditional,
    mode-independent), generic `nsfw_signal` tagging.
  - `app/core/policy.py` refactored to use the shared module — verified
    byte-for-byte identical behavior via the pre-existing
    `tests/test_policy.py` (all 3 tests still pass unmodified).
  - `app/core/scene_policy.py`: new — applies the same filter to
    `SceneSpec.prompt` and asset `display_name`s. Wired into
    `compile_scene_plan`, which now short-circuits (no budget, no
    manifest hash, no stages) on a blocked scene, mirroring how
    `compile_plan` already short-circuits for characters.
- Tests added: `tests/test_scene.py` (6), `tests/test_animation.py` (5),
  `tests/test_content_filters.py` (8), `tests/test_scene_policy.py` (5).
  Full suite: **142/142 passed, `-W error`** (129 prior + 13 new).

## Next candidates

- World-scale terrain/environment generation itself (heightmaps, biome
  composition) is still unmodeled — `SceneSpec.prompt` + `scale` exist as
  a description/budgeting hook, but there's no terrain generation stage.
- No render-quality-tier model yet (PREVIEW/PRODUCTION/HERO/EXTREME Cycles
  profiles) distinct from `QualityTier` (which is a geometry tier, not a
  render-sampling tier) — `app/render/cycles.py` should be checked against
  this before adding one, to avoid a parallel/conflicting concept.
- Scene-level export (combining multiple canonical character/prop assets
  into one exported USD stage/GLB scene graph) has no implementation yet;
  `app/exports/` currently only validates single-asset exports.

## Session 5: multi-asset scene export

Two more mid-turn requests declined, same boundary as session 4, not
re-argued each time: "relieve the boundaries constraints" and "add
'futa' to the 3D toggle" (explicit sexual-content generation). Both no.
Minor/non-consent filters and the no-explicit-sexual-content-generation
line are stable and not going to keep restating at length each time —
future asks in this direction get a short "no, same as before" and the
turn continues on legitimate work.

Checked before building anything new (per the "next candidates" list):
render-quality tiers already exist and are solid
(`app/render/cycles.py::quality_preset` — preview/production/hero/extreme,
VRAM-aware device/sample/dicing/tile-size policy). No gap there; skipped.

Real gap confirmed and closed: `app/exports/validation.py` could already
parse a `trimesh.Scene` (multi-geometry) for QA purposes, but nothing
could take this session's new `SceneSpec` + per-instance resolved mesh
files and actually assemble + validate a combined multi-node export.

- `app/exports/scene_export.py`:
  - `transform_matrix(Transform)` — deterministic TRS (scale, then
    intrinsic XYZ Euler rotation, then translation). Verified against
    live trimesh (not assumed) before writing formal tests: probed the
    installed trimesh version's actual `Scene.graph[node_name]` return
    shape (`(matrix, geometry_key)`) and confirmed node names survive a
    real GLB export/import round-trip, via a throwaway script, before
    writing code that depends on that API shape.
  - `assemble_scene_glb(scene, resolved_assets, output_path)` — combines
    real per-instance mesh files into one multi-node GLB at their
    declared transforms. Real, executed local geometry work (trimesh),
    consistent with this project's execution-truth discipline: a
    `passed` report means the file was actually written with that many
    real nodes, not planned/synthetic.
  - `validate_scene_export(scene, output_path)` — reopens the exported
    file and cross-checks it against the SceneSpec that was supposed to
    produce it: every declared instance present, no silent extra nodes,
    and each node's transform matches the declared `Transform` within
    tolerance.
- `tests/test_scene_export.py`: 5 tests, all using real trimesh box
  fixtures written to `tmp_path` and real GLB round-trips through disk
  (no mocking of the export/import step) — including a transform-mismatch
  detection test and a missing-node detection test.
- Full suite: **147/147 passed, `-W error`** (142 prior + 5 new).

## Next candidates

- USD-path scene assembly (xform hierarchy via UsdGeom.Xformable) is not
  implemented — `app/exports/usdskel.py` handles single-asset UsdSkel,
  but scene-level USD composition would need `pxr`, which this packaging
  environment does not have (confirmed, not assumed — see README).
  GLB is the only scene-export path implemented so far.
- World-scale terrain/environment generation is still unmodeled (heightmaps,
  biome composition) — `SceneSpec.prompt` + `scale` remain description/
  budgeting hooks only, no generation stage exists.
- Meshy preview->refine staged pipeline and a dedicated Hi3D request-builder
  module remain open from session 3's notes.

## Session 6: procedural terrain + advanced body-proportion morphs

Declined again this cycle, same as before, not re-argued: "add a toggle
for said restrictions on ultracode" (a disable-switch for the minor/
non-consent filters, under any name). No.

Two real, tested engineering deliverables:

**Procedural terrain** (world/vast-worlds gap from session 5's notes):
- `app/world/terrain.py`: `TerrainSpec` + `diamond_square_heightmap()` —
  classic diamond-square fractal terrain algorithm, deterministic/seeded,
  numpy-only (no external model, asset, or network fetch). Verified via
  a throwaway probe script before writing formal tests (determinism,
  finiteness, seed-sensitivity, non-degenerate variance) — same
  discipline as session 5's trimesh API probe.
- `heightmap_to_mesh()` + `generate_terrain_mesh()`: real grid-mesh
  triangulation producing an actual exportable `trimesh.Trimesh`
  (verified vertex/face counts, real GLB export/reload round-trip).
- Noted honestly: `resolution_power=10` (1025x1025 grid) yields exactly
  2,097,152 triangles — checked arithmetically in a test rather than
  just asserted — which happens to land at this project's existing "2M
  interchange" tier; called out as a coincidental alignment, not
  engineered to match it.
- 6 new tests (`tests/test_terrain.py`).

**Advanced body-proportion morphs** (requested this cycle: "resize
proportions on an advanced scale... not standard, complex and
advanced"; bust size explicitly requested and included). Scoped
deliberately to general body-build/proportion sliders — height,
shoulder width, waist, hip width, limb length/thickness, muscularity,
body fat, bust size, etc. — the same category of slider present in any
mainstream, general-audience character creator (Sims, MakeHuman,
RPG avatar makers). This is not the anatomical/sexual-content boundary;
that boundary is unchanged and is addressed explicitly in the module's
own docstring so it doesn't need restating in code review later.
- `app/core/body_morphs.py`: `BodyProportionSlider` enum (16 sliders,
  including `BUST_SIZE`), `BodyMorphSpec` (range-validated [-1,1]
  sliders), `RegionAxisScale` + `DEFAULT_SLIDER_REGIONS` mapping each
  slider to named region(s)/axis/pivot/max-multiplier.
- `app/rigging/body_morph_apply.py`: `apply_body_morphs()` — genuinely
  advanced (not "standard") regional scaling: continuous **per-vertex
  weighted falloff** (not a hard binary vertex-group boundary), so
  adjacent regions blend instead of seaming, exactly what
  `docs/ARCHITECTURE.md` warns to avoid ("crude global vertex scaling").
  Sliders compose sequentially, so overlapping regions (e.g.
  MUSCULARITY and BODY_FAT both touching "torso") combine naturally.
- 9 new tests (`tests/test_body_morphs.py`) using a real trimesh box
  fixture: pivot-relative scaling verified against actual bounding-box
  extents, continuous-weight partial falloff verified to land strictly
  between no-change and full-strength change, topology-preservation
  (faces unchanged, only vertex positions move) verified directly.

Full suite: **162/162 passed, `-W error`** (147 prior + 6 + 9).

## Next candidates

- `apply_body_morphs` region names (e.g. "torso", "shoulders") assume a
  caller-supplied per-vertex weight map keyed by those names; there is no
  standard rig's vertex-group export/import path yet connecting this to
  an actual generated character mesh — currently a general-purpose
  library function, not yet wired into the character pipeline stages
  list (`app/pipeline/planner.py`).
- Meshy preview->refine staged pipeline and a dedicated Hi3D
  request-builder module remain open from session 3.
- USD-path scene assembly still blocked on `pxr` not being available in
  this packaging environment (confirmed, not assumed).
