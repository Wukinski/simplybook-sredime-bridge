"""Local authenticated backup and isolated restore; no uploads or account calls.

SQLite's online backup is serialized in memory, so no temporary plaintext copy
is written. Restores always create a new file with a durable worker-start hold.
"""
import argparse
import base64
import hashlib
import json
import math
import os
import re
import sqlite3
import stat
import sys
import time
from contextlib import closing
from datetime import date
from pathlib import Path

from .model import Review
from .store import SCHEMA

MAGIC = b'ANDJELIJA-RECOVERY\x00\x01'
MAX_DATABASE_BYTES = 128 * 1024 * 1024
MAX_BUNDLE_BYTES = 192 * 1024 * 1024
MAX_ARTIFACT_BYTES = 1024 * 1024
MARKER_SUFFIX = '.recovery.json'


def _json(body):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError()
            value[key] = item
        return value
    return json.loads(body, object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError()))


def _bytes(path, limit):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise Review('recovery_input_invalid')
    with path.open('rb') as handle:
        body = handle.read(limit + 1)
    if len(body) > limit:
        raise Review('recovery_input_too_large')
    return body


def _key(path):
    path = Path(path)
    if os.name != 'nt' and stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise Review('recovery_key_permissions_required')
    value = _bytes(path, 32)
    if len(value) != 32:
        raise Review('recovery_key_must_be_32_bytes')
    return value


def _aes(key):
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        raise Review('recovery_crypto_unavailable') from None
    return AESGCM(key)


def _sha(body):
    return hashlib.sha256(body).hexdigest()


def _encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _exclusive_write(path, body):
    # O_EXCL reserves a new destination; no replace/overwrite fallback exists.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    _write_reserved(descriptor, body)


def _write_reserved(descriptor, body):
    with os.fdopen(descriptor, 'wb') as handle:
        handle.write(body)
        handle.flush()
        os.fsync(handle.fileno())


def _available(paths):
    if any(Path(path).exists() or Path(path).is_symlink() for path in paths):
        raise Review('recovery_output_exists')
    if any(not Path(path).parent.is_dir() for path in paths):
        raise Review('recovery_output_parent_required')


def _schema(connection):
    rows = connection.execute("SELECT name,type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
    if any(kind not in ('table', 'index') for _, kind in rows):
        raise Review('recovery_schema_unsupported')
    tables = [name for name, kind in rows if kind == 'table']
    if any(not re.fullmatch('[a-z][a-z0-9_]*', name) for name in tables):
        raise Review('recovery_schema_unsupported')
    result = {}
    for name in tables:
        columns = [tuple(row)[1:] for row in connection.execute('PRAGMA table_info("' + name + '")')]
        indexes = []
        for index in connection.execute('PRAGMA index_list("' + name + '")'):
            index_name = index[1]
            if not re.fullmatch('[A-Za-z_][A-Za-z0-9_]*', index_name):
                raise Review('recovery_schema_unsupported')
            indexes.append((index[2], index[3], index[4],
                            tuple(tuple(row)[1:] for row in connection.execute('PRAGMA index_info("' + index_name + '")'))))
        result[name] = (columns, sorted(indexes))
    return result


def _inspect_database(connection):
    if connection.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
        raise Review('recovery_database_integrity_failed')
    if connection.execute('PRAGMA user_version').fetchone()[0] != 1:
        raise Review('recovery_schema_unsupported')
    with closing(sqlite3.connect(':memory:')) as reference, reference:
        reference.executescript(SCHEMA)
        if _schema(connection) != _schema(reference):
            raise Review('recovery_schema_unsupported')
    tables = _schema(connection)
    counts = {name: connection.execute('SELECT COUNT(*) FROM "' + name + '"').fetchone()[0]
              for name in tables}
    return {'schema_version': 1, 'table_counts': counts,
            'unresolved_intents': connection.execute("SELECT COUNT(*) FROM intents WHERE state!='done'").fetchone()[0],
            'queued_events': connection.execute("SELECT COUNT(*) FROM events WHERE state IN ('queued','working')").fetchone()[0],
            'open_issues': connection.execute('SELECT COUNT(*) FROM issues WHERE resolved=0').fetchone()[0]}


def _online_snapshot(source):
    source = Path(source)
    if source.is_symlink() or not source.is_file():
        raise Review('recovery_source_database_required')
    deadline = time.monotonic() + 60
    def progress(status, remaining, total):
        if time.monotonic() >= deadline or total * 4096 > MAX_DATABASE_BYTES * 16:
            raise Review('recovery_snapshot_bound_exceeded')
    with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)) as original, original:
        size = original.execute('PRAGMA page_count').fetchone()[0] * original.execute('PRAGMA page_size').fetchone()[0]
        if size > MAX_DATABASE_BYTES:
            raise Review('recovery_database_too_large')
        with closing(sqlite3.connect(':memory:')) as snapshot, snapshot:
            snapshot.execute('PRAGMA temp_store=MEMORY')
            original.backup(snapshot, pages=256, progress=progress, sleep=0.05)
            # Online backup from WAL retains WAL header bytes even for an
            # in-memory destination. Rebuild this private memory image with
            # SQLite itself so deserialize needs no external -wal file.
            snapshot.execute('VACUUM')
            summary = _inspect_database(snapshot)
            body = snapshot.serialize()
    if len(body) > MAX_DATABASE_BYTES:
        raise Review('recovery_database_too_large')
    return body, summary


