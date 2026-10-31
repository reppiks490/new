"""QA45: synthetic SQLite tests for opt-in malformed-row-safe queue reads.

No production worker, FFmpeg, owner media, model inference or mobile device.
"""
import json
import sqlite3

import pytest

from app.video import cinematic_queue_sql_guard_qa45 as safe

PROJECT = 'c' * 32
OTHER = 'd' * 32
KIND = 'video_assembly_job'
BAD = '{"status":"running", BROKEN'  # deliberately invalid JSON text


def seed(*entries):
    db = sqlite3.connect(':memory:')
    db.execute('CREATE TABLE records (id TEXT PRIMARY KEY, kind TEXT, data TEXT, updated REAL)')
    for identifier, project, status, updated in entries:
        payload = BAD if status == 'MALFORMED' else json.dumps({
            'project_id': project, 'status': status, 'project_revision': 1,
            'ffmpeg_path': 'ffmpeg',
        })
        db.execute('INSERT INTO records VALUES(?,?,?,?)', (identifier, KIND, payload, updated))
    return db


def test_unguarded_production_query_reproduces_malformed_json_failure():
    db = seed(('bad', PROJECT, 'MALFORMED', 1), ('good', PROJECT, 'queued', 2))
    with pytest.raises(sqlite3.OperationalError, match='malformed JSON'):
        db.execute("SELECT id FROM records WHERE kind=? AND json_extract(data,'$.status')='queued'", (KIND,)).fetchall()


def test_safe_fifo_claim_ignores_malformed_without_deleting_evidence():
    db = seed(('bad', PROJECT, 'MALFORMED', 0), ('late', PROJECT, 'queued', 3), ('early', PROJECT, 'queued', 2))
    before = db.execute('SELECT id,data,updated FROM records ORDER BY id').fetchall()
    assert safe.running_count(db) == 0
    assert safe.next_queued(db)[0] == 'early'
    assert db.execute('SELECT id,data,updated FROM records ORDER BY id').fetchall() == before


def test_running_guard_still_sees_live_worker():
    db = seed(('bad', PROJECT, 'MALFORMED', 0), ('live', OTHER, 'running', 1), ('pending', PROJECT, 'queued', 2))
    assert safe.running_count(db) == 1
    assert safe.next_queued(db)[0] == 'pending'  # caller must NOT claim while running_count > 0


def test_startup_recovery_scan_only_valid_running_rows():
    db = seed(('bad', PROJECT, 'MALFORMED', 0), ('live', PROJECT, 'running', 1), ('pending', PROJECT, 'queued', 2))
    assert [r[0] for r in safe.running_rows_for_recovery(db)] == ['live']
    assert db.execute('SELECT data FROM records WHERE id=?', ('bad',)).fetchone()[0] == BAD


def test_active_project_idempotency_isolated_and_capacity_counts():
    db = seed(('bad', PROJECT, 'MALFORMED', 0), ('one', PROJECT, 'queued', 1), ('two', OTHER, 'running', 2), ('done', PROJECT, 'succeeded', 3))
    assert [r[0] for r in safe.active_project_rows(db, PROJECT)] == ['one']
    assert [r[0] for r in safe.active_project_rows(db, OTHER)] == ['two']
    assert safe.outstanding_count(db) == 2


def test_history_count_pagination_and_bad_row_exclusion():
    db = seed(('bad', PROJECT, 'MALFORMED', 0), ('old', PROJECT, 'failed', 1), ('new', PROJECT, 'queued', 3), ('other', OTHER, 'queued', 4))
    total, page = safe.project_history_page(db, PROJECT, limit=1, offset=0)
    assert total == 2 and [r[0] for r in page] == ['new']
    total, page = safe.project_history_page(db, PROJECT, limit=1, offset=1)
    assert total == 2 and [r[0] for r in page] == ['old']


@pytest.mark.parametrize('limit,offset', [(0,0),(201,0),(1,-1),(True,0),(1,False),(1.5,0)])
def test_history_rejects_invalid_pagination(limit, offset):
    db = seed()
    with pytest.raises(ValueError):
        safe.project_history_page(db, PROJECT, limit=limit, offset=offset)


def test_project_scope_is_parameterized_not_sql_injection():
    db = seed(('one', PROJECT, 'queued', 1), ('two', OTHER, 'queued', 2))
    total, rows = safe.project_history_page(db, "' OR 1=1 --")
    assert total == 0 and rows == []
    assert safe.active_project_rows(db, "' OR 1=1 --") == []


def test_other_record_kind_malformed_text_does_not_poison_queue():
    db = seed(('good', PROJECT, 'queued', 1))
    db.execute('INSERT INTO records VALUES(?,?,?,?)', ('unrelated','video_project',BAD,0))
    assert safe.next_queued(db)[0] == 'good'
    assert safe.outstanding_count(db) == 1
