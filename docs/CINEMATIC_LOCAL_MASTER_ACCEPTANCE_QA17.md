# Character3D — offline master MP4 acceptance (QA17)

**Purpose:** A read-only local verifier for a master already produced by the authorized Character3D renderer. This does not render, download, upload, serve, or publish media. It does not access credentials or start inference. Run only on the owner's own PC or another expressly authorized local environment.

## Why this is separate

The lead cinematic integration PR #40 verifies an H.264 master through FFprobe metadata and a SHA-256 record. Later independent draft QA #49, #50, #52 and #54 demonstrate that persisted identity, media presence, full decoding, and source completeness are different gates. The existing synthetic FFmpeg CI checks short fixtures; it does not certify a ten-minute owner-PC output. This tool provides a reproducible **post-render** verification contract without touching the lead's service, queue, frontend or other helpers' tests.

## Command on an authorized local MP4

Obtain the expected SHA-256, frame count, frame rate and dimensions from the **trusted persisted master record** before reading the local MP4. Do not generate the expected SHA by hashing the same suspect file immediately before verification; that would make the identity check meaningless. Do not copy owner paths, private media, prompt text or credentials into a PR or public CI log.

```powershell
python scripts/cinematic_master_acceptance.py `
  --mp4 "C:\path\to\private\master.mp4" `
  --expected-sha256 "<64-character-sha256-from-persisted-record>" `
  --fps 24 --frames 14400 --width 1920 --height 1080
```

The example describes 600 seconds at 24 FPS; substitute the *actual authored delivery metadata*. Requires local `ffprobe` and `ffmpeg` executables on PATH. It reads and hashes the file, rejects missing/mismatched bytes, checks H.264 dimensions/FPS/frame count/duration against the declared record and the 600-second ceiling, then runs strict **full FFmpeg decode**. Exit code `0` produces privacy-minimized JSON with `verified=true`; exit code `2` produces a neutral failure reason. The tool never prints file paths, prompt text, credentials, decoder stderr or raw frames. It does not create or modify a master.

If the output is longer than ten minutes, the input metadata is inconsistent, the trusted digest does not match, the codec is not H.264, or FFprobe/full decode fails, **do not mark it release-ready**. Preserve private diagnostics locally and ask the source owner to investigate. Full decoding does not detect frozen source frames, repeated/interpolated motion, incorrect prompts or continuity defects; use the independent source-duration and provenance gates.

## Evidence classes and open gates

- **QA17 automated unit tests:** mocked FFprobe/FFmpeg subprocess results and synthetic placeholder bytes only. These prove CLI fail-closed behavior and privacy-minimized output; they **do not** prove real MP4 decoding.
- **Synthetic real FFmpeg media:** separate dedicated media workflows in PRs #23, #32 and #40; run strict current-head integration again after reviewed source fixes. Their success does not prove model generation.
- **Actual local model inference:** still requires owner-approved model weights, GPU, source-image bytes, prompt and authentic execution identity. This script does not perform it.
- **Owner-PC/mobile acceptance:** after an actual render, run this tool locally and separately test the authenticated mobile fetch, background/reconnect, Quick Hide, seek/playback, duration, storage, thermals and long-form continuity. The current preview gate may reject masters larger than 80 MiB; no large-master streaming implementation is proven. Do not expose the local API to the public internet.

**Ownership:** additive `scripts/cinematic_master_acceptance.py`, `tests/test_cinematic_master_acceptance_qa17.py` and this document only. No lead/async/mobile/Helper 1–4 production paths modified. Draft PR; no merge, deploy, cloud generation, service purchase, owner media or automation change.
