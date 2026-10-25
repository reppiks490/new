# QA54 — opt-in completed-master full-decode integrity acceptance

**Scope:** isolated draft PR #119, stacked on QA53 #116 at `4b2aa660fafaf9768ebf22c9d1a95116f26e11ec`. Only QA54-specific files are added; production assembler, SQLite queue, cache, mobile client and other agents' files are untouched.

## Evidence-backed gap and test-first approach

The existing QA49–QA53 orphan inventory deliberately never opens or decodes owner media. QA53 catches zero-byte completed MP4s but cannot detect a **nonzero** corrupt master. An MP4 with a faststart metadata atom can be accepted by ffprobe despite truncated video payload. The dedicated synthetic test generates a 2-second H.264/MP4 with FFmpeg, truncates it to 60%, confirms it is still nonzero and requires the full FFmpeg decode to fail. This does **not** imply any owner master is corrupt.

A test-only contract stub was committed first, before the implementation. See this PR's initial CI for intended RED assertions; subsequent final-head CI is the acceptance gate.

## Operation and safety

Opt-in offline command on an owner-selected, **quiescent** workspace:

```sh
python tools/cinematic_completed_master_decode_qa54.py --workspace /local/studio --database /local/studio/studio.sqlite --timeout 120
```

The tool reads only `video_master` SQLite records, verifies each distinct ready asset ID has a uniquely linked regular nonempty MP4, runs local `ffprobe` for container/video metadata, and then fully decodes the first video stream with local `ffmpeg -xerror`. It does not render, generate, repair, hash, delete, upload or modify any media. It does not print private paths, prompts, asset IDs, FFmpeg stderr or source bytes. The only output is aggregate counters; return code 0 means all nonempty discovered ready masters fully decoded, 1 means incomplete evidence, and 2 means the audit itself failed. An empty master set is **not** considered verified. Timeout applies separately to each local subprocess, so a large collection can take substantial time.

Only local `file` protocol input is allowed; no shell or network request is used. It skips symlinks and multiply-linked entries. This is not a sandbox against malicious media/FFmpeg vulnerabilities; do not run on untrusted files or against an active writer. Filesystem races remain possible between metadata inspection and FFmpeg opening the file.

## Evidence boundaries and integration

Passing synthetic FFmpeg tests proves only the fixture files can or cannot be fully decoded. It does **not** prove frame-accurate 600-second assembly, correct continuity, audio retention, private source lineage, native 4K/120 FPS, model inference, owner-PC resource sufficiency or physical iPhone playback. No cloud generation, paid provider, owner media or credentials were used.

Coordinate before integration with master #8, async queue #21, cache/media #23, lead #40, orphan inventory ancestry #109/#110/#112/#114/#116 and concurrent Helper 1 #117. This is a separate, opt-in diagnostic, **not** a replacement for the fast metadata-only QA49–QA53 inspector. Do not automatically merge or deploy.