def _budget(value):
    if (not isinstance(value, dict) or set(value) != {'day', 'requests'} or
            type(value['requests']) is not int or value['requests'] < 0):
        raise Review('recovery_budget_invalid')
    day = value['day']
    if day is None:
        if value['requests'] != 0:
            raise Review('recovery_budget_invalid')
    elif not isinstance(day, str) or date.fromisoformat(day).isoformat() != day:
        raise Review('recovery_budget_invalid')
    return value


def _budget_files(files, floors):
    saved = {}
    for source in files:
        source = Path(source)
        if source.name not in ('budget.json', 'last-request.json') or source.name in saved:
            raise Review('recovery_explicit_budget_artifact_required')
        value = _json(_bytes(source, MAX_ARTIFACT_BYTES))
        if source.name == 'budget.json':
            _budget(value)
        elif (not isinstance(value, dict) or set(value) != {'time'} or
              type(value['time']) not in (int, float) or not math.isfinite(value['time']) or value['time'] < 0):
            raise Review('recovery_budget_invalid')
        saved[source.name] = value
    extracted = [_budget(_json(_bytes(source, MAX_BUNDLE_BYTES))['budget']) for source in floors]
    return saved, extracted


def backup(source, output, key_file, *, budget_files=(), budget_floors=()):
    """Prepare ciphertext and a sanitized local export manifest, never upload."""
    output = Path(output)
    manifest_path = Path(str(output) + '.manifest.json')
    _available([output, manifest_path])
    cipher = _aes(_key(key_file))
    database, summary = _online_snapshot(source)
    artifacts, floors = _budget_files(budget_files, budget_floors)
    created_at = time.time()
    bundle = {'format_version': 1, 'created_at': created_at, 'database': base64.b64encode(database).decode('ascii'),
              'database_sha256': _sha(database), 'database_summary': summary,
              'budget_files': artifacts, 'budget_floors': floors}
    plaintext = _encode(bundle)
    if len(plaintext) > MAX_BUNDLE_BYTES:
        raise Review('recovery_bundle_too_large')
    nonce = os.urandom(12)
    encrypted = MAGIC + nonce + cipher.encrypt(nonce, plaintext, MAGIC)
    manifest = {'format_version': 1, 'created_at': created_at, 'encrypted': True, 'algorithm': 'AES-256-GCM',
                'ciphertext_sha256': _sha(encrypted), 'database_sha256': _sha(database),
                'database_summary': summary, 'budget_files': len(artifacts), 'budget_floors': len(floors),
                'off_host_export_prepared': True, 'off_host_export_performed': False,
                'remote_reconciliation_required': True, 'worker_start_allowed': False}
    _exclusive_write(output, encrypted)
    try:
        _exclusive_write(manifest_path, _encode(manifest))
    except Exception:
        # Preserve the valid encrypted backup if a concurrent manifest collision
        # occurs. Its verified metadata can still be read with verify().
        raise Review('recovery_manifest_not_written_backup_retained') from None
    return manifest


