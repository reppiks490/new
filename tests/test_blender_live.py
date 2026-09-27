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


def _repair(tmp_path, source):
    from app.qa.exact_intersections import detect_exact_self_intersections
    from app.workers.blender import execute
    from app.workers.localized_repair import (
        LocalizedRepairReceipt, build_localized_repair_invocation, compile_localized_repair_contract, write_localized_repair_contract,
    )

    before = detect_exact_self_intersections(source)
    out = tmp_path / f"repaired{source.suffix}"
    contract = compile_localized_repair_contract(before, source, out)
    assert not contract.blockers, contract.blockers
    cp = write_localized_repair_contract(contract, tmp_path / "repair_contract.json")
    proc = execute(build_localized_repair_invocation(find_blender(), cp, "blender_scripts/localized_intersection_repair.py"), timeout_seconds=600)
    assert proc.returncode == 0, proc.stderr[-2000:]
    receipt = LocalizedRepairReceipt.model_validate_json((tmp_path / "localized_repair_receipt.json").read_text())
    return before, receipt, detect_exact_self_intersections(out), out


@blender
def test_repair_of_overlapping_closed_shells_removes_intersections_and_stays_closed(tmp_path):
    import trimesh

    from app.qa.mesh import inspect_mesh

    a = trimesh.creation.icosphere(subdivisions=3)
    b = trimesh.creation.icosphere(subdivisions=3)
    b.apply_translation([1.95, 0, 0])
    source = tmp_path / "shells.glb"
    trimesh.util.concatenate([a, b]).export(source)
    before, receipt, after, out = _repair(tmp_path, source)
    assert before.intersecting_pair_count > 0
    assert receipt.status == "succeeded" and receipt.input_was_closed
    assert after.intersecting_pair_count == 0 and receipt.remaining_intersecting_pairs == 0
    assert receipt.boundary_edges_after == 0 and receipt.filled_hole_loops >= 2
    assert inspect_mesh(out).watertight


@blender
def test_repair_of_a_quad_mesh_targets_the_right_faces_and_never_caps_open_borders(tmp_path):
    n = 8
    lines, faces = [], []
    for plane in ("xy", "xz"):
        base = len(lines)
        for i in range(n + 1):
            for j in range(n + 1):
                u, v = -1 + 2 * i / n, -1 + 2 * j / n
                lines.append((u, v, 0.013) if plane == "xy" else (u, 0.017, v))
        faces += [(base + i * (n + 1) + j, base + (i + 1) * (n + 1) + j, base + (i + 1) * (n + 1) + j + 1, base + i * (n + 1) + j + 1)
                  for i in range(n) for j in range(n)]
    source = tmp_path / "crossing.obj"
    source.write_text("".join("v %f %f %f\n" % v for v in lines) + "".join("f %d %d %d %d\n" % tuple(x + 1 for x in f) for f in faces))
    before, receipt, after, _ = _repair(tmp_path, source)
    assert before.intersecting_pair_count > 0
    assert receipt.detected_faces == 16  # the two rows of quads along the crossing, in Blender's quad index space
    assert after.intersecting_pair_count == 0  # independent check, including coplanar overlap
    assert receipt.created_faces == 0 and receipt.open_boundary_chains > 0  # cut strips are left open, borders never capped


@blender
def test_character_pipeline_worker_initializes_the_scene_on_this_blender(tmp_path):
    from app.workers.blender import build_blender_job_invocation, execute

    manifest = tmp_path / "job.json"
    manifest.write_text(json.dumps({"job_id": "t1"}))
    proc = execute(build_blender_job_invocation(find_blender(), manifest, "blender_scripts/character_pipeline.py"), timeout_seconds=300)
    assert proc.returncode == 0, proc.stderr[-2000:]
    receipt = json.loads((tmp_path / "blender_receipt.json").read_text())
    assert receipt["status"] == "scene_initialized"
    assert receipt["render_engine"] in {"BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"}
    assert set(receipt["collections"]) == {"C3D_BASE", "C3D_HERO", "C3D_GROOM", "C3D_RIG", "C3D_EXPORT"}


