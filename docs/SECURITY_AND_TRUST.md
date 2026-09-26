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
