# QA106 — Unicode-decoding privacy and fail-closed preflight verification

**Status:** draft, unmerged, QA-only; frozen QA105 #206 parent `37dc82e4a0831e79012d1cf9117a811ba71a4fb0`. This is a verification continuation, **not** a production fix.

## Question and evidence

The new QA105 local media preflight invokes FFmpeg/FFprobe with `subprocess.run(text=True)`. On a Windows/WSL2 host or a mixed-locale executable, non-decodable tool output can raise `UnicodeDecodeError` before any return code can be examined. The CLI must fail closed, emit only fixed public status codes, and avoid printing private subprocess bytes or paths.

QA106 introduced five isolated, mocked tests at `tests/test_cinematic_local_media_preflight_unicode_qa106.py` for:

1. Non-decodable `ffmpeg -version` output blocks FFmpeg and leaves H.264 not checked.
2. Non-decodable `ffmpeg -encoders` output blocks the H.264 encoder check.
3. Non-decodable `ffprobe -version` output blocks FFprobe.
4. A Unicode exception during executable lookup blocks the binary without leaking the path.
5. The CLI emits parseable, path-free JSON and exit code 2, not a traceback, when decoding fails.

**Finding:** The initial test-only CI was green on Python 3.12, rather than RED. Python's `UnicodeError` (including `UnicodeDecodeError`) subclasses `ValueError`, which QA105 already catches. Therefore these tests confirm existing fail-closed behavior; **no production defect was reproduced and no production code correction is justified**. Do not misreport the initial run as test-first RED.

The tests are synthetic mocks, not actual FFmpeg encoding, real Windows locale testing, owner-PC verification, model inference, or physical mobile playback. `release_ready` remains false. A genuine Windows/WSL2 run must still validate the actual executable paths and workspace.

## Integration and ownership

This QA branch adds only its own new test and documentation paths. It does not modify the QA105 implementation, Helper 1's #171 private-cache correction or #194 strict-media workflow, the #8/#21/#23 master/queue/cache stack, or lead #40 integration. Known blockers remain QA99 #200 live-worker recovery, QA100 #201 source-audio policy, QA103 #204 missing denial `no-store` pending #171, and independent combined-SHA CI.

Keep this PR draft. No merge, force push, deployment, cloud generation, owner media, credentials, spend, ICARUS, or ChatGPT automation changes.
