from __future__ import annotations

import os
from pydantic import BaseModel

from app.providers.models import ProviderId


_ENV_BY_PROVIDER: dict[ProviderId, str] = {
    ProviderId.TRIPO: 'TRIPO_API_KEY',
    ProviderId.MESHY: 'MESHY_API_KEY',
    ProviderId.HI3D: 'HI3D_API_KEY',
}


class ProviderAuthStatus(BaseModel):
    provider: ProviderId
    environment_variable: str
    configured: bool


def auth_status(provider: ProviderId | str) -> ProviderAuthStatus:
    pid = provider if isinstance(provider, ProviderId) else ProviderId(provider)
    name = _ENV_BY_PROVIDER[pid]
    return ProviderAuthStatus(provider=pid, environment_variable=name, configured=bool(os.getenv(name, '').strip()))
