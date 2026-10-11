# Beyond-Tripo Browser 3D Studio — Product and Quality Specification

**Status:** Product specification and execution plans approved; implementation
is in progress.

**Last updated:** 2026-10-10

**Owner brief:** Build a browser-accessible 3D editor whose useful model creation,
inspection, editing, mesh processing, and presentation capabilities meet or
exceed the value of Tripo3D. Edits must be precise and must not lower the quality
of the source model. Preserve this document as the canonical record of that goal.

## Product target

Forma must become an end-to-end 3D workspace, not a model viewer with a prompt
box. A user should be able to import an asset, understand what is editable,
change it with precise controls or a natural-language instruction, inspect and
repair the mesh, improve its materials and rig where supported, render it, and
export a verified result. Editing a model must preserve the original as a
reversible source version.

“Beyond Tripo” means deeper, inspectable control and a reliable local editing
path in addition to the AI-assisted workflow. It is a product target, not a
claim of present feature parity or equal visual output. Tripo's current public
Studio tutorial groups its workflow into Generate, Overview, Segmentation,
Retopology, Texture, Rigging, and Stylization. Tripo's quad-remesher page
describes AI-generated quad topology. Those are reference capabilities, not
proof that this repo has the same services or API access.

Sources reviewed:

- [Tripo Studio tutorial](https://www.tripo3d.ai/blog/tripo-studio-tutorial-english)
- [Tripo AI quad remesher](https://www.tripo3d.ai/features/ai-quad-remesher)
- [Tripo developer API](https://developers.tripo3d.ai/en)

## Editing contract: precision before execution

The prompt `slim her waist without reducing glute and hip size` is a key
acceptance case. The editor must resolve it into an explicit, reviewable change
plan, for example:

```json
{
  "operation": "reduce_width",
  "target_regions": ["waist"],
  "protected_regions": ["glutes", "hips"],
  "amount": null,
  "requires_amount_review": true
}
```

The exact amount is deliberately not guessed when the user omits it. Before
geometry changes, show the target, operation, amount, affected objects, and
protected regions. Let the user adjust the proposed amount and preview the
result. Ambiguous or unsupported anatomy must produce a clear question or a
blocked edit, never a silent best guess.

### Hard preservation requirements

- Parse conjunctions, negation, comparisons, units, numbers, and protected
  clauses as structured intent. Do not split a sentence on `and` before
  identifying its grammatical relationships.
- Resolve semantic regions to authored morph targets or explicit, inspectable
  masks. Never infer a body region solely from an object's generic name.
- Use existing source shape keys when they match the intended operation and
  pass region-delta checks. An authored target is not automatically safe for
  every prompt or protected-region constraint.
- For a hard-protected region, enforce zero displacement at protected vertices
  and report its measured maximum positional delta. If a valid, smooth result
  cannot satisfy that condition, reject the operation and explain why.
- Keep the original model bytes and source hash unchanged. Save edits as
  versioned operations with undo/redo and a restorable pre-edit state.
- Show a same-camera, same-lighting before/after preview, affected-region
  overlay, and quantitative report before accepting the edit.
- Validate finite coordinates, connected surfaces, normals, self-intersections,
  material/UV/rig compatibility, and export/reopen parity. A preview-only
  deformation is not a completed edit.
- Keep body, clothing, hair, accessories, and rig data distinct. Do not silently
  move only the body while leaving attached clothing behind or claim garment
  fit when it was not tested.

### Model capability discovery

Each imported model needs an inspectable capability report covering at least
mesh/object count, triangle count, material and image counts, UV sets, skeletons,
vertex groups, morph targets and names, animation clips, coordinate scale, and
known conversion constraints. The UI must distinguish supported now, supported
after a specific local operation, available only through an explicitly
configured provider, and unavailable for this asset.

The editor must not advertise a body slider merely because it exists for another
base model. Static models without authored morphs require region masks or a
validated deformation map before semantic body edits are enabled.

## Mesh and asset workflow

The target workflow covers import and capability inspection; prompt- and
image-conditioned generation; segmentation and part selection; direct numeric
transform and sculpt controls; morph editing; voxel remesh, quad retopology, and
face-count reduction; material/texture work; rigging and animation support;
rendering; and export. Operations that replace topology must create a new
version and report what happened to UVs, materials, morphs, vertex groups,
weights, skeletons, clips, clothing bindings, and attachments.

Local Blender operations are the first no-surprise-cost processing path.
Provider-backed generation or enhancement must name the provider, display
known cost/credit information when available, explain the data sent, and require
an explicit user action. Never call a paid service silently or claim an AI
operation ran when it did not. If required credentials, models, hardware, or
licenses are missing, show the dependency and retain the original asset.

## Render and enhancement contract

The current working interpretation is that 8K, 16K, and 32K describe final
render dimensions, not texture-map dimensions. Texture resolution is a separate
setting. The render workflow must expose actual output dimensions, quality
settings, samples/denoising where supported, format and bit depth, memory
preflight, background job progress, cancellation only when the worker supports
it, and verified output dimensions. High-resolution jobs must use the existing
tile/strip machinery where needed and report hardware and runtime limits.

“Enhance” must name the operation performed. Higher render resolution, denoising,
texture-map upscaling, and AI super-resolution are separate operations. Resizing
an image must not be described as adding detail. AI enhancement remains
unavailable until a real model/provider is installed and verified.

## Audited source-asset facts (2026-10-10)

These are initial structural measurements of files present in
`workspace/imported_models`; they do not certify visual quality, creator
licensing, deformation behavior, or a successful export round trip.

| Asset | Observed structure | Editing implication |
| --- | --- | --- |
| `street_fighter_cammy_tpose_bikini.glb` | 17 meshes, 2,000,000 triangles, 1 material, 2 images, no skins, animations, or morph targets | Dense static surface; no source-authored body controls to invoke |
| `female_cosplay-_street_figther_sexy.glb` | 4 meshes, 401,989 triangles, 1 material, 3 images, no skins, animations, or morph targets | Static surface; no source-authored body controls |
| `Command Grab.blend` | Body mesh has 6,318 vertices and 9 shape-key blocks; 233-bone deform armature plus a 966-bone control rig; the scene has many separately authored objects | Blender source contains substantially richer structure than the browser GLB workflow currently exposes |
| `Elegg_2.1.blend` | `BaseModel` has 17,612 vertices, 300 non-basis shape keys, one UV layer, and 280 vertex groups; a 233-bone armature and a separate 966-bone rig are present | Authored waist, breast, hip, and glute targets exist in the source and should be evaluated for reuse |
| `Haineko.blend` | `Body` has 29,483 vertices, 244 non-basis shape keys, 3 UV layers, 902 vertex groups; armatures with 174, 68, and 1,281 bones are present | Authored `Thin Waist`, `Breast Size`, `Hip Size`, and `Glutes Size` targets exist; interactions and protected-region deltas still require exhaustive testing |
| `command-grab-clothed.glb` | 21 meshes, 1,271,016 triangles, 18 materials, 4 images, one skin, and 12 morph targets | Imported GLB exposes a rig and morphs, but the available morph names are primarily facial; body compatibility needs a per-target report |

The other registered GLBs include `pomni_censored.glb` (120,826 triangles,
30 meshes), `pomni_censored__t_pose__clown_girl.glb` (2,000,000 triangles,
17 meshes), and `sexy_frozen_queen.glb` (493,953 triangles, 6 meshes). The
structural inspector reports no skins, animations, or morph targets on these
three files. Full compatibility and visual audits remain open.

The imported source files are user-provided. Their redistribution licenses have
not been verified; do not bundle them into a public package or deploy them to a
third-party model service without permission and licensing review.

## Current limits and implementation evidence (2026-10-10)

The browser now reviews and previews mapped prompt edits on its CC0 base. Supported
single-region operations map breast size to the authored breast target, glute size
to the authored glute target, hip width to the authored hip-width target, and
waist reduction to the constrained waist mask. Percentages for authored targets
mean morph strength, not a measured anatomical percentage. Each edit has an
accept/cancel step and accepted changes can be undone. A requested protected
region is checked against the target's authored vertex support; overlapping
targets are rejected rather than silently moving protected vertices.

The protected-region prompt `slim her waist without reducing glute and hip size`
parses to a waist reduction plan and requests an amount when omitted. The
supported CC0 base previews that edit with zero displacement across protected
authored hip and glute support vertices. Cumulative waist reduction is capped
at 15% after triangle-orientation checks; waist widening remains disabled.

Imported GLBs still need per-model semantic maps to support anatomical prompts.
The Pomni source has 30 meshes and no skins, animation clips, or morph targets;
its local brush only edits a picked surface patch. Named anatomy prompts are
blocked for this source so they cannot be mistaken for a precise body-part edit.
The brush does not provide Tripo-style AI segmentation or automated semantic
body reconstruction.

The Blender files are not currently imported by the browser model library, which
registers self-contained GLBs. Converting a `.blend` is not considered lossless
until shape keys, UVs, materials, vertex groups, skeletons, and a representative
pose survive conversion and are verified on the reopened GLB.

- `app/studio/web/edit-intent.js` returns typed targets, operations, protected
  regions, amounts, units, ambiguity, and conflict status. It does not split
  protected conjunctions or invent a missing amount.
- `app/studio/web/data/body_region_masks.json` defines source-specific masks
  from authored target support. `body-edits.js` measures protected-vertex deltas
  and limits waist reduction to 15%.
- Browser edits are previewed before acceptance. Accepted controls and waist
  operations enter undo history, remain editable, and export to GLB. A local
  browser round trip was verified for an accepted breast target edit.
- Imported GLBs expose mesh, triangle, UV, skin/joint, morph, and coordinate
  metadata. Morphs remain unmapped unless a per-target audit proves their
  semantic meaning and preservation behavior.
- These are source-specific controls, not general AI model editing or proof of
  visual parity with Tripo. Automated segmentation, imported-mesh anatomy edits,
  retopology, texturing, rigging, Blender project conversion, and remote render
  jobs remain incomplete. Generation and enhancement require configured provider
  credentials and a connected worker; a static GitHub Pages site cannot run
  those services by itself.

## Staged delivery and gates

1. **Asset truth and safe prompt editing:** preserve originals; inspect source
   capabilities; parse prompts into typed operations and protected regions;
   require review where amounts or anatomy are ambiguous; add regression tests
   for negative constraints and explicit value changes.
2. **Authored controls and masks:** import/convert editable Blender sources with
   round-trip checks; audit morph-target deltas; add correctable, versioned
   region masks and constraint-aware preview for static meshes.
3. **Mesh operations:** expose Blender voxel remesh, Quadriflow quad remesh, and
   face reduction as reversible jobs; compare pre/post geometry and preserve or
   explicitly report UV/material/rig/morph/animation losses.
4. **Full asset pipeline:** add verified segmentation, texture, rigging,
   stylization, and generation paths. Each operation must be local or backed by
   a named, configured provider; no cosmetic controls without a working result.
5. **Render and hosted browser workflow:** expose verified 8K/16K/32K output,
   resource-aware execution, durable job status, export/reopen validation, and
   a private browser deployment with the required Python/Blender worker.

### Acceptance gates

- The protected-region example produces a preview plan that targets waist and
  locks glutes and hips; no edit is applied until the user reviews the proposed
  amount. Measured protected-region max vertex delta is zero after application.
- Tests cover negation, conjunction, multiple targets, numbers/units, synonyms,
  unsupported regions, conflicting instructions, ambiguous amounts, and undo.
- Authored morphs are checked per target for affected vertex ranges and
  interactions. Every advertised morph passes protected-region tests or is
  marked incompatible with that constraint.
- Original model hash is unchanged. Saved project, exported GLB, and reopened
  GLB agree on the accepted edit; materials and supported rig data remain
  intact.
- Remesh/retopology reports target and actual face counts plus preservation
  status. Failure leaves the original and current project intact.
- 8K/16K/32K exports are verified from the produced file's actual dimensions;
  tests do not treat a requested tier or planned job as proof of a finished
  render.
- Browser tests cover keyboard operation, constraint review, before/after,
  save/reopen, and export. Visual review uses the same camera and neutral
  diagnostic lighting before presentation lighting.

## Open questions

- _Unknown - ask the owner and record the answer._ Which deployment should host
  the Python/Blender worker alongside the private browser front end?
- _Unknown - ask the owner and record the answer._ What hardware is available
  for interactive sculpting and 16K/32K rendering?
- _Unknown - ask the owner and record the answer._ Are paid external provider
  calls acceptable when the interface shows the provider and exact known cost
  before submission?

## Scope honesty

This document records the product goal and measurable requirements. It does not
mean that Tripo parity, source conversion, semantic prompting, model processing,
high-resolution browser jobs, or quality equivalence has been implemented or
verified. The existing Python suite must be run after implementation begins;
provider execution, hosted worker behavior, and visual quality require separate
live evidence.
