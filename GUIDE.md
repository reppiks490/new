# Getting started: opening and using Character3D Masterbuild

This is a practical walkthrough for running this on your own machine. For
the full capability list see `README.md`; for design/scope notes on each
major subsystem see the `docs/` files (`docs/V13_WORLDS_AND_RENDERING.md`
covers everything added most recently).

## 1. Clone and set up

```bash
git clone https://github.com/reppiks490/new.git character3d
cd character3d
git checkout claude/effort-status-tjzcfd   # or your merged branch, once merged

python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Confirm it's healthy:

```bash
pytest -q -W error
```

You should see `276 passed`. If something fails, your environment differs
from the one this was built in — check the Python version (`>=3.11`) first.

## 2. Configure credentials (all optional)

```bash
cp .env.example .env
```

Open `.env` and fill in whichever of these you actually have:

```
TRIPO_API_KEY=...
MESHY_API_KEY=...
HI3D_API_KEY=...
```

Nothing here is required to run the server or use the local pipeline
(planning, scenes, worlds, terrain, body morphs, QA, rendering, exports).
These three keys unlock the three *live remote generation* endpoints
specifically (section 5 below). Since this environment never had any of
these configured, those endpoints have been tested against their own
logic and against stubbed clients, but never against a real Tripo/Meshy/
Hi3D account — that first real run happens on your machine, not this one.

Load the file before starting the server (or export the variables however
your shell/process manager prefers):

```bash
export $(grep -v '^#' .env | xargs)   # simple one-liner for a bash shell
```

## 3. Run it

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Check it's alive:

```bash
curl http://localhost:8000/health
# {"ok":true,"version":"1.4.0"}

curl http://localhost:8000/v1/runtime/readiness
```

`readiness` is the honest status report: it tells you exactly what's
configured (Blender, OpenUSD `pxr`, each provider's credential) without
ever echoing a credential value back. Read it before assuming a live
generation call will work.

Every route is also browsable at `http://localhost:8000/docs` — FastAPI's
interactive Swagger UI, generated from the actual code, always current.

### Or run it in Docker

```bash
docker build -t character3d-masterbuild .
docker run -p 8000:8000 --env-file .env -v $(pwd)/workspace:/app/workspace character3d-masterbuild
```

## 4. The local pipeline (no credentials needed)

### Plan a character

```bash
curl -X POST http://localhost:8000/v1/plan \
  -H "Content-Type: application/json" \
  -d '{
    "character": {"prompt": "a fictional adventurer", "quality_tier": "hero_offline", "texture_tier": "8k"},
    "hardware": {"vram_gb": 24, "ram_gb": 64, "gpu_vendor": "nvidia"},
    "render_quality_mode": "hero",
    "render_resolution_tier": "8k"
  }'
```

Returns geometry/material budgets, provider routing, and a compiled render
job, all in one response.

Add a reference image to switch routing to image-sourced generation and
get real local pixel analysis (dominant palette, contrast, suggested
texture tier) folded in:

```bash
curl -X POST http://localhost:8000/v1/plan \
  -H "Content-Type: application/json" \
  -d '{"character": {"prompt": "a fictional adventurer"}, "reference_image_path": "/absolute/path/to/reference.png"}'
```

### Generate a world

```bash
curl -X POST http://localhost:8000/v1/world/terrain/generate \
  -H "Content-Type: application/json" \
  -d '{
    "terrain": {"name": "hills", "size_meters": 500, "resolution_power": 8, "height_scale_meters": 80, "seed": 7},
    "output_path": "./workspace/terrain.glb",
    "with_biomes": true
  }'
```

Writes a real, deterministic, biome-colored terrain mesh to
`./workspace/terrain.glb`. For a tiled, streamable world with LOD, see
`app/world/world_grid.py`'s `WorldGridSpec`/`WorldStreamingManager` and
`POST /v1/world/tile/generate`, which takes a `world` (`WorldGridSpec`:
grid dimensions, tile size, world seed) plus `tile_x`/`tile_z`/`lod` and
writes that one tile's mesh to `output_path`.

