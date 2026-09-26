from app.release.canonical import CanonicalArtifact, compile_canonical_release_manifest
from app.release.diff import compare_canonical_releases
from app.workers.execution_evidence import ExecutionEvidence, ExecutionMode


def ev(stage, mode=ExecutionMode.LIVE, success=True):
    return ExecutionEvidence(stage=stage, mode=mode, success=success, tool='x', started_at=1, finished_at=2)


def test_release_diff_reports_artifact_and_evidence_changes():
    before = compile_canonical_release_manifest(
        'j', [CanonicalArtifact(name='hero', kind='glb', size_bytes=10, sha256='a'*64)],
        [ev('provider_ingest')], production_gate_passed=False, required_live_stages=['provider_ingest'], created_at_unix=1,
    )
    after = compile_canonical_release_manifest(
        'j', [CanonicalArtifact(name='hero', kind='glb', size_bytes=12, sha256='b'*64)],
        [ev('provider_ingest', ExecutionMode.SYNTHETIC)], production_gate_passed=False, required_live_stages=['provider_ingest'], created_at_unix=2,
    )
    diff = compare_canonical_releases(before, after)
    assert not diff.identical
    assert diff.changed_artifacts[0].key == 'glb:hero'
    assert diff.evidence_changes[0].stage == 'provider_ingest'
