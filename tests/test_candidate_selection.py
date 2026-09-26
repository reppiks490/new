from pathlib import Path

import trimesh

from app.providers.models import ProviderId
from app.providers.selection import LocalCandidate, evaluate_local_candidates, promote_best_candidate


def test_local_candidate_ranking_uses_measured_geometry(tmp_path: Path):
    clean = trimesh.creation.icosphere(subdivisions=2)
    clean_path = tmp_path / "clean.obj"
    clean.export(clean_path)

    broken = trimesh.creation.box()
    broken.faces = broken.faces[:-2]
    broken_path = tmp_path / "broken.obj"
    broken.export(broken_path)

    ranked = evaluate_local_candidates([
        LocalCandidate(provider=ProviderId.HI3D, model_path=str(broken_path), pbr_channel_count=4, max_texture_resolution=8192),
        LocalCandidate(provider=ProviderId.TRIPO, model_path=str(clean_path), pbr_channel_count=4, max_texture_resolution=8192),
    ], target_faces=clean.faces.shape[0])
    assert ranked[0].candidate.provider == ProviderId.TRIPO
    assert ranked[0].inspection.manifold_edge_ratio >= ranked[1].inspection.manifold_edge_ratio


def test_promotion_is_atomic_and_receipted(tmp_path: Path):
    mesh = trimesh.creation.box()
    source = tmp_path / "source.obj"
    mesh.export(source)
    target = tmp_path / "canonical" / "hero.obj"
    receipt_path = tmp_path / "canonical" / "promotion.json"

    receipt = promote_best_candidate([
        LocalCandidate(provider=ProviderId.MESHY, model_path=str(source), pbr_channel_count=4, max_texture_resolution=8192)
    ], target, target_faces=12, receipt_path=receipt_path)

    assert target.exists()
    assert receipt_path.exists()
    assert receipt.winner.sha256
    assert receipt.canonical_model_path == str(target)
