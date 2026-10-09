# Browser studio design — 2026-10-08

Status: proposed design for user review; no implementation or deployment claimed.

## Intended outcome

Evolve Character3D into a private browser application for creating, customizing,
dressing, inspecting, rendering, and downloading adult fictional characters and
procedural environments. The user requested extensive customization, a wardrobe,
and accessibility in the browser. Accessibility also includes keyboard and
assistive-technology support. Both realistic and extreme stylized proportions are
in scope, alongside tattoos, piercings, prosthetics, and fantasy attachments.

The wardrobe target is 200 alluring fashion outfits, 80 customizable skimpy
outfits, 40 bikinis, and 20 lingerie sets. Assume 20 skin suits/bodysuits pending
correction: 360 total designs. Clothing is non-explicit fashion. A mature-content
display preference can cover artistic nudity and mature clothing; explicit sexual
generation and sexual anatomical customization are outside this design.

## Findings from source inspection

- FastAPI provides many useful planning, generation, terrain, validation, and
  rendering endpoints, but there is no complete browser editing workflow.
- `BodyProportionSlider` contains 18 controls. Regional weighted scaling exists,
  but height-band estimation does not support arms or hands. Existing mappings
  are not a validated anatomical deformation system for arbitrary imported rigs.
- Existing morph output constructs a new trimesh from vertices and faces; a
  character workflow must explicitly preserve UVs, materials, skinning, animation,
  and coordinate conventions instead of treating an appearance asset as geometry
  alone.
- Cloth look development exists, but garment meshes, wardrobe metadata, surface
  attachments, garment fitting, and an asset browser do not.
- Provider submission/polling, trusted-host asset ingestion, artifact lineage,
  checkpoints, job claims, Blender execution, and output verification offer reuse
  opportunities. A compiled plan is not evidence of completed generation.
- Several legacy API routes accept filesystem paths. They are unsuitable as an
  unrestricted public interface; the browser-facing API must use scoped asset IDs.
- Blender-dependent tests exist and conditionally skip without Blender. The
  current checkout has not had its test suite run in this environment.

## Architecture and hosting

Recommended: serve a modular browser frontend and scoped studio API from the
existing Python application. Use Three.js for GLB preview and interaction. Keep
Blender in a separate worker process and preserve existing provider adapters.
This minimizes duplicated APIs and allows one deployment origin.

Alternative: independently hosted frontend with an authenticated Python worker
service. This supports independent scaling but adds origin, session, and network
configuration. A static or edge-only deployment cannot run the Python/Blender
pipeline. A frontend URL alone is not completion of the hosted product.

Start with one authenticated owner and private project storage. Store API keys in
server-side environment configuration. Do not expose credential values in the
browser, source bundle, logs, saved projects, or export metadata. Authenticate all
legacy routes if the process is internet accessible, or prevent external routing
to them. Prefer scoped studio endpoints over direct calls to legacy path routes.

Hosted completion requires an actual Python-capable runtime, persistent storage,
and a verified private HTTPS URL. If such a runtime is unavailable, deliver and
verify the local browser application and deployment package, explicitly identify
the missing host, and obtain the required connection rather than fabricating a
live link. GPU rendering is optional initially; CPU Blender must be identified
as CPU rendering and its longer runtimes reflected in job status.

## Browser experience

Use a dark studio workspace with a central viewport, project/asset navigation,
and a parameter inspector. On mobile, switch inspector panels rather than
squeezing the desktop layout. Start with a useful clothed supported base
character or generated terrain, clearly identified as a starter asset.

Provide orbit, pan, zoom, frame selection, front/side/back views, wireframe,
lighting presets, visible mesh statistics, and a low-resolution interactive
preview. Full-resolution exports and offline renders run asynchronously.

Separate sections: Character, Body, Wardrobe, Details, Scene, Render, and Jobs.
Show unavailable tools with a specific dependency explanation. An unavailable
provider must not produce a fabricated result or be silently replaced by a
different paid service. Show live, estimated, and unvalidated results distinctly.

