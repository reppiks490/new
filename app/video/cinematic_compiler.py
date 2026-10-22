from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import hashlib
import math
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.video.cinematic_models import CinematicProject, CinematicScene, CinematicShot


_MAX_AUTOMATIC_SCENE_CHARS = 2_000
_MAX_SHOT_PROMPT_CHARS = 20_000
_SENTENCE_SPLIT = re.compile(r'(?<=[.!?])\s+')
_EXPLICIT_MARKERS = (
    re.compile(r'^\s*SCENE\s+\d+\s*:\s*(?P<title>.+?)\s*$', re.IGNORECASE),
    re.compile(r'^\s*#{1,6}\s*Scene\s*:\s*(?P<title>.+?)\s*$', re.IGNORECASE),
    re.compile(r'^\s*\[\s*SCENE\s*:\s*(?P<title>.+?)\s*\]\s*$', re.IGNORECASE),
    re.compile(r'^\s*-{3,}\s*SCENE(?:\s+\d+)?\s+(?P<title>.+?)\s*-{3,}\s*$', re.IGNORECASE),
)


@dataclass(frozen=True)
class SourceScene:
    title: str
    text: str


class CompileResult(BaseModel):
    model_config = ConfigDict(extra='forbid')
    scenes: list[CinematicScene]
    diagnostics: dict[str, Any] = Field(default_factory=dict)


def _stable_id(*parts: object) -> str:
    normalized = '\x1f'.join(str(part).strip() for part in parts)
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:32]


def _marker_title(line: str) -> str | None:
    for pattern in _EXPLICIT_MARKERS:
        match = pattern.match(line)
        if match:
            return match.group('title').strip(' -:#[]\t')[:160] or 'Untitled Scene'
    return None


def parse_explicit_scenes(prompt: str) -> list[SourceScene]:
    lines = prompt.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    scenes: list[SourceScene] = []
    current_title: str | None = None
    current_lines: list[str] = []
    saw_marker = False

    for line in lines:
        title = _marker_title(line)
        if title is None:
            current_lines.append(line)
            continue
        saw_marker = True
        if current_title is not None:
            text = '\n'.join(current_lines).strip()
            scenes.append(SourceScene(current_title, text or current_title))
        elif any(piece.strip() for piece in current_lines):
            prelude = '\n'.join(current_lines).strip()
            scenes.append(SourceScene(_derive_title(prelude, fallback='Opening'), prelude))
        current_title = title
        current_lines = []

    if not saw_marker:
        return []
    if current_title is not None:
        text = '\n'.join(current_lines).strip()
        scenes.append(SourceScene(current_title, text or current_title))
    return scenes


def _derive_title(text: str, *, fallback: str = 'Scene') -> str:
    compact = re.sub(r'\s+', ' ', text).strip()
    if not compact:
        return fallback
    first = re.split(r'[.!?\n]', compact, maxsplit=1)[0].strip(' -:#[]\t')
    return (first or fallback)[:160]


def _split_hard(text: str, limit: int) -> list[str]:
    text = re.sub(r'\s+', ' ', text).strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        cut = remaining.rfind(' ', 0, limit + 1)
        if cut <= 0:
            cut = limit
        chunks.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    return [chunk for chunk in chunks if chunk]


def _chunk_paragraph(paragraph: str, limit: int) -> list[str]:
    paragraph = re.sub(r'\s+', ' ', paragraph).strip()
    if not paragraph:
        return []
    if len(paragraph) <= limit:
        return [paragraph]

    sentences = [item.strip() for item in _SENTENCE_SPLIT.split(paragraph) if item.strip()]
    if len(sentences) <= 1:
        return _split_hard(paragraph, limit)

    chunks: list[str] = []
    current = ''
    for sentence in sentences:
        pieces = _split_hard(sentence, limit)
        for piece in pieces:
            candidate = f'{current} {piece}'.strip() if current else piece
            if current and len(candidate) > limit:
                chunks.append(current)
                current = piece
            else:
                current = candidate
    if current:
        chunks.append(current)
    return chunks


def decompose_prose(prompt: str, target_scene_seconds: float = 30.0) -> list[SourceScene]:
    del target_scene_seconds  # duration budgeting is handled globally and deterministically below.
    normalized = prompt.replace('\r\n', '\n').replace('\r', '\n').strip()
    if not normalized:
        raise ValueError('master prompt cannot be blank')
    paragraphs = [part.strip() for part in re.split(r'\n\s*\n', normalized) if part.strip()]
    if not paragraphs:
        paragraphs = [normalized]

    scenes: list[SourceScene] = []
    for paragraph in paragraphs:
        for chunk in _chunk_paragraph(paragraph, _MAX_AUTOMATIC_SCENE_CHARS):
            scenes.append(SourceScene(_derive_title(chunk, fallback=f'Scene {len(scenes) + 1}'), chunk))
    return scenes or [SourceScene('Scene 1', normalized)]


