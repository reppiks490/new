# QA48 — actual offline Docker restart and durable cinematic master recovery

## Ownership and ancestry

This is an **additive draft acceptance candidate** stacked on Helper 1's draft
#105 at exact `029bc85e0cc808353a94e9ab4de357915dc16017`,
which itself stacks on opt-in cinematic Docker #103. The lead's #40, master
#8, async queue #21 and cache/media #23 remain unchanged. New paths are only
`tools/cinematic_docker_restart_recovery_qa48.py`,
`.github/workflows/cinematic-docker-restart-qa48.yml` and this document.
Do not cherry-pick or merge this stacked branch without lead/Helper 1 review.

## Previously missing acceptance

#105 verified actual HTTP async FFmpeg assembly and cache reuse **inside one
container**, but explicitly did not test persistence across container restarts.
#21 has startup-recovery unit tests, and #63 describes multi-worker safety
concerns; neither proves a mounted cinematic Docker workspace can survive an
actual stop/start and still assemble a real H.264 master.

## Test contract

The isolated CI matrix builds opt-in `Dockerfile.cinematic` for Python 3.11
and 3.12. It runs with `--network none`, no host ports, no owner mounts,
no token, no paid services, no GPU, a read-only root filesystem, UID 10001
and a dedicated disposable host-mounted workspace. The test:

1. Creates a real SQLite project with two locally FFmpeg-encoded 2-second
   synthetic red/blue clips and project revision 3.
2. **Directly seeds** one `running` and one `queued` assembly row to
   isolate startup recovery; it does **not** claim the running FFmpeg process
   was actually interrupted or that HTTP admitted the queued record.
3. Abruptly kills the first container; starts a second container using the
   exact same persistent workspace.
4. Requires startup recovery to mark the synthetic running row failed and
   dispatch the queued row to the real CPU worker. Polls the real private
   loopback HTTP API, checks persisted master identity, SHA-256, private
   `Cache-Control: no-store` asset download, 854x480 H.264, 24 FPS,
   96 frames / 4 seconds, and full FFmpeg decode.
5. Kills and restarts the container a second time; verifies the same master
   identity/hash and exactly one persisted master record.
6. Removes synthetic containers and workspace regardless of outcome.

The script refuses an already-populated QA48 state manifest and never prints
the synthetic private-script canary or media paths in normal success output.

## Boundaries and dependencies

This verifies **synthetic durable startup recovery and real FFmpeg output**
only. It does not reproduce a crash of an actually running encoder, a torn
SQLite write, simultaneous application workers, partial source mutation,
long-form 600-second throughput, owner-PC filesystem semantics, actual model
inference, owner footage, physical iPhone playback or token-protected WAN
operation. No container is deployed and no live user workspace is mounted.

Lead #40 and async #21 own recovery semantics; #63 owns multi-process fencing,
#95 status-write failure, #99/#100 malformed JSON isolation, #102 payload
shape, #103/#105 Docker ownership and #23 cache/media acceptance. This gate
must not be mistaken for a fix to any of those independent defects. JSON
`no-store` responses remain a separate privacy proposal (#78).

Final exact-head CI status and any failures must be posted to this draft PR
after checking GitHub Actions. No automatic merge or deployment.
