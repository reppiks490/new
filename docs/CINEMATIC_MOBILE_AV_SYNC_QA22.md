# QA22 — Optional read-only A/V presentation-timestamp acceptance

**Owner:** isolated QA22 branch, stacked on QA21 #70. **No production source edits.**

## Reproduced defect

QA21 validates audio codec, full audio decode and absolute *duration* difference
<=125ms. That does not prove alignment of the first audible sample to the
first video frame. Genuine synthetic FFmpeg input with 48 video frames at
24 FPS, and a 120ms audio-input delay plus shortened audio to end on the
same frame, produces a ~98ms AAC presentation-start offset. The SHA, video
full decode, faststart, AAC and QA21 duration gate all pass.

## Acceptance

`python -m scripts.cinematic_mobile_av_sync_preflight --mp4 PRIVATE.mp4 --expected-sha256 <trusted 64-char sha> --fps 24 --frames 48 --width 320 --height 240 --require-audio`

The verifier first runs QA17–21 gates and then compares FFprobe video/audio
stream presentation **start** and **end** times. The optional conservative
threshold is 50ms at both endpoints; missing, nonfinite or malformed stream
timestamps fail closed. Silent films remain supported unless audio is required;
when silent, timing is explicitly `not_applicable`, never reported verified.
It prints neutral JSON without paths, prompts, credentials, FFmpeg stderr or
media bytes, and never writes/uploads media. Re-run with trusted expected SHA
on the actual finished local MP4; no owner media is needed in CI.

This is a container-level PTS check, **not** semantic lip-sync or actual
phone/browser playback. It does not repair production assembly, guarantee
subframe audio alignment, verify 600-second owner-PC renders, infer scenes,
or test actual generative-model inference. SHA validation is a check at a
point in time, not a guarantee against later file mutation.

## Dependencies

- #70 QA21 read-only AAC/duration acceptance; #66 faststart; #64 H.264; #62 SHA/full decode.
- #40 lead owns assembly/router; #21 async queue; #28 mobile UI. Do not change their files here.
- #67/#68 authenticated HEAD regression and browser bearer-streaming remain separate.

No merge, deployment, paid generation or cloud activation is authorized by this QA.
