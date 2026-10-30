import copy
from datetime import datetime, timezone
import hashlib
import io
import json
import os
import sqlite3

import pytest

from booking_bridge.deploy import offhost_backup as runner
from booking_bridge.model import Review
from booking_bridge.recovery import MAGIC

NOW = 1793358000


@pytest.fixture
def config(store, event, tmp_path, now):
    store.ingest(event, now)
    store.put('synthetic-sensitive-value', {'contact': 'SYNTHETIC_PRIVATE_CONTACT'}, now)
    key = tmp_path / 'key.bin'
    key.write_bytes(os.urandom(32)); key.chmod(0o600)
    budget = tmp_path / 'budget.json'
    budget.write_text(json.dumps({'day': '2026-10-30', 'requests': 3939}))
    return {'source_database': str(store.path), 'key_file': str(key),
            'spool_directory': str(tmp_path / 'spool'), 'credentials_file': str(tmp_path / 'credentials.json'),
            'endpoint_url': 'https://synthetic-storage.invalid', 'region': 'auto',
            'bucket': 'synthetic-backup-bucket', 'prefix': 'bridge-production/backups/',
            'destination_independent_of_source': True, 'retention_days': 30,
            'keep_last': 2, 'delete_expired': False, 'budget_files': [str(budget)], 'budget_floors': []}


class Storage:
    def __init__(self):
        self.data, self.uploads, self.deleted = {}, [], []
        self.list_calls = 0
        self.tamper = False
        self.fail_upload = False

    def upload(self, key, body, digest):
        if self.fail_upload:
            raise RuntimeError('SYNTHETIC_SECRET_URL_AND_TOKEN_MUST_NOT_PRINT')
        assert body.startswith(MAGIC)
        assert hashlib.sha256(body).hexdigest() == digest
        self.data[key] = body
        self.uploads.append((key, body))

    def download(self, key):
        body = self.data[key]
        return body[:-1] + bytes([body[-1] ^ 1]) if self.tamper else body

    def objects(self):
        self.list_calls += 1
        return list(self.data)

    def delete(self, key):
        self.deleted.append(key)
        self.data.pop(key)


def test_real_encrypted_upload_download_and_held_restore_preserve_source(config, store, tmp_path):
    storage = Storage()
    with sqlite3.connect(store.path) as connection:
        before = connection.execute('SELECT * FROM events').fetchall()
    report = runner.run_backup(config, transport_factory=lambda _: storage, clock=lambda: NOW, restore_drill=True)
    assert report['status'] == 'verified' and report['off_host_export_performed']
    assert report['remote_readback_verified'] and report['restore_drill_performed']
    assert report['worker_start_allowed'] is False and report['booking_writes'] == 0
    assert report['budget_files'] == 1
    drill = json.loads((tmp_path / 'spool' / 'restore-drill-status.json').read_text())
    assert drill['restore_drill_performed'] is True and drill['worker_start_allowed'] is False
    assert len(storage.uploads) == 1 and storage.deleted == []
    body = storage.uploads[0][1]
    assert b'SYNTHETIC_PRIVATE_CONTACT' not in body
    assert (tmp_path / 'key.bin').read_bytes() not in body
    assert not list((tmp_path / 'spool').glob('.restore-drill-*'))
    assert not list((tmp_path / 'spool').glob('.verify-*'))
    with sqlite3.connect(store.path) as connection:
        assert connection.execute('SELECT * FROM events').fetchall() == before
    text = json.dumps(report)
    assert str(tmp_path) not in text and 'synthetic-storage' not in text


@pytest.mark.parametrize('failure', ['tampered_readback', 'upload_failed'])
def test_failure_retains_encrypted_copy_and_never_runs_retention(config, failure, capsys):
    storage = Storage()
    storage.tamper = failure == 'tampered_readback'
    storage.fail_upload = failure == 'upload_failed'
    config['delete_expired'] = True
    with pytest.raises(Review, match='offhost_backup_requires_review'):
        runner.run_backup(config, transport_factory=lambda _: storage, clock=lambda: NOW)
    assert storage.list_calls == 0 and storage.deleted == []
    spool = __import__('pathlib').Path(config['spool_directory'])
    assert len(list(spool.glob('backup-*.enc'))) == 1
    report = json.loads((spool / 'backup-status.json').read_text())
    assert report['status'] == 'failed' and not report['remote_readback_verified']
    assert 'SYNTHETIC_SECRET' not in json.dumps(report) + capsys.readouterr().out


