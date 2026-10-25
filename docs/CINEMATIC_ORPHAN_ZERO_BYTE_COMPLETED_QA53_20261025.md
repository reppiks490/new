# Character3D QA53 — zero-byte completed MP4 inventory integrity

## Frozen ancestry and ownership
Draft #116 is based on QA52 #114 exact commit `0d1485d52f7b2e5314b07571deec6fea1db176ac`, stacked on QA51 #112, QA50 #110, QA49 #109, and lead #40. Only the previously QA49–QA52-owned read-only inspector is amended; the three new QA53 paths are this handoff, dedicated tests and CI. No production service, queue worker, mobile UI, Docker image or Helper 1 files are changed.

## Reproduced diagnostic gap
A `video_master` with `status=ready` or a `video_job` with `status=succeeded` can refer to a UUID-named, zero-byte regular MP4. Prior inventory counts it as present, so `missing_completed_mp4_ids=0` and `candidate_inventory_not_quiescent=false` could be returned despite impossible MP4 decoding. This is an **offline diagnostic integrity gap**, not evidence that owner media is corrupted. The inspector does not inspect MP4 contents or perform actual decoding.

**Test-first RED:** [QA53 workflow 40166199771](https://github.com/reppiks490/new/actions/runs/40166199771), on test-only commit `24c28fffd4ee1d443b8539ff819bbd4373d6a4e2`: **four expected new test failures and 25 inherited passes** on Python 3.11 and 3.12. Failures were missing `zero_byte_completed_mp4_files` output key; setup and inherited real synthetic FFmpeg tests passed. No skipped tests counted as passes.

## Minimal read-only correction
While collecting metadata through `lstat()`, count completed UUID MP4s whose `st_size == 0` in `zero_byte_completed_mp4_files` and treat a positive count as an inventory uncertainty blocker. Untracked zero-byte MP4s remain candidates under the preexisting small-candidate count; nonempty completed media remains unaffected. The existing QA51 contract for *missing* completed media remains unchanged. No private filenames, IDs, paths, prompts or credentials appear in output; `safe_to_delete_automatically=false` is unconditional.

## Verification and limits
Dedicated QA53 matrix runs strict inherited QA49–QA52 and four QA53 tests on Python 3.11/3.12, including genuine **short synthetic** FFmpeg H.264 inherited acceptance. General CI must pass on the final exact commit; preserve draft until verified and lead reviews. This is not proof of a running encoder's absence, owner-PC filesystem correctness, actual model inference, long-form 600-second rendering, or physical mobile playback. No cleanup, merges, deployment, paid services, cloud generation, ICARUS or ChatGPT automation changes.

## Coordination
#8 master assembly; #21 durable async queue; #23 cache/media acceptance; #40 lead; #109/#110/#112/#114 inspector ancestry; #115 concurrent Helper 1 authenticated Docker/real-media tests. These branches are not merged or overwritten.
