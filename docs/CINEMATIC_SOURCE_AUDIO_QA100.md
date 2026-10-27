# QA100 — source audio continuity acceptance and ownership handoff

**Scope:** draft evidence-only acceptance, no production implementation, no
owner media, cloud generation, model inference, deployment or service spend.
Frozen parent QA99 #200 at
`5b8065aeee6db906d695391a47cd3fe43212f1cf`.
QA100 is a disjoint child PR (#201), not a release or merge authorization.

## Code-level audio gap

The current `app/video/cinematic_service.py::assemble_project_master`
constructs only video filters (`[index:v:0]`), uses
`concat=n=...:v=1:a=0[v]`, maps only `[v]`, explicitly passes
`-an`, and persists `has_audio=False`. Its verified master probe
selects `v:0` and therefore does not attest audio presence or continuity.

Existing 600-second QA93–QA98 accepts silent, synthetic color-only sources;
it establishes video frames, shot order, cut timing, full video decode, SHA
and cache reuse, **not** audio preservation. This is a documented capability
gap until the product owner specifies whether a master must carry source
audio, generated dialogue, music, or an intentional silent soundtrack.

## Reproducible, opt-in genuine-media acceptance

`tests/test_cinematic_source_audio_qa100.py` creates two local 5-second
MP4s with actual AAC audio: 440 Hz then 880 Hz at 48 kHz. It probes both
source streams and decodes PCM to estimate the actual tone frequencies
before calling the real Character3D master assembler. It then verifies
10-second / 240-frame H.264 video, full decode and SHA-256 before checking
for output audio, truthful `has_audio`, and decoded tones at 2.5s / 7.5s.

The dedicated `.github/workflows/cinematic-source-audio-qa100.yml`
runs the opt-in test inside the existing bounded, nonroot, network-disabled,
read-only synthetic FFmpeg image. Ordinary general CI skips the opt-in test
and is not evidence that audio was exercised. A strict xfail, if added after
a test-first reproduction, **documents an unresolved capability gap**;
it does not mean audio preservation passed.

## Implementation proposal — lead review required

1. Decide explicit audio policy: source audio vs dialogue/music tracks,
   silent-source behavior, silence padding, mixed channel layouts, and
   whether audio is allowed at all in an exported master.
2. If preservation is intended, add an audio-aware FFmpeg filtergraph
   with independently defined sample-accurate timing for each shot.
   Prevent overlapping audio, truncated tails, and cumulative drift;
   normalize sample rate/channel layout and use a supported MP4 audio
   codec, without mixing owner media into logs or artifacts.
3. Include audio policy/version in master cache identity so previously
   verified silent masters cannot be silently reused as audio-capable
   masters. Extend the media probe, durable record and mobile UI to
   report audio truthfully, and fail closed on mismatches.
4. Add negative controls for muted clips, mixed audio/no-audio sources,
   variable rates, fractional video cuts, 600-second masters, and
   corrupted/unauthorized source files. Test audio decode, frequency
   transitions, exact duration and authenticated mobile Range playback.
5. Re-run on the final integrated SHA and owner Windows/WSL2 machine;
   physical mobile playback and actual model-generated dialogue remain
   separate unverified acceptance requirements.

## Dependencies and safety

Master #8, async queue #21, cache/media #23, lead integration #40,
strict private HTTP/Range Helper 1 #194, 600-second integration gate #199
and live-worker recovery blocker #200 remain independently owned.
QA100 modifies no files owned by those PRs. Do not merge #201 as an
audio fix; do not enable multiple API processes against one SQLite
workspace while #200's strict xfail is unresolved.
