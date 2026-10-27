# QA102 — authenticated byte-range delivery of an actual 600-second master

**Status:** independent, draft acceptance candidate. No production changes,
owner media, credentials, external generation, deployment or merges.

## Distinct coverage gap

QA101 #202 proves a real Character3D 600-second H.264 master has progressive
MP4 indexing and supports FFmpeg input-side seeks. Helper 1 #194 proves
authenticated HTTP Range behavior with synthetic short media on its separate
branch. Neither establishes **HTTP byte-range responses for the actual
600-second Character3D assembly output**. This QA102 test composes those
two concerns on the QA101 parent without modifying Helper 1 files.

## Acceptance and negative controls

The opt-in test creates two genuine synthetic color MP4 sources, constructs
twenty ordered 30-second shots, and invokes the actual Character3D master
assembler. It requires 600 seconds and exactly 14,400 output frames.
It then mounts the actual FastAPI application with a synthetic bearer token
and requests the assembled private MP4 via its normal asset URL.

- Missing bearer, incorrect bearer and query-string token are rejected
  with HTTP 401 even when a Range header is supplied.
- Authorized first, middle and final 1,024-byte ranges must return HTTP
  206, exact Content-Range offsets/total length, video/mp4, no-store,
  and byte-for-byte equality with the private on-disk master.
- No full-file transfer is used to satisfy a small Range request.
- The workflow uses the existing isolated FFmpeg container with no network,
  read-only filesystem, bounded memory/PIDs, and synthetic tmpfs workspace.
- The dedicated workflow runs for relevant PR changes and canonical
  feat/cinematic-orchestrator-v1 pushes. A real canonical-branch push
  remains separately unverified until one occurs after integration.

This is in-process HTTP acceptance. It **does not** establish browser media
element behavior, remote tunnels, physical iOS/Android playback, Windows
filesystem semantics, real model inference, artistic continuity or 4K
performance. General CI skips the opt-in test; only its dedicated workflow
can establish real-media green.

## Coordination and dependencies

Frozen parent: QA101 #202 commit
`1edb3b4593718db7f073e43af29f56d57fa609b4`.
Master #8, async queue #21, cache/media #23, lead integration #40, Helper 1
#194, long-form integration gate #199, QA99 live-worker recovery #200,
QA100 audio-policy gap #201, and QA101 faststart #202 must remain under
lead-owned review. Do not confuse a successful synthetic HTTP acceptance
with resolution of the **strict xfail** multi-process recovery or
source-audio preservation limitations.

No concurrent helper files or existing production files are modified.
No automatic merge. Verify exact final-head CI and run combined-SHA CI
after dependency integration.