def object_key(config, day, suffix):
    timestamp = datetime.fromtimestamp(day, timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    return config['prefix'] + 'backup-' + timestamp + '-' + f'{suffix:032x}' + '.enc'


def test_retention_keeps_minimum_age_floor_and_never_touches_foreign_keys(config):
    keys = [object_key(config, NOW - day * 86400, day) for day in (0, 31, 32, 33)]
    foreign = ['other/' + keys[-1], config['prefix'] + 'important.enc',
               config['prefix'] + '../' + keys[-1], object_key(config, NOW + 86400, 55)]
    expired = runner.retention_candidates(keys + foreign, config, NOW, keys[0], set(keys))
    assert expired == [keys[3], keys[2]]
    with pytest.raises(Review, match='uploaded_object_not_listed'):
        runner.retention_candidates(keys[1:], config, NOW, keys[0], set(keys))


def test_retention_is_bounded_and_runs_only_after_verified_readback(config):
    storage = Storage()
    old = [object_key(config, NOW - (40 + day) * 86400, day) for day in range(50)]
    storage.data.update({key: b'old-encrypted-placeholder' for key in old})
    spool = __import__('pathlib').Path(config['spool_directory'])
    spool.mkdir(mode=0o700)
    for key in old:
        receipt = {'off_host_export_performed': True, 'remote_readback_verified': True,
                   'destination_fingerprint': runner.destination_fingerprint(config),
                   'remote_reference': hashlib.sha256(key.encode()).hexdigest()}
        path = spool / (key[len(config['prefix']):] + '.uploaded.json')
        path.write_text(json.dumps(receipt)); path.chmod(0o600)
    config['delete_expired'] = True
    report = runner.run_backup(config, transport_factory=lambda _: storage, clock=lambda: NOW)
    assert report['remote_deleted'] == 32 == len(storage.deleted)
    assert all(key in old for key in storage.deleted)
    assert storage.uploads[0][0] not in storage.deleted


def test_unverified_names_never_inflate_retention_minimum_copy_floor(config):
    keys = [object_key(config, NOW - day * 86400, day) for day in (0, 31, 32, 33)]
    unverified = [object_key(config, NOW - 86400, number + 100) for number in range(100)]
    expired = runner.retention_candidates(keys + unverified, config, NOW, keys[0], set(keys))
    assert expired == [keys[3], keys[2]]


def test_receipts_from_another_destination_cannot_authorize_retention(config):
    spool = __import__('pathlib').Path(config['spool_directory'])
    spool.mkdir(mode=0o700)
    key = object_key(config, NOW, 1)
    receipt = {'off_host_export_performed': True, 'remote_readback_verified': True,
               'destination_fingerprint': 'wrong-destination',
               'remote_reference': hashlib.sha256(key.encode()).hexdigest()}
    path = spool / (key[len(config['prefix']):] + '.uploaded.json')
    path.write_text(json.dumps(receipt)); path.chmod(0o600)
    assert runner.verified_catalog(spool, config) == set()


def test_repeated_runs_prune_only_expired_verified_local_and_remote_archives(config):
    storage = Storage()
    config.update(retention_days=1, keep_last=2, delete_expired=True)
    moments = [NOW - 10 * 86400, NOW - 9 * 86400, NOW - 8 * 86400, NOW]
    for moment in moments:
        result = runner.run_backup(config, transport_factory=lambda _: storage, clock=lambda: moment)
        assert result['status'] == 'verified'
    assert len(storage.data) == 2 and len(storage.deleted) == 2
    spool = __import__('pathlib').Path(config['spool_directory'])
    assert len(list(spool.glob('backup-*.enc'))) == 2
    assert len(list(spool.glob('backup-*.enc.uploaded.json'))) == 2
    assert len(runner.verified_catalog(spool, config)) == 2


@pytest.mark.parametrize('change', [
    {'destination_independent_of_source': False}, {'prefix': '../backups/'},
    {'prefix': 'bridge//backups/'}, {'keep_last': 1}, {'delete_expired': 'yes'},
    {'endpoint_url': 'http://synthetic.invalid'},
    {'endpoint_url': 'https://169.58.118.33'}, {'endpoint_url': 'https://user:secret@synthetic.invalid'},
])
def test_unreviewed_destination_and_unsafe_configuration_rejected_before_upload(config, change):
    config.update(change)
    with pytest.raises(Review):
        runner.validate(config)


class S3Client:
    def __init__(self, body=b'encrypted', declared=None):
        self.body = body
        self.declared = len(body) if declared is None else declared
        self.stream = io.BytesIO(body)
        self.put = None

    def put_object(self, **kwargs):
        self.put = kwargs

    def get_object(self, **kwargs):
        return {'Body': self.stream, 'ContentLength': self.declared}


def test_s3_conditional_create_and_exact_bounded_download(config):
    client = S3Client()
    transport = runner.S3Transport(config, client=client)
    transport.upload('key', b'encrypted', 'a' * 64)
    assert client.put['IfNoneMatch'] == '*'
    assert client.put['Metadata'] == {'ciphertext-sha256': 'a' * 64}
    assert transport.download('key') == b'encrypted'
    assert client.stream.closed


@pytest.mark.parametrize('declared', [0, -1, runner.MAX_OBJECT + 1, 999])
def test_s3_bad_length_is_rejected_and_stream_closed(config, declared):
    client = S3Client(declared=declared)
    with pytest.raises(Review):
        runner.S3Transport(config, client=client).download('key')
    assert client.stream.closed


def test_repeated_pagination_token_stops_without_deleting(config):
    class Looped(S3Client):
        def list_objects_v2(self, **kwargs):
            return {'IsTruncated': True, 'NextContinuationToken': 'same'}
    with pytest.raises(Review, match='listing_invalid'):
        runner.S3Transport(config, client=Looped()).objects()
