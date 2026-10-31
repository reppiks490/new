# QA27 — Private filtergraph-script transport for long-form master assembly

**Status:** Isolated opt-in helper and acceptance tests only. This PR does **not** change the production assembler. Lead/owner review and explicit integration are required. The existing QA26 `E2BIG` defect remains unresolved in production.

## Verified defect and mitigation boundary

[QA26 #79](https://github.com/reppiks490/new/pull/79) establishes that a legal 700-shot/350-second timeline can generate a `-filter_complex` argument larger than Linux's typical 131072-byte per-string `execve` limit. This PR provides a separate context manager that writes the graph to a unique, 0600 temporary file and replaces the argument with `-filter_complex_script <path>`. It always removes the script after execution, including exceptions. A 700-filter **synthetic** graph is intentionally padded to exceed 131072 bytes, so CI can demonstrate both real Linux `E2BIG` for the inline form and successful actual FFmpeg execution for the script form. This is a transport proof, **not** a 700-shot video render.

## Proposed lead integration (review, do not blindly paste)

Within the current `assemble_project_master` FFmpeg `try` block, use `with private_filtergraph_script_command(command, directory=trusted_private_local_directory) as safe_command:` and call `_run_master_ffmpeg(safe_command, ...)` before leaving the context. The directory must already exist, be trusted and local, and be available to the FFmpeg subprocess. Do not print command, graph or owner source paths. Ensure cancellation/timeouts keep the context alive until FFmpeg exits; handle abrupt process termination with a stale-script cleanup policy. Preserve exact frame budgeting, metadata stripping (#73), revision/queue publication validation, and verified output identity. Probe the owner's FFmpeg version for `-filter_complex_script` support (some builds deprecate this option) before enabling. Avoid default system temp paths if project filtergraphs may reveal private paths.

## What CI does and does not prove

The strict Python 3.11/3.12 job tests file permissions, deterministic cleanup on exceptions, invalid-command rejection, real FFmpeg 2-second synthetic red/blue concat to H.264 with 48 frames at 24 FPS, full decoding, and Linux's 4KiB-page argument ceiling using a real 700-filter graph. It does **not** run 700 source clips, exercise the production assembler, invoke models, render a 600-second film on the owner PC, or test iPhone playback. No cloud generation, external uploads, or owner media are involved. No existing agent-owned source files are changed.
