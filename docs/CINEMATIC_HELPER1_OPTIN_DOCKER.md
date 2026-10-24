# Helper 1 — opt-in cinematic Docker candidate (review only)

The repository's default `Dockerfile` intentionally continues to serve the
Character3D API. The isolated `Dockerfile.cinematic` is a **separate proposal**:
it runs `app.studio.server:app` with distro FFmpeg/ffprobe, under UID/GID
10001, and writes private studio state under `/app/workspace/studio`.

## Test-first motivation

The predecessor Helper 1 [draft #101](https://github.com/reppiks490/new/pull/101)
established that the default image's generic `/health` is not cinematic
acceptance: its opt-in strict contract failed the studio identity check,
private project-route check, and missing FFmpeg check, after a successful
real image build and offline boot. Ordinary CI remained green. Do not
reinterpret this as a defect in the existing Character3D Docker target.

This stacked candidate **reuses the exact same contract script** from #101,
without relaxing any assertion, and adds a new isolated Dockerfile plus
Python 3.11/3.12 opt-in image verification workflow. Each job must build
the real image, boot it with `--network none`, no host ports, no owner
mounts, no credentials, a read-only root and temporary writable scratch,
and check actual studio identity, private route, synthetic H.264 encoding,
FFprobe frame count/codec, full FFmpeg decode, and SHA-256.

## Boundaries and release requirements

- **No default Dockerfile change**, no migration, no deployment, no paid
  model service, no private owner media. This is a draft engineering
  candidate, not an assertion that cinematic Docker is a supported product.
- The opt-in image contains no local GPU generation runtime. Passing
  synthetic FFmpeg acceptance cannot prove 600-second inference, owner-PC
  throughput, phone playback, or complete film continuity.
- No token is provided in the offline CI test. For any remote studio
  access, configure `CHARACTER3D_STUDIO_TOKEN`, TLS/reverse-proxy controls,
  trusted hosts and approved origins. The separate trusted-Host production
  correction proposed in Helper 1 #96 still requires lead review; this
  Docker proposal **does not** integrate or resolve that security blocker.
- A persistent private workspace, file ownership, backup/recovery policy,
  image provenance and vulnerability scanning need owner/lead review before
  considering real deployment. The CI instance is intentionally ephemeral.
- The lead must decide whether cinematic Docker should be supported at all;
  a host-only studio is a valid alternative. Do not merge either proposal
  without a reviewed decision and exact integrated-head CI.
