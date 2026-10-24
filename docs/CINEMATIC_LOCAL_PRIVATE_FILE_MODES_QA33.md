# QA33 — Local cinematic artifact filesystem privacy (draft handoff)

## Ownership and scope

Disjoint additive QA on frozen lead integration PR #40, commit `05c59556d64a808dcc3a8ca96fae5e572c9e446d`. This branch adds **only** a strict synthetic-media test, a dedicated workflow, and this handoff. No changes to lead `app/studio/storage.py`, `app/video/storage.py`, `app/video/cinematic_service.py`, async PR #21, cache/media PR #23, mobile UI, other helpers, ICARUS, or automations. Do not auto-merge.

## Defect hypothesis and evidence

The project advertises bearer-protected private masters over HTTP, but the local POSIX filesystem is a separate security boundary. On a standard Linux process umask of `022`:

- `app/studio/storage.py:root()` calls `Path.mkdir(parents=True, exist_ok=True)` without restrictive mode: newly created studio directory can be `0755`.
- `app/studio/storage.py:connection()` opens `studio.sqlite` through SQLite without explicitly creating a private file: new database can be `0644`. The database can contain private screenplay, prompts and project metadata.
- `app/video/storage.py:video_asset_path()` creates `video-assets` with default directory permissions, commonly `0755`.
- `app/video/cinematic_service.py:assemble_project_master()` launches FFmpeg without a private child-process umask or pre-created private destination. New master MP4s can be `0644`.

Independent local **genuine synthetic FFmpeg** control under umask `022` created an H.264 MP4 with mode `0644`. The new application-level tests verify all four storage surfaces, including an actual 24-frame synthetic master, and an independent owner-only file creation control. The strict tests intentionally fail until production is hardened.

**Impact is conditional:** permissive mode bits alone do not prove another user accessed files. A secure ancestor directory, mount ACL, or dedicated owner-only account may block traversal. The test fixture's outer pytest temporary directory is itself restrictive, so the test asserts individual mode bits rather than claiming an end-to-end disclosure. No owner media, real prompts, or credentials were read.

## Proposed lead repair contract

1. Establish a documented private local storage policy: POSIX studio root and video-assets directory owner-only (`0700`), SQLite DB, WAL/SHM, source uploads and generated master MP4 owner-only (`0600`), subject to explicit shared-workspace requirements.
2. Create new paths securely **before** writing private data; avoid a create-world-readable-then-chmod window. Consider a private per-process FFmpeg umask (`subprocess.run(..., umask=0o077)` on POSIX) and secure DB creation; verify FFmpeg output and temporary files. Do not change global process umask in a concurrent web server.
3. Define an explicit, non-destructive policy for existing files/directories and Windows ACLs; avoid assuming POSIX mode bits apply on Windows. Review backups, inherited ACLs, symlinks, WAL/SHM, and owner-PC service account.
4. Re-run strict QA33 on both Python versions, full general CI, authenticated mobile/Range tests, real-media cache, and owner-PC filesystem/ACL checks. A green mock alone is not enough.

## Verification boundaries

The synthetic FFmpeg control establishes a real media file-creation mode. The application tests require GitHub Actions execution for a complete service-level result. This does not test model inference, owner-PC ACLs, physical phone playback, or real private media. Report expected-red dedicated CI as a confirmed regression, not as a successful repair. No production remediation is included here.
