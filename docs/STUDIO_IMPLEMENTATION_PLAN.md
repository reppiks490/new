# Browser Studio Implementation Plan

**Goal:** Deliver a usable browser editing workflow over the existing pipeline,
then deepen its asset and rig fidelity without presenting unsupported tools as
finished.

**Architecture:** Same-origin FastAPI studio router, scoped workspace assets,
SQLite projects/jobs, modular Three.js frontend, existing provider and terrain
adapters. Native implementation in this session.

**Spec:** [BROWSER_STUDIO_SPEC.md](BROWSER_STUDIO_SPEC.md)

## Constraints and review focus

Keep legacy APIs compatible but restrict network exposure. Never expose arbitrary
filesystem paths or credentials through studio APIs. Validate finite control
values, uploads, project payloads, and output IDs. Generated starter shapes and
procedural clothing must be labeled honestly. Preserve project appearance across
reload/export. Do not claim hosted or live provider execution without verification.

## Increment 1: Executable browser foundation

- [x] Create `app/studio/parameters.py`: control registry and bounds, side-aware
  values, validated character state. Verify finite values and unknown controls.
- [x] Create `app/studio/character.py`: licensed CC0 MakeHuman mesh with 228
  authored target pairs and 14 localized controls. Export a static multi-node GLB;
  browser geometry additionally exports visible static attachments.
- [x] Create `app/studio/wardrobe.py`: 360 versioned procedural design recipes
  across requested categories; real executable clothing geometry, material
  overrides, filtering. Distinguish design variants from authored couture assets.
- [x] Create `app/studio/storage.py`: confined asset paths, SQLite projects and
  persistent job state, atomic edits, bounded uploads. Validate ID traversal and
  reload behavior.
- [ ] Create `app/studio/router.py`: capabilities, controls, wardrobe, projects,
  asynchronous character/terrain creation, scoped uploads/downloads, provider
  jobs and pipeline reports. Validate failed/missing dependencies and ingest.
- [x] Create `app/studio/web/`: responsive editor, Three.js viewport, forms,
  searchable body controls, wardrobe, attachments, creation inputs, export,
  project save/open, undo/reset, job polling, readiness. Test actual browser flows.
- [x] Integrate router/static assets in a separate `app/studio/server.py`, package data in
  `pyproject.toml`, and private launch instructions. Protect remote exposure with
  a configured studio session secret; no public unauthenticated legacy endpoints.
- [ ] Run new integration tests and existing regression suite; inspect mobile and
  desktop screenshots. Verify downloadable meshes and persisted projects.
- [ ] Launch locally and investigate a supported browser access path. If hosting
  is unavailable, report that blocker alongside the working local deliverable.

## Later fidelity increments — remain explicitly incomplete until tested

- Authored/licensed human base, skeleton-aware morphs, region bindings,
  combination correctives, true facial targets and per-digit anatomy.
- Garment weight transfer, cloth simulation, collision-tested animation and
  production-quality authored wardrobe replacements.
- UV-aware tattoo baking, local sculpting, hair/groom detail, posed and animated
  prosthetic/fantasy attachments.
- Blender-backed bake/render workers, credentialed live provider verification,
  recovery/cancellation, production deployment and authenticated persistence.

These are part of the requested roadmap; the procedural browser foundation
does not claim to satisfy their quality or functionality.
