# QA43 — privacy-safe, read-only cinematic master queue health snapshot

**Owner:** isolated QA43. **Base:** lead cinematic integration PR #40 at `05c59556d64a808dcc3a8ca96fae5e572c9e446d`. **Status:** opt-in diagnostic only; not wired to UI, worker or production queue admission.

## Why this is useful

The master-assembly queue persists `video_assembly_job` records in the local studio SQLite database. QA42 PR #95 demonstrated a synthetic transient status-write failure leaving a `running` row that can block subsequent jobs. PR #94 covers a different post-commit dispatch receipt failure; #56 covers duplicate dispatch futures; #63 covers concurrent startup. Existing API history is project-scoped, whereas a local operator needs a *global*, nonidentifying snapshot to distinguish a full backlog from an empty queue without publishing scripts, filenames or project IDs. This utility is an **observability aid**, not a queue recovery implementation.

## Offline usage (owner-controlled PC only)

From the repository root, with a local database already present:

```bash
python tools/cinematic_queue_health_qa43.py --db ./workspace/studio/studio.sqlite
```

If `CHARACTER3D_STUDIO_WORKSPACE` points elsewhere, supply that existing directory's `studio.sqlite` explicitly. Output is one JSON object containing only aggregate counts, oldest queued/running record ages, capacity reference and neutral warning codes. It deliberately omits paths, record IDs, project IDs, prompts, error details and executable settings. Do **not** attach a database file to an issue or upload owner media.

The inspector opens SQLite using `mode=ro` and `PRAGMA query_only=ON`. It does not invoke the app, dispatch workers, cancel jobs, change statuses, run FFmpeg, or create a missing database. SQLite may access its WAL/SHM sidecars; this is **not** a byte-for-byte immutable filesystem audit. It does not validate SQLite filesystem ACLs.

## Interpretation boundaries

- `running > 1` violates the current one-lane claim design, but is not proof of duplicate live FFmpeg processes.
- A single `running` row, even an old one, **does not prove** a stuck/orphaned worker; a long render or a stopped PC can produce the same snapshot.
- `queued + running >= 32` matches the frozen #40 `_MAX_OUTSTANDING` threshold; future lead changes may alter that reference.
- Ages use the `records.updated` SQLite timestamp; invalid/future timestamps are excluded and flagged.
- A green QA43 does not repair #95, validate FFmpeg decoding, perform model inference, or verify Windows owner-PC/mobile playback.

## Verification / integration handoff

Seven hermetic tests use genuine temporary SQLite rows (including an uncheckpointed WAL transaction), malformed JSON, missing schema, private canary strings and no-row-mutation comparisons. No real media or model inference. Dedicated workflow tests Python 3.11 and 3.12; normal CI remains authoritative for the full application. Lead may later expose a safe **authenticated** operator view or incorporate a liveness lease, but must coordinate fencing and single-flight semantics with #21/#40/#56/#63/#94/#95 and preserve media/hash acceptance from #23. Do not automatically merge divergent branches.
