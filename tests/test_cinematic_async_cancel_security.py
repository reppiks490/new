"""Cancellation route regression for asynchronous cinematic jobs."""


def test_cancel_route_supports_post_only():
    from app.video.router import router
    matching = [r for r in router.routes if r.path.endswith('/assembly-jobs/{job_id}/cancel')]
    assert len(matching) == 1
    assert matching[0].methods == {'POST'}
