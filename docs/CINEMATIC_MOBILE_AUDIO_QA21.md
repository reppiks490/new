# QA21 — offline mobile audio compatibility acceptance

This optional **read-only** gate extends QA17 (#62), QA18 (#64), and QA19 (#66). It accepts silent H.264 4:2:0 progressive MP4 masters by default, or requires audio when `--require-audio` is set. For a master with an audio track, it requires exactly one AAC-LC mono/stereo stream at 44.1 or 48 kHz, independently decodes the entire audio stream with FFmpeg, and rejects audio duration differing from the verified video duration by more than 125 ms. Multiple audio streams and unreviewed extra stream types fail closed.

Run locally **only against an authorized, stable master** with trusted persisted SHA-256, expected FPS/frame count and dimensions:

```bash
python -m scripts.cinematic_mobile_audio_preflight --mp4 /local/private/master.mp4 --expected-sha256 '<trusted-sha256>' --fps 24 --frames 14400 --width 1920 --height 1080 --require-audio
```

The tool does not alter or upload media and emits privacy-minimized JSON. Audio is optional unless the caller explicitly requires it; an absent track is reported as absent, never as AAC-verified. `--require-audio` is a caller policy choice, not a claim that every film needs sound. ALAC can be supported by some Apple software; rejection here is a deliberately **narrow AAC-LC cross-browser acceptance policy**, not a claim that ALAC is universally unplayable.

Tests use actual locally generated **synthetic FFmpeg media** (2 seconds, 48 video frames) to prove that the previous video-only gates accept an ALAC or shortened AAC track while this new gate rejects them. They do not exercise actual model inference, audio quality, 600-second owner-PC rendering, authenticated HTTP Range, or private iPhone/Safari playback. A 125 ms duration check is only a coarse container-duration guard, **not** proof of lip-sync or per-frame A/V alignment. The verifier is not a substitute for atomic publication/TOCTOU protections; media must remain unchanged between SHA and later inspection. No owner media or credentials belong in CI.