def _decrypt(source, key_file):
    encrypted = _bytes(source, MAX_BUNDLE_BYTES + len(MAGIC) + 28)
    if len(encrypted) < len(MAGIC) + 28 or not encrypted.startswith(MAGIC):
        raise Review('recovery_encrypted_format_invalid')
    nonce = encrypted[len(MAGIC):len(MAGIC) + 12]
    try:
        plaintext = _aes(_key(key_file)).decrypt(nonce, encrypted[len(MAGIC) + 12:], MAGIC)
    except Review:
        raise
    except Exception:
        raise Review('recovery_authentication_failed') from None
    bundle = _json(plaintext)
    if (not isinstance(bundle, dict) or set(bundle) != {'format_version', 'created_at', 'database', 'database_sha256',
            'database_summary', 'budget_files', 'budget_floors'} or
            type(bundle['format_version']) is not int or bundle['format_version'] != 1 or
            type(bundle['created_at']) not in (int, float) or not math.isfinite(bundle['created_at']) or bundle['created_at'] <= 0 or
            not isinstance(bundle['budget_files'], dict) or not isinstance(bundle['budget_floors'], list)):
        raise Review('recovery_bundle_invalid')
    database = base64.b64decode(bundle['database'], validate=True)
    if len(database) > MAX_DATABASE_BYTES or _sha(database) != bundle['database_sha256']:
        raise Review('recovery_database_hash_mismatch')
    if not database.startswith(b'SQLite format 3\x00'):
        raise Review('recovery_database_invalid')
    with closing(sqlite3.connect(':memory:')) as connection, connection:
        connection.execute('PRAGMA temp_store=MEMORY')
        connection.deserialize(database)
        summary = _inspect_database(connection)
    if summary != bundle['database_summary']:
        raise Review('recovery_database_summary_mismatch')
    for name, value in bundle['budget_files'].items():
        if name == 'budget.json':
            _budget(value)
        elif name == 'last-request.json':
            if (not isinstance(value, dict) or set(value) != {'time'} or
                    type(value['time']) not in (int, float) or not math.isfinite(value['time']) or value['time'] < 0):
                raise Review('recovery_budget_invalid')
        else:
            raise Review('recovery_budget_invalid')
    for floor in bundle['budget_floors']:
        _budget(floor)
    report = {'format_version': 1, 'created_at': bundle['created_at'], 'authenticated': True, 'integrity_check': 'ok',
              'ciphertext_sha256': _sha(encrypted), 'database_sha256': _sha(database),
              'database_summary': summary, 'budget_files': len(bundle['budget_files']),
              'budget_floors': len(bundle['budget_floors']),
              'remote_reconciliation_required': True, 'budget_reconciliation_required': True,
              'worker_start_allowed': False, 'remote_calls': 0}
    return database, bundle, report


def verify(source, key_file):
    """Authenticate and inspect in memory; no output or database files created."""
    return _decrypt(source, key_file)[2]


