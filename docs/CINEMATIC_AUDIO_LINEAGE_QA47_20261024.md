# QA47 — source-to-master audio presence, without owner media

**Scope:** opt-in offline read-only audio stream presence diagnostic. Frozen parent: lead cinematic PR #40 `05c59556d64a808dcc3a8ca96fae5e572c9e446d`. No changes to production FFmpeg, queue, mobile client, agent files, credentials, ICARUS or automations. Draft review only.

## Source-backed finding and independent reproduction

`app/video/cinematic_service.py::assemble_project_master` currently creates a video-only concat (`concat=...:a=0`) and adds `-map [v] -an` to FFmpeg. It then persists `has_audio: False`. This is a deliberate **video-only implementation**, not evidence of a bug if the intended policy is silent masters. However, if rendered shot MP4s carry useful dialogue, music, or ambient audio, the master cannot retain it. A valid, frame-accurate video-only master may pass the existing video acceptance gates while losing source sound. No evidence about real owner footage or generation-engine audio capabilities is asserted.

The new helper only counts which input clips and output master have an audio stream. It flags **source_audio_absent_from_master** when any source has audio and the master has none. It cannot verify that present output audio originated from the sources, nor lip sync, levels, licensing, crossfade policy, dialogue alignment or AAC/mobile acceptance. Existing #70 and #71 address *output* audio codec/duration/timestamp acceptance, not input-to-output preservation.

## Use / privacy

`python tools/cinematic_audio_lineage_qa47.py --source /path/to/shot1.mp4 --source /path/to/shot2.mp4 --master /path/to/master.mp4`

Run only on trusted local media, not remote URLs. Reports numeric counts, booleans and fixed diagnostic state; no paths, titles, tags, codec metadata, transcripts or prompts. Sanitized errors do not include FFprobe output. FFprobe subprocesses are bounded by a 30-second timeout per clip, and a 1–1000 source count. The helper does not mutate source files or master. CLI paths still appear in the local process command line; do not pass owner paths through shared CI or logs.

## Evidence and decision gate

Hermetic tests cover invalid arguments, probe errors and neutral output. Genuine synthetic FFmpeg creates a one-second H.264+AAC source, copies it with `-an` to a video-only master, fully decodes both, and verifies the audio-loss warning. Positive AAC-presence and silent-video controls are included. These are **synthetic media tests**, not a production assembler invocation, model inference, real dialogue, owner-PC 600-second render or physical mobile playback.

**Lead decision required:** explicitly document whether v1 masters are intentionally silent, or audio-bearing shot masters must preserve/mix audio. If audio is required, design per-shot audio trim/pad against the exact editorial frame budget, A/V timestamps, silence policy, safe concat/mix, and AAC-LC acceptance (#70/#71) before changing the production FFmpeg command or cache identity. Preserve queue readiness, revision fencing and privacy. Coordinate with #8, #21, #23, #40, #70, #71 and mobile #28. No automatic merge.
