"""QA98: guard final integration-branch execution of 600s real-media acceptance.

Static CI contract only: this does not run FFmpeg, prove media quality, or
verify any combined integration commit. The dedicated QA97 workflow does that.
"""
from __future__ import annotations

from pathlib import Path
import re


WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github/workflows/cinematic-600s-fractional-cut-qa97.yml"
)
CANONICAL_BRANCH = "feat/cinematic-orchestrator-v1"


def _event_body(workflow: str, event: str) -> str:
    """Read a top-level YAML event block without a third-party YAML parser."""
    match = re.search(
        rf"(?m)^  {re.escape(event)}:\s*\n(?P<body>(?:^    .*\n|^\s*\n)*)",
        workflow,
    )
    assert match is not None, f"Missing {event!r} trigger in {WORKFLOW.name}"
    return match.group("body")


def test_600s_real_media_runs_on_every_canonical_integration_push():
    """PR-only green checks must not substitute for final integration-SHA QA."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    push = _event_body(workflow, "push")
    assert re.search(r"(?m)^    branches:\s*$", push)
    branches = re.findall(r"(?m)^      -\s+(.+?)\s*$", push)
    assert [branch.strip("\'\"") for branch in branches] == [CANONICAL_BRANCH]
    assert not re.search(r"(?m)^    paths(?:-ignore)?:", push), (
        "Final integration-SHA acceptance must not be skipped by path filters"
    )


def test_600s_integration_gate_preserves_pr_manual_and_offline_boundaries():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    _event_body(workflow, "pull_request")
    assert re.search(r"(?m)^  workflow_dispatch:\s*$", workflow)
    assert "--network none --read-only" in workflow
    assert "--pids-limit 2048 --memory 4g" in workflow
    assert "--env CINEMATIC_FRACTIONAL_MEDIA_QA=1" in workflow
    assert "tests/test_cinematic_600s_fractional_cut_qa97.py" in workflow