def restore(source, output, key_file):
    """Restore to a new isolated file; publish the start hold BEFORE database bytes."""
    output = Path(output)
    marker = Path(str(output) + MARKER_SUFFIX)
    artifact_dir = Path(str(output) + '.budgets')
    _available([output, marker, artifact_dir])
    database, bundle, report = _decrypt(source, key_file)
    with closing(sqlite3.connect(':memory:')) as isolated, isolated:
        isolated.execute('PRAGMA temp_store=MEMORY')
        isolated.deserialize(database)
        hold = {'remote_reconciliation_required': True, 'budget_reconciliation_required': True,
                'worker_start_allowed': False, 'source_database_sha256': report['database_sha256']}
        isolated.execute('INSERT OR REPLACE INTO cache VALUES(?,?,?)',
                         ('recovery-hold', json.dumps(hold), time.time()))
        isolated.commit()
        database = isolated.serialize()
        report = {**report, 'source_database_sha256': report['database_sha256'],
                  'database_sha256': _sha(database), 'database_summary': _inspect_database(isolated)}
    # Reserve the database before touching its adjacent marker. A racing creator
    # therefore cannot make us install a hold next to somebody else's database.
    # The reserved empty file also fails the integrity gate if a crash occurs
    # before its marker is written; valid database bytes are published last.
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        _exclusive_write(marker, _encode({**report, 'restored': True}))
    except BaseException:
        os.close(descriptor)
        raise
    _write_reserved(descriptor, database)
    if bundle['budget_files'] or bundle['budget_floors']:
        artifact_dir.mkdir(mode=0o700)
        for name, value in bundle['budget_files'].items():
            _exclusive_write(artifact_dir / name, _encode(value))
        for index, floor in enumerate(bundle['budget_floors']):
            _exclusive_write(artifact_dir / ('floor-' + str(index + 1) + '.json'), _encode({'budget': floor}))
    return {**report, 'restored': True}


def recovery_start_allowed(database, *, deep=True):
    """Read-only fail-closed gate; every restored file remains quarantined.

    There is deliberately no automatic release command. Missing marker means an
    original database; restore also embeds the hold in its cache, so copying the
    database alone cannot lose the gate. Invalid existing databases also block.
    Callers must check this at every mutation worker entry point.
    """
    marker = Path(str(database) + MARKER_SUFFIX)
    if marker.exists() or marker.is_symlink():
        return False
    database = Path(database)
    if not database.exists():
        return not database.is_symlink()
    if database.is_symlink() or not database.is_file():
        return False
    try:
        with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True, timeout=1)) as connection, connection:
            if deep:
                _inspect_database(connection)
            elif connection.execute('PRAGMA user_version').fetchone()[0] != 1:
                return False
            return not connection.execute("SELECT 1 FROM cache WHERE key='recovery-hold'").fetchone()
    except Exception:
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('backup', 'verify', 'restore'))
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--key-file', type=Path, default=None,
                        help='Private 32-byte key file; defaults to BRIDGE_RECOVERY_KEY_FILE')
    parser.add_argument('--budget-file', action='append', type=Path, default=[])
    parser.add_argument('--budget-floor', action='append', type=Path, default=[])
    args = parser.parse_args(argv)
    try:
        key_file = args.key_file or os.getenv('BRIDGE_RECOVERY_KEY_FILE')
        if not key_file:
            raise Review('recovery_private_key_file_required')
        if args.mode == 'verify':
            if args.output or args.budget_file or args.budget_floor:
                raise Review('recovery_verify_inputs_only')
            result = verify(args.source, key_file)
        else:
            if not args.output:
                raise Review('recovery_new_output_required')
            if args.mode == 'backup':
                result = backup(args.source, args.output, key_file,
                                budget_files=args.budget_file, budget_floors=args.budget_floor)
            else:
                if args.budget_file or args.budget_floor:
                    raise Review('recovery_restore_bundle_artifacts_only')
                result = restore(args.source, args.output, key_file)
        print(json.dumps(result))
        return 0
    except Review as exc:
        print(json.dumps({'ok': False, 'reason': str(exc)}))
        return 2
    except Exception:
        # Paths, keys, SQLite errors, payload fragments and provider records must
        # never enter stdout/stderr through exception formatting.
        print(json.dumps({'ok': False, 'reason': 'recovery_operation_failed'}))
        return 2


if __name__ == '__main__':
    sys.exit(main())
