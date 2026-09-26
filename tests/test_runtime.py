from pathlib import Path
from app.core.models import CharacterSpec, HardwareProfile, QualityTier, TextureTier
from app.runtime.compile_job import compile_job_manifest
from app.workers.blender import build_blender_job_invocation


def test_job_manifest_is_reproducible_across_job_identity(tmp_path: Path):
    spec = CharacterSpec(prompt="fictional adult hero", quality_tier=QualityTier.HERO_OFFLINE, texture_tier=TextureTier.T8K)
    hw = HardwareProfile(vram_gb=24, ram_gb=64, gpu_vendor="nvidia")
    a = compile_job_manifest(spec, hw, tmp_path / "a")
    b = compile_job_manifest(spec, hw, tmp_path / "a")
    assert a.plan_hash == b.plan_hash
    assert a.reproducibility_hash() == b.reproducibility_hash()


def test_blender_invocation_is_background_and_disables_autoexec():
    inv = build_blender_job_invocation("/opt/blender/blender", "job.json", "worker.py")
    assert inv.command[1:3] == ["--background", "--disable-autoexec"]
    assert inv.command[-3:] == ["--", "--manifest", "job.json"]
    assert inv.command.index("--python") < inv.command.index("--")
