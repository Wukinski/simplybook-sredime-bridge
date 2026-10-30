import base64
import json
import os
import sqlite3
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from booking_bridge import recovery
from booking_bridge.model import Review


@pytest.fixture
def recovery_inputs(store, event, now, tmp_path):
    store.ingest(event, now)
    store.execute('INSERT INTO links VALUES(?,?,?,?,?)', ('synthetic-booking', 1001, now, '{}', 'active'))
    store.execute('INSERT INTO intents VALUES(?,?,?,?,?,?,?,?,?)',
                  ('synthetic-booking', event['id'], 'edit', 1001, '{}', '[]', 'uncertain', None, now))
    store.execute('INSERT INTO clients VALUES(?,?)', ('synthetic-client', 71))
    store.put('applied:synthetic-booking', {'private': 'SYNTHETIC_CONTACT_MUST_NOT_PRINT'}, now)
    store.rate('sredime-post:synthetic-employee', 60, now=now)
    store.issue('synthetic-issue', 'requires_review', now)
    store.refresh('synthetic-employee', now)
    key = tmp_path/'key.bin'
    key.write_bytes(os.urandom(32))
    key.chmod(0o600)
    return store.path, key, tmp_path/'backup.enc'


def rows(path):
    with sqlite3.connect(path) as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='sqlite_sequence'")]
        return {name: conn.execute('SELECT * FROM "' + name + '" ORDER BY rowid').fetchall() for name in tables}


def test_real_authenticated_roundtrip_preserves_all_rows_and_quarantines_worker(recovery_inputs, tmp_path):
    source, key, output = recovery_inputs
    before = rows(source)
    budget, timing, checkpoint = tmp_path/'budget.json', tmp_path/'last-request.json', tmp_path/'checkpoint.json'
    budget.write_text(json.dumps({'day': '2026-10-28', 'requests': 3999}))
    timing.write_text(json.dumps({'time': 1793199000}))
    checkpoint.write_text(json.dumps({'budget': {'day': '2026-10-28', 'requests': 317},
                                    'credentials': 'SYNTHETIC_PRIVATE_CHECKPOINT_MUST_NOT_EXPORT'}))
    manifest = recovery.backup(source, output, key, budget_files=[budget, timing], budget_floors=[checkpoint])
    assert rows(source) == before
    assert manifest['encrypted'] and manifest['off_host_export_prepared']
    assert manifest['off_host_export_performed'] is False
    assert manifest['database_summary']['unresolved_intents'] == 1
    assert manifest['database_summary']['table_counts']['rates'] == 1
    assert b'SYNTHETIC_CONTACT' not in output.read_bytes()
    assert str(key) not in json.dumps(manifest)
    assert key.read_bytes().hex() not in json.dumps(manifest)
    assert recovery.verify(output, key)['integrity_check'] == 'ok'
    target = tmp_path/'isolated.sqlite'
    restored = recovery.restore(output, target, key)
    restored_rows = rows(target)
    held = [row for row in restored_rows['cache'] if row[0] == 'recovery-hold']
    assert len(held) == 1 and json.loads(held[0][1])['worker_start_allowed'] is False
    restored_rows['cache'] = [row for row in restored_rows['cache'] if row[0] != 'recovery-hold']
    assert restored_rows == before
    assert restored['remote_reconciliation_required'] is True
    assert restored['budget_reconciliation_required'] is True
    assert restored['worker_start_allowed'] is False
    assert recovery.recovery_start_allowed(target) is False
    assert recovery.recovery_start_allowed(source) is True
    copied = tmp_path/'copied-alone.sqlite'
    copied.write_bytes(target.read_bytes())
    assert recovery.recovery_start_allowed(copied) is False
    assert restored['database_sha256'] == recovery._sha(target.read_bytes())
    assert restored['source_database_sha256'] == manifest['database_sha256']
    artifacts = Path(str(target) + '.budgets')
    assert json.loads((artifacts/'budget.json').read_text()) == {'day': '2026-10-28', 'requests': 3999}
    assert json.loads((artifacts/'last-request.json').read_text()) == {'time': 1793199000}
    assert json.loads((artifacts/'floor-1.json').read_text()) == {'budget': {'day': '2026-10-28', 'requests': 317}}
    assert 'SYNTHETIC_PRIVATE_CHECKPOINT' not in ''.join(p.read_text() for p in artifacts.iterdir())