## Creation inputs — prompt, text, and images

Provide three visible creation entry points sharing the same asynchronous job,
asset ingestion, preview, and export workflow. Prompt-to-3D and text-to-3D are
two input experiences for text-conditioned generation, not claims of separate
underlying AI models.

1. Guided prompt-to-3D: compose a description from subject, style, proportions,
   clothing, materials, pose, and intended use. Display the final editable text
   before submission. Do not invent semantic image descriptions from the current
   pixel-statistics analyzer or silently rewrite the user's intent.
2. Text-to-3D: accept a free-form description with supported geometry, texture,
   and output controls. Use configured text-capable Tripo or Meshy adapters.
   Validate provider-specific limits without silent truncation. The current
   Tripo request builder limits text to 1,024 characters; verify that limit and
   the provider's current API contract before live release.
3. Image-to-3D: upload a reference image, inspect its preview, optionally crop,
   and choose a configured image-capable provider. Reuse Hi3D local-file upload
   and add validated upload/reference handling for Tripo and Meshy. A caller's
   local filesystem path is not a browser upload implementation.

For Meshy, existing image request builders do not by themselves establish a
complete image upload/submission/polling/ingestion workflow. Implement and test
that path explicitly. Likewise, Tripo's `input_ref` needs a verified
provider-accepted image reference or upload, not an arbitrary browser URL.
Where a provider must fetch a URL, use bounded-lifetime signed image access or
the provider's upload facility. Show that the reference is sent to the selected
external provider before the user submits it. Remove reference access after the
required lifetime; do not expose an unrestricted upload directory.

Use server-validated PNG/JPEG/WebP inputs with byte, pixel, and dimension caps,
decoded format checking, orientation handling, and metadata removal. Keep the
original image private and preserve processing provenance. Unsupported alpha,
background removal, or multiview inputs must be described accurately. Enable
multi-image generation only where the actual adapter supports it and its input
ordering/count requirements have been verified.

All paths show provider readiness, chosen settings, known cost information, and
the explicit Generate action before any paid request. Persist a submission ID
and remote task ID, poll with bounded backoff, distinguish timeout from remote
failure, and recover jobs without resubmitting already accepted paid tasks.
Show the actual provider stage/progress rather than a fabricated countdown.

Pipeline: validate inputs → submit → poll → ingest verified output → inspect
mesh/materials → create project asset → show interactive preview and downloads.
Optional repair, rigging, topology conversion, and texture refinement are
separate tracked stages, with their own supported limits and costs.

A generated mesh is not automatically compatible with every detailed body
control. Show its rig/region/UV report and offer supported retopology or binding
steps. Do not label a raw generated mesh as fully fitted to the wardrobe or
supported morph base without completing the needed conversion and checks.

Generation targets include characters, props, and environments where supported.
Local terrain generation remains usable without provider keys. No keys means
text/image AI generation shows an actionable unavailable state, never a
procedural substitute falsely presented as the requested AI-generated asset.

Verification includes malformed uploads, prompt limits, unavailable credentials,
provider rejection, terminal failure, interrupted polling, duplicate requests,
asset-download failure, successful preview/download, and reopened exported files.
Live end-to-end claims require actual provider output with execution evidence.

## Body deformation

Ship a supported neutral-pose base with authored region weights, UVs, skeleton,
and a compatibility manifest. Review licensing before bundling external assets;
record origin and redistribution rights. Procedural starter assets must be
labeled as such and not presented as scan-quality humans.

Preserve the existing 18 controls and add supported controls for left/right
limb proportions, neck length, head width/depth, facial proportions, hand/foot
dimensions, and asymmetric stylization. Shape-based face controls need dedicated
targets or authored face regions; do not advertise a working facial slider until
its geometry change is observable and validated.

Separate standard and extreme stylized profiles. Each parameter declares units,
default, minimum/maximum, affected region, dependencies, and compatibility.
Extreme ranges remain finite and positive where required. Never accept NaN,
infinite transforms, inverted scale, or unbounded subdivision. Ranges are
calibrated against the supported mesh; arbitrary large multipliers are not a
substitute for supported deformation.

