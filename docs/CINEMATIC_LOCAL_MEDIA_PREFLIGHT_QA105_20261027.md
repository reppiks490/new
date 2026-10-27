# QA105 — read-only local media preflight (draft, not release certification)

**Scope:** new isolated module `app.video.cinematic_local_media_preflight_qa105`, with unit tests. Frozen parent QA104 #205 at `cdb3e735b1656bec58fb47e6c3f394e4adfb9717`. Do not automatically merge.

## Why this exists

QA104 identified that successful GitHub CI and synthetic 600-second FFmpeg acceptance do **not** establish whether the owner's Windows/WSL2 workstation has a responsive FFmpeg/FFprobe pair, the `libx264` encoder required for local H.264 masters, or enough free space on the actual workspace volume. The existing project/engine/reference preflight intentionally does not inspect runtime binaries or host storage. This adds a **narrow local operator diagnostic**, not a server endpoint or a remote capability.

## Trusted local invocation

From a locally checked-out copy of the Character3D repository, run:

```bash
python -m app.video.cinematic_local_media_preflight_qa105 --workspace "/path/to/existing/workspace" --min-free-gib 10
```

On Windows PowerShell, substitute an existing trusted local folder, for example `--workspace "D:\\Character3D\\workspace"`. For WSL2, pass the WSL-visible path to the **actual** workspace volume. Only pass trusted executable paths to optional `--ffmpeg` and `--ffprobe` arguments; binaries are executed for metadata probes.

The command prints a JSON object with fixed finding codes, **never the local paths, FFmpeg banner, stderr, prompts, media or credentials**. Exit 0 means only the four narrow checks passed; exit 2 means blocked or incomplete. No workspace is created or modified. The disk threshold is a caller-chosen floor, not an estimate of the space required for a 600-second film.

## Evidence classes and limits

- **Unit tests:** mock binary lookup, subprocess return codes and disk usage. They assert fail-closed behavior, explicit not-checked status, no path/diagnostic leakage and no workspace writes. These tests **do not run a real FFmpeg encode**.
- **Local diagnostic when the owner actually runs it:** probes `ffmpeg -version`, `ffprobe -version`, `ffmpeg -hide_banner -encoders` for `libx264`, and read-only disk usage of an existing workspace. A passing result is instantaneous toolchain metadata only. It does **not** verify filter support, actual encode/decode, writable filesystem, GPU availability, throughput, thermals, 4K or cross-volume path behavior.
- **Previous independent genuine synthetic FFmpeg evidence:** QA93–103 tested aspects of the application media path in CI. It is not owner-PC evidence and is not repeated by QA105.
- **Not tested:** actual model inference or artistic continuity, physical mobile HTTP Range/reconnect, owner media, Windows/WSL2 locking, source-audio policy, and multi-process queue safety. The report always has `release_ready=false`.

## Dependencies / integration

- #8 master assembly, #21 durable queue, #23 real-media/cache acceptance, #40 lead integration remain separate unmerged drafts.
- #171 Helper 1's unauthorized denial `no-store` production fix and #194 strict-media push workflow are divergent lead-review candidates.
- #200 QA99 demonstrated unsafe second-process startup recovery; **one API process per SQLite workspace** remains the operational boundary.
- #201 QA100 demonstrated source AAC stripping, pending an explicit product audio policy.
- #204 QA103 demonstrated missing `Cache-Control: no-store` on unauthorized 401; a strict expected failure is **not** a fix.
- #205 QA104 maps integration ownership and the missing combined-SHA CI gate.

QA105 changes no queue, master, auth, media, web, workflow, or Helper 1 files. Lead should review it independently of the larger integration stack. Do not promote a cinematic release based on this diagnostic alone.

**Safety:** no cloud provider requests, media reads/writes, directory creation, credentials, owner media, deployment, spend, ICARUS, or automation changes.
