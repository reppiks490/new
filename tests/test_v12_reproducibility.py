from pathlib import Path

from app.release.reproducibility import compile_build_fingerprint, compare_build_fingerprints, verify_build_fingerprint


def test_build_fingerprint_is_mtime_independent(tmp_path: Path):
    (tmp_path / 'a.txt').write_text('alpha')
    first = compile_build_fingerprint(tmp_path, metadata={'v': 1})
    (tmp_path / 'a.txt').touch()
    second = compile_build_fingerprint(tmp_path, metadata={'v': 1})
    assert first.root_digest_sha256 == second.root_digest_sha256
    assert verify_build_fingerprint(tmp_path, first)


def test_build_fingerprint_detects_content_change_and_ignores_cache(tmp_path: Path):
    (tmp_path / 'a.txt').write_text('alpha')
    cache = tmp_path / '__pycache__'
    cache.mkdir()
    (cache / 'x.pyc').write_bytes(b'noise')
    before = compile_build_fingerprint(tmp_path)
    (tmp_path / 'a.txt').write_text('beta')
    after = compile_build_fingerprint(tmp_path)
    diff = compare_build_fingerprints(before, after)
    assert not diff.identical
    assert diff.changed == ['a.txt']
    assert all('__pycache__' not in f.path for f in after.files)