Apply non-destructive edits from a stable neutral base so moving sliders back to
zero restores the baseline. Use a versioned, deterministic composition order.
Update bone positions/rest transforms for limb-length changes, preserve skin
weights, refit garments/attachments, and run representative pose checks. Do not
promise existing animations remain valid until checked after deformation.

Offer presets, symmetry link/unlink, exact numeric values, per-control reset,
global reset, undo/redo, and side-by-side baseline comparison. Warn about detected
intersections and present inspection results. Block release-grade export on
invalid geometry; an explicitly labeled experimental export may be allowed for
non-critical shape/fit warnings, retaining its reports.

Imports receive a capability report. Missing authored regions or skeleton data
disable dependent controls, with an explanation. Generic height heuristics are
an approximate preview fallback, never silently a production-quality fit.

## Detailed customization requirement — expanded user request

The user's priority is maximum useful customization depth. Do not optimize for
an impressive slider count at the expense of visible, distinct, exportable
effects. The catalog is extensible; each shipped control must have an authored
target or implemented operation, compatibility coverage, and verification.
Global, regional, and local editing complement each other rather than competing.

### Parameter families

Breast and glute customization is a priority, per the user's latest direction.
Give overall size controls prominent placement and provide separate supported
shape operations: projection, width, upper/lower fullness, lift, spacing where
applicable, contour firmness/roundness, and independent left/right size. Distinguish
authored targets from derived local sculpt deltas, and contour shape from physical
soft-tissue simulation. Keep the character visibly clothed during routine preview.
Combining global and side-specific controls is additive and requires fit inspection.
Do not represent extreme combinations as validated for animation or cloth physics.

| Family | Required supported edits |
| --- | --- |
| Overall proportions | Stature, head/body ratio, torso/leg ratio, upper/lower body balance, shoulder/pelvis relationship, bilateral or independent sides |
| Torso | Shoulder breadth/slope, clavicle shape, ribcage width/depth/height, chest volume/position/separation, waist width/depth, abdomen profile, back width, pelvis width/depth, hip contour, glute volume/position |
| Arms | Upper-arm and forearm length, biceps/triceps volume, elbow width, forearm taper, wrist size; independent left/right |
| Legs | Thigh and lower-leg length, thigh volume, knee width, calf volume/height, shin profile, ankle size; independent left/right |
| Hands | Palm width/length/thickness, each digit length/thickness, thumb proportions, knuckle definition, nail shape/length; independent left/right |
| Feet | Length/width/height, heel shape, arch profile, toe length/spacing, nail shape; independent left/right |
| Neck and head | Neck length/width, trapezius contour, head height/width/depth, forehead and cranium shape |
| Eyes and orbital region | Spacing, height, opening, tilt, depth, eyelid folds, brow height/shape, iris size and color; independent sides |
| Nose | Bridge height/width, length, tip position/shape, nostril width/shape, profile |
| Mouth and jaw | Mouth width/position, upper/lower lip volume, corners, philtrum length, chin height/width/projection, jaw breadth/angle, cheek volume/position |
| Ears | Size, position, rotation, lobe shape, pointiness; independent sides |
| Body composition | Global and regional muscle/fat distribution with separate shape definitions and volume behavior |
| Skin detail | Color/undertone, regional roughness, pore/detail strength, freckles, moles, scars, wrinkles, stretch marks, tattoos, makeup |
| Hair and grooming | Compatible hairstyle selection, color, length/density where actually supported, eyebrows, lashes, facial hair, ordinary body hair |
| Modifications | Compatible prosthetic limbs, surface ornaments/piercings, fantasy ears/horns/tails/wings, attachment position/scale/material |

Posture, expression, and animation are separate layers from permanent body shape.
Expose shoulder posture, pelvis orientation, neutral stance, facial expressions,
and representative pose previews only when the rig supports them. Do not label
a temporary posed bend as a permanent change in limb anatomy.