def _allocate_counts(weights: list[int], total_count: int) -> list[int]:
    count = len(weights)
    if count == 0:
        raise ValueError('cannot allocate shots without scenes')
    total_count = max(total_count, count)
    allocations = [1] * count
    remaining = total_count - count
    if remaining == 0:
        return allocations

    safe_weights = [max(int(weight), 1) for weight in weights]
    weight_total = sum(safe_weights)
    quotas = [remaining * weight / weight_total for weight in safe_weights]
    floors = [int(math.floor(quota)) for quota in quotas]
    for index, floor_value in enumerate(floors):
        allocations[index] += floor_value
    leftovers = remaining - sum(floors)
    order = sorted(range(count), key=lambda i: (quotas[i] - floors[i], safe_weights[i], -i), reverse=True)
    for index in order[:leftovers]:
        allocations[index] += 1
    return allocations


def _local_prompts(text: str, count: int) -> list[str]:
    compact = re.sub(r'\s+', ' ', text).strip()
    if not compact:
        compact = 'Continue the scene while preserving established visual continuity.'
    pieces = _chunk_paragraph(compact, _MAX_SHOT_PROMPT_CHARS)
    if not pieces:
        pieces = [compact[:_MAX_SHOT_PROMPT_CHARS]]
    if count == 1:
        return [pieces[0]]

    prompts: list[str] = []
    for index in range(count):
        prompts.append(pieces[index % len(pieces)])
    return prompts


def budget_shots(
    scene_sources: list[SourceScene],
    target_duration_seconds: float,
    preferred_shot_seconds: float,
    engine_max_duration_seconds: float,
    *,
    project_fingerprint: str,
) -> list[CinematicScene]:
    if target_duration_seconds <= 0:
        raise ValueError('target duration must be positive')
    if preferred_shot_seconds <= 0 or engine_max_duration_seconds <= 0:
        raise ValueError('shot duration limits must be positive')
    if not scene_sources:
        raise ValueError('at least one scene is required')

    effective_cap = min(float(preferred_shot_seconds), float(engine_max_duration_seconds), 30.0)
    total_shots = max(len(scene_sources), int(math.ceil(float(target_duration_seconds) / effective_cap)))
    counts = _allocate_counts([len(scene.text) for scene in scene_sources], total_shots)

    total_decimal = Decimal(str(target_duration_seconds))
    shot_decimal = total_decimal / Decimal(total_shots)
    if shot_decimal <= 0 or shot_decimal > Decimal(str(effective_cap)):
        raise ValueError('duration budget exceeds engine shot capability')

    scenes: list[CinematicScene] = []
    global_shot_ordinal = 1
    for scene_index, (source, shot_count) in enumerate(zip(scene_sources, counts, strict=True), start=1):
        scene_id = _stable_id(project_fingerprint, 'scene', scene_index, source.title, source.text)
        prompts = _local_prompts(source.text, shot_count)
        shots: list[CinematicShot] = []
        for local_index in range(1, shot_count + 1):
            shot_id = _stable_id(project_fingerprint, scene_id, 'shot', local_index)
            shots.append(
                CinematicShot(
                    shot_id=shot_id,
                    ordinal=global_shot_ordinal,
                    title=f'{source.title} — Shot {local_index}',
                    prompt=prompts[local_index - 1],
                    duration_seconds=float(shot_decimal),
                )
            )
            global_shot_ordinal += 1
        scenes.append(
            CinematicScene(
                scene_id=scene_id,
                ordinal=scene_index,
                title=source.title,
                synopsis=_derive_title(source.text, fallback=source.title),
                source_text=source.text,
                target_duration_seconds=float(shot_decimal * Decimal(shot_count)),
                shots=shots,
            )
        )
    return scenes


def compile_project_prompt(
    project: CinematicProject,
    *,
    preferred_shot_seconds: float = 10.0,
    engine_max_duration_seconds: float = 10.0,
) -> CompileResult:
    prompt = project.master_prompt
    explicit = parse_explicit_scenes(prompt)
    if explicit:
        mode = 'explicit'
        sources = explicit
    else:
        mode = 'automatic'
        sources = decompose_prose(prompt)

    fingerprint = hashlib.sha256(
        (re.sub(r'\s+', ' ', prompt).strip() + f'|{project.title}').encode('utf-8')
    ).hexdigest()
    scenes = budget_shots(
        sources,
        project.target_duration_seconds,
        preferred_shot_seconds,
        engine_max_duration_seconds,
        project_fingerprint=fingerprint,
    )
    shots = [shot for scene in scenes for shot in scene.shots]
    return CompileResult(
        scenes=scenes,
        diagnostics={
            'mode': mode,
            'scene_count': len(scenes),
            'shot_count': len(shots),
            'total_duration_seconds': float(project.target_duration_seconds),
            'preferred_shot_seconds': float(preferred_shot_seconds),
            'engine_max_duration_seconds': float(engine_max_duration_seconds),
        },
    )
