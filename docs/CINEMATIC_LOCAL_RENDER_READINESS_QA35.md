# Character3D QA35 — owner-PC local rendering readiness (draft)

**Status:** Independent, opt-in, non-production acceptance aid. No production queue, renderer, HTTP route, or helper-owned file is changed. Built against cinematic integration PR #40 at `05c59556d64a808dcc3a8ca96fae5e572c9e446d`.

## Evidence and gap

The current master assembly launches local FFmpeg and ffprobe, writes a potentially long H.264 master into the studio workspace, and does not perform an explicit free-disk or encoder-availability admission check before the render. Earlier QA found separate unsafe local file modes (#86), many-shot Linux argument limits (#79), decoder/thread memory limits (#81), and extreme geometry admission (#82). The existing CI cannot establish the owner's particular PC's binary availability, free disk capacity, ACLs, GPU models, or mobile playback.

## Optional offline check on the owner PC

From the repository root, with the Python environment installed and the studio workspace already created:

```bash
python scripts/cinematic_local_render_readiness_qa35.py --minimum-free-gib 20
```

To additionally generate **only one second of synthetic 160x90 test footage** inside an automatically cleaned private temporary directory, probe 24 frames, and fully decode it:

```bash
python scripts/cinematic_local_render_readiness_qa35.py --minimum-free-gib 20 --synthetic-smoke
```

Set `CHARACTER3D_STUDIO_WORKSPACE` to the same workspace as the local studio, or pass `--workspace` (never put credentials in the path). The command **does not create or modify workspace files**, read owner footage, call providers, invoke models, upload media, or access the network. The synthetic smoke option writes and deletes temporary synthetic media outside the workspace. It returns `0` for all selected checks passing and `2` for one or more failed checks.

Output is a machine-readable JSON object containing neutral codes and booleans; it never includes the workspace path, executable paths, environment tokens, prompts, filenames, or captured FFmpeg output. It checks local FFmpeg and ffprobe invocability, libx264 encoder advertisement, workspace existence and final-component symlink rejection, POSIX workspace mode when applicable, and configured free-space headroom. The default **20 GiB is an advisory operator threshold, not a calculated 600-second/4K capacity requirement**. On Windows, ACLs are not validated by this utility; a passing result does not prove private filesystem access.

## Acceptance boundaries and blockers

- The automated test includes nine mock/temporary-workspace checks and one **genuine synthetic FFmpeg encode + ffprobe + full decode**. CI checks GitHub-hosted Linux, **not the owner's PC**.
- A successful synthetic smoke proves only the tested tiny H.264 path; it does not prove 700 distinct inputs, 600 seconds, 4K/60 or 120 FPS, disk throughput, FFmpeg process cancellation, owner-PC power-loss recovery, or hardware performance.
- It does **not** exercise model inference, actual owner footage, authenticated iPhone byte-range streaming, or physical phone playback.
- The utility is not wired into production queue admission. Lead owner should decide whether to add a non-destructive prequeue policy and measure real disk budgets. Do not use a fixed threshold as a substitute for output-size/resource estimation.
- Existing defects in PRs #73, #79–#86 and integration dependencies #8/#21/#23/#40 remain independently unresolved until production fixes and release acceptance.

No merge, deployment, cloud generation, purchase, owner-media transfer, ICARUS modification, or ChatGPT automation change is authorized by this QA artifact.
