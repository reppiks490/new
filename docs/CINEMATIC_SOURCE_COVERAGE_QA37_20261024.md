# QA37 — Source-clip underlength versus delivery-frame completeness

## Reproduction and consequence

Frozen lead PR #40 (`05c59556d64a808dcc3a8ca96fae5e572c9e446d`) uses
`fps`, `tpad=stop_mode=clone`, `trim=end_frame`, and `setpts` for every source.
A genuine **synthetic** one-second 24-FPS MP4 is therefore accepted by the
same FFmpeg filter sequence for a three-second, 72-frame delivery slot. The
output probes as a valid 72-frame H.264 file and fully decodes. The missing
source motion is replaced by held frames; duration/frame-count checks alone
cannot detect that creative-motion deficit. This is a **quality acceptance
blind spot**, not proof of corruption or a universal defect: deliberate still
holds can be an editorial choice.

## Isolated opt-in utility

`app/video/cinematic_source_coverage_qa37.py` provides read-only FFprobe
video-stream duration inspection against an explicit **delivery frame budget**.
It distinguishes `underlength`, `nominal`, and `unknown`, never treats an
audio-extended container duration as video coverage, and returns no source
path, prompt, private metadata or FFmpeg stderr. A half-frame tolerance
accounts for rounded probe durations. Tests exercise missing metadata, bad
inputs, private-path-safe errors, and genuine synthetic FFmpeg output.

This is **not wired to production**, changes no owner files, and never starts
inference. `nominal` means stream *metadata* reports adequate duration; it is
not full-decode, unique-motion-frame, visual continuity or source authenticity
proof. FFprobe cannot establish that every encoded frame is decodable. This
utility is intentionally advisory until the lead chooses a source-shortfall
policy (reject, explicit hold with UI warning, or re-render missing footage).

## Integration handoff

The lead owns `app/video/cinematic_service.py` and queue admission. Before
integration, decide the allowed deliberate hold policy, check source stream
coverage at assembly readiness, avoid leaking paths to phone clients, and
bind any policy change to assembly version/cache identity. Keep #21/#23
histories separate from #40 pending deliberate reconciliation. Re-run real
synthetic integration plus complete owner-PC and physical iPhone acceptance.

No owner media, paid services, cloud generation, GPU model inference, actual
600-second production render, or mobile-device playback was used.
