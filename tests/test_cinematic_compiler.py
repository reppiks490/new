from __future__ import annotations

from datetime import datetime, timezone
import importlib

import pytest


def _project(prompt: str, *, duration: float = 600):
    models = importlib.import_module("app.video.cinematic_models")
    now = datetime.now(timezone.utc)
    return models.CinematicProject(
        revision=1,
        title="Feature Film",
        master_prompt=prompt,
        target_duration_seconds=duration,
        delivery_fps=120,
        delivery_resolution="2160p",
        aspect_ratio="16:9",
        continuity_bible={},
        reference_image_ids=[],
        scenes=[],
        created_at=now,
        updated_at=now,
    )


def test_explicit_scene_markers_preserve_boundaries_and_titles():
    compiler = importlib.import_module("app.video.cinematic_compiler")
    project = _project(
        "SCENE 1: Rooftop\nRain lashes the roof.\n\n"
        "## Scene: Alley\nThe camera follows her into the alley.\n\n"
        "[SCENE: Station]\nA train arrives through steam.\n\n"
        "--- SCENE Dawn ---\nSunlight breaks over the skyline.",
        duration=120,
    )
    result = compiler.compile_project_prompt(project, preferred_shot_seconds=10, engine_max_duration_seconds=10)
    assert [scene.title for scene in result.scenes] == ["Rooftop", "Alley", "Station", "Dawn"]
    assert "Rain lashes the roof" in result.scenes[0].source_text
    assert "camera follows her" in result.scenes[1].source_text


def test_plain_paragraphs_decompose_without_network_or_llm():
    compiler = importlib.import_module("app.video.cinematic_compiler")
    prompt = "First location. A character arrives.\n\nSecond location. The weather changes.\n\nThird location. Night falls."
    result = compiler.compile_project_prompt(_project(prompt, duration=90), preferred_shot_seconds=10, engine_max_duration_seconds=10)
    assert result.diagnostics["mode"] == "automatic"
    assert len(result.scenes) >= 3
    assert all(scene.source_text.strip() for scene in result.scenes)


def test_oversized_paragraph_splits_on_sentences():
    compiler = importlib.import_module("app.video.cinematic_compiler")
    prompt = " ".join(f"Beat {i} advances the action." for i in range(300))
    result = compiler.compile_project_prompt(_project(prompt, duration=180), preferred_shot_seconds=10, engine_max_duration_seconds=10)
    assert len(result.scenes) > 1
    assert all(len(scene.source_text) <= 2000 for scene in result.scenes)


def test_same_input_produces_same_scene_and_shot_ids():
    compiler = importlib.import_module("app.video.cinematic_compiler")
    project = _project("One. Two. Three.\n\nFour. Five. Six.", duration=60)
    first = compiler.compile_project_prompt(project, preferred_shot_seconds=7, engine_max_duration_seconds=9)
    second = compiler.compile_project_prompt(project, preferred_shot_seconds=7, engine_max_duration_seconds=9)
    assert [s.scene_id for s in first.scenes] == [s.scene_id for s in second.scenes]
    assert [[q.shot_id for q in s.shots] for s in first.scenes] == [[q.shot_id for q in s.shots] for s in second.scenes]


def test_600_second_project_budgets_legal_shots_and_exact_total():
    compiler = importlib.import_module("app.video.cinematic_compiler")
    project = _project("SCENE 1: Beginning\nA long opening.\nSCENE 2: Middle\nEscalation.\nSCENE 3: End\nResolution.")
    result = compiler.compile_project_prompt(project, preferred_shot_seconds=10, engine_max_duration_seconds=10)
    durations = [shot.duration_seconds for scene in result.scenes for shot in scene.shots]
    assert len(durations) == 60
    assert sum(durations) == pytest.approx(600.0, abs=1e-6)
    assert all(0 < value <= 10 for value in durations)


def test_no_shot_exceeds_engine_max_duration():
    compiler = importlib.import_module("app.video.cinematic_compiler")
    result = compiler.compile_project_prompt(_project("A single continuous sequence.", duration=100), preferred_shot_seconds=15, engine_max_duration_seconds=6)
    assert max(shot.duration_seconds for scene in result.scenes for shot in scene.shots) <= 6


def test_whitespace_prompt_is_rejected():
    compiler = importlib.import_module("app.video.cinematic_compiler")
    models = importlib.import_module("app.video.cinematic_models")
    now = datetime.now(timezone.utc)
    with pytest.raises(Exception):
        models.CinematicProject(
            revision=1,
            title="Blank",
            master_prompt="   ",
            target_duration_seconds=60,
            delivery_fps=24,
            delivery_resolution="1080p",
            aspect_ratio="16:9",
            continuity_bible={},
            scenes=[],
            created_at=now,
            updated_at=now,
        )


def test_100000_character_prompt_compiles_iteratively():
    compiler = importlib.import_module("app.video.cinematic_compiler")
    sentence = "The camera advances while the subject remains visually consistent. "
    prompt = (sentence * ((100_000 // len(sentence)) + 1))[:100_000]
    result = compiler.compile_project_prompt(_project(prompt, duration=600), preferred_shot_seconds=10, engine_max_duration_seconds=10)
    assert result.diagnostics["shot_count"] == 60
    assert sum(shot.duration_seconds for scene in result.scenes for shot in scene.shots) == pytest.approx(600.0, abs=1e-6)
