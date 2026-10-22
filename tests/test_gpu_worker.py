from app.gpu_worker import gpu_pool
from app.video import jobs as video_jobs


def test_video_jobs_use_shared_single_gpu_pool():
    assert video_jobs.pool is gpu_pool
    assert gpu_pool._max_workers == 1
