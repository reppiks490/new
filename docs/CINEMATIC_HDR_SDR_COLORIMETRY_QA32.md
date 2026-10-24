# QA32 — Synthetic HDR-tagged source versus generic mobile SDR master

## Ownership and scope

Independent test-first QA only. Frozen parent: lead integration draft #40,
`05c59556d64a808dcc3a8ca96fae5e572c9e446d`.
This branch adds only QA32-named test, CI, and handoff files. It does not
change the lead's assembler, async queue, media cache, mobile client, or
another helper's files. Draft/unmerged; no automatic deployment.

## Observed reproduction and proposed contract

The current master filtergraph runs `fps,scale,pad,setsar,format=yuv420p`
and encodes with `libx264` but has no explicit source colorimetry admission,
HDR-to-SDR tone mapping, or SDR output-color metadata policy. An H.264
source carrying BT.2020 primaries, BT.2020 nonconstant-luminance matrix,
and SMPTE ST 2084 (PQ) transfer metadata can therefore produce a
generic 8-bit `yuv420p` master still tagged PQ. Probe-verified frames,
duration, and SHA do not establish SDR playback color correctness.

Local FFmpeg 7.1.5 independently reproduced the metadata propagation using
synthetic 160x90 red footage; 48-frame two-second output remained
`yuv420p` / `bt2020nc` / `smpte2084` / `bt2020`. This verifies
color *signaling*, not the physical correctness of synthetic HDR pixels,
actual tone-mapping quality, mobile display behavior, or source-model output.

The strict test in this branch generates a ten-second synthetic tagged source,
links it as a completed shot in genuine local application storage, calls
`assemble_project_master`, then probes the actual 480p output. It proposes
that a **generic mobile SDR master must not silently publish PQ signaling**.
Until the lead chooses an explicit HDR mode, the safe options are:
(1) reject unsupported HDR-tagged source media before assembly/publication,
or (2) implement and verify genuine color-space/transfer conversion and
tone mapping to an explicit SDR delivery policy. **Do not simply relabel
PQ pixels as BT.709**; metadata rewriting is not tone mapping.

## Expected CI interpretation

The first test is a real synthetic FFmpeg reencode control and should PASS.
The application acceptance test is expected to FAIL on the unmodified
lead assembler, demonstrating the missing SDR admission/normalization gate.
The strict workflow sets `CINEMATIC_REQUIRE_COLORIMETRY_QA=1`; ordinary
CI skips these tests. A green general workflow therefore does not prove
the production color issue is fixed.

The lead should coordinate any accepted policy with #62/#64 mobile
preflight, #76 display geometry, #84 stream inventory, #73/#83 metadata
privacy, and #21 async publication. Previously cached masters require
policy-aware revalidation. Never log private source filenames, titles,
prompts, media, or credentials in diagnostics.

## Verification limits

Real synthetic FFmpeg encoding/decoding and application-level assembly
are covered by the dedicated workflow. No model inference, authentic HDR
camera footage, owner-PC 600-second 480p+ benchmark, physical phone playback,
paid generation, or cloud deployment is performed.
