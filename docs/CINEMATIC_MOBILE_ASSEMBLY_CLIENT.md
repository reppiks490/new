# Cinematic master assembly — private mobile-client integration

Scope: `app/studio/web/cinematic-assembly-client.js` and `tests/test_cinematic_assembly_client.mjs`.
Base: `chatgpt/cinematic-async-master-jobs-20261022` (draft PR #21); no shared inspector or cinematic editor files changed.

## Behavior

The JavaScript client accepts the existing authenticated `deps.api` callback from the cinematic workspace. It never reads, writes, stores, logs or serializes API tokens, private master prompts, full job records, or source media.

- `submit(projectId, expectedRevision)` calls the durable HTTP 202 assembly queue and returns a privacy-minimized job.
- `get(projectId, jobId)` reads one job and rejects project-identity mismatches.
- `cancel(projectId, jobId)` cancels only queued work. The server returns 409 for work already running or finished. Never label an active FFmpeg encode as cancelled.
- `list(projectId, {limit,offset})` validates explicit pagination and rejects malformed or non-advancing server results.
- `findActive(projectId)` discovers the most recent active assembly across all server pages after mobile reconnect, without storing job IDs or tokens in localStorage, IndexedDB, or URLs.
- `waitForTerminal(projectId, jobId, {signal,onUpdate,intervalMs})` polls serially, is abortable, and never schedules an overlapping request. The caller should cancel polling when the cinematic mode closes, tab is hidden, or quick-hide activates.
- `normalizeAssemblyJob` whitelists IDs, revision, status and progress only; strips private job strings; refuses unverified, mismatched, tokenized or cross-origin master asset URLs.

## Integration ownership

The cinematic editor owner should import the module, supply the existing `deps.api`, and render only `assemblyStatusSummary(job)`. Do not place the raw job record or server-supplied `stage`/`error` fields directly in HTML. Use textContent or HTML escaping for any additional labels. When a verified master is ready, use the existing authenticated private-blob fetch and browser object-URL mechanism; do not navigate directly to an API URL containing a token.

Unknown assembly progress is null, never displayed as zero percent. The backend only reports 100% after successful ffprobe validation; this client does not invent progress metrics.

Do not persist the bearer token, screenplay, private images, or output video in browser storage. The client itself stores none of these. The caller remains responsible for privacy-mode quick hide, media URL revocation, and controlled polling lifecycle.

## Quality boundaries

Run `node --test tests/test_cinematic_assembly_client.mjs` and the repository's complete Python/Node/Docker matrix. Mocked client tests prove protocol and privacy behavior, not real iPhone playback or GPU video generation.

Remaining integration gate: wire the client to the cinematic inspector/timeline in a nonconflicting UI-owner branch; validate a real long-running FFmpeg master in the owner's private PC environment, including disconnect/reconnect, quick-hide, bearer fetch, cancellation before claim, and real video playback.