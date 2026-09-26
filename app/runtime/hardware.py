from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from pydantic import BaseModel, Field


class GPUInfo(BaseModel):
    name: str = "unknown"
    vendor: str = "unknown"
    vram_gb: float | None = None
    compute_api: list[str] = Field(default_factory=list)


class RuntimeHardware(BaseModel):
    os: str
    architecture: str
    ram_gb: float | None = None
    gpus: list[GPUInfo] = Field(default_factory=list)


def _system_ram_gb() -> float | None:
    try:
        if hasattr(os, "sysconf"):
            pages = os.sysconf("SC_PHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            return round((pages * page_size) / (1024**3), 2)
    except (ValueError, OSError, AttributeError):
        pass
    return None


def _probe_nvidia() -> list[GPUInfo]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    try:
        proc = subprocess.run(
            [exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    out: list[GPUInfo] = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split(",", 1)]
        mib = float(parts[1]) if len(parts) == 2 and re.fullmatch(r"[0-9.]+", parts[1]) else None
        out.append(GPUInfo(name=parts[0], vendor="nvidia", vram_gb=round(mib / 1024, 2) if mib else None,
                           compute_api=["cuda", "optix"]))
    return out


def detect_runtime_hardware() -> RuntimeHardware:
    return RuntimeHardware(
        os=platform.system().lower(),
        architecture=platform.machine().lower(),
        ram_gb=_system_ram_gb(),
        gpus=_probe_nvidia(),
    )
