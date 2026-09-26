from pathlib import Path
import pytest

from app.runtime.lineage import ArtifactLineageStore


def h(ch: str) -> str:
    return ch * 64


def test_lineage_is_immutable_and_rollback_changes_pointer_only(tmp_path: Path):
    store = ArtifactLineageStore(tmp_path / 'lineage.db')
    v1 = store.register('hero', h('a'), 'provider_ingest')
    v2 = store.register('hero', h('b'), 'blender', parent_sha256=v1.sha256)
    assert store.current('hero').sha256 == h('b')
    event = store.rollback('hero', h('a'), reason='bad bake', expected_current_sha256=h('b'))
    assert event.from_sha256 == h('b')
    assert store.current('hero').sha256 == h('a')
    assert [v.sha256 for v in store.history('hero')] == [h('a'), h('b')]
    assert store.history('hero')[1].parent_sha256 == h('a')


def test_lineage_cas_prevents_lost_update(tmp_path: Path):
    store = ArtifactLineageStore(tmp_path / 'lineage.db')
    store.register('hero', h('a'), 'ingest')
    store.register('hero', h('b'), 'qa', parent_sha256=h('a'))
    with pytest.raises(RuntimeError):
        store.set_active('hero', h('a'), expected_current_sha256=h('c'))


def test_lineage_requires_parent_in_same_asset(tmp_path: Path):
    store = ArtifactLineageStore(tmp_path / 'lineage.db')
    with pytest.raises(ValueError):
        store.register('hero', h('b'), 'qa', parent_sha256=h('a'))
