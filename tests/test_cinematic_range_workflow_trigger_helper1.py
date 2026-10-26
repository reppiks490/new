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


def test_private_master_range_workflow_tracks_imported_cinematic_models_and_compiler():
    """Directly imported assembly models/compilers must trigger strict media QA.

    The FFmpeg test fixture creates and edits cinematic projects, and the
    assembly service imports these modules. A PR changing only one of them
    must not bypass the genuine-media Docker gate.
    """
    from fnmatch import fnmatchcase

    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github/workflows/cinematic-private-master-http-range-qa.yml"
    )
    source = workflow.read_text(encoding="utf-8")
    match = re.search(
        r"(?m)^on:\n  pull_request:\n    paths:\n(?P<entries>(?:      - .+\n)+)",
        source,
    )
    assert match, "Strict real-media QA needs explicit pull_request paths"
    watched = {
        line.split(" - ", 1)[1].strip().strip("'\\\"")
        for line in match["entries"].splitlines()
    }
    directly_imported = {
        "app/video/cinematic_models.py",
        "app/video/cinematic_compiler.py",
        "app/video/cinematic_requests.py",
        "app/video/models.py",
        "app/video/cinematic_editing.py",
    }
    missing = sorted(
        path for path in directly_imported
        if not any(fnmatchcase(path, pattern) for pattern in watched)
    )
    assert not missing, (
        "Strict FFmpeg/FFprobe/full-decode HTTP QA is skipped for cinematic "
        "project/assembly dependency-only edits: " + ", ".join(missing)
    )


def test_private_master_range_workflow_tracks_shared_studio_persistence_and_routes():
    """A shared SQLite/auth routing edit must not bypass strict media HTTP QA.

    The real-media fixture imports app.studio.server, which includes the studio
    router and invokes app.studio.storage for the persistent records that bind
    cinematic master identity and authenticated asset delivery.
    """
    from fnmatch import fnmatchcase

    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github/workflows/cinematic-private-master-http-range-qa.yml"
    )
    source = workflow.read_text(encoding="utf-8")
    match = re.search(
        r"(?m)^on:\n  pull_request:\n    paths:\n(?P<entries>(?:      - .+\n)+)",
        source,
    )
    assert match, "Strict media QA needs explicit pull_request paths"
    watched = {
        line.split(" - ", 1)[1].strip().strip("'\\\"")
        for line in match["entries"].splitlines()
    }
    shared_dependencies = {
        "app/studio/storage.py",  # SQLite persistence for master/job records
        "app/studio/router.py",  # mounted routes alongside private video assets
        "app/studio/parameters.py",  # server startup/static-root configuration
    }
    missing = sorted(
        path for path in shared_dependencies
        if not any(fnmatchcase(path, pattern) for pattern in watched)
    )
    assert not missing, (
        "Shared studio persistence or routing edits could bypass real-media "
        "private master HTTP QA: " + ", ".join(missing)
    )
