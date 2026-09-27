from __future__ import annotations

"""Executes a compiled RenderJobSpec in real Blender/Cycles and verifies the
file it produced. compile_render_job decides "how good" (CyclesPreset) and
"how big" (RenderOutputSpec); this turns that plan into pixels on disk.
"""

import json
import math
from pathlib import Path

from pydantic import BaseModel, Field

from app.render.job import RenderJobSpec
from app.render.output_verification import RenderOutputVerification, verify_render_output
from app.workers.blender import BlenderInvocation, execute, find_blender

WORKER_SCRIPT = Path(__file__).resolve().parents[2] / "blender_scripts" / "render_scene.py"
_FORMATS = {".png": "PNG", ".exr": "OPEN_EXR"}


class CameraSpec(BaseModel):
    azimuth_deg: float = -50.0
    elevation_deg: float = 32.0
    distance_factor: float = Field(default=1.25, gt=0)
    focal_length_mm: float = Field(default=35.0, gt=0)


class LightingSpec(BaseModel):
    sun_elevation_deg: float = Field(default=16.0, ge=-5, le=90)
    sun_rotation_deg: float = 200.0  # low raking light: relief and canopy read in 3D
    sun_strength: float = Field(default=3.0, ge=0)  # tuned on real renders: 0% clipped
    sky_strength: float = Field(default=0.15, ge=0)
    # aerial perspective volume, 1/m (0 = off). 1.5e-4 -> 6.7 km mean free path
    atmosphere_density_per_m: float = Field(default=1.5e-4, ge=0, le=0.05)  # 4.0/0.6 clipped 5.1% of pixels


class VegetationSpec(BaseModel):
    """Instanced 3D trees scattered from the terrain's vegetation sidecar.
    Leaves are individual translucent cards, so canopies have real gaps."""
    enabled: bool = True
    forest_density_per_m2: float = Field(default=1 / 30, ge=0, le=1)
    plains_density_per_m2: float = Field(default=1 / 400, ge=0, le=1)
    seed: int = 7


class CyclesRenderResult(BaseModel):
    returncode: int
    receipt: dict
    verification: RenderOutputVerification
    stderr_tail: str = ""

    @property
    def passed(self) -> bool:
        return self.returncode == 0 and self.receipt.get("status") == "succeeded" and self.verification.meets_or_exceeds_spec


DEFAULT_MICROPOLYGON_BUDGET = 6_000_000  # measured ~1 KB/micropolygon over a ~6 GB base: fits 16 GB
ASSUMED_FRAME_COVERAGE = 0.8


def effective_dicing_rate(job: RenderJobSpec, *, micropolygon_budget: int, override: float | None = None) -> tuple[float, dict]:
    """Adaptive-subdivision dicing rate in pixels. The quality preset's rate
    (e.g. 0.75 px for hero) is used unless the micropolygons it would create
    over the frame exceed the budget -- at 16K a 0.75 px rate means ~190M
    micropolygons, far past what a CPU box holds -- in which case the rate is
    raised just enough to fit, and the receipt records that."""
    frame = job.output.full_width * job.output.full_height * ASSUMED_FRAME_COVERAGE
    requested = override if override is not None else job.quality.subdivision_dicing_rate
    floor = (frame / micropolygon_budget) ** 0.5
    rate = max(requested, floor)
    return rate, {"requested_px": requested, "budget_floor_px": round(floor, 4), "micropolygon_budget": micropolygon_budget,
                  "estimated_micropolygons": int(frame / rate ** 2)}


OFFSCREEN_DICING_SCALE = 64.0  # Cycles default 4: terrain under/behind a low camera otherwise dices finely


def texel_limited_subdivisions(displacement: dict | None, *, fallback: int = 12) -> int:
    """Subdivision levels past 2 micropolygons per displacement texel add no
    detail -- the map has nothing finer -- but near a low camera Cycles keeps
    dicing to the cap (measured: 8.7 GB at the default camera vs >13.9 GB,
    OOM, at a low one with the old cap of 12 = 4096 cuts per base quad)."""
    if not displacement or not displacement.get("base_grid"):
        return fallback
    texels_per_quad = displacement["resolution"] / (displacement["base_grid"]["vertices_per_side"] - 1)
    return max(1, min(fallback, math.ceil(math.log2(max(texels_per_quad, 1.0))) + 1))


