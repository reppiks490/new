# Work checkpoint — 2026-10-10

This checkpoint preserves the user's latest product direction and the evidence
collected before implementation. It is a requirements and audit checkpoint, not
a claim that the requested product is built or at Tripo parity.

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

- `app/studio/web/app.js` splits prompt text on `and`, has no protected-region
  constraints, and applies a default 40% when an amount is missing. The example
  prompt can miss the waist, reduce glutes, and increase hip width.
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
- Exact CI test command: `.venv/bin/python -m pytest -q -W error` — 462 passed,
  11 failed in 60.54 seconds. It fails the same 11 Blender live tests as the
  initial run. The captured common render error is the missing
  `SubsurfModifier.use_adaptive_subdivision` property in Blender 4.3.2.
- Local Docker 28.4.0 is available. `docker build -t
  character3d-masterbuild:codex-check .` failed while pip tried to install
  build dependencies: the container did not trust the environment's
  self-signed TLS certificate chain for PyPI. The image was not built or
  smoke-tested. No remote GitHub Actions run was triggered.

## Worktree and next gate

The worktree is `codex/browser-studio-customization`. This turn has only added
requirements documentation; application code and deployments are unchanged.
The user asked to preserve the direction in the repository and run tests. The
resulting spec remains a draft for owner review. After spec approval, write and
review an implementation plan, then implement in testable increments.

Do not claim feature parity, lossless source conversion, prompt precision,
finished high-resolution render jobs, or visual quality equivalence until their
acceptance gates pass with evidence.
