# Character3D — offline progressive MP4 startup preflight (QA19)

This optional **read-only** preflight stacks on QA17 (trusted SHA, exact video metadata, complete FFmpeg video decode) and QA18 (H.264 8-bit 4:2:0 MP4 profile). A progressive MP4 must have a valid top-level `ftyp`, then `moov`, then `mdat`. MP4s with the `moov` index at the end may be fully decodable and hash-consistent yet require downloading most/all of a large master before playback can start. Fragmented MP4 (`moof`) is outside this progressive-file gate, not declared universally unplayable.

Run on an **authorized local copy** of the output with expectations from the trusted persisted master record:

```powershell
python scripts/cinematic_mobile_progressive_preflight.py `
  --mp4 "C:\\path\\to\\private\\master.mp4" `
  --expected-sha256 "<trusted-persisted-64-char-sha256>" `
  --fps 24 --frames 14400 --width 1920 --height 1080
```

The verifier reads the complete bytes for the trusted SHA and full video decode through QA17/18, then scans only MP4 top-level box headers by seeking over payloads. It **never rewrites media**, uploads it, starts generation, or prints local paths/prompts/tool stderr. It fails closed on truncated, invalid or duplicate required boxes and reports `mp4_faststart_verified=true` only after all prerequisites pass.

**Synthetic real FFmpeg evidence:** the dedicated workflow creates a two-second, 48-frame H.264 4:2:0 MP4 with `-movflags +faststart`, which must pass, and an otherwise equivalent MP4 without faststart, which passes QA18 but fails this stricter progressive preflight. Additional synthetic atom fixtures cover extended-size boxes, corruption, duplicates and fragmented files. These are not owner footage.

**Not verified:** private authenticated HTTP Range/206 delivery, streaming seek, >80 MiB mobile previews, iPhone/Safari/Android playback, audio track format or synchronization, file replacement after the trusted SHA, owner-PC 600-second rendering, real AI model inference or cinematic visual continuity. Those remain separate lead/mobile/release gates. An absent `moov`-before-`mdat` is a progressive-readiness issue, **not evidence that the video itself is corrupted**. Do not automatically modify a delivered master: any remux must be explicitly reviewed, atomically written, and accompanied by a new trusted SHA record.

**Ownership:** four uniquely named QA19 files; no lead service, queue, mobile UI, helper paths, owner media, credentials, deployment, purchases or automation changes.
