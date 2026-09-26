from __future__ import annotations

from pydantic import BaseModel, Field

class CyclesPreset(BaseModel):
    name: str; device: str; samples: int; adaptive_sampling: bool; denoise: bool
    max_bounces: int; transparent_bounces: int; subdivision_dicing_rate: float
    use_persistent_data: bool; tile_size: int; texture_limit: int | None = None
    notes: list[str] = Field(default_factory=list)


def quality_preset(vram_gb: float, *, gpu_vendor: str='nvidia', mode: str='hero') -> CyclesPreset:
    if vram_gb <= 0: raise ValueError('vram_gb must be positive')
    device={'nvidia':'OPTIX','amd':'HIP','intel':'ONEAPI','apple':'METAL'}.get(gpu_vendor.lower(),'CPU')
    table={
      'preview': (128, 3.0, 256, 2048, 6, 8),
      'production': (512, 1.5, 512, 4096, 10, 12),
      'hero': (1536, 0.75, 1024, None, 12, 16),
      'extreme': (3072, 0.35, 2048, None, 16, 24),
    }
    if mode not in table: raise ValueError(f'unknown mode: {mode}')
    samples,dice,tile,limit,bounces,tb=table[mode]
    if vram_gb < 12: samples=min(samples,512); dice=max(dice,1.5); tile=min(tile,256); limit=limit or 4096
    elif vram_gb < 24: samples=min(samples,1024); dice=max(dice,1.0); tile=min(tile,512)
    elif vram_gb >= 48 and mode in {'hero','extreme'}: dice*=0.75; tile=max(tile,2048)
    notes=['Profile is deterministic policy, not a guarantee of VRAM residency; hair, displacement and UDIM count remain scene-dependent.']
    if vram_gb < 16: notes.append('Prefer tiled baking and lower-resolution interactive textures for 8K multi-UDIM characters.')
    return CyclesPreset(name=f'{mode}_quality',device=device,samples=samples,adaptive_sampling=True,denoise=True,max_bounces=bounces,transparent_bounces=tb,subdivision_dicing_rate=dice,use_persistent_data=True,tile_size=tile,texture_limit=limit,notes=notes)


def maximum_quality_preset(vram_gb: float, *, gpu_vendor: str='nvidia') -> CyclesPreset:
    return quality_preset(vram_gb,gpu_vendor=gpu_vendor,mode='hero')
