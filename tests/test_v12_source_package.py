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


def test_egg_info_directories_excluded_from_manifest_and_zip(tmp_path: Path):
    # Real bug: a dev checkout that's ever run `pip install -e .` has a
    # <project>.egg-info/ directory sitting in the source tree, which is
    # NOT an exact match for anything in DEFAULT_EXCLUDED_PARTS (only
    # .venv/.git/__pycache__/etc. are exact-matched) -- confirmed by
    # actually building a release from this repo's own working tree and
    # finding character3d_masterbuild.egg-info inside the resulting zip
    # before this fix.
    root = tmp_path / "src"
    root.mkdir()
    (root / "real_source.py").write_text("x = 1")
    egg_info = root / "myproject.egg-info"
    egg_info.mkdir()
    (egg_info / "PKG-INFO").write_text("should not be packaged")

    manifest = build_source_release_manifest(root, version="1.2.0")
    manifest_paths = {f.path for f in manifest.files}
    assert "real_source.py" in manifest_paths
    assert not any("egg-info" in p for p in manifest_paths)

    out = tmp_path / "release.zip"
    build_deterministic_zip(root, out)
    import zipfile
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    assert "real_source.py" in names
    assert not any("egg-info" in n for n in names)


def test_zip_still_includes_release_manifest_json_itself(tmp_path: Path):
    # build_deterministic_zip must keep its existing behavior of including
    # release_manifest.json in the zip contents, even though
    # build_source_release_manifest excludes it from its own file listing
    # by default (the manifest describes the source tree; it isn't itself
    # part of what it's describing).
    root = tmp_path / "src"
    root.mkdir()
    (root / "a.py").write_text("x = 1")
    write_source_release_manifest(root, version="1.2.0")

    out = tmp_path / "release.zip"
    build_deterministic_zip(root, out)
    import zipfile
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    assert "release_manifest.json" in names
