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
