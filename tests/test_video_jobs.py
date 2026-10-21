from types import SimpleNamespace

import pytest
from PIL import Image

from app.video import engine, jobs
from app.video.models import EngineCapabilities, VideoGenerationRequest
from app.video.storage import get_video_record, put_video_record, video_asset_path


class InlinePool:
    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)
        return SimpleNamespace()


def prepare_source(tmp_path, monkeypatch, ident='4'*32):
    monkeypatch.setenv('CHARACTER3D_STUDIO_WORKSPACE', str(tmp_path))
    Image.new('RGB', (32, 24), 'white').save(video_asset_path(ident, 'png'))
    return ident


def test_job_lifecycle_reaches_succeeded(tmp_path, monkeypatch):
    ident = prepare_source(tmp_path, monkeypatch)
    engine.clear_engines()
    engine.register_engine('fake', engine.FakeVideoEngine)
    monkeypatch.setattr(jobs, 'pool', InlinePool())
    record = jobs.enqueue_video_job(VideoGenerationRequest(image_id=ident, prompt='move'))
    final = get_video_record('video_job', record['id'])
    assert final['status'] == 'succeeded'
    assert final['stage'] == 'Ready'
    assert final['asset_url'].endswith('.mp4')
    assert final['history'][:4] == ['Queued', 'Loading', 'Generating', 'Encoding']
    assert final['history'][-1] == 'Ready'


def test_job_failure_redacts_secrets(tmp_path, monkeypatch):
    ident = prepare_source(tmp_path, monkeypatch, ident='5'*32)
    secret = 'super-secret-token'
    monkeypatch.setenv('CHARACTER3D_STUDIO_TOKEN', secret)

    class Broken:
        name = 'broken'
        def capabilities(self):
            return EngineCapabilities(name='broken', available=True, profiles=['auto'], resolutions=['720p'])
        def generate(self, request, source_image, output_path, progress):
            raise RuntimeError('failure ' + secret)

    engine.clear_engines()
    engine.register_engine('broken', Broken)
    monkeypatch.setattr(jobs, 'pool', InlinePool())
    record = jobs.enqueue_video_job(VideoGenerationRequest(image_id=ident, prompt='move'))
    final = get_video_record('video_job', record['id'])
    assert final['status'] == 'failed'
    assert secret not in final['error']
    assert '[redacted]' in final['error']


def test_interrupt_active_video_jobs_marks_failed(tmp_path, monkeypatch):
    monkeypatch.setenv('CHARACTER3D_STUDIO_WORKSPACE', str(tmp_path))
    a = put_video_record('video_job', {'status': 'queued', 'stage': 'Queued', 'history': ['Queued']})
    b = put_video_record('video_job', {'status': 'running', 'stage': 'Generating', 'history': ['Queued', 'Generating']})
    count = jobs.interrupt_active_video_jobs()
    assert count == 2
    for ident in (a['id'], b['id']):
        value = get_video_record('video_job', ident)
        assert value['status'] == 'failed'
        assert value['stage'] == 'Interrupted'


def test_enqueue_without_engine_is_actionable(tmp_path, monkeypatch):
    ident = prepare_source(tmp_path, monkeypatch, ident='6'*32)
    engine.clear_engines()
    with pytest.raises(jobs.VideoEngineUnavailable, match='No compatible local image-to-video engine'):
        jobs.enqueue_video_job(VideoGenerationRequest(image_id=ident, prompt='move'))
