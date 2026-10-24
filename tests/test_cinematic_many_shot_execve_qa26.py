"""QA26: legal long-form multi-shot master must launch FFmpeg on Linux.

This is a *process-launch* test: no FFmpeg decoding, model inference, owner
media, cloud calls or phone playback. A real Linux execve is exercised with
the exact filtergraph argument built by the application, replacing only the
FFmpeg executable with an inert Python process. The service's other
dependencies are isolated to keep 700 shots inexpensive and private.
"""
from __future__ import annotations

from datetime import datetime, timezone
import errno
import importlib
import os
from pathlib import Path
import subprocess
import sys

import pytest


pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or os.environ.get("CINEMATIC_REQUIRE_LONG_FORM_ARG_QA") != "1",
    reason="Strict Linux execve reproduction runs in the dedicated QA26 workflow",
)


@pytest.mark.parametrize("shot_count", [200, 700])
def test_valid_many_shot_master_filtergraph_can_be_launched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, shot_count: int,
) -> None:
    """200 shots is a control; 700 half-second shots remain under 600 seconds.

    On Linux, a single execve argument is limited to MAX_ARG_STRLEN (normally
    32 pages / 131072 bytes), even when total ARG_MAX is much larger. A huge
    -filter_complex argument fails before FFmpeg can read any source media.
    """
    service = importlib.import_module("app.video.cinematic_service")
    models = importlib.import_module("app.video.cinematic_models")
    requests = importlib.import_module("app.video.cinematic_requests")

    duration = shot_count / 2
    now = datetime.now(timezone.utc)
    source_id = "f" * 32
    source_file = tmp_path / f"{source_id}.mp4"
    source_file.write_bytes(b"synthetic process-launch placeholder; NOT video")

    shots = [
        models.CinematicShot(
            shot_id=f"{index + 1:032x}", ordinal=index + 1,
            title="Synthetic shot", prompt="Synthetic only",
            duration_seconds=0.5,
        )
        for index in range(shot_count)
    ]
    scene = models.CinematicScene(
        scene_id="e" * 32, ordinal=1, title="Synthetic scene",
        target_duration_seconds=duration, shots=shots,
    )
    project = models.CinematicProject(
        id="d" * 32, revision=1, title="Synthetic long-form launch",
        master_prompt="No private owner media", target_duration_seconds=duration,
        delivery_fps=24, delivery_resolution="480p", aspect_ratio="16:9",
        scenes=[scene], created_at=now, updated_at=now,
    )
    assert duration <= models.MAX_FILM_DURATION_SECONDS
    service.enforce_film_duration(project)

    monkeypatch.setattr(service, "get_project", lambda _identifier: project)
    monkeypatch.setattr(
        service, "_linked_shot_job",
        lambda _project, _scene, shot, **_kwargs: {
            "id": shot.shot_id, "asset_id": source_id,
        },
    )
    monkeypatch.setattr(service, "_job_has_local_render", lambda _job: True)
    monkeypatch.setattr(
        service, "video_asset_path",
        lambda identifier, extension: tmp_path / f"{identifier}.{extension}",
    )
    monkeypatch.setattr(service, "list_video_records", lambda _kind: [])

    observed = {}

    def launch_only(command: list[str], **_kwargs) -> subprocess.CompletedProcess:
        if "-filter_complex" in command:
            graph = command[command.index("-filter_complex") + 1]
            observed["filtergraph_bytes"] = len(os.fsencode(graph))
            # Real Linux kernel argument validation; NOT an FFmpeg encode.
            try:
                subprocess.run(
                    [sys.executable, "-c", "pass", graph],
                    check=True, capture_output=True, timeout=10,
                )
            except OSError as exc:
                if exc.errno == errno.E2BIG:
                    pytest.fail(
                        f"Legal {duration:g}s/{shot_count}-shot film cannot launch: "
                        "single FFmpeg filtergraph argument exceeds Linux execve "
                        "limit; use a filter_complex_script or bounded assembly"
                    )
                raise
        elif "-filter_complex_script" in command:
            # A reviewed future repair may pass a temporary script file instead.
            script = Path(command[command.index("-filter_complex_script") + 1])
            assert script.is_file(), "Filtergraph script missing at process launch"
            observed["script_bytes"] = script.stat().st_size
        else:
            pytest.fail("Master command has no FFmpeg filtergraph")
        # Stop before media probing; process-launch contract is the only claim.
        return subprocess.CompletedProcess(command, 2, stdout="", stderr="")

    monkeypatch.setattr(service, "_run_master_ffmpeg", launch_only)
    with pytest.raises(RuntimeError, match="FFmpeg master assembly failed with exit code 2"):
        service.assemble_project_master(
            project.id, requests.AssembleMasterRequest(expected_revision=1),
        )
    assert observed, "Assembly never reached the subprocess boundary"
