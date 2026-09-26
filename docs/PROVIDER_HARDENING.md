# Provider hardening and local admission (v0.5)

Provider outputs are untrusted inputs until local admission completes.

## Network and asset rules

- Only HTTPS provider asset hosts on the provider allow-list may be fetched.
- Redirect targets are checked again after redirect resolution.
- Assets stream into `.part` files with hard byte caps rather than being buffered as multi-GB responses in RAM.
- A `Content-Length` above the configured cap is rejected before body ingestion when available.
- SHA-256 is calculated while streaming; an expected digest, when supplied, must match before the file is atomically promoted.
- Partial files are removed on any exception.

## Task/callback authority

- Tripo task webhooks can become authoritative because the documented HMAC-SHA256 signature and replay window are verified, with delivery-id deduplication.
- Meshy webhooks and Hi3D callbacks are treated as wake-up/advisory events; terminal state must be independently re-queried from the official task API before asset ingestion.
- SQLite stores normalized task state, asset receipts and first-seen webhook deliveries.

## Local geometry admission

The first local inspector uses `trimesh`/NumPy and measures:

- vertex and triangle counts;
- connected components;
- watertightness and winding consistency;
- fraction of unique edges with exactly two incident triangles (manifold edge ratio);
- degenerate triangle ratio using a scale-aware area threshold;
- UV-set presence;
- bounding-box diagonal, surface area and watertight volume.

These measurements feed the provider-neutral candidate scorer. Provider brand is not a scoring input.

## Still pending

Self-intersection detection, UV atlas occupancy/overlap, texel-density consistency, tangent quality, PBR map inspection, perceptual multiview similarity, skin/hair-specific QA and Blender-rendered comparison remain future layers.
