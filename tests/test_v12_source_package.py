from pathlib import Path
import hashlib

from app.release.source_package import (
    build_deterministic_zip,
    build_source_release_manifest,
    verify_source_release_manifest,
    write_source_release_manifest,
)


def test_source_manifest_verifies_and_detects_change(tmp_path: Path):
    (tmp_path / 'a.txt').write_text('alpha')
    manifest = build_source_release_manifest(tmp_path, version='1.2.0')
    assert verify_source_release_manifest(tmp_path, manifest)
    (tmp_path / 'a.txt').write_text('beta')
    assert not verify_source_release_manifest(tmp_path, manifest)


def test_deterministic_zip_is_byte_identical(tmp_path: Path):
    root = tmp_path / 'src'; root.mkdir()
    (root / 'b.txt').write_text('beta')
    (root / 'a.txt').write_text('alpha')
    write_source_release_manifest(root, version='1.2.0')
    z1 = tmp_path / 'one.zip'; z2 = tmp_path / 'two.zip'
    build_deterministic_zip(root, z1)
    build_deterministic_zip(root, z2)
    assert hashlib.sha256(z1.read_bytes()).hexdigest() == hashlib.sha256(z2.read_bytes()).hexdigest()
    assert z1.read_bytes() == z2.read_bytes()
