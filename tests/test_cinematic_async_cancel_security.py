"""HTTP cancellation security regression for cinematic assembly jobs."""

from __future__ import annotations


def test_cancel_endpoint_is_present():
    from app.video.router import router
    paths = {route.path for route in router.routes}
    assert '/projects/{project_id}/assembly-jobs/{job_id}/cancel' in paths
