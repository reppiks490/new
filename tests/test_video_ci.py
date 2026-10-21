from pathlib import Path


def test_ci_runs_browser_privacy_suite_on_python311_leg():
    workflow = (Path(__file__).resolve().parents[1] / '.github' / 'workflows' / 'ci.yml').read_text(encoding='utf-8')
    assert "node --test tests/*.mjs" in workflow
    assert "matrix.python-version == '3.11'" in workflow
