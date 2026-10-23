# Image-to-film acceptance target — 2026-10-23

The owner requested image upload plus prompted filmmaking, with a current maximum
of ten minutes, selectable duration/FPS/resolution, very high reference fidelity,
and a result demonstrably better than their WAN 3.0 benchmark. They explicitly
asked to continue until a usable build is proven. This is a requirement record
and an evidence gate, not a claim that the target has been achieved.

## Current implementation and observed limits

This continuation uses the frozen cinematic integration snapshot
`2c771a134e7153c7498c1d9d3529e5574b695ca7` in an isolated worktree. Other source
branches and open validation/provenance proposals remain unchanged.

- `cinematic_models.py`, `cinematic_service.py`, and `cinematic_assembly_jobs.py`
  now limit new edits and actual shot timelines to **600 seconds** before work.
  Existing overlong persisted documents remain readable so the owner can shorten
  them explicitly. No old project is silently trimmed or deleted.
- The current production adapter is `ltx25_local`, pinned by
  `app/video/adapters/ltx25.py`. It advertises **24 FPS**, up to 30 seconds per
  generated shot, and 480p/720p/1080p tiers subject to runtime/VRAM checks.
  Its source conditioning is applied at frame zero with strength 0.8; this is
  not a guarantee of preserved identity/anatomy across generated frames.
- Delivery targets allow up to **2160p / 120 FPS**. The master assembler can
  rescale and convert frame rate; these operations do not prove native 4K
  detail or 120 distinct generated motion frames per second.
- Long projects use short generated shots plus editorial assembly. Prompt
  packing has a 2,000-character engine boundary and can condense intent;
  authored lenses/framing/reference metadata are not all forwarded as native
  model controls. Those limits must remain visible in any precision claim.
- Runtime probe executed here: **no NVIDIA GPU, no CUDA model runtime, no local
  model weights, engine unavailable**. FFmpeg and FFprobe are available.
- WAN 3.0 superiority has not been tested or established. Primary-source
  benchmark research was blocked by an exhausted Firecrawl account and a
  Tavily connection requiring reauthentication; neither result is evidence of
  a model capability or benchmark win.

The published GitHub Pages address is currently a 3D browser studio. Loading
that website, viewing a GLB, passing mock tests, or assembling synthetic clips
does not prove image-to-video generation. Do not relabel it as a completed
filmmaking system or replace it with an unvalidated integration.

## Required proof before a fully capable filmmaking link

1. A reachable, authenticated rendering backend with known GPU/VRAM, model
   revision, installed weights and working generation/encoding tools. Use the
   owner's NVIDIA worker by default; cloud spending requires an explicit budget.
2. A real owner-approved test image and prompt submitted through the same phone
   UI and API that will be delivered. Capture an actual generated short clip,
   execution identity and hashes; a fixture engine cannot satisfy this gate.
3. A generated/edited project at up to 600 seconds, with verified source-image
   bytes and shot/render-input freshness, resumable jobs, and private retrieval.
   Reconcile the outstanding render-provenance and client reconnect proposals
   on the exact combined commit before sign-off.
4. The resulting MP4 fully decodes; FFprobe confirms actual dimensions, FPS,
   duration and frame count against the requested delivery. Clearly identify
   rescaling, repeated frames or interpolation separately from native generation.
5. Shot-by-shot review of action compliance, identity, anatomy, continuity and
   unwanted changes. Generic prompts and negative constraints cannot guarantee
   zero duplicated limbs or perfect execution of arbitrary imagined actions.
   A quality check must not claim it can prove that guarantee automatically.
6. A defined, like-for-like WAN comparison using the same source image/prompt
   and a recorded evaluation method. Until outputs exist and are compared,
   “beyond WAN 3.0”, “maximum precision” and “peak performance” are goals.
7. Actual iPhone playback/reconnect testing and fresh Python 3.11/3.12, browser
   and Docker checks on the final deployed commit.

## Verification and continuation

The baseline core checks passed 28 tests. The first five new duration tests
failed before the policy change. The updated duration-focused suite passes
seven Python tests plus two browser tests. A broader video/cinematic check
passed 290 Python tests, including real short synthetic FFmpeg media checks;
the browser suite passed 54 tests, including the two new duration tests.
These counts do not demonstrate live model inference or a generated ten-minute
film.

The owner was asked asynchronously which rendering backend can be used: their
NVIDIA PC plus private worker URL, a cloud GPU plus spending limit, or no existing
backend. Live generation and deployment proof depend on that answer. Do not
invent an endpoint, spend on an unapproved GPU, or substitute a fake render.

Knowledge delta lives in this acceptance record and the existing progress
ledger; no dependency, new deployment, provider call, schema migration, or
separate skill/router layer was introduced. Current native/control limits are
canonical in the adapter and capability/preflight modules, not this prose.
Revisit this record when the engine, backend, quality acceptance, duration policy,
or benchmark changes.