def find_displacement_sidecar(source_model: str | Path) -> dict | None:
    from app.world.textured_terrain import DISPLACEMENT_SCHEMA, displacement_sidecar_paths

    png, meta_path = displacement_sidecar_paths(source_model)
    if not meta_path.is_file():
        return None
    meta = json.loads(meta_path.read_text())
    base = meta.get("base_grid") or {}
    heights = meta_path.with_name(base.get("heights_file", ""))
    if (meta.get("schema") != DISPLACEMENT_SCHEMA or meta.get("kind") != "terrain_base_grid"
            or not png.is_file() or not base or not heights.is_file()):
        raise ValueError(f"invalid displacement sidecar next to {source_model}")
    return {
        "path": str(png.resolve()), "resolution": int(meta["resolution"]), "min_m": float(meta["min_m"]), "max_m": float(meta["max_m"]),
        "water_level_m": meta.get("water_level_m"),
        "vegetation_path": str(meta_path.with_name(meta["vegetation"]["image"]).resolve()) if meta.get("vegetation") else None,
        "base_grid": {"heights_path": str(heights.resolve()), "vertices_per_side": int(base["vertices_per_side"]),
                      "size_meters": float(base["size_meters"])},
    }


def compile_cycles_render_manifest(
    job: RenderJobSpec,
    source_model: str | Path,
    output_path: str | Path,
    *,
    camera: CameraSpec | None = None,
    lighting: LightingSpec | None = None,
    samples_override: int | None = None,
    use_displacement: bool = True,
    dicing_rate_override: float | None = None,
    micropolygon_budget: int = DEFAULT_MICROPOLYGON_BUDGET,
    max_subdivisions: int | None = None,
    vegetation: VegetationSpec | None = None,
) -> dict:
    out = Path(output_path)
    fmt = _FORMATS.get(out.suffix.lower())
    if fmt is None:
        raise ValueError("render output must be .png or .exr")
    if fmt == "PNG" and job.output.bit_depth > 16:
        raise ValueError("PNG supports at most 16-bit output; use .exr for 32-bit float")
    if samples_override is not None and samples_override < 1:
        raise ValueError("samples_override must be >= 1")
    quality = job.quality.model_dump()
    if samples_override is not None:
        quality["samples"] = samples_override
    if dicing_rate_override is not None and dicing_rate_override <= 0:
        raise ValueError("dicing_rate_override must be > 0")
    if micropolygon_budget < 1:
        raise ValueError("micropolygon_budget must be >= 1")
    displacement = find_displacement_sidecar(source_model) if use_displacement else None
    if max_subdivisions is None:
        max_subdivisions = texel_limited_subdivisions(displacement)
    veg = vegetation or VegetationSpec()
    vegetation_manifest = None
    if veg.enabled and displacement and displacement.get("vegetation_path") and Path(displacement["vegetation_path"]).is_file():
        vegetation_manifest = {"path": displacement["vegetation_path"], **veg.model_dump(exclude={"enabled"})}
    rate, dicing = effective_dicing_rate(job, micropolygon_budget=micropolygon_budget, override=dicing_rate_override)
    return {
        "schema": "character3d-cycles-render-v1",
        "displacement": displacement,
        "vegetation": vegetation_manifest,
        "atmosphere_density_per_m": (lighting or LightingSpec()).atmosphere_density_per_m if displacement else 0.0,
        "subdivision": {"dicing_rate_px": rate, "max_subdivisions": max_subdivisions,
                        "offscreen_dicing_scale": OFFSCREEN_DICING_SCALE, **dicing},
        "source_model": str(Path(source_model).resolve()),
        "output_path": str(out.resolve()),
        "receipt_path": str(out.resolve().with_suffix(out.suffix + ".receipt.json")),
        "file_format": fmt,
        "quality": quality,
        "output": job.output.model_dump(mode="json"),
        "camera": (camera or CameraSpec()).model_dump(),
        "lighting": (lighting or LightingSpec()).model_dump(),
    }


STRIP_PIXEL_LIMIT = 7680 * 4320  # largest single frame proven to fit 16 GB (8K)
STRIP_OVERLAP_ROWS = 32  # denoiser context either side of every seam


def plan_strips(height: int, width: int, pixel_limit: int = STRIP_PIXEL_LIMIT) -> list[tuple[int, int, int, int]]:
    """(core_y0, core_y1, render_y0, render_y1) row ranges, top-down. A 32K
    frame (531M pixels, 8.5 GB for one float RGBA buffer) cannot be held by
    one Cycles process on 16 GB, so it is rendered as horizontal strips --
    same camera, so dicing and sampling match -- each with overlap rows the
    denoiser sees but the stitcher discards."""
    n = max(1, math.ceil(height * width / pixel_limit))
    cuts = [round(i * height / n) for i in range(n + 1)]
    return [(c0, c1, max(0, c0 - STRIP_OVERLAP_ROWS) if n > 1 else 0, min(height, c1 + STRIP_OVERLAP_ROWS) if n > 1 else height)
            for c0, c1 in zip(cuts, cuts[1:])]


