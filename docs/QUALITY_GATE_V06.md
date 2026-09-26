# v0.6 production quality gate

A provider output is not final merely because generation succeeded. v0.6 adds local admission checks before hero refinement or export.

## Geometry
- local triangle/vertex/topology metrics from v0.5 remain mandatory;
- UV presence is supplemented with occupancy and texel-density variation estimates;
- broad-phase non-adjacent triangle overlap localizes regions that require exact self-intersection testing in Blender/a robust geometry kernel;
- the broad-phase report is intentionally labeled a candidate detector and never claims exact self-intersection.

## Materials
PBR maps are assigned explicit semantics. Base color is expected in sRGB. Normal, roughness, metallic, AO, height/displacement, SSS and opacity are data maps expected as Non-Color. Hero displacement is expected at >=16-bit; the canonical hero bake plan uses 32-bit displacement.

## UDIM bake compiler
The bake compiler creates deterministic 2K/4K/8K pass specifications, margins, sample budgets, bit depth and color-space intent. Raw memory estimates are emitted before baking so scheduling can avoid accidental VRAM/RAM exhaustion.

## Render profiles
Cycles profiles are now separated into preview, production, hero and extreme tiers. VRAM modifies sample ceilings, dicing rate, tile size and texture limits without pretending that VRAM alone predicts scene residency.

## Restart/resume
Provider state is read from the durable SQLite ledger. Missing tasks submit, non-terminal tasks poll, successful tasks with incomplete local provenance ingest, verified successful tasks complete, and failed/cancelled tasks stop rather than duplicating paid jobs.

## Provenance
The JSONL provenance chain links each event to the prior event hash. This detects modification/reordering/deletion within the retained chain. It is a tamper-evident integrity chain, not a cryptographic identity signature; external signing/attestation remains a later layer.
