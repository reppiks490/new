"""Helper 1: ensure strict real-media HTTP QA follows its production dependencies.

This static regression runs in ordinary Python CI (without FFmpeg) and
guards the opt-in FFmpeg workflow's path filters. The strict media runner
copies only its synthetic media test into a minimal Docker context.
"""
from pathlib import Path
import re


def test_private_master_range_workflow_covers_storage_and_assembly_changes():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github/workflows/cinematic-private-master-http-range-qa.yml"
    )
    source = workflow.read_text(encoding="utf-8")
    match = re.search(
        r"(?m)^on:\n  pull_request:\n    paths:\n(?P<entries>(?:      - .+\n)+)",
        source,
    )
    assert match, "Strict real-media QA must have an explicit pull_request path filter"
    watched = set(
        re.findall(r"(?m)^      - ['\"]?([^'\"\n]+)['\"]?$", match["entries"])
    )
    required = {
        "app/video/storage.py",  # persisted master size/SHA and asset lookup
        "app/video/cinematic_service.py",  # FFmpeg master assembly/cache behavior
        "Dockerfile.cinematic",  # FFmpeg executable and container Python runtime
        "pyproject.toml",  # installed application and test dependency versions
        "app/video/jobs.py",  # MP4 signature and source asset validation
    }
    assert required <= watched, (
        "Private master storage or assembly edits must run genuine H.264/"
        "FFprobe/full-decode HTTP QA; missing: "
        + ", ".join(sorted(required - watched))
    )
