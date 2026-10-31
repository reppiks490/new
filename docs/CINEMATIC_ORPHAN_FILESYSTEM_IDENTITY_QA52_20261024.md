# Character3D QA52 — offline orphan-media filesystem identity and conservative quiescence

## Frozen ownership and dependencies

Draft #114 is stacked on QA51 #112 exact `d3efb3961d016f3548f60b2dda9a3acede140a27`, itself stacked on QA50 #110, QA49 #109 and lead #40. QA52 adds its own isolated test/workflow/this memo and minimally changes **only** the previously QA49–QA51-owned read-only inspector. Production cinematic service, async queue, FFmpeg worker, browser/mobile UI, Helper 1 files, ICARUS and ChatGPT automations remain untouched. No merge or deployment authorized.

## Reproduced defect and scope

The inspector previously marked symlink and non-file UUID-named `.mp4` entries as `unsafe_mp4_entries_skipped` but could still report `candidate_inventory_not_quiescent=false`. It also followed a multi-step `is_symlink` / `is_file` / `stat` metadata path and classified hardlinked files as ordinary untracked candidates, potentially including byte counts for a file linked outside the selected workspace.

Test-first [QA52 RED run 40162619164](https://github.com/reppiks490/new/actions/runs/40162619164) exercised genuine temporary SQLite and synthetic filesystem entries. The Python 3.11 job showed **4 intended failures, 21 inherited/control passes** (external symlink, dangling symlink, external hardlink, UUID-named directory). This is an offline diagnostic interpretation/privacy-hardening defect, **not** evidence of a malicious owner-PC filesystem or a production media failure.

## Minimal proposed correction

A single `Path.lstat()` no-follow metadata lookup now determines whether each matching directory entry is a regular file and has exactly one hardlink. Nonregular entries or multiply-linked inodes are counted as unsafe and omitted from orphan candidate/byte counts. Any unsafe entries set `candidate_inventory_not_quiescent=true`; the diagnostic remains read-only, aggregate-only and never deletes media. Existing valid unique regular MP4 candidate reporting is preserved. Filesystem race or detached FFmpeg processes cannot be ruled out, and hardlink count is a **conservative heuristic**, not proof of external ownership.

## Verification and integration requirements

Run strict QA52 Python 3.11/3.12 including inherited QA49–QA51 SQLite and short genuine synthetic FFmpeg acceptance, then verify exact-final-commit general CI and diff/ancestry. Do not mistake the aggregate-only inspector for proof of process quiescence or safe deletion. No actual model inference, owner footage, complete 600-second owner-PC rendering, physical mobile playback or genuine mid-encoding crash is exercised here.

Coordinate with #8 master, #21 async queue, #23 cache/media acceptance, #40 lead, #109/#110/#112 inventory ancestry and Helper 1's concurrent #113 Docker/bearer work. Keep #114 draft until the lead reviews the stacked dependencies. Do not merge automatically.
