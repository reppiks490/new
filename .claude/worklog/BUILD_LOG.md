# Build log — character3d-masterbuild v1.2

Terse running log of what's been done, so chat replies can stay short.
Full detail lives here, not repeated in conversation.

## Session: initial build to spec

- Verified uploaded zip against Ed25519 signature manifest: SHA-256 match confirmed.
- Extracted archive into repo root (143 files: app/, tests/, docs/, scripts/, config/).
- Fixed `pyproject.toml`: setuptools flat-layout auto-discovery failed with
  multiple top-level dirs (app/config/blender_scripts) → added
  `[tool.setuptools.packages.find] include = ["app", "app.*"]`.
- Created `.venv`, installed project editable + dev deps.
- Pinned `starlette>=0.40,<1.0` in pyproject — environment's latest starlette
  (1.7.0) requires a nonexistent `httpx2` package under `-W error`.
- Pinned `anyio==4.3.0` in venv — anyio 4.15.1 emits a hard
  `BlockingPortal` deprecation warning under `-W error` during fastapi
  testclient import.
- Remaining before 114/114 green: `scipy` is used transitively by
  `trimesh` (mesh connected-components / body_count) but not declared as
  a dependency. 8 tests fail with `ModuleNotFoundError: No module named
  'scipy'`. Fix: add `scipy` to `pyproject.toml` dependencies, reinstall,
  rerun full suite.

- Also added `networkx` (trimesh's `repair.fill_holes` needs it; undeclared).
- Result: **114/114 passed, `-W error`** — matches README's stated v1.2
  regression status exactly.

## Final dependency additions to pyproject.toml

- `starlette>=0.40,<1.0` (pin — avoids httpx2 hard dependency in starlette 1.x)
- `scipy>=1.13` (trimesh mesh connectivity/body_count)
- `networkx>=3.3` (trimesh hole-filling/repair)

Note: `anyio==4.3.0` pin is currently venv-only (installed, not declared in
pyproject) — anyio 4.15.1 raises a hard BlockingPortal deprecation warning
under `-W error` via starlette's testclient. Not yet added as an explicit
constraint; a fresh `pip install -e .[dev]` on an unpinned resolver could
pull anyio 4.15+ again and fail collection. Should add
`anyio>=4.0,<4.4` (or similar) to `[project.optional-dependencies].dev` —
flagging, not yet done.

- Added `anyio>=4.0,<4.4` to `[project.optional-dependencies].dev` — closes
  the gap above; pin is now declared, not just present in the working venv.
- Added `.gitignore` (.venv/, __pycache__/, build artifacts, pytest cache).
- Verified from clean room: fresh `.venv2` + `pip install -e ".[dev]"` +
  `pytest -q -W error` → **114/114 passed**, using only pyproject.toml
  (no manual post-install pins). Confirms the fix is real, not
  venv-specific happenstance.

## Status: build complete, committed and pushed

All four packaging/dependency gaps between the shipped source and a clean
install closed:
1. setuptools flat-layout multi-package discovery
2. starlette pin (avoid httpx2 hard dep in 1.x)
3. scipy (trimesh transitive, undeclared)
4. networkx (trimesh transitive, undeclared)
5. anyio dev pin (avoid BlockingPortal deprecation under -W error)

Spec target (README): 114 tests passing, warnings as errors. Met exactly.
