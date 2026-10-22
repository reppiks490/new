# Cinematic asynchronous master assembly — API and recovery runbook

**Owner:** Cinematic orchestrator / master assembly. **Integration base:** PR #8,
\`chatgpt/cinematic-master-assembly-20261022\`. This is a new additive workstream;
do not merge without the full CI matrix and independent review.

## Why it exists

The legacy \`POST /api/video/projects/{id}/assemble\` executes FFmpeg inside
the HTTP request and may exceed browser/proxy timeouts during long film output.
That synchronous route remains unchanged for existing callers and test coverage.

A new SQLite-backed queue persists a small, prompt-free request, immediately
returns HTTP 202, and executes FFmpeg on a separate serialized CPU executor.
It does **not** use the shared GPU generation pool and requires neither an
external cloud service nor any paid API.

## Mobile/client protocol

All routes are behind the existing \`CHARACTER3D_STUDIO_TOKEN\` bearer
authentication and normal same-origin/CORS protections:

1. \`GET /api/video/projects/{project_id}/render-status\` — render status;
   require \`ready_for_assembly: true\`.
2. \`POST /api/video/projects/{project_id}/assembly-jobs\` with
   \`{"expected_revision": N}\` — returns HTTP 202 immediately, including
   \`id\`, \`status: queued\`, and \`project_revision\`.
3. \`GET /api/video/projects/{project_id}/assembly-jobs/{job_id}\` —
   authenticated polling after a refresh or phone reconnect. Status values:
   \`queued\`, \`running\`, \`succeeded\`, \`failed\`.
4. \`GET /api/video/projects/{project_id}/assembly-jobs?limit=50&offset=0\` —
   paginated history with \`total\` and \`has_more\`.
5. \`POST /api/video/projects/{project_id}/assembly-jobs/{job_id}/cancel\` —
   idempotently cancels a **queued** assembly. Returns HTTP 409 if the job
   is already running or finished; it never claims to kill FFmpeg.
6. Once \`succeeded\`, the job includes the opaque \`asset_url\` of a
   validated master MP4, which must be retrieved using the **same private
   bearer-header fetch** as the existing video assets (never a tokenized URL).

No private prompts, screenplay text, local paths, or model output are placed
in the queue or response. \`ffmpeg_path\` is limited to the literal binary
names \`ffmpeg\` and \`ffmpeg.exe\`.

## Durable state and failure semantics

- Jobs live in the existing SQLite \`records\` table with kind
  \`video_assembly_job\`; a new table or cloud dependency is not required.
- The same active project/revision/executable request returns the same job
  identifier. SQLite \`BEGIN IMMEDIATE\` prevents duplicate records from two
  simultaneous phone/browser submissions.
- A global atomic claim permits only one \`running\` assembly; other persisted
  requests stay \`queued\`. No silent request loss or arbitrary 100-job list cap:
  history is explicitly paginated.
- The local CPU executor drains queued jobs oldest-first. The queue has a
  documented bounded outstanding capacity of 32, returning HTTP 429 once full.
- \`cancelled\` jobs are excluded from dispatch and terminal history is preserved.
- At application startup, \`queued\` jobs are dispatched. Formerly \`running\`
  jobs become \`failed/Interrupted\`, because a killed FFmpeg process cannot be
  safely declared complete or automatically resumed in-place. The user can
  submit another job after verifying the source clips and current revision.
- A project edit after queueing produces a \`failed/Stale revision\` job;
  missing rendered media produces \`failed/Missing clips\`. In both cases
  the worker must not publish a success artifact.
- The completed master is still validated by the synchronous assembly
  service's SHA-256, ffprobe, timeline and project-revision gates.
- There is no assertion that code will continue executing while the user's
  laptop or its local backend is powered off.

## Operating limits / next gates

Run as a **single local application server instance** for this phase. The
SQLite running-job claim works cross-process, but startup recovery assumes
there is no other live worker already assembling; multi-worker deployments
must use an owner lease/heartbeat and coordinate startup before enabling.
Do not configure multi-worker Uvicorn/Gunicorn for this local setup.

For 10-minute/4K films, real-hardware and iPhone acceptance must separately
verify: authenticated polling across disconnected Wi-Fi, actual local
FFmpeg and ffprobe binaries, output frame count and duration, source-content
hashes, full file decode, sample scene-boundary playback, disk capacity,
long worker lifecycle, and clean restart after power loss.

## CI verification

\`python -m pytest -q -W error tests/test_cinematic_assembly_queue.py\`

The tests exercise durable queue creation, idempotency, crash/restart behavior,
stale revisions, paginated histories, neutral error reporting, and authenticated
HTTP polling. Existing \`tests/test_cinematic_ffmpeg_live.py\` exercises local
real FFmpeg output. Neither verifies private PC GPU generation or artistic
visual continuity.
