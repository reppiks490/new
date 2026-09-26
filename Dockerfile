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
RUN pip install --no-cache-dir -e .

RUN mkdir -p /app/workspace
ENV CHARACTER3D_LEASE_DB=/app/workspace/runtime_leases.db \
    CHARACTER3D_CLAIM_DB=/app/workspace/job_claims.db \
    CHARACTER3D_LINEAGE_DB=/app/workspace/artifact_lineage.db \
    CHARACTER3D_CHECKPOINT_DB=/app/workspace/stage_checkpoints.db

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://127.0.0.1:8000/health').raise_for_status()"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
