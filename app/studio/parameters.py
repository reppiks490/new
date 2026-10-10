from functools import lru_cache
import json
import math
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import Literal

WEB = Path(__file__).parent / 'web'


@lru_cache(maxsize=1)
def human_data() -> dict:
    return json.loads((WEB / 'data/human.json').read_text())


class BodyEdit(BaseModel):
    model_config = ConfigDict(extra='forbid')
    region: Literal['waist']
    operation: Literal['reduce_width']
    amount_pct: float = Field(gt=0, le=15, allow_inf_nan=False)
    protected_regions: list[Literal['hips', 'glutes']] = Field(default_factory=list, max_length=2)

    @field_validator('amount_pct', mode='before')
    @classmethod
    def reject_boolean_amount(cls, value):
        if isinstance(value, bool):
            raise ValueError('Edit amount must be numeric, not boolean')
        return value

    @model_validator(mode='after')
    def unique_protected_regions(self):
        if len(set(self.protected_regions)) != len(self.protected_regions):
            raise ValueError('Protected regions must be unique')
        return self


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
    body_edits: list[BodyEdit] = Field(default_factory=list, max_length=10)

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
        if sum(edit.amount_pct for edit in self.body_edits) > 15:
            raise ValueError('Combined waist width reduction cannot exceed 15 percent')
        if any(not re.fullmatch(r'#[0-9a-fA-F]{6}', c) for c in (self.skin, self.cloth, self.iris)):
            raise ValueError('Colors must be six-digit hex values')
        if not set(self.attachments) <= {'horns', 'ears', 'wings', 'tail', 'earrings'}:
            raise ValueError('Unsupported attachment')
        return self
