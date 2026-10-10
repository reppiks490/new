"""Generation lifecycle regressions with fake providers and real local storage."""
import builtins
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib
import io
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest
import trimesh

from app.providers.execution import CanonicalTaskStatus, ProviderTaskSnapshot, RemoteAsset
from app.studio import storage
from app.studio.server import app

studio = importlib.import_module('app.studio.router')


@pytest.fixture(autouse=True)
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv('CHARACTER3D_STUDIO_WORKSPACE', str(tmp_path))
    monkeypatch.delenv('CHARACTER3D_STUDIO_TOKEN', raising=False)
    for provider in ('TRIPO', 'MESHY', 'HI3D'):
        monkeypatch.delenv(f'{provider}_API_KEY', raising=False)
    return tmp_path


@pytest.fixture
def client():
    with TestClient(app) as value:
        yield value


def configure_generation(monkeypatch, executor):
    monkeypatch.setattr(studio, 'pool', executor)
    monkeypatch.setattr(studio, 'detect_runtime_readiness', lambda: SimpleNamespace(
        providers=[SimpleNamespace(name='provider:tripo', available=True)]))


def test_generation_admission_is_atomic_under_concurrent_requests(monkeypatch):
    executor = SimpleNamespace(submit=Mock())
    configure_generation(monkeypatch, executor)
    request = studio.GenerationRequest(prompt='A ceramic vase')

    def submit(_):
        try:
            return studio.generate(request)['status']
        except studio.HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=12) as workers:
        results = list(workers.map(submit, range(12)))
    assert results.count('queued') == 4
    assert results.count(429) == 8
    assert executor.submit.call_count == 4
    assert len(storage.list_records('job')) == 4


def test_admission_counts_active_jobs_older_than_the_display_limit():
    for _ in range(4):
        storage.enqueue_job({'provider': 'tripo'})
    for _ in range(105):
        storage.put('job', {'status': 'succeeded'})
    assert all(job['status'] == 'succeeded' for job in storage.list_records('job'))
    with pytest.raises(storage.JobCapacityError):
        storage.enqueue_job({'provider': 'tripo'})


def test_restart_recovers_all_unfinished_jobs_and_preserves_remote_ids():
    queued = storage.enqueue_job({'provider': 'tripo'})
    running = storage.put('job', {'status': 'running', 'task_id': 'remote-preview',
                                  'refine_task_id': 'remote-refine'})
    for _ in range(105):
        completed = storage.put('job', {'status': 'succeeded', 'asset_id': 'kept'})
    with TestClient(app) as client:
        for identifier in (queued['id'], running['id']):
            recovered = client.get('/api/studio/jobs/' + identifier).json()
            assert recovered['status'] == 'failed'
            assert recovered['stage'] == 'Interrupted'
        recovered = storage.get('job', running['id'])
        assert recovered['task_id'] == 'remote-preview'
        assert recovered['refine_task_id'] == 'remote-refine'
        assert storage.get('job', completed['id'])['status'] == 'succeeded'
    assert storage.enqueue_job({'provider': 'tripo'})['status'] == 'queued'


def test_database_connections_close_on_success_and_rollback(monkeypatch):
    opened = []
    connect = sqlite3.connect

    class TrackedConnection(sqlite3.Connection):
        closed = False

        def close(self):
            self.closed = True
            super().close()

    def tracked_connect(*args, **kwargs):
        db = connect(*args, **kwargs, factory=TrackedConnection)
        opened.append(db)
        return db

    monkeypatch.setattr(storage.sqlite3, 'connect', tracked_connect)
    record = storage.put('project', {'name': 'persisted'})
    assert storage.get('project', record['id'])['name'] == 'persisted'
    assert storage.list_records('project') == [record]
    with pytest.raises(RuntimeError, match='rollback'):
        with storage.connection() as db:
            db.execute("DELETE FROM records WHERE kind='project'")
            raise RuntimeError('rollback')
    assert storage.get('project', record['id'])['name'] == 'persisted'
    assert opened and all(db.closed for db in opened)


def test_worker_submission_failure_releases_the_reserved_slot(client, monkeypatch):
    configure_generation(monkeypatch, SimpleNamespace(submit=Mock(side_effect=RuntimeError('closed'))))
    response = client.post('/api/studio/generate', json={'prompt': 'A ceramic vase'})
    assert response.status_code == 503
    [job] = storage.list_records('job')
    assert job['status'] == 'failed'
    assert 'unavailable' in job['error']
    assert 'asset_url' not in job


def test_worker_import_error_is_persisted_instead_of_leaving_a_queued_job(monkeypatch):
    job = storage.enqueue_job({'provider': 'tripo'})
    original = builtins.__import__

    def fail_import(name, *args, **kwargs):
        if name == 'app.providers.execution':
            raise ImportError('Provider dependency is unavailable')
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', fail_import)
    studio.execute_generation(job['id'], studio.GenerationRequest(prompt='A ceramic vase'))
    result = storage.get('job', job['id'])
    assert result['status'] == 'failed'
    assert result['error'] == 'Provider dependency is unavailable'


