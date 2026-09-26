from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.providers.auth import auth_status
from app.providers.models import ProviderId
from app.workers.blender import find_blender


class CapabilityStatus(BaseModel):
    name: str
    available: bool
    mode: Literal['live', 'optional', 'unavailable']
    detail: str
    version: str | None = None


class RuntimeReadinessReport(BaseModel):
    blender: CapabilityStatus
    openusd_pxr: CapabilityStatus
    providers: list[CapabilityStatus]
    canonical_live_possible: bool
    blockers: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def _blender_version(executable: str) -> str | None:
    try:
        cp = subprocess.run(
            [executable, '--version'], capture_output=True, text=True, check=False, timeout=5,
        )
        line = (cp.stdout or cp.stderr or '').splitlines()
        return line[0].strip() if line else None
    except (OSError, subprocess.SubprocessError):
        return None


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, AttributeError, ValueError):
        return False


def detect_runtime_readiness(*, blender_executable: str | None = None) -> RuntimeReadinessReport:
    blender = find_blender(blender_executable)
    blender_status = CapabilityStatus(
        name='blender',
        available=bool(blender),
        mode='live' if blender else 'unavailable',
        detail='Blender executable is available for headless workers.' if blender else 'Blender executable was not found; Blender stages are contract/test only.',
        version=_blender_version(blender) if blender else None,
    )

    pxr_available = _module_available('pxr')
    pxr_status = CapabilityStatus(
        name='openusd_pxr',
        available=pxr_available,
        mode='live' if pxr_available else 'optional',
        detail='pxr/OpenUSD Python bindings are available for authoritative USD schema validation.' if pxr_available else 'pxr/OpenUSD bindings are unavailable; USDA can use static structural validation, binary USD cannot be authoritative.',
    )

    provider_statuses: list[CapabilityStatus] = []
    for pid in ProviderId:
        status = auth_status(pid)
        provider_statuses.append(CapabilityStatus(
            name=f'provider:{pid.value}',
            available=status.configured,
            mode='live' if status.configured else 'unavailable',
            detail=f'{status.environment_variable} is configured.' if status.configured else f'{status.environment_variable} is not configured.',
        ))

    blockers: list[str] = []
    if not blender:
        blockers.append('Blender is required for a live canonical pipeline when repair/bake/export stages are enabled.')
    if not any(x.available for x in provider_statuses):
        blockers.append('At least one provider credential must be configured for live provider generation/ingest.')

    notes = [
        'Credential values are never returned by readiness inspection.',
        'OpenUSD pxr is optional for GLB-only workflows but required for authoritative binary USD/UsdSkel validation.',
    ]
    return RuntimeReadinessReport(
        blender=blender_status,
        openusd_pxr=pxr_status,
        providers=provider_statuses,
        canonical_live_possible=not blockers,
        blockers=blockers,
        notes=notes,
    )