@pytest.mark.parametrize('failure', ['tamper', 'wrong_key', 'truncate', 'header'])
def test_authentication_and_truncation_fail_before_restore_outputs(recovery_inputs, tmp_path, failure):
    source, key, encrypted = recovery_inputs
    recovery.backup(source, encrypted, key)
    if failure == 'wrong_key':
        key.write_bytes(os.urandom(32))
    else:
        body = bytearray(encrypted.read_bytes())
        if failure == 'tamper':
            body[-1] ^= 1
        elif failure == 'truncate':
            body = body[:len(recovery.MAGIC) + 15]
        else:
            body[0] ^= 1
        encrypted.write_bytes(body)
    target = tmp_path/'isolated.sqlite'
    with pytest.raises(Review):
        recovery.restore(encrypted, target, key)
    assert not target.exists()
    assert not Path(str(target) + recovery.MARKER_SUFFIX).exists()


@pytest.mark.parametrize('collision', ['backup', 'manifest', 'restore', 'marker', 'budgets'])
def test_existing_outputs_are_never_overwritten(recovery_inputs, tmp_path, collision):
    source, key, encrypted = recovery_inputs
    if collision in ('backup', 'manifest'):
        existing = encrypted if collision == 'backup' else Path(str(encrypted) + '.manifest.json')
        existing.write_bytes(b'PRESERVE_EXISTING')
        with pytest.raises(Review, match='output_exists'):
            recovery.backup(source, encrypted, key)
    else:
        recovery.backup(source, encrypted, key)
        target = tmp_path/'isolated.sqlite'
        existing = {'restore': target, 'marker': Path(str(target) + recovery.MARKER_SUFFIX),
                    'budgets': Path(str(target) + '.budgets')}[collision]
        existing.write_bytes(b'PRESERVE_EXISTING')
        with pytest.raises(Review, match='output_exists'):
            recovery.restore(encrypted, target, key)
    assert existing.read_bytes() == b'PRESERVE_EXISTING'


def test_verify_is_memory_only_and_does_not_create_plaintext_files(recovery_inputs, tmp_path):
    source, key, output = recovery_inputs
    recovery.backup(source, output, key)
    files = set(tmp_path.rglob('*'))
    assert recovery.verify(output, key)['authenticated'] is True
    assert set(tmp_path.rglob('*')) == files


def test_crash_before_marker_leaves_empty_reserved_database_blocked(recovery_inputs, tmp_path, monkeypatch):
    source, key, encrypted = recovery_inputs
    recovery.backup(source, encrypted, key)
    target = tmp_path/'isolated.sqlite'
    real_write = recovery._exclusive_write

    def interrupted(path, body):
        if path == Path(str(target) + recovery.MARKER_SUFFIX):
            assert target.exists() and target.stat().st_size == 0
            assert recovery.recovery_start_allowed(target) is False
            raise OSError('synthetic interruption')
        return real_write(path, body)

    monkeypatch.setattr(recovery, '_exclusive_write', interrupted)
    with pytest.raises(OSError):
        recovery.restore(encrypted, target, key)
    assert target.exists() and target.stat().st_size == 0
    assert recovery.recovery_start_allowed(target) is False


def test_restore_marker_is_durable_before_database_bytes_are_published(recovery_inputs, tmp_path, monkeypatch):
    source, key, encrypted = recovery_inputs
    recovery.backup(source, encrypted, key)
    target = tmp_path/'isolated.sqlite'
    real_write = recovery._write_reserved

    def interrupted(descriptor, body):
        if body.startswith(b'SQLite format 3\x00'):
            assert Path(str(target) + recovery.MARKER_SUFFIX).exists()
            assert recovery.recovery_start_allowed(target) is False
            os.close(descriptor)
            raise OSError('synthetic interruption')
        return real_write(descriptor, body)

    monkeypatch.setattr(recovery, '_write_reserved', interrupted)
    with pytest.raises(OSError):
        recovery.restore(encrypted, target, key)
    assert target.stat().st_size == 0
    assert recovery.recovery_start_allowed(target) is False


