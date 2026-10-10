# Work checkpoint — 2026-10-10

This checkpoint preserves the user's product direction and implementation
evidence. It is not a claim that the requested product is complete or at Tripo
parity.

## User goal

Build a private, browser-accessible 3D editor with useful model creation,
inspection, editing, mesh processing, and presentation capabilities meeting or
exceeding Tripo3D. Prompt edits must be precise, preserve explicitly protected
regions, and must not reduce source quality. The canonical requirements and
acceptance gates are in [`BEYOND_TRIPO_SPEC.md`](BEYOND_TRIPO_SPEC.md).

The user emphasized prompts such as “slim her waist without reducing glute and
hip size.” This is a hard semantic-constraint acceptance case, not a cosmetic
prompt-box requirement.

## Audit findings

- The former prompt parser split on `and`, lacked protected-region constraints,
  and guessed 40% when an amount was missing. It has been replaced by structured
  intent parsing; the protected waist example now plans the waist change and
  protects glutes and hips without guessing an amount.
- The two imported Street Fighter GLBs are static. Cammy has 17 meshes and
  2,000,000 triangles; neither Street Fighter GLB contains skins, animation
  clips, or body morph targets.
- The Elegg and Haineko Blender sources have authored shape keys and rig data.
  Elegg's `BaseModel` has 300 non-basis keys; Haineko's `Body` has 244, including
  `Thin Waist`, `Breast Size`, `Hip Size`, and `Glutes Size`. Their interaction,
  exported fidelity, and protected-region behavior remain unverified.
- The browser model library currently registers self-contained GLBs, not Blender
  source projects. A Blender conversion counts as lossless only after verifying
  morphs, UVs, materials, vertex groups, rigs, and representative poses after
  export and reopen.
- Tripo's public tutorial describes Generate, Overview, Segmentation,
  Retopology, Texture, Rigging, and Stylization. The current repo's Tripo adapter
  is generation-oriented; these listed UI capabilities do not prove all are
  available through the API adapter in this repository.
- Local Blender 4.3.2 has both voxel remesh and Quadriflow quad remesh. The
  browser app does not expose these as model-editing jobs.

## Verification baseline

- System Python has no `pytest`; the repository `.venv` does.
- Initial full `.venv` run: 462 passed, 11 failed in 65.60 seconds. Failures
  include Blender live render/bake tests; the captured common error is that
  Blender 4.3.2's `SubsurfModifier` lacks `use_adaptive_subdivision`. This must
  be investigated before relying on the rendering pipeline.
- App import, Python compilation, JavaScript syntax checks, and `git diff
  --check` passed before this checkpoint was written.
- Exact initial CI test command: `.venv/bin/python -m pytest -q -W error` — 462
  passed, 11 failed in 60.54 seconds. It fails the same 11 Blender live tests as
  the initial run. The captured common render error is the missing
  `SubsurfModifier.use_adaptive_subdivision` property in Blender 4.3.2.
- Local Docker 28.4.0 is available. `docker build -t
  character3d-masterbuild:codex-check .` failed while pip tried to install
  build dependencies: the container did not trust the environment's
  self-signed TLS certificate chain for PyPI. The image was not built or
  smoke-tested. No remote GitHub Actions run was triggered.

## Worktree and next gate

The worktree is `codex/browser-studio-customization`. The owner approved the
spec and all five execution plans, and implementation has begun. Current code
adds a typed prompt intent parser, review-before-preview UI, and one tested local
waist-width operation for the supported CC0 base. That operation uses explicit
authored-target-derived masks, protects the vertices touched by hip and glute
targets with measured zero displacement, limits width change to 15%, supports
preview/cancel/accept/undo, persists in project state, and exports as geometry.
Imported models expose capability reports; their semantic edits remain blocked
until per-model maps pass equivalent checks.

The model inspector now reports mesh and triangle counts, UV sets, skin joint
counts/attributes, morph names, coordinate bounds when source accessors provide
them, and explicitly unmapped morph targets. The prompt parser tests cover
negation, conjunctions, protection, units, missing amounts, conflicts,
unsupported regions, and comparison ranges.

Latest verification: `.venv/bin/python -m pytest -q -W error` reports 469 passed
and the same 11 pre-existing Blender 4.3.2 live failures caused by missing
`SubsurfModifier.use_adaptive_subdivision`. Targeted studio/model/body-edit
tests pass (34 passed), all Node tests pass (23 passed), JavaScript syntax and
`git diff --check` pass. A Playwright smoke test at 390px verified plan review,
preview, cancel, accept, save, no horizontal overflow, and no browser errors.
The project remains far from full Tripo parity; remaining approved plans cover
asset ingest, mesh processing, rendering, and provider-backed creation stages.

Do not claim feature parity, lossless source conversion, prompt precision,
finished high-resolution render jobs, or visual quality equivalence until their
acceptance gates pass with evidence.
