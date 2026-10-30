# Helper Bot 2 — fail-closed engine capability declaration preflight

## Scope

Implementation: `app/video/cinematic_capability_preflight.py`  
Tests: `tests/test_cinematic_malformed_capabilities.py`  
Integration parent: Helper Bot 2 PR #16 (`chatgpt/helper2-capability-integration-20261022`).

The engine capability preflight is *read-only*. It is intended for provider
metadata supplied by trusted engine adapters and a persisted cinematic project.
It must not crash, disclose provider values or produce a passing compatibility
result when `EngineCapabilities.model_copy(update=...)` or an in-memory project
edit bypasses ordinary Pydantic validation.

## Additional fail-closed diagnostics

All codes are stable, value-free, and independent of secrets:

| Finding | Cause |
|---|---|
| `ENGINE_AVAILABILITY_DECLARATION_INVALID` | The `available` field is not a boolean |
| `ENGINE_PROFILES_DECLARATION_INVALID` | Engine profiles missing, malformed, or unsupported |
| `ENGINE_CAMERA_PRESETS_DECLARATION_INVALID` | The camera preset list is malformed or includes unsupported labels |
| `ENGINE_MOTION_SUPPORT_DECLARATION_INVALID` | The motion-strength support field is not a boolean |
| `ENGINE_FPS_DECLARATION_INVALID` | FPS catalog is not a nonempty integer sequence of positive values |
| `ENGINE_RESOLUTION_DECLARATION_INVALID` | Resolution catalog malformed or not supported by the current VideoGenerationRequest |
| `ENGINE_DURATION_DECLARATION_INVALID` | Duration bounds are malformed, nonfinite, nonpositive or reversed |
| `PROJECT_DELIVERY_FPS_INVALID` | Unvalidated project FPS is outside the cinematic project contract |
| `PROJECT_DELIVERY_RESOLUTION_INVALID` | Unvalidated project delivery resolution is outside the cinematic project contract |
| `SHOT_DURATION_UNSUPPORTED` | Individual shot duration is malformed or incompatible |

These declarations generate **blocking errors**. A malformed global engine
declaration means `compatible_shots == 0`, even when every shot looks
otherwise valid. A malformed individual shot duration blocks only that shot
(and leaves compatible shots counted correctly).

An empty camera preset list is valid: it means the engine offers no presets.
An empty engine profile or FPS list is not valid for declaring shot compatibility.
The audit accepts explicitly valid nonempty lists or tuples, but does not
coerce arbitrary strings into collections or Boolean values into integers.

## Evidence and boundaries

All tests use `FakeVideoEngine` and synthetic in-memory project metadata.
No API calls, actual user prompts, media reads, FFmpeg runs, GPU usage,
external-provider fees or storage writes are required. Results contain only
finding codes, counts, an opaque project ID and opaque scene/shot IDs.

Provider declarations are an **untrusted snapshot**, not proof of current
engine installation, runtime availability, GPU capability, video quality,
source rights, playable media or owner-phone readiness.

The report is advisory and does **not** authorize a render request. Lead and
other helpers retain ownership of service selection, real-media acceptance,
auth/privacy, editorial EDL and immutable output provenance. No automatic
integration or merge is requested.