**Fully textured terrain in one file** — geometry, UVs, and embedded
baseColor / metallicRoughness / normal maps, ready for any glTF viewer or
engine (texture up to 8192):

```bash
curl -X POST http://localhost:8000/v1/world/terrain/generate-textured \
  -H "Content-Type: application/json" \
  -d '{
    "terrain": {"name": "highlands", "size_meters": 1000, "resolution_power": 8, "height_scale_meters": 260, "seed": 11},
    "output_path": "./workspace/highlands.glb",
    "texture_size": 4096
  }'
```

**Standalone texture maps up to 16384×16384** (streamed to disk; ~28 s at
8K, ~2 min at 16K, under 1 GB RAM):

```bash
curl -X POST http://localhost:8000/v1/world/terrain/biome-texture \
  -H "Content-Type: application/json" \
  -d '{
    "terrain": {"name": "highlands", "size_meters": 1000, "resolution_power": 8, "height_scale_meters": 260, "seed": 11},
    "texture_size": 8192,
    "basecolor_path": "./workspace/basecolor.png",
    "roughness_path": "./workspace/roughness.png",
    "normal_path": "./workspace/normal.png"
  }'
```

**Let it pick the best of several seeds** — each candidate is scored on
biome diversity, walkable area and height variety; the winner is exported
and every candidate's score is returned:

```bash
curl -X POST http://localhost:8000/v1/world/terrain/generate-best-of-n \
  -H "Content-Type: application/json" \
  -d '{
    "terrain": {"name": "hills", "size_meters": 500, "resolution_power": 7, "height_scale_meters": 80},
    "candidate_seeds": [1, 2, 3, 4, 5, 6, 7, 8],
    "output_path": "./workspace/best.glb"
  }'
```

`roughness` in a terrain spec is a smoothness exponent: **higher =
smoother**. The default 0.95 gives natural fractal terrain; values near 0.5
are close to noise at vertex scale.

### Live 3D preview

```bash
curl -X POST http://localhost:8000/v1/viz/threejs-scene \
  -H "Content-Type: application/json" \
  -d '{"input_path": "./workspace/best.glb"}'
```

Returns self-contained Three.js scene code (geometry, vertex colors, lights,
orbit camera framed to the mesh) you can drop into any page that provides
`THREE`, `OrbitControls`, `canvas`, `width` and `height`.

### Axis convention

Internally everything is Z-up (like Blender). Every `.glb`/`.gltf` written
is converted to glTF's mandatory Y-up, and every `.glb`/`.gltf` read —
including Tripo/Meshy/Hi3D output — is converted back, so provider
characters stand upright on generated terrain. OBJ/STL/PLY carry no
standard up axis and are treated as Z-up; pass `"up_axis": "y"` for OBJs
exported from Blender with default settings.

### Compose a scene

```bash
curl -X POST http://localhost:8000/v1/scenes/plan \
  -H "Content-Type: application/json" \
  -d '{"scene": {"name": "campsite", "assets": []}, "hardware": {}}'
```

A scene's `assets` reference already-canonical, already-QA'd character/prop
files by their SHA-256 hash — see `app/core/scene_models.py` and
`app/exports/scene_export.py` for the full assembly/export/verify chain.

### Body-proportion morphs

```bash
curl -X POST http://localhost:8000/v1/body-morphs/apply \
  -H "Content-Type: application/json" \
  -d '{
    "input_path": "./workspace/character.glb",
    "output_path": "./workspace/character_morphed.glb",
    "percentages": {"height": 10, "shoulder_width": 20, "waist": -15, "glute_size": 25}
  }'
```

Percentages run -100..100. Region weights are estimated automatically from
the mesh for every region except arms/hands (those depend on pose; supply
them in `region_weights`, one 0-1 value per vertex, if you use
`arm_length`). Provider GLBs work directly: height is read from the file's
real vertical axis.

### Mesh/render QA

