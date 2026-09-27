import json
import struct
import subprocess

import numpy as np
import pytest

from app.render.cycles_worker import compile_cycles_render_manifest, run_cycles_render
from app.render.job import compile_render_job
from app.render.output_resolution import RenderResolutionTier
from app.render.output_verification import exr_dimensions
from app.workers.blender import find_blender


def _job(width=160, height=90, bit_depth=16):
    job = compile_render_job(vram_gb=24, ram_gb=16, quality_mode="preview", resolution_tier=RenderResolutionTier.HD, bit_depth=bit_depth)
    job.output.width, job.output.height = width, height
    return job


def test_manifest_rejects_unknown_format_and_32bit_png(tmp_path):
    with pytest.raises(ValueError):
        compile_cycles_render_manifest(_job(), "a.glb", tmp_path / "x.jpg")
    with pytest.raises(ValueError):
        compile_cycles_render_manifest(_job(bit_depth=32), "a.glb", tmp_path / "x.png")


def test_exr_dimensions_reads_data_window(tmp_path):
    p = tmp_path / "h.exr"
    header = struct.pack("<iI", 20000630, 2)
    header += b"channels\0chlist\0" + struct.pack("<i", 1) + b"\0"
    header += b"dataWindow\0box2i\0" + struct.pack("<i", 16) + struct.pack("<4i", 0, 0, 7679, 4319)
    p.write_bytes(header + b"\0")
    assert exr_dimensions(p) == (7680, 4320)
    (tmp_path / "n.exr").write_bytes(b"notexr!!")
    with pytest.raises(ValueError):
        exr_dimensions(tmp_path / "n.exr")


blender = pytest.mark.skipif(find_blender() is None, reason="Blender not installed")


@pytest.fixture(scope="module")
def terrain_glb(tmp_path_factory):
    from app.world.terrain import TerrainSpec
    from app.world.textured_terrain import export_textured_terrain_glb

    path = tmp_path_factory.mktemp("src") / "terrain.glb"
    export_textured_terrain_glb(TerrainSpec(name="t", size_meters=200, resolution_power=4, height_scale_meters=40, seed=3), path, texture_size=64)
    return path


@blender
@pytest.mark.parametrize("ext", ["png", "exr"])
def test_real_cycles_render_is_verified(tmp_path, terrain_glb, ext):
    result = run_cycles_render(_job(), terrain_glb, tmp_path / f"r.{ext}", samples_override=2)
    assert result.passed, (result.receipt, result.stderr_tail)
    assert result.receipt["resolution"] == [160, 90]
    assert result.receipt["mesh_count"] == 1
    assert (result.verification.width, result.verification.height) == (160, 90)


@blender
def test_render_is_lit_not_black_or_blown_out(tmp_path, terrain_glb):
    from PIL import Image

    out = tmp_path / "r.png"
    assert run_cycles_render(_job(), terrain_glb, out, samples_override=4).passed
    pixels = np.asarray(Image.open(out).convert("RGB")).astype(float)
    assert 40 < pixels.mean() < 200
    assert (pixels.max(axis=2) >= 250).mean() < 0.02


@blender
def test_production_worker_exports_only_the_asset(tmp_path, terrain_glb):
    from app.core.axes import load_mesh_zup
    from app.workers.blender import build_blender_job_invocation, execute
    from app.workers.blender_pipeline import compile_blender_production_manifest, write_blender_production_manifest

    manifest = compile_blender_production_manifest(terrain_glb, tmp_path, vram_gb=24, render_mode="preview", export_formats=["glb", "usd"])
    mp = write_blender_production_manifest(manifest, tmp_path / "m.json")
    cp = execute(build_blender_job_invocation(find_blender(), mp, "blender_scripts/production_pipeline.py"), timeout_seconds=600)
    assert cp.returncode == 0, cp.stderr[-2000:]
    assert json.loads((tmp_path / "blender_production_receipt.json").read_text())["status"] == "succeeded"
    exported = load_mesh_zup(tmp_path / "exports" / "character.glb")
    assert np.ptp(exported.vertices, axis=0)[0] == pytest.approx(200, abs=1e-3)  # no stray default cube
    pytest.importorskip("pxr")
    from pxr import Usd, UsdGeom

    stage = Usd.Stage.Open(str(tmp_path / "exports" / "character.usd"))
    assert sum(p.IsA(UsdGeom.Mesh) for p in stage.Traverse()) == 1


