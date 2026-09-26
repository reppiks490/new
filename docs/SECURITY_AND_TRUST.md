# Security and Trust Boundaries

## Blender execution

- Headless workers launch with `--disable-autoexec` by default.
- Embedded scripts/drivers from untrusted `.blend` files are not implicitly trusted.
- The Character3D worker script is supplied explicitly with `--python`.
- Job manifests are JSON, versioned and hashed for reproducibility.
- Capability-pack files may declare SHA-256 digests for installation verification.

## Generated/imported assets

Future import adapters should treat mesh, USD, FBX, GLTF, image and archive inputs as untrusted data. Validate paths, reject traversal, constrain extraction roots, cap decompressed sizes, and do not execute embedded content.

## Adult fictional mode

Policy checks occur before any downstream external or local generation adapter is invoked. Explicit mode is restricted to fictional adults and retains the hard exclusions documented in the main architecture.

## Content filtering (`app/core/content_filters.py`)

Prompt-text safety patterns (minor-sexual-content, non-consensual-content, real-person-sexual-content, and a generic NSFW signal) are centralized in one module rather than duplicated per spec type. Two categories — **minor sexual content** and **non-consensual sexual content** — are unconditionally hard-blocking (`HARD_BLOCK_CATEGORIES`) wherever they are detected, independent of mode, quality tier, or any other flag. This is enforced in two places:

- `app/core/policy.py` — `CharacterSpec.mode == ADULT_FICTIONAL` (stricter: any minor-referencing term blocks outright, since the whole mode is already an explicit/adult path).
- `app/core/scene_policy.py` — every `SceneSpec.prompt` and asset `display_name` (scene composition previously had **no content filtering at all**, since it only references already-generated, already-policy'd assets by hash; this closed that gap).

These hard-block categories are not configurable, not bypassable by a mode flag, and are not to be removed or weakened — that boundary is intentional and permanent, independent of any other instruction given to an agent working on this repository.
