# Beyond-Tripo Browser Studio — Execution Roadmap

**Goal:** Turn Forma into a dependable browser 3D workspace with precise edits,
preserved source assets, verifiable mesh processing, and high-quality creation
and presentation workflows.

**Architecture:** Same-origin FastAPI studio APIs and scoped asset storage;
Three.js browser editor; persistent operation/job records; isolated Blender
workers for local geometry and rendering; explicitly configured generation
providers for remote AI operations. Every mutation is versioned and reversible.

**Tech stack:** Python 3.11+, FastAPI, Pydantic, SQLite, Blender 4.x, Three.js,
GLB/glTF, pytest, Node-based frontend tests, Playwright browser tests.

**Spec:** [BEYOND_TRIPO_SPEC.md](../../BEYOND_TRIPO_SPEC.md)

**Global constraints:** Preserve original file bytes and hash; confine all asset
paths; validate payloads and worker inputs; make operations idempotent or
versioned; make capability claims depend on inspected, tested outputs; never
silently spend provider credits or upload a model; surface topology/rig/material
losses; do not fake enhancement or parity. A failed operation must leave the
last good asset available.

**Review focus:** Is the output actually editable/exportable? Are protected
regions unchanged within the stated tolerance? Are before/after comparisons
reproducible? Does a reopened output retain the claimed data? Are unsupported
features clearly disabled or identified as provider-dependent? Do outputs meet
the visual acceptance bar in the product spec rather than merely passing API
tests?

## Delivery order

1. [Precision edits and region constraints](2026-10-10-precision-editing.md)
2. [Model inspection and source-preserving import](2026-10-10-model-ingest.md)
3. [Remesh, retopology, and reduction](2026-10-10-mesh-processing.md)
4. [Verified high-resolution render workflow](2026-10-10-render-workflow.md)
5. [Generation and Tripo-inspired asset pipeline](2026-10-10-asset-pipeline.md)

Work on step 1 can begin independently. Steps 2 and 3 provide dependable
asset/job foundations for step 5. Step 4 can proceed independently once scoped
worker jobs and browser capability reporting are ready. The final provider and
visual parity gate depends on the preceding workflows and explicit provider
configuration.

## Completion gate

The roadmap is complete only after every individual plan passes its regression
and browser checks, representative assets pass save/reopen/export round trips,
worker jobs survive failure and restart, visual reviewers approve a fixed set of
neutral and presentation renders, and every product capability is backed by
that evidence. Passing unit tests or adding interface controls alone does not
establish Tripo-level quality.
