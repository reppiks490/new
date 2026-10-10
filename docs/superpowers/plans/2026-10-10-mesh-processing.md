# Reversible Mesh Processing

**Goal:** Provide real inspectable voxel remesh, quad retopology, and face
reduction operations, with measured output and explicit preservation results.

**Architecture:** Submit typed processing jobs to an isolated Blender worker;
write outputs to derived asset versions; validate and reopen outputs before
marking jobs successful; retain source and job reports for rollback.

**Tech stack:** FastAPI, SQLite job records, Blender 4.x operators and Python,
GLB/glTF, pytest, Blender live integration tests, Playwright.

**Spec:** [BEYOND_TRIPO_SPEC.md](../../BEYOND_TRIPO_SPEC.md)

**Global constraints:** Never replace the only copy; bound resources, input
size, polygon targets, and time; report topology and data losses; do not call
Quadriflow “AI retopology”; do not claim production quad flow unless measured.

**Review focus:** Actual face count and edge flow, preserved shapes/materials/UVs
and rig where supported, failure recovery, and user understanding of destructive
topology changes.

## Task 1: Mesh-processing schema and job lifecycle

**Files/interfaces:** `app/studio/processing/` task and report schemas,
`app/studio/storage.py`, `app/studio/router.py`, and
`tests/test_mesh_processing_jobs.py`.

- Write failing tests for accepted/rejected operations, invalid targets, job
  state transitions, status persistence, output ID confinement, duplicate
  submissions, worker absence, timeouts, and failed jobs retaining source.
- Implement background jobs for `voxel_remesh`, `quadriflow`, and
  `reduce_faces`, with bounded parameters and no arbitrary path input. Record
  Blender version/operator, settings, source/output hashes, logs, and validation
  status.
- Verify API isolation, restart-persistent status, and source immutability.
- Commit: `feat: add bounded mesh processing jobs`.

## Task 2: Implement and validate local Blender operations

**Files/interfaces:** Blender worker modules and fixtures in
`tests/fixtures/mesh_processing/`; live tests in
`tests/test_blender_mesh_processing.py`.

- Write failing fixture tests for manifold and non-manifold meshes, thin
  details, disconnected parts, UV/material seams, morphs, and skinned meshes.
- Implement the three operators, preflight unsupported combinations, and
  measure input/output faces, components, bounds, normals, finite vertices,
  self-intersections where available, UV/material coverage, morphs, groups,
  weights, skeletons, and clips.
- Verify the accepted error budget for target face count and ensure unsupported
  data is either preserved or listed as lost before the user starts. Reopen the
  result and compare checksums/manifests. A failure returns no “success” asset.
- Commit: `feat: process meshes with preservation reports`.

## Task 3: Browser controls, previews, and reversible outputs

**Files/interfaces:** `app/studio/web/app.js`, `index.html`, styles and browser
tests.

- Write failing browser tests for each operation's settings, preflight report,
  progress, failure state, result comparison, cancellation only if supported,
  undo/restore, and download of the derived mesh.
- Add focused controls with labels and estimated memory/time where available;
  compare source/output using the same camera and material. Show the exact
  preservation report and disable incompatible settings.
- Verify keyboard operation, narrow screens, job restart behavior, and actual
  output download/reopen.
- Commit: `feat: expose verified mesh processing in browser`.