### Local sculpting and detail

Add a local sculpt mode for supported topology: grab, inflate/deflate, smooth,
and crease brushes with radius, strength, falloff, symmetry, and region masks.
Include keyboard/numeric alternatives for brush placement and settings. Store
sculpt deltas non-destructively and support undo. Freehand manipulation is an
optional interaction, never the only way to perform essential edits.

Keep base-shape targets, corrective shapes, local sculpt deltas, and surface
detail layers separate. Higher-resolution surface detail can use normal and
displacement maps rather than forcing the interactive browser to manipulate
millions of vertices. Topology-changing operations require explicit rebinding
of UVs, regions, rig, garments, and attachments; do not silently invalidate them.

### Control metadata and navigation

Define stable parameter IDs with group/subgroup, units, supported range,
neutral value, authored operation, side, symmetry partner, prerequisites,
conflicts, preview cost, and export support. Include searchable control names,
favorites, recently edited controls, regional selection, and a modified-only
view. Show coarse controls first and expand fine controls on demand.

Use linked slider and numeric input, visible before/after values, and per-group
resets. Anatomical measurements are calculated from defined mesh landmarks in
world units; label them approximate where the topology does not support exact
measurement. Do not infer weight or health from mesh volume.

### Deformation quality and compatibility

Use authored blendshape deltas for specific contours, skeleton-aware transforms
for segment length/placement, regional cages or surface bindings for broad
changes, and pose-space correctives where validated. Existing corrective-plan
metadata does not count as actual corrective geometry or working rig drivers.
Construct and exercise those targets/drivers before marking support complete.

Maintain controlled transition zones at joints and neighboring regions. Define
which controls compose additively and which require combination correctives.
Preserve appearance attributes and export morph targets where the selected
format supports them. A baked-shape export is a separate option, with the rig
and garment compatibility checked against the resulting mesh.

Every advertised control must pass a neutral/minimum/maximum sweep. Check
representative interacting pairs and high-risk combinations: extreme stature
with limb proportions, opposing torso profiles, asymmetry with attachments,
hand/foot edits with animation, and body edits under fitted clothing. Report
the tested parameter domain rather than promising every mathematical combination
is anatomically plausible or collision-free.

The supported base is the full-feature path. Imported characters receive
per-control compatibility; unsupported shape targets are unavailable until
authored or mapped. Advanced controls are not implemented by assigning new
names to the same global scale operation.

## Surface details and attachments

- Tattoos: UV-aware placement, scale, rotation, opacity, color, and layers; use
  decals for preview and bake/composite for exports. Handle UV seams visibly.
- Piercings: ordinary non-sexual adornments at face/ear/body anchors, editable
  size/material and side, with pose-aware transforms and collision checks.
- Prosthetics: replaceable arm/leg/hand components at supported joint interfaces,
  material/style controls, clear compatibility, and attachment/export validation.
- Fantasy features: ears, horns, tails, and wings at supported anchors. Static
  attachments and animated attachments carry different capability labels.
- Skin appearance: non-explicit color, roughness, freckles, scars, and makeup
  controls with exportable textures. Do not claim medically accurate anatomy.

All attachments follow the selected morph/rig, retain provenance, and are
included in saved projects and exports. Unsupported combinations show actionable
errors rather than appearing to work only in the viewport.

## Wardrobe assets and fitting

Every catalog item needs an actual garment asset or executable garment generator,
stable ID, category, thumbnail, material definitions, compatibility information,
fit metadata, and source/license records. Metadata-only entries are not completed
outfits. Count designs separately from colorways; changing color does not create
another design toward the requested counts.

Use reusable garment construction templates with distinct cuts, silhouettes,
panels, straps, layering, and supported fabric treatments. Procedurally generated
items are a viable starting library but must pass mesh and fit checks. If a
requested quality level needs authored assets, report it instead of calling
simple proxy shapes finished garments.