def _run_worker(blender: str, manifest: dict, timeout_seconds: int):
    out = Path(manifest["output_path"])
    manifest_path = out.with_suffix(out.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    receipt_path = Path(manifest["receipt_path"])
    receipt_path.unlink(missing_ok=True)
    invocation = BlenderInvocation(
        executable=blender,
        args=["--background", "--disable-autoexec", "--python", str(WORKER_SCRIPT), "--", "--manifest", str(manifest_path)],
    )
    cp = execute(invocation, timeout_seconds=timeout_seconds)
    receipt = json.loads(receipt_path.read_text()) if receipt_path.is_file() else {"status": "failed", "error": "worker wrote no receipt"}
    return cp, receipt


def _run_strips(blender: str, manifest: dict, strips, bit_depth: int, timeout_seconds: int):
    import numpy as np

    from app.world.biome_texture_synthesis import StreamingPNGWriter

    out = Path(manifest["output_path"])
    width, height = (manifest["output"]["width"] + 2 * manifest["output"]["overscan_px"],
                     manifest["output"]["height"] + 2 * manifest["output"]["overscan_px"])
    receipts, cp = [], None
    for i, (c0, c1, r0, r1) in enumerate(strips):
        strip_png = out.with_name(f"{out.stem}.strip{i:02d}.png")
        m = dict(manifest, output_path=str(strip_png), receipt_path=str(strip_png) + ".receipt.json",
                 strip={"y0": r0, "y1": r1, "raw_path": str(strip_png.with_suffix(".npy"))})
        cp, r = _run_worker(blender, m, timeout_seconds)
        receipts.append(r)
        if cp.returncode != 0 or r.get("status") != "succeeded":
            return cp, dict(r, status="failed", error=f"strip {i} failed: {r.get('error')}", strips_done=i)
        if r["strip"]["rows"] != r1 - r0 or r["strip"]["width"] != width:
            return cp, dict(r, status="failed", error=f"strip {i} is {r['strip']['width']}x{r['strip']['rows']}, expected {width}x{r1 - r0}")
    writer = StreamingPNGWriter(out, width, height, 3, bit_depth=16 if bit_depth >= 16 else 8)
    try:
        for (c0, c1, r0, _r1), r in zip(strips, receipts):
            rows = np.load(r["strip"]["raw_path"], mmap_mode="r")[c0 - r0:c1 - r0]
            for b in range(0, len(rows), 256):
                band = np.asarray(rows[b:b + 256])
                writer.write_rows(band if bit_depth >= 16 else (band >> 8).astype(np.uint8))
    finally:
        writer.close()
    for r in receipts:
        Path(r["strip"]["raw_path"]).unlink(missing_ok=True)
        strip_png = Path(r["output_path"])
        for leftover in (strip_png, Path(str(strip_png) + ".receipt.json"), Path(str(strip_png) + ".manifest.json")):
            leftover.unlink(missing_ok=True)
    receipt = dict(receipts[0], resolution=[width, height], output_path=str(out),
                   render_seconds=round(sum(r["render_seconds"] for r in receipts), 2),
                   strips=[{"core_rows": [c0, c1], "rendered_rows": [r0, r1], "render_seconds": r["render_seconds"]}
                           for (c0, c1, r0, r1), r in zip(strips, receipts)])
    receipt.pop("strip", None)
    Path(manifest["receipt_path"]).write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return cp, receipt


def run_cycles_render(
    job: RenderJobSpec,
    source_model: str | Path,
    output_path: str | Path,
    *,
    camera: CameraSpec | None = None,
    lighting: LightingSpec | None = None,
    samples_override: int | None = None,
    use_displacement: bool = True,
    dicing_rate_override: float | None = None,
    micropolygon_budget: int = DEFAULT_MICROPOLYGON_BUDGET,
    vegetation: VegetationSpec | None = None,
    strip_pixel_limit: int = STRIP_PIXEL_LIMIT,
    blender_executable: str | None = None,
    timeout_seconds: int = 6 * 60 * 60,
) -> CyclesRenderResult:
    source = Path(source_model)
    if not source.is_file():
        raise FileNotFoundError(source)
    blender = find_blender(blender_executable)
    if blender is None:
        raise RuntimeError("Blender is not available (set BLENDER_BIN or put `blender` on PATH)")
    manifest = compile_cycles_render_manifest(
        job, source, output_path, camera=camera, lighting=lighting, samples_override=samples_override,
        use_displacement=use_displacement, dicing_rate_override=dicing_rate_override,
        micropolygon_budget=micropolygon_budget, vegetation=vegetation,
    )
    out = Path(manifest["output_path"])
    out.parent.mkdir(parents=True, exist_ok=True)
    strips = plan_strips(job.output.full_height, job.output.full_width, strip_pixel_limit)
    if len(strips) == 1:
        cp, receipt = _run_worker(blender, manifest, timeout_seconds)
    else:
        if manifest["file_format"] != "PNG":
            raise ValueError("strip rendering (outputs above strip_pixel_limit) writes PNG only")
        cp, receipt = _run_strips(blender, manifest, strips, job.output.bit_depth, timeout_seconds)
    return CyclesRenderResult(
        returncode=cp.returncode,
        receipt=receipt,
        verification=verify_render_output(job.output, out),
        stderr_tail=(cp.stderr or "")[-2000:],
    )
