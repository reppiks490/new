# QA59 — opt-in strict completed-master integrity exit

This proposal is stacked on draft QA58 PR #127 and is **not integrated into the production assembler**.

The offline `tools/cinematic_completed_master_decode_qa54.py` inspector has two different success definitions:

- **Default:** exit 0 when every ready master is decodable and the ready records are valid. This is the existing backward-compatible `verification_complete` behavior. It does **not** mean SHA, frame or presentation timing attestation passed.
- **`--require-integrity`:** exit 0 only when `integrity_attestation_complete` is true. Every distinct ready master must be fully decodable, match persisted timeline frames, pass all frame presentation timestamps and durations, and match a valid nonconflicting persisted SHA-256. Missing or conflicting historical claims fail strict attestation without labeling media as corrupt.

Example on a **quiescent, owner-selected local workspace**, never an active production renderer:

```bash
python tools/cinematic_completed_master_decode_qa54.py --workspace /path/to/private/workspace --database /path/to/private/workspace/studio.sqlite --require-integrity
```

The report is aggregate-only; it does not expose filenames, asset IDs, prompts or digest strings, and `safe_to_delete_automatically` remains false. The CLI does not upload, modify, repair, or delete media. This is a diagnostic gate, not a security boundary against concurrent writers; no atomic filesystem snapshot is taken. FFprobe/FFmpeg results, SQLite records and file bytes can change during an active render, so run on a quiescent workspace.

## Test-first evidence

QA59 initial exact-head CI run 40189504256 failed four intended tests per Python 3.11 and 3.12: the strict flag was absent, so `argparse` rejected it. Genuine disposable synthetic H.264 files and temporary SQLite records were used. The follow-up correction adds the opt-in gate without changing the existing default exit policy.

This does **not** verify actual model inference, owner media, audio/video sync, 600-second owner-PC rendering, or physical mobile playback. Parent QA58 and other draft ancestors require lead review; do not auto-merge or deploy.
