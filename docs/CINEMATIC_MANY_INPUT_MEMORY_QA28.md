# Cinematic QA28 — many-input FFmpeg resource-boundary handoff

**Status:** isolated, draft, test-first; production assembly is **not fixed**.
**Base:** QA27 draft PR #80 at `38b025f2e4f6ac533c219c26dc61d6d888541eb8`.
**Owner boundary:** no changes to `app/video/cinematic_service.py`, async queue,
mobile client, launcher, private API, or other helpers.

## Why QA27 is necessary but insufficient

QA26 PR #79 reproduced a valid 700-shot/350-second project's oversized
single `-filter_complex` argument being rejected by Linux `execve` with
`E2BIG`. QA27 PR #80 demonstrates private `-filter_complex_script`
transport, but the current service also launches one `-i` decoder for
each shot with FFmpeg's automatic decoder and filter threading.

**New bounded local experiment (2026-10-23, FFmpeg 7.1.5, Linux 4 GiB cgroup):**
One locally generated 32x32, 24-fps, 0.5-second H.264 clip was opened
repeatedly as independent FFmpeg input contexts. Each input used the same
frame-exact `fps/scale/pad/setsar/format/tpad/trim/setpts` filter chain as
the service (at 32x32 to keep the experiment safe), followed by `concat`.
All trials used a filtergraph *script* to eliminate QA26's argument limit.

| Input contexts | Default FFmpeg peak RSS | Bounded input + filter peak RSS |
| ---: | ---: | ---: |
| 100 | 934,340 KiB | 320,328 KiB |
| 200 | 1,837,288 KiB | 540,796 KiB |
| 350 | 3,192,308 KiB | 925,740 KiB |
| 700 | OOM-killed in 4 GiB cgroup (exit -9) | 700-input 350s H.264 encode succeeded |

The bounded variant used `-threads 1` **before every `-i`**, plus
`-filter_complex_threads 1` and a one-thread output encoder. The actual
700-input bounded encode produced **8,400 H.264 frames, 24 fps, 350.000
seconds**, and passed FFprobe and full decode. The generated MP4 was tiny
and synthetic; all 700 inputs referenced the same source file.

These figures are local measurements, **not GitHub CI results, a universal
memory model, owner-PC hardware proof, or evidence that 700 distinct model
outputs have been rendered**. CPU count, FFmpeg version, resolution, source
codecs, hardware and filter complexity can change resource usage greatly.
At real 480p+ dimensions the risk needs separate measurement.

## Test-first contract

`tests/test_cinematic_many_input_memory_qa28.py` adds:

1. An application-level **expected RED** contract: capture the real
   700-shot service FFmpeg argv using synthetic persisted-job stubs;
   require explicit conservative input-decoder and complex-filter
   thread limits. No FFmpeg runs in this contract.
2. A **genuine synthetic FFmpeg** test: 700 independent input contexts,
   700 concat segments, private QA27 filtergraph script, bounded threads,
   350-second 8,400-frame H.264 MP4, FFprobe and full decode.

The strict dedicated Python 3.11/3.12 workflow sets
`CINEMATIC_REQUIRE_MANY_INPUT_QA=1`. Ordinary CI skips these expensive
tests by design. A RED contract means the production command is still
unbounded, even if the real bounded-thread control passes.

## Lead-owned integration decisions

- Integrate QA27's private script transport only after reviewing trusted
  temp directory, FFmpeg CLI compatibility, cancellation and crash cleanup.
- Decide a **resource budget** based on owner hardware, including bounded
  input decoders, filter threads and output encoding. The exact value of
  one thread is a conservative diagnostic, not an imposed universal optimum.
- Consider bounded staging/concat-demuxer or batching if hundreds of
  simultaneously opened decoders remain too costly, while retaining frame
  accuracy, source-byte provenance, cache identity, private paths and
  cancellation.
- Validate under a real 480p+ mixed-codec synthetic corpus and separately
  on the owner's PC for the complete 600-second timeline. Do not activate
  cloud generation or infer model performance from FFmpeg-only tests.
- Keep #73 MP4 source metadata privacy, #74/#75 local-network privacy,
  #49/#51/#53/#56 durable queue integrity, and #67/#68 authenticated
  mobile streaming as independent release gates.

**No automatic merge, deployment, service purchase, owner-media upload,
model inference, physical iPhone test, ICARUS or ChatGPT automation edit.**