```bash
curl -X POST http://localhost:8000/v1/qa/topology -H "Content-Type: application/json" -d '{"path": "./character.obj"}'
curl -X POST http://localhost:8000/v1/render/output/verify -H "Content-Type: application/json" -d '{"resolution_tier": "8k", "output_path": "./render.exr"}'
```

## 5. Live provider generation (needs your API keys)

These three actually call the remote provider, submit a real task, and
poll until it finishes — real network calls, real wall-clock time, real
credit/cost consumption on your provider account.

```bash
# Tripo (text or image)
curl -X POST http://localhost:8000/v1/providers/tripo/generate \
  -H "Content-Type: application/json" \
  -d '{"mode": "text", "prompt": "a fictional adventurer, quad topology, PBR"}'

# Meshy (two-phase preview -> refine, handled for you as one call)
curl -X POST http://localhost:8000/v1/providers/meshy/preview-refine \
  -H "Content-Type: application/json" \
  -d '{"prompt": "a fictional adventurer"}'

# Hi3D (image-to-3D, dense reconstruction)
curl -X POST http://localhost:8000/v1/providers/hi3d/generate \
  -H "Content-Type: application/json" \
  -d '{"image_path": "/absolute/path/to/reference.png", "face_count": 5000000}'
```

If the relevant `*_API_KEY` isn't set, you get a `503` with a clear
message rather than a silent failure or a fabricated result — check
`/v1/runtime/readiness` first if you're unsure what's configured.

Each returns a receipt: `task_id`, the final `status` (`succeeded` /
`failed`), and — on success — a `snapshot` containing the real asset URLs
the provider returned. Nothing here is a mock; if it says `succeeded`,
that's a live provider generation.

## 6. Blender and OpenUSD

Both run live. Blender stages (production export, high→low baking,
localized repair, Cycles rendering) and authoritative USD validation are
exercised by the test suite, not just planned.

**OpenUSD** comes with `pip install -e ".[usd]"` (included in `[dev]` and
the Docker image).

**Blender** can be any real install (`BLENDER_BIN=/path/to/blender`), or
the official `bpy` 5.0.1 build through the bundled CLI shim, which is
what the Docker image and CI use. `bpy` needs Python 3.11 and pins
numpy<2 (this app needs numpy≥2), so it goes in its own venv:

```bash
python3.11 -m venv /opt/blender-bpy
/opt/blender-bpy/bin/pip install bpy==5.0.1
export BLENDER_BIN="$PWD/scripts/blender"      # or: ln -s "$PWD/scripts/blender" /usr/local/bin/blender
# set BLENDER_BPY_PYTHON if the venv lives somewhere other than /opt/blender-bpy
blender --version                              # Blender 5.0.1 (bpy module)
curl http://localhost:8000/v1/runtime/readiness  # blender: live, openusd_pxr: live
```

**Render for real in Cycles** at any tier up to 16K, PNG or EXR, with the
output file opened and checked against the requested resolution:

```bash
curl -X POST http://localhost:8000/v1/render/execute \
  -H "Content-Type: application/json" \
  -d '{
    "source_model": "./workspace/highlands.glb",
    "output_path": "./workspace/highlands_8k.png",
    "vram_gb": 24, "ram_gb": 64,
    "quality_mode": "production",
    "resolution_tier": "8k"
  }'
```

The receipt records the compute device actually used. A requested GPU
backend (OptiX, HIP, oneAPI, Metal) falls back to CPU if it isn't present,
and the receipt says so. `samples_override` trades quality for time;
`camera` and `lighting` take azimuth/elevation/focal length and sun
angle/strength.

## 7. Where to look next

- `README.md` — full capability list, version history (v1.0 through v1.3)
- `docs/V13_WORLDS_AND_RENDERING.md` — scope notes on the most recent
  additions, including what's deliberately left out and why
- `docs/SECURITY_AND_TRUST.md` — the content-filtering boundaries (fixed,
  not configurable)
- `docs/V10_EXECUTION_TRUTH.md` — how this project distinguishes tested-
  but-never-run from actually-verified-live
- `.claude/worklog/BUILD_LOG.md` — a session-by-session build history, if
  you want the full "why" behind any particular design choice