def test_dicing_rate_is_raised_to_fit_the_micropolygon_budget():
    from app.render.cycles_worker import effective_dicing_rate

    job16 = compile_render_job(vram_gb=24, ram_gb=16, quality_mode="hero", resolution_tier=RenderResolutionTier.UHD_16K)
    rate, info = effective_dicing_rate(job16, micropolygon_budget=25_000_000)
    assert info["requested_px"] == job16.quality.subdivision_dicing_rate
    assert rate > info["requested_px"] and info["estimated_micropolygons"] <= 25_000_000
    roomy, _ = effective_dicing_rate(job16, micropolygon_budget=10**12)
    assert roomy == job16.quality.subdivision_dicing_rate
    assert effective_dicing_rate(job16, micropolygon_budget=10**12, override=0.5)[0] == 0.5


def test_render_manifest_picks_up_the_displacement_sidecar(tmp_path):
    from app.world.terrain import TerrainSpec
    from app.world.textured_terrain import export_textured_terrain_glb

    glb = tmp_path / "t.glb"
    export_textured_terrain_glb(TerrainSpec(name="t", size_meters=50, resolution_power=3, height_scale_meters=10), glb, texture_size=16)
    m = compile_cycles_render_manifest(_job(), glb, tmp_path / "o.png")
    assert m["displacement"] and m["displacement"]["path"].endswith("t.displacement.png")
    assert compile_cycles_render_manifest(_job(), glb, tmp_path / "o.png", use_displacement=False)["displacement"] is None
    (tmp_path / "t.displacement.json").write_text('{"schema": "something-else"}')
    with pytest.raises(ValueError):
        compile_cycles_render_manifest(_job(), glb, tmp_path / "o.png")


@blender
def test_render_applies_displacement_with_adaptive_subdivision(tmp_path):
    from PIL import Image

    from app.world.terrain import TerrainSpec
    from app.world.textured_terrain import export_textured_terrain_glb

    glb = tmp_path / "ridge.glb"
    export_textured_terrain_glb(TerrainSpec(name="r", size_meters=200, resolution_power=4, height_scale_meters=60, seed=4), glb, texture_size=64)
    on = run_cycles_render(_job(), glb, tmp_path / "on.png", samples_override=2)
    off = run_cycles_render(_job(), glb, tmp_path / "off.png", samples_override=2, use_displacement=False)
    assert on.passed and off.passed, (on.receipt, on.stderr_tail)
    assert on.receipt["displacement"]["applied"] and not off.receipt["displacement"]["applied"]
    assert on.receipt["displacement"]["dicing_rate_px"] > 0
    a = np.asarray(Image.open(tmp_path / "on.png").convert("L"), dtype=float)
    b = np.asarray(Image.open(tmp_path / "off.png").convert("L"), dtype=float)
    assert np.abs(a - b).mean() > 0.5  # the geometry really changed


def test_render_manifest_carries_the_vegetation_map(tmp_path):
    from app.render.cycles_worker import VegetationSpec
    from app.world.terrain import TerrainSpec
    from app.world.textured_terrain import export_textured_terrain_glb

    glb = tmp_path / "t.glb"
    export_textured_terrain_glb(TerrainSpec(name="t", size_meters=50, resolution_power=3, height_scale_meters=10), glb, texture_size=16)
    m = compile_cycles_render_manifest(_job(), glb, tmp_path / "o.png")
    assert m["vegetation"]["path"].endswith("t.vegetation.png") and m["vegetation"]["forest_density_per_m2"] > 0
    assert compile_cycles_render_manifest(_job(), glb, tmp_path / "o.png", vegetation=VegetationSpec(enabled=False))["vegetation"] is None
    assert compile_cycles_render_manifest(_job(), glb, tmp_path / "o.png", use_displacement=False)["vegetation"] is None


