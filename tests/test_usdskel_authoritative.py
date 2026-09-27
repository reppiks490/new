import pytest

from app.exports.usdskel import validate_usdskel

pytest.importorskip("pxr")

IDENTITY = "((1,0,0,0),(0,1,0,0),(0,0,1,0),(0,0,0,1))"


def _rig(tmp_path, *, api=True, matrix=IDENTITY):
    meta = ' (\n prepend apiSchemas = ["SkelBindingAPI"]\n)' if api else ""
    p = tmp_path / "rig.usda"
    p.write_text(
        f'#usda 1.0\ndef SkelRoot "Character"{meta} {{\n'
        f' rel skel:skeleton = </Character/Skeleton>\n int[] primvars:skel:jointIndices = [0, 1]\n'
        f' def Skeleton "Skeleton" {{\n  uniform token[] joints = ["root", "root/spine"]\n'
        f'  uniform matrix4d[] bindTransforms = [{matrix}, {matrix}]\n'
        f'  uniform matrix4d[] restTransforms = [{matrix}, {matrix}]\n }}\n}}\n'
    )
    return p


def test_valid_rig_passes_with_computed_transforms(tmp_path):
    r = validate_usdskel(_rig(tmp_path))
    assert r.backend == "pxr" and r.authoritative
    assert r.passed and r.production_ready and r.computed_transform_validation


def test_malformed_matrices_are_a_blocker_not_a_crash(tmp_path):
    r = validate_usdskel(_rig(tmp_path, matrix="(1)"))
    assert not r.parsed and not r.passed
    assert "OpenUSD failed to parse" in r.blockers[0]


def test_binding_without_applied_api_is_diagnosed(tmp_path):
    r = validate_usdskel(_rig(tmp_path, api=False))
    assert not r.passed
    assert any("SkelBindingAPI" in b for b in r.blockers)
