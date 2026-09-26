from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from pydantic import BaseModel, Field


class BlenderInvocation(BaseModel):
    executable: str
    args: list[str]
    env: dict[str, str] = Field(default_factory=dict)

    @property
    def command(self) -> list[str]:
        return [self.executable, *self.args]


def find_blender(explicit: str | None = None) -> str | None:
    candidates = [explicit, os.environ.get("BLENDER_BIN"), shutil.which("blender")]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(Path(candidate))
    return None


def build_blender_job_invocation(
    blender_executable: str,
    manifest_path: str | Path,
    worker_script: str | Path,
    blend_file: str | Path | None = None,
    allow_blend_autoexec: bool = False,
) -> BlenderInvocation:
    args: list[str] = ["--background"]
    # Security-first default: downloaded .blend files cannot auto-run embedded scripts.
    args.append("--enable-autoexec" if allow_blend_autoexec else "--disable-autoexec")
    if blend_file:
        args.append(str(blend_file))
    args.extend(["--python", str(worker_script), "--", "--manifest", str(manifest_path)])
    return BlenderInvocation(executable=str(blender_executable), args=args)


def execute(invocation: BlenderInvocation, timeout_seconds: int = 60 * 60) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(invocation.env)
    return subprocess.run(
        invocation.command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        env=env,
    )


def write_invocation_receipt(invocation: BlenderInvocation, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(invocation.model_dump(), indent=2), encoding="utf-8")
    return path
