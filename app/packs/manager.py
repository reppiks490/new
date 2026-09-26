from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class PackFile(BaseModel):
    path: str
    sha256: str | None = None
    optional: bool = False


class CapabilityPack(BaseModel):
    id: str
    name: str
    category: Literal[
        "geometry", "reconstruction", "materials", "upscaling", "hair_groom",
        "rigging", "animation", "render", "environment", "interop", "core"
    ]
    version: str
    expected_size_gb: float = Field(ge=0)
    description: str
    dependencies: list[str] = Field(default_factory=list)
    files: list[PackFile] = Field(default_factory=list)


class PackRegistry:
    def __init__(self, packs: list[CapabilityPack]):
        self.packs = {p.id: p for p in packs}

    @classmethod
    def from_yaml(cls, path: str | Path) -> "PackRegistry":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        packs = [CapabilityPack.model_validate(x) for x in raw.get("packs", [])]
        return cls(packs)

    def resolve(self, requested: list[str]) -> list[CapabilityPack]:
        ordered: list[CapabilityPack] = []
        seen: set[str] = set()
        visiting: set[str] = set()

        def visit(pack_id: str) -> None:
            if pack_id in seen:
                return
            if pack_id in visiting:
                raise ValueError(f"Capability-pack dependency cycle at {pack_id}")
            if pack_id not in self.packs:
                raise KeyError(f"Unknown capability pack: {pack_id}")
            visiting.add(pack_id)
            pack = self.packs[pack_id]
            for dep in pack.dependencies:
                visit(dep)
            visiting.remove(pack_id)
            seen.add(pack_id)
            ordered.append(pack)

        for pack_id in requested:
            visit(pack_id)
        return ordered

    def expected_size_gb(self, requested: list[str]) -> float:
        return round(sum(p.expected_size_gb for p in self.resolve(requested)), 3)

    def verify_installed(self, pack: CapabilityPack, root: str | Path) -> tuple[bool, list[str]]:
        root = Path(root)
        errors: list[str] = []
        for item in pack.files:
            p = root / pack.id / item.path
            if not p.exists():
                if not item.optional:
                    errors.append(f"missing:{item.path}")
                continue
            if item.sha256:
                digest = hashlib.sha256(p.read_bytes()).hexdigest()
                if digest.lower() != item.sha256.lower():
                    errors.append(f"sha256:{item.path}")
        return (not errors, errors)
