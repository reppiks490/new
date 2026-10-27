# QA108 — FFmpeg/FFprobe version-banner fail-closed preflight

**Status:** isolated draft PR #209, unmerged. Frozen QA107 #208 parent
`c1599ffbdd0295f605185a4f92e4066b45261fdd`. The scope is the
standalone, read-only local operator preflight and its QA105–QA108 tests.
No shared master assembly, queue, media API, mobile, helper-owned source,
or CI workflow is modified.

## Test-first finding

The QA105 preflight originally treated **any executable** that returned
exit status zero to `-version` as a responsive `ffmpeg` or `ffprobe`.
An unrelated program (or wrong executable on PATH) can return zero and
cause misleading `FFMPEG_RESPONSIVE` / `FFPROBE_RESPONSIVE` results.
The `libx264` listing check alone does not establish FFmpeg identity.

Test-only commit: `ea7e8695c54c4b1b642717f9d9a6c68d4d5b72c8`.
The new QA108 tests cover empty, unrelated and wrong-tool version banners,
plus a valid FFmpeg/FFprobe banner positive control. Tests use mocked
subprocess metadata, not owner media or actual encoding.

## Narrow correction

Require the first stdout line to begin with the expected
`ffmpeg version ` or `ffprobe version ` banner before reporting that
tool responsive. If the FFmpeg version probe fails, do not query encoders.
Existing synthetic mocks in QA105, QA106 and QA107 were updated to use
realistic version-banner strings; their existing privacy and failure
coverage remains intact. This is **metadata sanity checking, not a
cryptographic executable-authenticity guarantee**. An intentionally
malicious program could forge the banner. Executables and PATH must
still be trusted.

The output remains stable, path-free, read-only and always reports
`release_ready=false`. No media files are opened or generated.

## Acceptance and unresolved dependencies

Verify the exact final commit using general CI (Python 3.11/3.12,
Node/browser and Docker), inspect test-first RED independently, and
check the new QA108 tests on the final SHA. The mocked regressions do
**not** establish genuine FFmpeg encoding, owner-PC Windows/WSL2
compatibility, model inference, artistic continuity or physical mobile
playback.

Lead integration still owns #8 master, #21 queue, #23 media, #40
combined cutover; Helper 1 #171 denial no-store and #194 strict media
gate remain divergent. QA99 #200 multi-process worker recovery,
QA100 #201 source-audio policy and QA103 #204 no-store remain
independent blockers. No automatic merge, deployment, paid/cloud
generation, owner media/credentials, ICARUS or automation changes.
