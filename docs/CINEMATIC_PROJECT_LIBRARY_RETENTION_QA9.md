# Character3D project-library visibility beyond 100 records — QA handoff

**Owner boundary:** QA-only additive files on a frozen cinematic integration base. No edits to lead-owned `app/video/cinematic_service.py`, `app/video/router.py`, `app/studio/storage.py`, active helpers' tests, mobile UI, or deployed application. This PR is **draft / not merge-ready** while the test is RED.

## Exact observed source path

- `app/video/cinematic_service.py::list_projects` calls `list_video_records('video_project')`.
- `app/video/storage.py::list_video_records` delegates to `app/studio/storage.py::list_records`.
- That shared query uses `ORDER BY updated DESC LIMIT 100` for all kinds.
- `app/video/router.py::cinematic_projects` exposes the service list as `GET /api/video/projects`, without a pagination or truncation indicator.
- `get_project(project_id)` uses a direct `get_video_record` lookup; an omitted project can still be present in SQLite.

**Impact:** after 101 or more valid cinematic projects exist, the list endpoint can silently omit persisted projects, potentially making older filmmaking work appear lost. This is a **discoverability/continuity** defect, not demonstrated deletion or unauthorized access. It is distinct from the master-cache `video_master` history-window regression in PRs #41 and #43, although it shares the capped storage primitive.

## Reproduction / verification

`tests/test_cinematic_project_library_history_qa9.py` creates 100 and 101 synthetic projects in an isolated temporary workspace. It confirms every ID is individually persisted and readable, then asserts that the project-library listing contains those same IDs.

Expected before production fix: the 100-project control is GREEN; the 101-project case is RED, without FFmpeg, cloud inference, private footage, or owner-PC/mobile access. **Do not claim the full regression is reproduced until its actual GitHub CI result is inspected.**

## Lead-owned repair choices

Prefer a **deliberate, backward-compatible API contract** rather than indiscriminately removing the cap from every storage listing. One option is explicit project pagination with a stable ordering, total count, and a client path that can traverse all pages without silently dropping older records. An alternative is a complete project list if acceptable for the existing clients, but avoid shipping unbounded private script/scene payloads to constrained mobile devices without reviewing privacy, performance, and compatibility. Avoid weakening the existing per-project authentication and direct lookup.

Review integration against PR #40 and its successors. The production cache fix for `video_master` should not be assumed to fix `video_project` listing. Verify Python 3.11/3.12, Node/mobile privacy, Docker and targeted retention tests at the **final combined commit**, and perform actual owner-device checks separately.

No production fix, merge, deployment, service activation, paid inference, or private-media transfer is authorized by this QA handoff.