Include filters, search, category counts, fit status, material/color controls,
equip/unequip, layers, and saved combinations. Support a parameter schema for the
80 custom items so users can alter supported cut/coverage/strap/length options.

Fit against the supported base using transferred weights and surface bindings;
then respond to morph edits, preserve thickness, check collisions, and verify
poses. Ordinary form-fitting and extreme proportions have different validation
coverage. Render previews and downloads must use the same fitted garment asset.
Validate all 360 entries and document unique design counting and tested ranges.

## Browser-facing APIs and storage

Use a studio router with project, asset, wardrobe, edit, and job resources.
Persist versioned projects with selected assets, control values, attachment
anchors, material overrides, camera, lighting, and output settings. Record schema
version and migrate known versions rather than guessing unknown formats.

Resolve asset IDs only under the owned workspace; prevent traversal, symlink
escapes, arbitrary file reads/writes, and untrusted remote URLs. Bound uploads by
size/type and validate files before exposing them. Support GLB initially; add
other imports only with verified conversion and compatibility reports.

Create background jobs for generation, fitting/baking, validation, and rendering.
Reuse existing SQLite claim/lease mechanisms where compatible. Persist stage
status, retry limits, errors, timestamps, and verified outputs. Report truthful
stage progress; unknown completion time must remain unknown. Expired jobs need
recovery or explicit failure after restart. Cancellation must be implemented in
workers before exposing a cancel button. Deduplicate submissions to avoid
accidental duplicate paid provider tasks.

Provider output passes trusted-host ingestion and local verification before
browser preview or canonical promotion. Existing evidence gates remain in place.
Generate scoped downloads; do not return arbitrary backend paths to the client.

## Accessibility

Target WCAG 2.2 AA with keyboard-reachable panels, visible focus, semantic forms,
named sliders paired with numeric inputs, large touch targets, sufficient
contrast, reduced-motion support, and layouts usable at 200% zoom. Avoid
color-only status and announce asynchronous changes through an appropriate live
region without announcing every frame or every dragged slider value.

Provide keyboard camera controls and a textual scene/selection description so
critical actions do not require drag gestures or interpreting the viewport.
Respect preferred reduced motion and avoid forced camera animation.

## Acceptance and verification

1. Open the studio in desktop and mobile browsers; generate terrain, orbit it,
   save/reopen the project, and download a verified GLB.
2. Import a valid supported GLB; reject malformed/oversized uploads and path
   traversal; show actual compatibility for an unsupported character.
3. Exercise every advertised body control on the supported base. Verify zero
   reset, symmetry/asymmetry, undo/redo, finite vertices, preserved appearance,
   skeleton consistency, and fit/pose reports at standard and extreme limits.
4. Prove catalog counts with actual assets and distinct design metadata. Equip
   representative garments from every construction family; validate every item
   on neutral and defined morphology/pose samples. Separate untested combinations.
5. Verify tattoos and attachments survive save/reopen and GLB export with the
   declared compatibility; use screenshots and reopened exported assets.
6. Verify real provider execution only with configured credentials and explicit
   paid generation actions. Mocked network tests verify handling, not live output.
7. Run Blender-backed render/bake/export checks on an available worker and inspect
   actual images. Report skipped dependencies, resource limits, and receipts.
8. Run the existing regression suite plus meaningful new API, deformation,
   persistence, and authorization tests. Browser-test core workflows and keyboard
   operation, inspect mobile/zoom layouts, and audit accessibility.
9. Verify the authenticated hosted URL from a browser outside the worker runtime,
   refresh persistence, downloads, and background jobs. Record deployment/version
   and remaining dependencies. Localhost is not a remotely accessible deployment.

## Delivery boundaries

Implement in reviewable increments: browser foundation and real preview/export;
supported base and deformation; details/attachments; wardrobe construction and
fit; worker integration and private deployment. Each increment must preserve a
working app, include verified behavior, and report incomplete capabilities.

Completion means the agreed workflows and asset counts work, pass their relevant
checks, and are reachable through the promised browser URL. It does not mean all
future features of a general-purpose modeling application are complete.
