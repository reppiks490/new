# Character3D master-library history retention — independent QA 10

**Base:** integrated lead cinematic PR #40 at `05c59556d64a808dcc3a8ca96fae5e572c9e446d`. This isolated QA branch adds only `tests/test_cinematic_master_library_retention_qa10.py` and this handoff. No edits to lead-owned service/router/storage, existing helpers' tests, UI, credentials or private media.

## Distinct defect hypothesis

`app/video/router.py::cinematic_project_masters` calls `list_video_records('video_master')`, then filters that result by `project_id`. The shared `app/studio/storage.py::list_records` selects the **100 newest records across all projects**. A legitimate older master may therefore disappear from **GET /api/video/projects/{project_id}/masters** after unrelated projects create newer masters, even though `get_video_record('video_master', id)` can still read it. The endpoint has no explicit pagination, total count, or truncation indicator.

This is a project-master history/discoverability contract, distinct from #41/#43's cache *reuse* defect and #46's `video_project` project-library listing. It is **not evidence of deleted media or a privacy exploit**.

## Deterministic test-first evidence contract

Two synthetic projects, two target-project master metadata records and 98 unrelated newer masters form a 100-record GREEN control. Adding one unrelated record (101 total) should leave both target masters discoverable; the existing global cap is expected to hide the older target master. Both remain individually readable. A separate assertion rejects cross-project records in the target listing.

The test sets explicit SQLite `updated` values to eliminate clock-resolution flakiness. It calls the actual route handler but **does not exercise HTTP authentication middleware**. Records are mock metadata with `actual_video_probe_verified=False`: **no FFmpeg, actual model inference, GPU, owner footage, local 600-second render or mobile-device verification**. Do not call the synthetic metadata a verified render.

## Production handoff and acceptance

The lead owns `app/video/router.py`, `app/video/storage.py`, and `app/studio/storage.py`. Prefer a backward-compatible **project-scoped, explicit paginated** master-history query with stable ordering, bounded response size, `total`/`has_more`, and authenticated mobile-client traversal. Evaluate whether to return only metadata rather than exposing large/private source details in history. Preserve per-project isolation, direct lookup semantics, and cache SHA/probe safeguards. Do not globally remove every 100-record cap or assume that fixing #41 or #46 automatically fixes this endpoint.

Keep this QA PR draft and unmerged while RED. After any lead-owned correction, run this test on the **combined exact head** with full Python 3.11/3.12, Node privacy/mobile, Docker, dedicated real synthetic-FFmpeg acceptance and other red QA gates (#41, #43, #44, #45, #46). An ancestor's GREEN CI does not certify a new combined commit. Do not merge, deploy, activate paid/cloud inference or touch ICARUS/ChatGPT automations.

## Coordination

Lead PR #40: source/API ownership and integration. PRs #41/#43: master cache history/candidate fallback. PR #46: project library discovery. This PR changes no overlapping paths. The current 100-record limit is visible in source; **GitHub exact-head CI outcome must be inspected before claiming the new test has reproduced RED**.
