from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

# One serialized lane for all heavyweight local GPU inference. This prevents
# image and video models from loading concurrently and competing for VRAM.
gpu_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='local-gpu')
