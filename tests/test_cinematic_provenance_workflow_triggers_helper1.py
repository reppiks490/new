"""Guard the real-media provenance workflow against silent path-filter bypasses.

This test is intentionally independent of FFmpeg, Docker and PyYAML. A change
to the source-snapshot lease or startup-recovery caller must trigger the
separate Python 3.11/3.12 genuine-media regression, not only generic CI.
"""
from __future__ import annotations

import ast
from pathlib import Path
import re


WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github/workflows/cinematic-inflight-source-provenance-helper1.yml"
)

REQUIRED = {
    "app/video/cinematic_service.py",
    "app/video/cinematic_source_snapshots.py",
    "app/video/cinematic_assembly_jobs.py",
    "tools/cinematic_inflight_source_provenance_helper1.py",
    "tests/test_cinematic_provenance_workflow_triggers_helper1.py",
}


def _pull_request_paths(text: str) -> set[str]:
    # Match only the pull_request path list; a comment or unrelated job
    # mentioning a filename must not satisfy the trigger contract.
    match = re.search(
        r"(?m)^  pull_request:\s*\n    paths:\s*\n"
        r"(?P<entries>(?:      - [^\n]+\n)+)",
        text,
    )
    assert match is not None, "Missing pull_request.paths trigger"
    paths = set()
    for entry in match.group("entries").splitlines():
        value = entry.strip().removeprefix("- ").strip()
        paths.add(ast.literal_eval(value))
    return paths


def test_real_media_provenance_workflow_watches_all_recovery_dependencies() -> None:
    watched = _pull_request_paths(WORKFLOW.read_text(encoding="utf-8"))
    missing = REQUIRED - watched
    assert not missing, (
        "Genuine-media source-provenance CI will silently skip edits to "
        f"these relevant files: {sorted(missing)}"
    )


def test_real_media_provenance_workflow_retains_both_python_versions() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "fail-fast: false" in text
    assert re.search(r"python-version:\s*\['3\.11', '3\.12'\]", text)
    assert "docker run --rm" in text
