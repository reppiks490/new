from functools import lru_cache
import json
import math
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, model_validator

WEB = Path(__file__).parent / 'web'


@lru_cache(maxsize=1)
def human_data() -> dict:
    return json.loads((WEB / 'data/human.json').read_text())


class CharacterState(BaseModel):
    model_config = ConfigDict(extra='forbid')
    base: str = 'female'
    controls: dict[str, float] = Field(default_factory=dict)
    extreme: bool = False
    skin: str = '#b77f60'
    cloth: str = '#253d65'
    iris: str = '#527c83'
    outfit: str = 'bodysuit-001'
    hair: str = 'none'
    shoes: str = 'none'
    skinTexture: bool = True
    attachments: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode='after')
    def validate_state(self):
        import re
        if self.base not in {'male', 'female'}:
            raise ValueError('Unknown supported base')
        if self.hair not in {'none','long01','bob02'}:
            raise ValueError('Unknown hair asset')
        if self.shoes not in {'none','shoes01','shoes02'}:
            raise ValueError('Unknown footwear')
        known = {c['id'] for c in human_data()['controls']}
        limit = 150 if self.extreme else 100
        for key, value in self.controls.items():
            if key not in known or not math.isfinite(value) or abs(value) > limit:
                raise ValueError(f'Unsupported control or value: {key}')
        if any(not re.fullmatch(r'#[0-9a-fA-F]{6}', c) for c in (self.skin, self.cloth, self.iris)):
            raise ValueError('Colors must be six-digit hex values')
        if not set(self.attachments) <= {'horns', 'ears', 'wings', 'tail', 'earrings'}:
            raise ValueError('Unsupported attachment')
        return self
