FROM python:3.11-slim

WORKDIR /app

# Build tooling for any dependency without a prebuilt wheel on this platform
# (numpy/scipy/trimesh/Pillow/cryptography all ship wheels for standard
# platforms, but this keeps the build resilient rather than assuming it).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app
COPY config ./config
COPY blender_scripts ./blender_scripts
COPY scripts ./scripts
# [usd] = OpenUSD (usd-core) for authoritative USD/UsdSkel validation.
RUN pip install --no-cache-dir -e ".[usd]"

# Blender 5.0.1 as the official `bpy` build, in its own venv (bpy pins
# numpy<2; this app needs numpy>=2), exposed as `blender` via the CLI shim.
# Build with --build-arg WITH_BLENDER=0 for a smaller image without it.
ARG WITH_BLENDER=1
RUN if [ "$WITH_BLENDER" = "1" ]; then \
      apt-get update && apt-get install -y --no-install-recommends \
        libxrender1 libxxf86vm1 libxfixes3 libxi6 libxkbcommon0 libsm6 libgl1 libegl1 \
      && rm -rf /var/lib/apt/lists/* \
      && python -m venv /opt/blender-bpy \
      && /opt/blender-bpy/bin/pip install --no-cache-dir bpy==5.0.1 \
      && ln -s /app/scripts/blender /usr/local/bin/blender \
      && blender --version; \
    fi

RUN mkdir -p /app/workspace
ENV CHARACTER3D_LEASE_DB=/app/workspace/runtime_leases.db \
    CHARACTER3D_CLAIM_DB=/app/workspace/job_claims.db \
    CHARACTER3D_LINEAGE_DB=/app/workspace/artifact_lineage.db \
    CHARACTER3D_CHECKPOINT_DB=/app/workspace/stage_checkpoints.db

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://127.0.0.1:8000/health').raise_for_status()"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
