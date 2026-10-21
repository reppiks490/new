import pytest
from pydantic import ValidationError

from app.video.models import PrivacyPreferences, VideoGenerationRequest
from app.video.storage import video_asset_path, put_video_record, get_video_record, list_video_records


def test_video_asset_path_accepts_safe_extensions(tmp_path, monkeypatch):
    monkeypatch.setenv('CHARACTER3D_STUDIO_WORKSPACE', str(tmp_path))
    ident = 'a' * 32
    assert video_asset_path(ident, 'png') == tmp_path / 'video-assets' / f'{ident}.png'
    assert video_asset_path(ident, 'mp4') == tmp_path / 'video-assets' / f'{ident}.mp4'
    assert video_asset_path(ident, 'json') == tmp_path / 'video-assets' / f'{ident}.json'


def test_video_asset_path_rejects_invalid_input(tmp_path, monkeypatch):
    monkeypatch.setenv('CHARACTER3D_STUDIO_WORKSPACE', str(tmp_path))
    for ident in ['../escape', 'A' * 32, 'a' * 31, 'a' * 33]:
        with pytest.raises(ValueError):
            video_asset_path(ident, 'mp4')
    with pytest.raises(ValueError):
        video_asset_path('a' * 32, 'exe')


def test_video_asset_path_rejects_symlink_escape(tmp_path, monkeypatch):
    monkeypatch.setenv('CHARACTER3D_STUDIO_WORKSPACE', str(tmp_path))
    asset_dir = tmp_path / 'video-assets'
    asset_dir.mkdir(parents=True)
    target = tmp_path / 'outside.mp4'
    target.write_bytes(b'x')
    link = asset_dir / f"{'b'*32}.mp4"
    link.symlink_to(target)
    with pytest.raises(ValueError):
        video_asset_path('b' * 32, 'mp4')


def test_generation_request_validates_bounds():
    good = VideoGenerationRequest(image_id='c'*32, prompt='slow camera push in')
    assert good.engine_profile == 'auto'
    assert good.resolution == '720p'
    assert good.fps == 24

    bad_cases = [
        dict(image_id='bad', prompt='x'),
        dict(image_id='c'*32, prompt=''),
        dict(image_id='c'*32, prompt='x', fps=0),
        dict(image_id='c'*32, prompt='x', fps=61),
        dict(image_id='c'*32, prompt='x', duration_seconds=0),
        dict(image_id='c'*32, prompt='x', duration_seconds=13),
        dict(image_id='c'*32, prompt='x', resolution='4k'),
        dict(image_id='c'*32, prompt='x', motion_strength=1.1),
    ]
    for kwargs in bad_cases:
        with pytest.raises(ValidationError):
            VideoGenerationRequest(**kwargs)


def test_privacy_defaults_are_private():
    p = PrivacyPreferences()
    assert p.privacy_mode is True
    assert p.mask_prompts is True
    assert p.blur_media is True
    assert p.quick_hide is True
    assert p.idle_lock_seconds == 30
    assert p.require_unlock_on_resume is True
    assert p.neutral_project_names is True


def test_video_record_helpers_use_namespaced_kinds(tmp_path, monkeypatch):
    monkeypatch.setenv('CHARACTER3D_STUDIO_WORKSPACE', str(tmp_path))
    record = put_video_record('video_job', {'status': 'queued'})
    loaded = get_video_record('video_job', record['id'])
    assert loaded['status'] == 'queued'
    assert [x['id'] for x in list_video_records('video_job')] == [record['id']]
    with pytest.raises(ValueError):
        put_video_record('project', {'x': 1})
