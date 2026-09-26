from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field

class ChainEntry(BaseModel):
    index: int
    timestamp: float
    event: str
    artifact_sha256: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    previous_hash: str | None = None
    entry_hash: str

class ProvenanceChain:
    """Append-only tamper-evident provenance chain. This is integrity chaining, not identity signing."""
    def __init__(self, path: str | Path):
        self.path=Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _digest(payload: dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',',':')).encode()).hexdigest()

    def entries(self) -> list[ChainEntry]:
        if not self.path.exists(): return []
        return [ChainEntry.model_validate(json.loads(line)) for line in self.path.read_text(encoding='utf-8').splitlines() if line.strip()]

    def append(self, event: str, *, artifact_sha256: str | None=None, metadata: dict[str,Any] | None=None) -> ChainEntry:
        entries=self.entries(); prev=entries[-1].entry_hash if entries else None
        base={'index':len(entries),'timestamp':time.time(),'event':event,'artifact_sha256':artifact_sha256,'metadata':metadata or {},'previous_hash':prev}
        entry=ChainEntry(**base, entry_hash=self._digest(base))
        with self.path.open('a', encoding='utf-8') as f: f.write(entry.model_dump_json()+'\n')
        return entry

    def verify(self) -> bool:
        prev=None
        for i,e in enumerate(self.entries()):
            base={'index':e.index,'timestamp':e.timestamp,'event':e.event,'artifact_sha256':e.artifact_sha256,'metadata':e.metadata,'previous_hash':e.previous_hash}
            if e.index != i or e.previous_hash != prev or e.entry_hash != self._digest(base): return False
            prev=e.entry_hash
        return True
