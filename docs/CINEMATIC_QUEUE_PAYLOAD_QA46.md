# QA46 — active master queue payload shape audit (opt-in, read-only)

**Frozen parent:** cinematic lead #40, `05c59556d64a808dcc3a8ca96fae5e572c9e446d`. This is an additive helper, not a production fix, worker integration, migration, queue recovery, or deployment.

## Evidence and risk

`app/video/cinematic_assembly_jobs.py` uses SQLite `json_extract(data,'$.status')='running'` to block claims while any master is running. A *synthetic, valid JSON* record such as `{"status":"running","project_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}` passes that SQL status test but lacks the `project_revision` and `ffmpeg_path` needed for execution. A separate healthy queued record cannot be claimed while this row remains `running`. This is different from #99's syntactically malformed JSON and #95's status-write exception. It does **not** demonstrate that the owner's DB contains such a row or that a worker has died.

## Utility

Run locally and deliberately: `python tools/cinematic_queue_payload_audit_qa46.py --db /path/to/studio.sqlite`. Only aggregate counts and neutral warnings are emitted. Checks minimum active-record fields (`status`, 32-hex `project_id`, positive integer revision, nonempty string `ffmpeg_path`); does not print IDs, paths, scripts, prompts or credentials. SQLite `mode=ro` plus `PRAGMA query_only` is used, though WAL/SHM access can occur. No FFmpeg is invoked.

## Integration contract

Coordinate with #21 (durable queue), #40 (revision/ownership), #95 (transient write recovery), #97 (status-only health), #99/#100 (malformed-JSON isolation), #56 (dispatch coalescing), #63 (process fencing), and #23 (media acceptance). Do **not** automatically change status of a malformed `running` row: a live worker or other process may exist. Any recovery needs verified process ownership, a fenced lease, atomic CAS and evidence-preserving quarantine policy. This diagnostic does not replace full schema validation at durable admission or genuine owner-PC validation.

**Proof level:** synthetic SQLite and pure-Python validation only; no model inference, FFmpeg encoding, owner data, 600-second rendering, or physical mobile playback.
