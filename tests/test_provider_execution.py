import hashlib
import hmac

from app.providers.execution import CanonicalTaskStatus
from app.providers.hi3d import parse_task as parse_hi3d
from app.providers.meshy import multi_image_request, parse_task as parse_meshy
from app.providers.scoring import CandidateMetrics, rank_candidates
from app.providers.models import ProviderId
from app.providers.tripo import parse_task as parse_tripo, verify_webhook_signature


def test_tripo_task_normalization_and_assets():
    snap = parse_tripo({"code": 0, "data": {"task_id": "task_1", "status": "success", "progress": 100, "output": {"model_url": "https://cdn.tripo3d.ai/a.glb"}}})
    assert snap.status == CanonicalTaskStatus.SUCCEEDED
    assert snap.assets[0].format == "glb"


def test_meshy_task_normalization():
    snap = parse_meshy({"id": "m1", "status": "SUCCEEDED", "progress": 100, "model_urls": {"glb": "https://assets.meshy.ai/a.glb"}, "texture_urls": [{"base_color": "https://assets.meshy.ai/t.png"}]})
    assert snap.status == CanonicalTaskStatus.SUCCEEDED
    assert len(snap.assets) == 2


def test_hi3d_task_normalization_collects_https_outputs():
    snap = parse_hi3d({"code": 200, "msg": "success", "data": {"task_id": "h1", "status": "success", "result": {"model_url": "https://hitem3dstatic.zaohaowu.net/a.glb"}}})
    assert snap.status == CanonicalTaskStatus.SUCCEEDED
    assert any(a.format == "glb" for a in snap.assets)


def test_tripo_webhook_hmac_and_replay_window():
    body = b'{"type":"task.completed"}'
    ts = 1_700_000_000
    secret = "secret"
    sig = hmac.new(secret.encode(), str(ts).encode() + b"." + body, hashlib.sha256).hexdigest()
    header = f"t={ts},v1={sig}"
    assert verify_webhook_signature(body, header, secret, now=ts)
    assert not verify_webhook_signature(body, header, secret, now=ts + 301)


def test_meshy_multiview_refuses_4k():
    try:
        multi_image_request(["https://example.com/a.jpg", "https://example.com/b.jpg"], geometry_resolution="4k")
        assert False, "expected error"
    except ValueError:
        pass


def test_candidate_ranker_prefers_measured_quality_not_vendor_name():
    scores = rank_candidates([
        CandidateMetrics(provider=ProviderId.TRIPO, face_count=2_000_000, manifold_ratio=.98, degenerate_face_ratio=.001, uv_coverage_ratio=.95, pbr_channel_count=4, max_texture_resolution=8192, rig_ready=True, source_similarity=.92),
        CandidateMetrics(provider=ProviderId.HI3D, face_count=5_000_000, manifold_ratio=.80, degenerate_face_ratio=.04, uv_coverage_ratio=.6, pbr_channel_count=4, max_texture_resolution=4096, rig_ready=False, source_similarity=.88),
    ])
    assert scores[0].provider == ProviderId.TRIPO
