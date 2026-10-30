# Helper 1 — cinematic Docker acceptance boundary (2026-10-24)

## Why this is a separate strict gate

The existing repository `.github/workflows/ci.yml` Docker job builds the default
`Dockerfile`, boots `uvicorn app.main:app`, and checks only HTTP `/health`.
That endpoint returns `{"ok":true,"version":"1.5.0"}` for the generic
Character3D application. The long-form cinematic private studio is a *different*
ASGI app, `app.studio.server:app`, with `/health` returning `studio:true`
and private `/api/video/projects` routes. Therefore a green default Docker
job does **not** establish that a Docker container serves the cinematic system.

This opt-in QA branch does **not** change Docker defaults, expose ports,
modify lead-owned server/router/queue, or claim the 3D API's container is broken.
It makes the distinction measurable for a cinematic Docker release gate.

## Contract and safety

The dedicated workflow builds the actual Dockerfile with `WITH_BLENDER=0`,
boots an ephemeral container with `--network none`, no host ports, no owner
mounts and no secrets, then executes the standalone standard-library contract
*inside the container*. It requires:

1. `/health` identifies the cinematic studio, not the generic 3D API.
2. A genuine loopback `GET /api/video/projects` is served (HTTP 200).
3. Container-local FFmpeg/libx264 generates a 12-frame synthetic blue H.264
   MP4; FFprobe confirms codec, dimensions and decoded frame count; FFmpeg
   completes a full decode and the output has a SHA-256 digest.

A failed contract is an intentionally red **cinematic Docker readiness** result,
not evidence that the generic 3D container is unhealthy. This gate does not
test owner PC hardware, paid inference, mobile playback, private footage, or
long-form 600-second assembly.

## Owner decision required before any production correction

Choose whether cinematic delivery needs a separate Docker target/entrypoint,
or remains an explicitly host-only `uvicorn app.studio.server:app` service.
If Docker support is desired, the lead should implement a separately secured
cinematic container with FFmpeg and validate the final integrated SHA, preserving
the generic 3D container and local/token-auth boundaries. Do not change
`Dockerfile` or the existing CI smoke test just to make this red gate green.