@blender
def test_render_scatters_see_through_3d_trees_and_leaves_no_stray_files(tmp_path, monkeypatch):
    from app.render.cycles_worker import VegetationSpec
    from app.world.terrain import TerrainSpec
    from app.world.textured_terrain import export_textured_terrain_glb

    monkeypatch.chdir(tmp_path)
    glb = tmp_path / "f.glb"
    export_textured_terrain_glb(TerrainSpec(name="f", size_meters=300, resolution_power=5, height_scale_meters=40, seed=11), glb, texture_size=64)
    before = set(tmp_path.iterdir())
    r = run_cycles_render(_job(), glb, tmp_path / "v.png", samples_override=2,
                          vegetation=VegetationSpec(forest_density_per_m2=0.02, plains_density_per_m2=0.01))
    assert r.passed, (r.receipt, r.stderr_tail)
    v = r.receipt["vegetation"]
    assert v["instances"] > 100 and v["unique_tree_triangles"] > 1000
    assert v["effective_triangles"] > v["unique_tree_triangles"]
    # packed textures are unpacked into the job's own folder, never the CWD
    assert {p.name for p in set(tmp_path.iterdir()) - before} <= {"v.png", "v.png.manifest.json", "v.png.receipt.json"}


def test_plan_strips_covers_every_row_once_with_overlap():
    from app.render.cycles_worker import STRIP_OVERLAP_ROWS, plan_strips

    strips = plan_strips(17280, 30720)
    assert len(strips) == 16 and strips[0][0] == 0 and strips[-1][1] == 17280
    assert all(a[1] == b[0] for a, b in zip(strips, strips[1:]))
    assert strips[1][2] == strips[1][0] - STRIP_OVERLAP_ROWS and strips[0][2] == 0
    assert plan_strips(1080, 1920) == [(0, 1080, 0, 1080)]


@blender
def test_strip_render_is_pixel_identical_to_a_single_pass(tmp_path):
    from app.world.terrain import TerrainSpec
    from app.world.textured_terrain import export_textured_terrain_glb
    from app.render.cycles_worker import plan_strips

    glb = tmp_path / "s.glb"
    export_textured_terrain_glb(TerrainSpec(name="s", size_meters=200, resolution_power=4, height_scale_meters=40, seed=2), glb, texture_size=64)
    job = _job(width=240, height=136, bit_depth=8)
    job.quality.denoise = False
    kw = dict(samples_override=2)
    one = run_cycles_render(job, glb, tmp_path / "one.png", **kw)
    many = run_cycles_render(job, glb, tmp_path / "many.png", strip_pixel_limit=240 * 40, **kw)
    assert one.passed and many.passed, (many.receipt, many.stderr_tail)
    assert len(many.receipt["strips"]) == 4
    from PIL import Image
    a = np.asarray(Image.open(tmp_path / "one.png").convert("RGB"), dtype=int)
    b = np.asarray(Image.open(tmp_path / "many.png").convert("RGB"), dtype=int)
    d = np.abs(a - b).mean(axis=(1, 2))  # per row; 8-bit output is dithered, so not bit-exact
    assert a.shape == b.shape and np.abs(a - b).max() <= 3 and d.mean() < 0.5
    seams = [c0 for c0, *_ in plan_strips(136, 240, 240 * 40)[1:]]
    assert max(d[y - 1:y + 1].max() for y in seams) <= d.max() and d[seams].mean() < 1.0  # no visible seam
    assert not list(tmp_path.glob("many.strip*"))


@blender
def test_character_lookdev_assigns_roles_and_renders(tmp_path):
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    glb = tmp_path / "head.glb"
    subprocess.run([find_blender(), "--background", "--python", str(root / "tests/fixtures/make_standin_head.py"), "--", str(glb)],
                   check=True, capture_output=True)
    m = {"source_model": str(glb), "output_path": str(tmp_path / "h.png"), "receipt_path": str(tmp_path / "r.json"),
         "resolution": [160, 200], "quality": {"samples": 4, "denoise": False}}
    (tmp_path / "m.json").write_text(json.dumps(m))
    subprocess.run([find_blender(), "--background", "--disable-autoexec", "--python", str(root / "blender_scripts/character_lookdev.py"),
                    "--", "--manifest", str(tmp_path / "m.json")], check=True, capture_output=True)
    r = json.loads((tmp_path / "r.json").read_text())
    assert r["status"] == "succeeded" and (tmp_path / "h.png").is_file()
    roles = set(r["roles"].values())
    assert {"skin", "cornea", "eye", "cloth"} <= roles
    assert r["rig"]["lights"] == ["key", "fill", "rim"]
