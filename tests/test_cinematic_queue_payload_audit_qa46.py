"""Synthetic SQLite-only QA46; no production worker, FFmpeg, owner media or phone."""
import importlib.util
import json
from pathlib import Path
import sqlite3

import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'tools' / 'cinematic_queue_payload_audit_qa46.py'
spec = importlib.util.spec_from_file_location('cinematic_queue_payload_audit_qa46', SOURCE)
audit = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(audit)
PRIVATE = 'OWNER_PRIVATE_SCREENPLAY_AND_TOKEN_DO_NOT_PRINT'


def db_with(tmp_path, *rows):
    path = tmp_path / 'private-owner.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE records(id TEXT PRIMARY KEY, kind TEXT, data TEXT, updated REAL)')
        for n, (kind, payload) in enumerate(rows):
            raw = json.dumps(payload) if not isinstance(payload, str) else payload
            db.execute('INSERT INTO records VALUES(?,?,?,?)', (str(n), kind, raw, 10.0 + n))
    return path


def job(status='queued', **updates):
    data = {'status': status, 'project_id': 'a' * 32, 'project_revision': 1,
            'ffmpeg_path': PRIVATE, 'private_prompt': PRIVATE}
    data.update(updates)
    return data


def test_valid_active_and_terminal_do_not_leak(tmp_path):
    path = db_with(tmp_path, ('video_assembly_job', job()),
                   ('video_assembly_job', job('running')),
                   ('video_assembly_job', job('failed')),
                   ('video_job', '{broken'))
    before = path.read_bytes()
    report = audit.inspect_payloads(path)
    assert report['counts']['valid_active'] == 2
    assert report['counts']['terminal_or_unrecognized'] == 1
    assert report['warnings'] == []
    assert PRIVATE not in json.dumps(report)
    assert path.read_bytes() == before


def test_valid_json_incomplete_running_is_flagged(tmp_path):
    path = db_with(tmp_path, ('video_assembly_job', {'status':'running','project_id':'a'*32}),
                   ('video_assembly_job', job()))
    report = audit.inspect_payloads(path)
    assert report['counts']['invalid_running_shape'] == 1
    assert report['counts']['valid_active'] == 1
    assert 'structurally_invalid_running_row_may_block_claims' in report['warnings']


@pytest.mark.parametrize('change', [
    {'project_revision': None}, {'project_revision': True}, {'project_revision': 0},
    {'project_id': PRIVATE}, {'ffmpeg_path': ''}, {'ffmpeg_path': 42},
])
def test_invalid_queued_fields_detected(tmp_path, change):
    path = db_with(tmp_path, ('video_assembly_job', job(**change)))
    report = audit.inspect_payloads(path)
    assert report['counts']['invalid_queued_shape'] == 1
    assert report['counts']['valid_active'] == 0
    assert PRIVATE not in json.dumps(report)


def test_malformed_and_non_object_json_are_distinguished(tmp_path):
    path = db_with(tmp_path, ('video_assembly_job', '{broken'),
                   ('video_assembly_job', '[1,2]'),
                   ('video_assembly_job', 'null'),
                   ('video_assembly_job', job()))
    report = audit.inspect_payloads(path)
    assert report['counts']['invalid_json'] == 1
    assert report['counts']['non_object_json'] == 2
    assert report['counts']['valid_active'] == 1


def test_missing_file_and_schema_fail_closed_without_leaking_path(tmp_path, capsys):
    missing = tmp_path / PRIVATE
    assert audit.main(['--db', str(missing)]) == 2
    assert not missing.exists()
    assert PRIVATE not in capsys.readouterr().out
    empty = tmp_path / 'empty.sqlite'
    with sqlite3.connect(empty):
        pass
    with pytest.raises(audit.QueueAuditError):
        audit.inspect_payloads(empty)


def test_cli_returns_only_neutral_json(tmp_path, capsys):
    path = db_with(tmp_path, ('video_assembly_job', job('running', ffmpeg_path='')))
    assert audit.main(['--db', str(path)]) == 0
    output = capsys.readouterr().out
    assert PRIVATE not in output and 'private-owner.sqlite' not in output
    assert json.loads(output)['counts']['invalid_running_shape'] == 1


def test_synthetic_production_sql_running_guard_counts_poisoned_running(tmp_path):
    path = db_with(tmp_path, ('video_assembly_job', {'status':'running','project_id':'a'*32}),
                   ('video_assembly_job', job()))
    with sqlite3.connect(path) as db:
        running = db.execute("SELECT COUNT(*) FROM records WHERE kind=? AND json_extract(data,'$.status')='running'", ('video_assembly_job',)).fetchone()[0]
        queued = db.execute("SELECT COUNT(*) FROM records WHERE kind=? AND json_extract(data,'$.status')='queued'", ('video_assembly_job',)).fetchone()[0]
    assert running == 1 and queued == 1
    assert audit.inspect_payloads(path)['counts']['invalid_running_shape'] == 1