def test_online_backup_includes_committed_data_still_in_wal(recovery_inputs, tmp_path):
    source, key, encrypted = recovery_inputs
    with sqlite3.connect(source) as writer:
        assert writer.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal'
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute('INSERT INTO cache VALUES(?,?,?)', ('uncheckpointed-commit', 'true', 100))
        writer.commit()
        assert Path(str(source) + '-wal').stat().st_size > 0
        recovery.backup(source, encrypted, key)
        target = tmp_path/'wal-isolated.sqlite'
        recovery.restore(encrypted, target, key)
        with sqlite3.connect(target) as restored:
            assert restored.execute("SELECT value FROM cache WHERE key='uncheckpointed-commit'").fetchone() == ('true',)


@pytest.mark.parametrize('content', [b'not a database', b''])
def test_corrupt_or_partial_existing_database_never_allows_worker(tmp_path, content):
    database = tmp_path/'invalid.sqlite'
    database.write_bytes(content)
    assert recovery.recovery_start_allowed(database) is False


@pytest.mark.parametrize('problem', ['version', 'missing_table', 'trigger', 'unique_constraint'])
def test_unsupported_database_schema_is_rejected_before_encrypted_output(recovery_inputs, problem):
    source, key, output = recovery_inputs
    with sqlite3.connect(source) as conn:
        if problem == 'version':
            conn.execute('PRAGMA user_version=99')
        elif problem == 'missing_table':
            conn.execute('DROP TABLE rates')
        elif problem == 'trigger':
            conn.execute('CREATE TRIGGER unexpected AFTER INSERT ON clients BEGIN DELETE FROM clients; END')
        else:
            conn.execute('DROP TABLE clients')
            conn.execute('CREATE TABLE clients (source TEXT PRIMARY KEY, target INTEGER NOT NULL)')
    with pytest.raises(Review, match='schema_unsupported'):
        recovery.backup(source, output, key)
    assert not output.exists()


def test_authenticated_bundle_still_requires_database_integrity(recovery_inputs, tmp_path):
    source, key, encrypted = recovery_inputs
    recovery.backup(source, encrypted, key)
    body = encrypted.read_bytes()
    nonce = body[len(recovery.MAGIC):len(recovery.MAGIC)+12]
    cipher = AESGCM(key.read_bytes())
    bundle = json.loads(cipher.decrypt(nonce, body[len(recovery.MAGIC)+12:], recovery.MAGIC))
    bad_database = b'SQLite format 3\x00' + b'\x00' * 4096
    bundle['database'] = base64.b64encode(bad_database).decode()
    bundle['database_sha256'] = recovery._sha(bad_database)
    nonce = os.urandom(12)
    encrypted.write_bytes(recovery.MAGIC + nonce + cipher.encrypt(nonce, json.dumps(bundle).encode(), recovery.MAGIC))
    target = tmp_path/'isolated.sqlite'
    with pytest.raises((Review, sqlite3.DatabaseError)):
        recovery.restore(encrypted, target, key)
    assert not target.exists()


@pytest.mark.parametrize('artifact', ['secret.env', 'budget.json', 'last-request.json'])
def test_unknown_or_malformed_budget_artifacts_are_rejected(recovery_inputs, tmp_path, artifact):
    source, key, encrypted = recovery_inputs
    candidate = tmp_path/artifact
    candidate.write_text(json.dumps({'token': 'SYNTHETIC_SECRET_MUST_NOT_EXPORT'}))
    with pytest.raises(Review):
        recovery.backup(source, encrypted, key, budget_files=[candidate])
    assert not encrypted.exists()


def test_cli_errors_are_sanitized_and_key_path_can_come_from_environment(tmp_path, monkeypatch, capsys):
    key = tmp_path/'private-key-marker.bin'
    key.write_bytes(os.urandom(32))
    key.chmod(0o600)
    monkeypatch.setenv('BRIDGE_RECOVERY_KEY_FILE', str(key))
    assert recovery.main(['verify', '--source', str(tmp_path/'PRIVATE_SOURCE_NOT_LOGGED')]) == 2
    output = capsys.readouterr().out
    assert 'PRIVATE_SOURCE' not in output and str(key) not in output
    assert json.loads(output)['ok'] is False


def test_invalid_restore_marker_still_blocks_worker(tmp_path):
    database = tmp_path/'isolated.sqlite'
    Path(str(database) + recovery.MARKER_SUFFIX).write_text('invalid private marker')
    assert recovery.recovery_start_allowed(database) is False
