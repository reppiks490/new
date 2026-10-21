from pathlib import Path


def test_private_video_runtime_artifacts_and_secrets_are_git_ignored():
    root = Path(__file__).resolve().parents[1]
    lines = {
        line.strip()
        for line in (root / '.gitignore').read_text().splitlines()
        if line.strip() and not line.lstrip().startswith('#')
    }
    assert 'workspace/' in lines
    assert 'weights/' in lines
    assert '.env' in lines
    assert '.env.*' in lines
    assert '!.env.example' in lines
    assert 'vendor/LTX-2/' in lines
