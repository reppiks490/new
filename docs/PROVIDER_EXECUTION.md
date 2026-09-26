# Provider execution layer (v0.5)

## Trust model

External generation providers are treated as non-canonical producers. A remote task is not accepted into the local character pipeline until its status is normalized, its returned asset is downloaded, and a SHA-256 provenance receipt is stored.

- **Tripo:** task webhooks can be cryptographically verified with the documented `Tripo-Webhook-Signature` HMAC-SHA256 scheme. Signed task results are still downloaded immediately because model URLs are short-lived.
- **Meshy:** webhooks are useful as a wake-up signal, but the pipeline re-queries the official task endpoint before accepting a terminal state.
- **Hi3D/Hitem3D:** callback state is also advisory; the official query-task endpoint is authoritative for ingestion. High-density v3.0 submission uses a 5M -> 2M retry ladder because current docs advertise 5M for `2048master` but retain an older 2M face validation error entry.

## Canonical lifecycle

1. Compile a provider route.
2. Submit task using a provider adapter.
3. Record provider + task ID.
4. Poll or receive callback.
5. Independently query terminal state when required.
6. Immediately download expiring assets from trusted provider domains.
7. Hash the bytes and write asset provenance.
8. Inspect geometry/material quality locally.
9. Score candidates with provider-neutral metrics.
10. Promote the best candidate into the Blender/USD canonical post-process path.

## Candidate scoring

The first scoring layer intentionally rewards measured output quality rather than a provider brand: target density, manifoldness, degenerate-face cleanliness, UV coverage, PBR completeness, texture resolution, rig readiness, source similarity, and optional portrait specialization.

This is not a learned quality model yet. v0.5 now adds local topology inspection and measured candidate promotion. Rendered multi-view similarity and perceptual/material QA remain next-stage work.
