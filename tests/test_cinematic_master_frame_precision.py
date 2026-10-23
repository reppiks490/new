"""Real-media check for accumulated cut rounding, without model inference."""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from app.video import cinematic_models as models, cinematic_service as service
from app.video.cinematic_requests import AssembleMasterRequest
from app.video.storage import put_video_record, video_asset_path


def test_fractional_cuts_use_cumulative_delivery_frames(monkeypatch, tmp_path):
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg or not shutil.which('ffprobe'):
        if os.getenv('CINEMATIC_REQUIRE_REAL_MEDIA') == '1':
            pytest.fail('Real-media check requires FFmpeg and FFprobe')
        pytest.skip('Real-media check requires FFmpeg and FFprobe')
    monkeypatch.setenv('CHARACTER3D_STUDIO_WORKSPACE', str(tmp_path))
    project = service.create_project(models.ProjectCreateRequest(
        title='Synthetic fractional cuts', master_prompt='No inference used.',
        target_duration_seconds=10.1, delivery_fps=24,
        delivery_resolution='480p',
    ))
    shots = [models.CinematicShot(
        shot_id=f'{index+1:032x}', ordinal=index+1, title='Synthetic shot',
        prompt='No inference used.', duration_seconds=2.525,
    ) for index in range(4)]
    scene = models.CinematicScene(
        scene_id='e'*32, ordinal=1, title='Synthetic scene',
        target_duration_seconds=10.1, shots=shots,
    )
    project = service.update_project(project.id, models.ProjectUpdateRequest(
        expected_revision=1, scenes=[scene],
    ))
    source = tmp_path/'source.mp4'
    subprocess.run([
        ffmpeg, '-nostdin', '-y', '-v', 'error', '-f', 'lavfi', '-i',
        'color=c=red:s=160x90:r=24:d=3', '-an', '-c:v', 'libx264',
        '-pix_fmt', 'yuv420p', str(source),
    ], check=True, capture_output=True, timeout=60)
    linked = []
    for index, shot in enumerate(shots):
        asset_id = f'{index+100:032x}'
        shutil.copyfile(source, video_asset_path(asset_id, 'mp4'))
        job = put_video_record('video_job', {
            'status':'succeeded', 'project_id':project.id,
            'scene_id':scene.scene_id, 'shot_id':shot.shot_id,
            'asset_id':asset_id,
        })
        linked.append(shot.model_copy(update={'latest_job_id':job['id']}))
    project = service.update_project(project.id, models.ProjectUpdateRequest(
        expected_revision=project.revision,
        scenes=[scene.model_copy(update={'shots':linked})],
    ))
    master = service.assemble_project_master(project.id, AssembleMasterRequest(
        expected_revision=project.revision,
    ))
    # Independent oracle: 10.1*24 rounds to 242 frames. Rounding each
    # 2.525-second clip separately instead produces 244 frames and drifts.
    assert master['probe']['frame_count'] == 242
    assert master['probe']['duration_seconds'] == pytest.approx(10.1, abs=1/24)
    subprocess.run([
        ffmpeg, '-nostdin', '-v', 'error', '-xerror', '-i',
        str(video_asset_path(master['asset_id'], 'mp4')), '-f', 'null', '-',
    ], check=True, capture_output=True, timeout=60)
