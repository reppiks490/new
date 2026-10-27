# QA107 — fail-closed FFmpeg video encoder type in local preflight

**Status:** isolated draft PR #208, not merged or deployed. Frozen QA106 #207 parent
`8927287df81d48d1c673292c59cd9304dc95f126`. This continuation
modifies only the QA105 standalone preflight encoder classifier and adds
QA107-specific tests and this handoff. No shared cinematic assembly, queue,
studio routing, media service, mobile, workflows or Helper 1 files change.

## Test-first reproduced defect

The QA105 preflight reads `ffmpeg -hide_banner -encoders` and reports
`LIBX264_AVAILABLE` if a six-character encoder flag is present before
`libx264`. The original expression `[A-Z.]{6}` does **not** require the
leading FFmpeg media type `V` (video). A synthetic line
`A..... libx264` or `S..... libx264` therefore passes the classifier,
and a report can incorrectly label its H.264 video encoder check passed.
This is a **local readiness false-positive**, not proof of a real
machine having a misregistered encoder, or of a failed render.

Test-first commit: `513928be69d746b3eed54f3a2bd7cbd67ad0b0d9`.
General CI run: https://github.com/reppiks490/new/actions/runs/40497312859
Python 3.12 reproduced **four failures** in QA107 tests: three invalid
encoder type flags plus the end-to-end mocked readiness report.
Other unrelated test results and final run conclusions must be inspected
separately; no GREEN claim follows from this RED run.

## Minimal correction

Fix commit `6b84ede9ae89b5c1478da3c0e8ab3ecb1b0a9233` changes the
encoder capability pattern to `V[A-Z.]{5}` and clarifies its docstring.
This still requires an exact `libx264` name, rejecting `libx264rgb`
and audio/subtitle/unknown type flags. Tests also preserve acceptance
of valid video flags, privacy-safe report codes and `release_ready=false`.

## Verification and operational boundary

The QA107 tests use **synthetic encoder-listing strings and mocked
subprocesses**, not a genuine encode, model inference, owner-PC test,
Windows/WSL2 validation, or physical mobile playback. A real FFmpeg
encoder listing from this sandbox showed `V....D libx264`, but this is
only a local metadata observation, not Character3D rendering proof.

Lead review must still reconcile master #8, queue #21, media #23,
integration #40, Helper 1 cache denial fix #171 and strict media gate
#194. QA99 #200 multi-process worker recovery, QA100 #201 source audio
policy and QA103 #204 denial no-store remain independent blockers.
QA105/QA106's local preflight remains a limited, read-only operator
diagnostic and must never be interpreted as a release certification.

**No automatic merge, deployment, cloud generation, owner media/keys,
paid services, ICARUS or ChatGPT automation changes.**
