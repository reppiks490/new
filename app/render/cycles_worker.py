from __future__ import annotations

"""Executes a compiled RenderJobSpec in real Blender/Cycles and verifies the
file it produced. compile_render_job decides "how good" (CyclesPreset) and
"how big" (RenderOutputSpec); this turns that plan into pixels on disk.
"""

import json
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
    sun_elevation_deg: float = Field(default=28.0, ge=-5, le=90)
    sun_rotation_deg: float = 135.0
    sun_strength: float = Field(default=3.0, ge=0)  # tuned on real renders: 0% clipped
    sky_strength: float = Field(default=0.15, ge=0)  # 4.0/0.6 clipped 5.1% of pixels


class CyclesRenderResult(BaseModel):
    returncode: int
    receipt: dict
    verification: RenderOutputVerification
    stderr_tail: str = ""

    @property
    def passed(self) -> bool:
        return self.returncode == 0 and self.receipt.get("status") == "succeeded" and self.verification.meets_or_exceeds_spec


def compile_cycles_render_manifest(
    job: RenderJobSpec,
    source_model: str | Path,
    output_path: str | Path,
    *,
    camera: CameraSpec | None = None,
    lighting: LightingSpec | None = None,
    samples_override: int | None = None,
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
    return {
        "schema": "character3d-cycles-render-v1",
        "source_model": str(Path(source_model).resolve()),
        "output_path": str(out.resolve()),
        "receipt_path": str(out.resolve().with_suffix(out.suffix + ".receipt.json")),
        "file_format": fmt,
        "quality": quality,
        "output": job.output.model_dump(mode="json"),
        "camera": (camera or CameraSpec()).model_dump(),
        "lighting": (lighting or LightingSpec()).model_dump(),
    }


def run_cycles_render(
    job: RenderJobSpec,
    source_model: str | Path,
    output_path: str | Path,
    *,
    camera: CameraSpec | None = None,
    lighting: LightingSpec | None = None,
    samples_override: int | None = None,
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
    )
    out = Path(manifest["output_path"])
    out.parent.mkdir(parents=True, exist_ok=True)
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
    return CyclesRenderResult(
        returncode=cp.returncode,
        receipt=receipt,
        verification=verify_render_output(job.output, out),
        stderr_tail=(cp.stderr or "")[-2000:],
    )
