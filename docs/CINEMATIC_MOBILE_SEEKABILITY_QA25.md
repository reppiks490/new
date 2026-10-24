# QA25 — offline CFR/keyframe seekability acceptance for private cinematic MP4s

**Scope / ownership:** A disjoint, read-only optional acceptance gate stacked on QA24 PR #76 (exact parent `7162544219ceb28be5b71637db8e06f06e7557f9`). Four new QA25-only paths; no production assembly, queue, router, browser/mobile client, other helpers' tests or existing acceptance scripts are modified. Keep draft; no automatic merge, deployment, paid inference, owner footage or cloud generation.

## Evidence and gap

Genuine local synthetic FFmpeg 7.1.5 generated two **four-second**, 320×240, 24 FPS, 96-frame, H.264 8-bit 4:2:0, AAC-LC, faststart MP4s. With `-g 24 -keyint_min 24 -sc_threshold 0`, ffprobe reported keyframe PTS at 0, 1, 2 and 3 seconds. With `-g 240 -keyint_min 240 -sc_threshold 0`, ffprobe reported only one keyframe at 0 seconds. Both had video duration 4.0 seconds, 96 frames, 24 FPS and aligned four-second audio. A 600-second master with an equivalent single-IDR pattern could require decoding a very long span to seek. This is a **seekability risk**, not proof that current production output has this defect.

QA17–24 verifies SHA, full decoding, mobile H.264, faststart, AAC, stream start/end timing and display geometry, but does not bound GOP seek distances. QA25 first calls the full prior gate, then reads *all* video packet PTS/keyframe flags with ffprobe. It conservatively requires one video packet per expected frame, regular CFR PTS and no gap larger than two seconds between presentation start, keyframes and end. Video packet PTS are sorted before checking to accommodate H.264 B-frame decode ordering.

**Run:** `python -m scripts.cinematic_mobile_seekability_preflight --mp4 /private/local/master.mp4 --expected-sha256 <trusted-sha256> --fps 24 --frames 96 --width 320 --height 240 --require-audio`. Never paste private paths or trusted hashes into public comments. This tool does not change, transmit or persist media. Outputs contain only neutral verdicts and metrics, never ffprobe stderr, filenames or owner prompts.

## Verification and release boundary

The dedicated workflow requires real synthetic FFmpeg/FFprobe/libx264/AAC on Python 3.11 and 3.12; no mocked media may count as real-media success. Regression cases cover periodic GOP acceptance, a single-IDR file that passes prior gates but fails QA25, silent-film handling, SHA fail-fast, malformed packet metadata and CLI privacy. General CI is a separate gate. An offline positive result does **not** prove native iPhone seek latency, authenticated large-file browser streaming, owner-PC 600-second rendering, visual continuity, or actual model inference. Those remain distinct owner/lead acceptance tasks.

**Integration:** PR #40 owns assembly; #21 owns durable queue; #28/#36 own mobile; #62/#64/#66/#70/#71/#76 own preceding optional QA gates. This is a proposed conservative delivery policy, not a mandatory production codec change. Confirm its 2-second GOP bound against actual owner-device playback before requiring it for all masters.
