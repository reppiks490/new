from pathlib import Path

from app.runtime.checkpoints import StageCheckpointStore, compile_checkpoint, verify_checkpoint


def test_checkpoint_chain_and_rollback_plan(tmp_path: Path):
    store = StageCheckpointStore(tmp_path / 'checkpoints.db')
    c1 = compile_checkpoint('job', 'ingest', 1, 'succeeded', config={'x': 1}, output_sha256={'mesh': 'a'*64}, created_at=1)
    c2 = compile_checkpoint('job', 'repair', 1, 'succeeded', config={'x': 2}, input_sha256={'mesh': 'a'*64}, output_sha256={'mesh': 'b'*64}, parent_checkpoint_sha256=c1.checkpoint_sha256, created_at=2)
    c3 = compile_checkpoint('job', 'export', 1, 'succeeded', config={'x': 3}, input_sha256={'mesh': 'b'*64}, output_sha256={'glb': 'c'*64}, parent_checkpoint_sha256=c2.checkpoint_sha256, created_at=3)
    for c in (c1, c2, c3):
        assert verify_checkpoint(c)
        store.append(c)
    assert store.verify_chain('job')
    plan = store.rollback_plan('job', c1.checkpoint_sha256)
    assert plan.safe
    assert plan.invalidated_stages == ['repair', 'export']


def test_checkpoint_rollback_blocks_nonreversible_crossing(tmp_path: Path):
    store = StageCheckpointStore(tmp_path / 'checkpoints.db')
    c1 = compile_checkpoint('job', 'ingest', 1, 'succeeded', config={}, created_at=1)
    c2 = compile_checkpoint('job', 'external_publish', 1, 'succeeded', config={}, parent_checkpoint_sha256=c1.checkpoint_sha256, rollback_safe=False, created_at=2)
    store.append(c1); store.append(c2)
    plan = store.rollback_plan('job', c1.checkpoint_sha256)
    assert not plan.safe
    assert 'external_publish' in plan.blockers[0]
