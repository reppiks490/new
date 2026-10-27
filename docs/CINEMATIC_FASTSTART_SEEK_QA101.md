# QA101 — 600-second MP4 progressive-start and indexed-seek acceptance

**Scope:** Independent, opt-in genuine synthetic FFmpeg application QA; no
production modification, owner media, model inference, actual mobile device,
cloud generation, paid services, merge or deployment. Parent QA100 #201
`5a9026aa2b7474053cd090ed25f3aca43c69ba22`.

## Why this acceptance is distinct

QA93–QA98 demonstrate 600-second frame count, ordering, fractional-cut
boundaries, full decode, SHA-256 and artifact reuse. Helper 1 #194 tests
authenticated private HTTP GET/HEAD/Range with genuine synthetic media.
Neither separately proves that a **600-second assembled Character3D master**
has an MP4 `moov` index **before** `mdat`, a broadly compatible
H.264/yuv420p video stream, or useful random access to late scenes.

The production assembler explicitly requests `-movflags +faststart` and
uses a yuv420p filter; this is an **unverified delivery acceptance gap**,
not a known application defect. Do not claim a bug or a fix without a failing
application-level test.

## Test design and evidence boundary

`tests/test_cinematic_600s_faststart_seek_qa101.py`:

1. Independently generate a real, non-faststart FFmpeg MP4 negative control
   and parse top-level ISO BMFF box sizes (including extended/EOF lengths).
   This demonstrates the test can distinguish `mdat` before `moov`.
2. Generate two actual 1-second synthetic MPEG-4 source files and link
   twenty 30-second shots, ten red followed by ten blue, through the
   **real Character3D project/update/assembly path**.
3. Check exact 600-second, 14,400-frame H.264/yuv420p master, complete
   video decode, SHA-256 integrity and verified artifact reuse.
4. Parse the actual master MP4 top-level boxes and require exactly one
   `moov` before `mdat`, rather than grepping arbitrary binary payload.
5. Use input-side FFmpeg seeking and independent RGB decoding at 0.5,
   299.5, 300.5 and 599.5 seconds to check beginning, both sides of the
   midpoint transition, and near-end random access.

The isolated CI job builds the existing local FFmpeg image and runs offline,
nonroot, network-disabled and read-only, with bounded memory/PIDs and
synthetic temp storage. General CI skips the opt-in real-media test.
No synthetic media bytes are committed or uploaded as artifacts.

## Limits and lead handoff

This proves **file structure and FFmpeg indexed seeking**, not physical
iOS/Android playback, native HLS, audio continuity, HTTP Range interaction
with this particular 600-second master, 4K/120fps hardware performance,
owner-PC Windows/WSL2 filesystem behavior, model inference or artistic
quality. A physical-device test must independently verify private
authenticated playback, Range responses, seeking and device decoding.

Lead integration must reconcile master #8, async queue #21, cache/media
#23, integration #40, Helper 1 #194, long-form gate #199, unresolved
multi-process recovery #200 and unresolved audio policy #201. QA101
changes only its three new QA-owned paths. No automatic merge.