def test_missing_credentials_fail_the_worker_without_fake_assets():
    job = storage.enqueue_job({'provider': 'tripo'})
    studio.execute_generation(job['id'], studio.GenerationRequest(prompt='A ceramic vase'))
    result = storage.get('job', job['id'])
    assert result['status'] == 'failed'
    assert 'TRIPO_API_KEY' in result['error']
    assert 'asset_url' not in result


@pytest.mark.parametrize('provider', ['tripo', 'meshy', 'hi3d'])
def test_each_provider_reaches_verified_downloadable_glb(provider, client, monkeypatch, workspace):
    monkeypatch.setenv(f'{provider.upper()}_API_KEY', 'configured-test-key')
    model = workspace / 'provider.glb'
    trimesh.creation.icosphere(subdivisions=1).export(model)
    digest = hashlib.sha256(model.read_bytes()).hexdigest()
    calls = []
    transport = SimpleNamespace(close=Mock())

    class Provider:
        def __init__(self, key):
            assert key == 'configured-test-key'
            self.transport = transport

        def create_text(self, prompt):
            calls.append(('text', prompt))
            return 'generated'

        def create_text_preview(self, prompt):
            calls.append(('preview', prompt))
            return 'preview'

        def create_text_refine(self, identifier, **options):
            calls.append(('refine', identifier, options))
            return 'refined'

        def create_image_file(self, path):
            assert path.is_file()
            calls.append(('image', path.name))
            return 'generated', None

        def query(self, identifier):
            calls.append(('query', identifier))
            return ProviderTaskSnapshot(provider=provider, task_id=identifier,
                                        status=CanonicalTaskStatus.SUCCEEDED, progress=100)

        query_text = query

    module = importlib.import_module(f'app.providers.{provider}')
    monkeypatch.setattr(module, {'tripo': 'TripoClient', 'meshy': 'MeshyClient', 'hi3d': 'Hi3DClient'}[provider], Provider)
    ingest = importlib.import_module('app.providers.ingest')

    def admit(snapshot, path, **kwargs):
        assert snapshot.task_id == ('refined' if provider == 'meshy' else 'generated')
        return snapshot.model_copy(update={'assets': [RemoteAsset(
            kind='model', url='https://assets.example.test/model.glb', format='glb',
            local_path=str(model), sha256=digest)]})

    monkeypatch.setattr(ingest, 'ingest_terminal_snapshot', admit)
    image_id = 'a' * 32
    if provider == 'hi3d':
        from PIL import Image
        Image.new('RGB', (8, 8)).save(storage.asset_path(image_id, 'png'))
    job = storage.enqueue_job({'provider': provider})
    request = studio.GenerationRequest(provider=provider, prompt='A ceramic vase',
                                        kind='image' if provider == 'hi3d' else 'text',
                                        image_id=image_id if provider == 'hi3d' else None)
    studio.execute_generation(job['id'], request)
    result = client.get('/api/studio/jobs/' + job['id']).json()
    assert result['status'] == 'succeeded', result
    assert result['sha256'] == digest
    assert result['fully_morph_compatible'] is False
    downloaded = client.get(result['asset_url'])
    assert downloaded.status_code == 200
    assert hashlib.sha256(downloaded.content).hexdigest() == digest
    assert trimesh.load(io.BytesIO(downloaded.content), file_type='glb', force='scene').geometry
    transport.close.assert_called_once()
    if provider == 'meshy':
        assert calls == [('preview', 'A ceramic vase'), ('query', 'preview'),
                         ('refine', 'preview', {'texture_resolution': '4k'}), ('query', 'refined')]
        assert result['task_id'] == 'preview' and result['refine_task_id'] == 'refined'


@pytest.mark.parametrize('prefix', ['', 'x' * 980])
def test_provider_failure_redacts_trimmed_keys_before_truncating_and_closes_transport(prefix, monkeypatch):
    key = 'sensitive-provider-credential-value'
    monkeypatch.setenv('TRIPO_API_KEY', '  ' + key + '  ')
    transport = SimpleNamespace(close=Mock())

    class Provider:
        def __init__(self, value):
            assert value == key
            self.transport = transport

        def create_text(self, prompt):
            raise RuntimeError(prefix + 'Bearer ' + key)

    monkeypatch.setattr(importlib.import_module('app.providers.tripo'), 'TripoClient', Provider)
    job = storage.enqueue_job({'provider': 'tripo'})
    studio.execute_generation(job['id'], studio.GenerationRequest(prompt='A ceramic vase'))
    result = storage.get('job', job['id'])
    assert result['status'] == 'failed'
    assert 'sensitive' not in result['error'] and '[redacted]' in result['error']
    assert len(result['error']) <= 1000
    assert 'asset_url' not in result
    transport.close.assert_called_once()