@blender
def test_blender_shim_script_errors_exit_nonzero(tmp_path):
    script = tmp_path / "boom.py"
    script.write_text("raise RuntimeError('boom')\n")
    cp = subprocess.run([find_blender(), "--background", "--python", str(script)], capture_output=True, text=True, timeout=300)
    assert cp.returncode != 0
    ok = tmp_path / "ok.py"
    ok.write_text("import sys, bpy\nassert sys.argv[sys.argv.index('--') + 1:] == ['--x', '1']\n")
    cp = subprocess.run([find_blender(), "--background", "--python", str(ok), "--", "--x", "1"], capture_output=True, text=True, timeout=300)
    assert cp.returncode == 0, cp.stderr[-1000:]


def _bake_pair(tmp_path, *, split_tiles=False):
    import trimesh

    from app.core.axes import export_mesh_from_zup
    from app.world.terrain import TerrainSpec, diamond_square_heightmap, heightmap_to_mesh, terrain_uvs

    hm = diamond_square_heightmap(TerrainSpec(name="b", size_meters=20, resolution_power=6, height_scale_meters=4, roughness=0.7, seed=9))
    high = heightmap_to_mesh(hm, size_meters=20, height_scale_meters=4)
    low_hm = hm[::8, ::8]
    low = heightmap_to_mesh(low_hm, size_meters=20, height_scale_meters=4)
    uv = terrain_uvs(low_hm.shape[0])
    if split_tiles:
        # per-corner UVs; faces on the +X half move to UDIM tile 1002
        faces = low.faces
        corners = low.vertices[faces.reshape(-1)]
        corner_uv = uv[faces.reshape(-1)].copy()
        right = np.repeat(low.vertices[faces].mean(axis=1)[:, 0] > 10, 3)
        corner_uv[right, 0] += 1.0
        low = trimesh.Trimesh(vertices=corners, faces=np.arange(len(corners)).reshape(-1, 3), process=False)
        uv = corner_uv
    low.visual = trimesh.visual.TextureVisuals(uv=uv)
    export_mesh_from_zup(high, tmp_path / "high.glb")
    export_mesh_from_zup(low, tmp_path / "low.glb")
    return tmp_path / "high.glb", tmp_path / "low.glb"


def _run_bake(tmp_path, contract):
    from app.workers.blender import execute
    from app.workers.high_low_bake import build_high_low_bake_invocation, load_bake_receipt, write_bake_contract

    cp = write_bake_contract(contract, tmp_path / "contract.json")
    proc = execute(build_high_low_bake_invocation(find_blender(), cp, tmp_path, "blender_scripts/high_low_udim_bake.py"), timeout_seconds=900)
    assert proc.returncode == 0, proc.stderr[-2000:]
    return load_bake_receipt(tmp_path / "high_low_bake_receipt.json")


@blender
def test_bake_measures_reach_hits_the_surface_and_flags_empty_udim_tiles(tmp_path):
    from app.qa.bake_output_verification import validate_bake_receipt_and_output
    from app.workers.bake_contract import compile_high_low_bake_contract

    high, low = _bake_pair(tmp_path, split_tiles=True)
    contract = compile_high_low_bake_contract(high, low, udim_tiles=[1001, 1002, 1003], resolution=2048, bake_samples=2)
    receipt = _run_bake(tmp_path, contract)
    assert receipt.status == "succeeded"
    assert receipt.ray["auto_ray_distance"] and receipt.ray["max_ray_distance"] > 0.02
    assert receipt.uv_tiles == [1001, 1002]
    assert receipt.uncovered_contract_tiles == [1003]
    assert receipt.hit_mask.miss_fraction < contract.max_miss_fraction
    normal = next(c for c in receipt.channels if c.channel == "normal")
    assert sorted(normal.tile_filepaths) == [1001, 1002, 1003]
    blockers, report = validate_bake_receipt_and_output(contract, receipt)
    assert report is not None and report.passed  # every tile file is real and full-size
    assert blockers and all("1003" in b for b in blockers)  # ...but the empty tile is called out


@blender
def test_bake_pinned_to_the_old_2cm_reach_is_rejected_by_its_measured_miss_rate(tmp_path):
    from app.qa.bake_output_verification import validate_bake_receipt_and_output
    from app.workers.bake_contract import compile_high_low_bake_contract

    high, low = _bake_pair(tmp_path)
    contract = compile_high_low_bake_contract(high, low, udim_tiles=[1001], resolution=2048, bake_samples=2,
                                              ray_distance=0.02, cage_extrusion=0.0)
    receipt = _run_bake(tmp_path, contract)
    assert receipt.hit_mask.miss_fraction > 0.3
    blockers, _ = validate_bake_receipt_and_output(contract, receipt)
    assert any("missed the high-poly" in b for b in blockers)
