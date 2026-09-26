from app.providers.execution import ProviderExecutionError
from app.providers.meshy import MeshyClient
from app.providers.meshy_pipeline import run_preview_refine


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _ScriptedTransport:
    def __init__(self, script):
        self.script = list(script)
        self.calls: list[tuple[str, str]] = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url))
        status, payload = self.script.pop(0)
        return _FakeResponse(status, payload)


def _client(script):
    return MeshyClient("test-key", transport=_ScriptedTransport(script))


def test_full_preview_refine_chain_succeeds():
    script = [
        (200, {"result": "preview-123"}),                                  # create preview
        (200, {"id": "preview-123", "status": "IN_PROGRESS", "progress": 40}),   # poll 1
        (200, {"id": "preview-123", "status": "SUCCEEDED", "model_urls": {"glb": "https://assets.meshy.ai/p.glb"}}),  # poll 2
        (200, {"result": "refine-456"}),                                   # create refine
        (200, {"id": "refine-456", "status": "IN_PROGRESS", "progress": 60}),    # poll 1
        (200, {"id": "refine-456", "status": "SUCCEEDED", "model_urls": {"glb": "https://assets.meshy.ai/r.glb"}, "texture_urls": [{"base_color": "https://assets.meshy.ai/t.png"}]}),  # poll 2
    ]
    client = _client(script)
    receipt = run_preview_refine(client, "a fictional adventurer", sleep=lambda s: None, max_polls=5)

    assert receipt.succeeded
    assert receipt.preview_task_id == "preview-123"
    assert receipt.refine_task_id == "refine-456"
    assert receipt.refine_snapshot.assets  # both model + texture assets parsed
    assert receipt.stage_log == [
        "preview_submit:preview-123",
        "preview_poll:succeeded",
        "refine_submit:refine-456",
        "refine_poll:succeeded",
    ]


def test_preview_failure_stops_before_refine_is_ever_submitted():
    script = [
        (200, {"result": "preview-123"}),
        (200, {"id": "preview-123", "status": "FAILED", "task_error": {"message": "bad prompt"}}),
    ]
    client = _client(script)
    receipt = run_preview_refine(client, "prompt", sleep=lambda s: None, max_polls=5)

    assert not receipt.succeeded
    assert receipt.status == "failed"
    assert "bad prompt" in receipt.error
    assert receipt.refine_task_id is None
    # Only 2 HTTP calls were made: create preview + one poll. Refine was never
    # submitted, proving the failure short-circuits rather than plowing ahead.
    assert len(client.transport.calls) == 2


def test_refine_failure_is_reported_after_preview_succeeded():
    script = [
        (200, {"result": "preview-123"}),
        (200, {"id": "preview-123", "status": "SUCCEEDED", "model_urls": {"glb": "https://assets.meshy.ai/p.glb"}}),
        (200, {"result": "refine-456"}),
        (200, {"id": "refine-456", "status": "FAILED", "task_error": {"message": "refine texture error"}}),
    ]
    client = _client(script)
    receipt = run_preview_refine(client, "prompt", sleep=lambda s: None, max_polls=5)

    assert not receipt.succeeded
    assert receipt.preview_task_id == "preview-123"
    assert receipt.refine_task_id == "refine-456"
    assert "refine texture error" in receipt.error


def test_task_creation_http_error_is_caught_and_reported():
    script = [(401, {"message": "invalid api key"})]
    client = _client(script)
    receipt = run_preview_refine(client, "prompt", sleep=lambda s: None, max_polls=5)

    assert not receipt.succeeded
    assert "invalid api key" in receipt.error
    assert receipt.preview_task_id == ""


def test_stalled_task_stops_after_max_polls_without_hanging():
    # Every poll returns IN_PROGRESS forever; max_polls must bound the loop.
    script = [(200, {"result": "preview-123"})]
    script += [(200, {"id": "preview-123", "status": "IN_PROGRESS", "progress": 1})] * 4
    client = _client(script)
    receipt = run_preview_refine(client, "prompt", sleep=lambda s: None, max_polls=3)

    assert not receipt.succeeded
    assert receipt.preview_snapshot is not None
    assert not receipt.preview_snapshot.terminal
    assert "preview task ended in status" in receipt.error
