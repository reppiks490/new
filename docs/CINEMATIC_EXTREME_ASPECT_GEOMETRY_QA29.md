# QA29 — Unbounded cinematic master geometry / owner-PC admission

**Scope:** Disjoint, additive QA on lead integrated cinematic PR #40 at `05c59556d64a808dcc3a8ca96fae5e572c9e446d`. No production code or other helper's files changed. Draft review only.

## Evidence and impact

The existing `ProjectCreateRequest` and `ProjectUpdateRequest` accept any 3–16 character `aspect_ratio` string. `cinematic_service._master_size` interprets positive integer ratios without an output width or pixel budget. For the valid-schema `999999999999:1` at 480p, the current calculation produces **479999999999520 × 480 pixels**, about **230 quadrillion pixels per frame**. This is arithmetic based on the inspected service implementation, **not an FFmpeg or GPU benchmark**.

Project creation and update currently do not call a bounded geometry preflight. A malformed/hostile or accidental ratio can therefore persist in a project, pass queue readiness, and reach a local FFmpeg launch attempt before rejection. The exact FFmpeg failure mode depends on the owner's installation; no owner media or paid services were used.

## Additive proof and proposed mitigation

- `tests/test_cinematic_extreme_geometry_contract_qa29.py`: strict expected-RED application contract requiring extreme geometry to be rejected **before project creation or revision mutation**. Real project storage code; no FFmpeg, model inference or mobile device.
- `app/video/cinematic_geometry_guard_qa29.py`: optional, side-effect-free guard with exact rational comparison, even dimensions, and **proposed** width/pixel ceilings. It is **not wired into production**.
- `tests/test_cinematic_geometry_guard_qa29.py`: normal and cinematic aspect ratios, extreme width, unrepresentable narrow ratio, odd dimensions, and privacy-minimized errors.
- Dedicated Python 3.11/3.12 workflow runs the strict app contract. General CI skips the intentionally RED application tests until the lead integrates a policy.

**Proposed local policy only:** width ≤ 8192, pixel count ≤ 8192 × 2160, and computed output width within one pixel of the exact requested ratio. This is not an owner-PC capability measurement. The lead must decide supported ultrawide/portrait bounds and enforce them in request validation, project updates, editorial preflight and assembly before any durable job is enqueued. Avoid persisting invalid project edits; preserve CAS revision semantics. Guard against extreme width and degenerate narrow ratios. Test 16:9, 9:16 and 239:100 controls.

## Dependencies / non-goals

Master assembly ownership remains #8/#40; async queue #21; cache/media #23. Long-form FFmpeg `E2BIG` #79, private script #80 and decoder memory #81 are independent, complementary resource risks. Mobile preflight #76 checks *encoded MP4* geometry, not **pre-render authored aspect ratios**.

This QA does not prove an owner-PC 600s render, real 700-shot footage, AI inference, actual mobile playback, or production deployment. No merges, cloud generation, credentials, owner media, ICARUS or ChatGPT automations were touched.
