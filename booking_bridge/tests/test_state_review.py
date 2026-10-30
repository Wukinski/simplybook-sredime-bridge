import copy
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from booking_bridge import state_review
from booking_bridge.model import stamp
from booking_bridge.store import Store


def snapshot(tmp_path, name, event, prepare=None):
    working = Store(tmp_path / (name + '-working') / 'bridge.sqlite')
    working.ingest(copy.deepcopy(event), now=stamp(event['created_at']).timestamp())
    if prepare:
        prepare(working)
    result = tmp_path / (name + '.sqlite')
    working.backup(result)
    return result


def owned(store, event, *, target=1001, client=71, applied=True):
    booking = event['data']['id']
    customer = event['data']['customer']['id']
    moment = stamp(event['created_at']).timestamp()
    store.execute('INSERT INTO links VALUES(?,?,?,?,?)',
                  (booking, target, moment, json.dumps(event['data']), 'active'))
    store.execute('INSERT INTO clients VALUES(?,?)', (customer, client))
    if applied:
        store.put('applied:' + booking, {'service_id': 91, 'provider_id': 81, 'client_id': client,
                                       'start_datetime': '2026-10-23 10:00:00',
                                       'end_datetime': '2026-10-23 11:00:00'}, moment)


def codes(report):
    return {row['code'] for row in report['blockers']}


def differences(report):
    return {row['code'] for row in report['differences']}


def mutate(path, sql, args=()):
    conn = sqlite3.connect(path)
    try:
        with conn:
            conn.execute(sql, args)
    finally:
        conn.close()


def file_identity(path):
    info = path.stat()
    return hashlib.sha256(path.read_bytes()).hexdigest(), info.st_size, info.st_mtime_ns


def test_equal_snapshots_are_deterministic_and_input_bytes_do_not_change(tmp_path, event):
    local = snapshot(tmp_path, 'local-private-path', event)
    host = snapshot(tmp_path, 'host-private-path', event)
    before = {path: file_identity(path) for path in (local, host)}
    files = set(tmp_path.rglob('*'))
    report = state_review.review_snapshots(local, host)
    assert report == state_review.review_snapshots(local, host)
    assert report['status'] == 'snapshots_consistent'
    assert report['snapshot_comparison_complete'] is True
    assert report['automatic_migration_allowed'] is report['activation_ready'] is False
    assert report['snapshots']['local']['event_states']['queued'] == 1
    assert before == {path: file_identity(path) for path in (local, host)}
    assert set(tmp_path.rglob('*')) == files


def test_report_omits_raw_identifiers_payloads_contacts_and_paths(tmp_path, event):
    event['data']['customer']['email'] = 'private-person@example.invalid'
    event['data']['customer']['phone'] = '+38123456789'
    event['data']['private_note'] = 'private note marker'
    local = snapshot(tmp_path, 'private-filename-marker', event,
                     lambda store: store.issue('private-token-marker', 'raw-private-reason', 100))
    host = snapshot(tmp_path, 'host', event)
    text = json.dumps(state_review.review_snapshots(local, host))
    for private in (str(local), 'private-filename-marker', event['id'], event['data']['id'],
                    event['data']['customer']['id'], 'private-token-marker', 'raw-private-reason',
                    'private-person@example.invalid', '+38123456789', 'private note marker'):
        assert private not in text


def test_local_done_does_not_ack_or_overwrite_host_queued_receipt(tmp_path, event):
    local = snapshot(tmp_path, 'local', event,
                     lambda store: store.finish(event['id'], 'done', 'applied_by_executor'))
    host = snapshot(tmp_path, 'host', event)
    before = file_identity(host)
    report = state_review.review_snapshots(local, host)
    assert report['status'] == 'manual_reconciliation_required'
    assert 'local_terminal_host_pending_requires_ack_review' in differences(report)
    assert report['comparison']['events']['host_pending_to_preserve'] == 1
    assert report['comparison']['events']['host_receipts_to_preserve'] == 1
    assert file_identity(host) == before
    assert not report['blockers']


def test_unshared_host_events_and_tombstones_are_retained(tmp_path, event):
    canceled = copy.deepcopy(event)
    canceled['id'] = 'f' * 32
    canceled['data']['id'] = 'private-canceled-booking'
    canceled['data']['status'] = -101
    local = snapshot(tmp_path, 'local', event)
    host = snapshot(tmp_path, 'host', event,
                    lambda store: (store.ingest(canceled), store.finish(canceled['id'], 'done')))
    report = state_review.review_snapshots(local, host)
    assert report['status'] == 'manual_reconciliation_required'
    assert report['comparison']['events']['host_only'] == 1
    assert report['snapshots']['host']['terminal_tombstones'] == 1
    assert report['comparison']['booking_heads']['host_only'] == 1
    assert 'preserve_booking_heads_and_terminal_tombstones' in report['plan']


def test_same_event_id_with_different_valid_payload_hashes_blocks(tmp_path, event):
    changed = copy.deepcopy(event)
    changed['data']['service']['id'] = 'different-private-service'
    local = snapshot(tmp_path, 'local', event)
    host = snapshot(tmp_path, 'host', changed)
    report = state_review.review_snapshots(local, host)
    assert report['status'] == 'blocked'
    assert 'event_id_payload_collision' in codes(report)
    assert 'equal_timestamp_booking_snapshot_conflict' in codes(report)


def test_tampered_stored_hash_is_invalid_even_when_other_snapshot_matches_payload(tmp_path, event):
    local = snapshot(tmp_path, 'local', event)
    host = snapshot(tmp_path, 'host', event)
    mutate(local, "UPDATE events SET hash=?", ('0' * 64,))
    report = state_review.review_snapshots(local, host)
    assert 'event_hash_mismatch' in codes(report)
    assert report['snapshot_comparison_complete'] is False
    assert report['snapshots']['local']['valid'] is False


@pytest.mark.parametrize('sql,reason', [
    ("UPDATE events SET state='unknown-private-state'", 'invalid_event_state'),
    ("UPDATE events SET booking='different-booking'", 'event_identity_mismatch'),
    ("UPDATE events SET created=0", 'event_timestamp_mismatch'),
    ("UPDATE events SET attempts=-1", 'invalid_event_counters'),
    ("UPDATE booking_heads SET snapshot_hash='wrong'", 'booking_head_mismatch'),
    ("DELETE FROM booking_heads", 'booking_head_missing_or_orphaned'),
    ("PRAGMA user_version=99", 'snapshot_schema_version_unsupported'),
    ("DROP TABLE clients", 'snapshot_schema_invalid'),
])
def test_invalid_snapshot_fails_closed(tmp_path, event, sql, reason):
    local = snapshot(tmp_path, 'local', event)
    host = snapshot(tmp_path, 'host', event)
    mutate(local, sql)
    before = file_identity(local)
    report = state_review.review_snapshots(local, host)
    assert report['status'] == 'blocked' and reason in codes(report)
    assert file_identity(local) == before


def test_duplicate_payload_json_keys_cannot_hide_hash_tampering(tmp_path, event):
    local = snapshot(tmp_path, 'local', event)
    host = snapshot(tmp_path, 'host', event)
    payload = json.dumps(event).replace('"data": {', '"data": {}, "data": {', 1)
    mutate(local, 'UPDATE events SET payload=?', (payload,))
    assert 'duplicate_json_key' in codes(state_review.review_snapshots(local, host))


def test_owned_link_without_applied_baseline_blocks(tmp_path, event):
    prepare = lambda store: owned(store, event, applied=False)
    local = snapshot(tmp_path, 'local', event, prepare)
    host = snapshot(tmp_path, 'host', event, prepare)
    report = state_review.review_snapshots(local, host)
    assert 'owned_link_missing_applied_baseline' in codes(report)
    assert report['snapshots']['local']['owned_links'] == 1


def test_local_ownership_missing_from_host_is_a_blocker(tmp_path, event):
    local = snapshot(tmp_path, 'local', event, lambda store: owned(store, event))
    host = snapshot(tmp_path, 'host', event)
    report = state_review.review_snapshots(local, host)
    assert 'ownership_missing_on_other_snapshot' in codes(report)
    assert report['comparison']['links']['local_only'] == 1


def test_conflicting_booking_target_blocks(tmp_path, event):
    local = snapshot(tmp_path, 'local', event, lambda store: owned(store, event, target=1001))
    host = snapshot(tmp_path, 'host', event, lambda store: owned(store, event, target=1002))
    report = state_review.review_snapshots(local, host)
    assert 'booking_mapping_target_conflict' in codes(report)
    assert report['automatic_migration_allowed'] is False


def test_conflicting_client_target_blocks(tmp_path, event):
    local = snapshot(tmp_path, 'local', event, lambda store: owned(store, event, client=71))
    host = snapshot(tmp_path, 'host', event, lambda store: owned(store, event, client=72))
    report = state_review.review_snapshots(local, host)
    assert 'client_mapping_target_conflict' in codes(report)
    assert 'cache_guard_conflict_requires_review' in codes(report)


def test_opaque_and_native_client_keys_sharing_target_are_not_aliased(tmp_path, event):
    local = snapshot(tmp_path, 'local', event,
                     lambda store: store.execute('INSERT INTO clients VALUES(?,?)', ('Opaque-Client', 71)))
    host = snapshot(tmp_path, 'host', event,
                    lambda store: store.execute('INSERT INTO clients VALUES(?,?)', ('12345', 71)))
    report = state_review.review_snapshots(local, host)
    assert 'client_target_has_different_source_keys' in codes(report)
    assert report['comparison']['clients'] == {'shared': 0, 'local_only': 1, 'host_only': 1}


def test_unresolved_intent_requires_manual_authoritative_readback(tmp_path, event):
    def prepare(store):
        store.execute('INSERT INTO intents VALUES(?,?,?,?,?,?,?,?,?)',
                      (event['data']['id'], event['id'], 'cancel', 1001, '{}', '[]', 'started', None, 100))
    local = snapshot(tmp_path, 'local', event, prepare)
    host = snapshot(tmp_path, 'host', event)
    report = state_review.review_snapshots(local, host)
    assert report['snapshots']['local']['unresolved_intents'] == 1
    assert 'unresolved_remote_intent_requires_readback' in codes(report)
    assert 'resolve_uncertain_intents_by_authoritative_readback_before_retry' in report['plan']


def test_source_binding_identity_conflict_blocks(tmp_path, event):
    other = copy.deepcopy(event)
    other['id'] = 'f' * 32
    other['data']['id'] = 'second-booking'
    def prepare(store, bound):
        owned(store, event)
        store.ingest(other)
        store.execute('INSERT INTO links VALUES(?,?,?,?,?)',
                      (other['data']['id'], None, stamp(other['created_at']).timestamp(),
                       json.dumps(other['data']), 'canceled'))
        store.execute('INSERT INTO source_bindings VALUES(?,?,?)', ('Opaque-Employee', 'private-uid', bound))
    local = snapshot(tmp_path, 'local', event, lambda store: prepare(store, event['data']['id']))
    host = snapshot(tmp_path, 'host', event, lambda store: prepare(store, other['data']['id']))
    assert 'source_binding_identity_conflict' in codes(state_review.review_snapshots(local, host))


def test_identical_rate_reservations_are_conservatively_retained_twice(tmp_path, event):
    def prepare(store):
        store.execute('INSERT INTO rates VALUES(?,?)', ('sredime-post:private-employee', 100))
        store.execute('INSERT INTO rates VALUES(?,?)', ('sredime-post:private-employee', 110))
    local = snapshot(tmp_path, 'local', event, prepare)
    host = snapshot(tmp_path, 'host', event, prepare)
    report = state_review.review_snapshots(local, host)
    assert report['comparison']['rate_quotas'] == {
        'local_rows': 2, 'host_rows': 2, 'conservative_rows_to_retain': 4,
        'deduplication_allowed': False, 'timestamps_must_be_preserved': True,
    }


def test_cache_guard_conflict_blocks_but_newer_read_cache_only_needs_review(tmp_path, event):
    local = snapshot(tmp_path, 'local', event, lambda store: (
        store.put('bookings', [], 100), store.put('refresh-failures:private-employee', 2, 100)))
    host = snapshot(tmp_path, 'host', event, lambda store: (
        store.put('bookings', [{'id': 1001}], 200), store.put('refresh-failures:private-employee', 3, 200)))
    report = state_review.review_snapshots(local, host)
    assert report['comparison']['cache']['divergent_values'] == 2
    assert report['comparison']['cache']['divergent_guards'] == 1
    assert 'cache_guard_conflict_requires_review' in codes(report)
    assert 'retain_guard_evidence_and_rebuild_freshness_from_new_reads' in report['plan']


@pytest.mark.parametrize('suffix', ['-wal', '-shm', '-journal'])
def test_live_sidecars_are_rejected_without_modification(tmp_path, event, suffix):
    local = snapshot(tmp_path, 'local', event)
    host = snapshot(tmp_path, 'host', event)
    sidecar = Path(str(local) + suffix)
    sidecar.write_bytes(b'private-sidecar-marker')
    before = file_identity(local), sidecar.read_bytes()
    report = state_review.review_snapshots(local, host)
    assert 'snapshot_sidecars_present' in codes(report)
    assert before == (file_identity(local), sidecar.read_bytes())


def test_missing_and_corrupt_inputs_are_not_initialized(tmp_path):
    local = tmp_path / 'missing-parent' / 'missing.sqlite'
    host = tmp_path / 'corrupt.sqlite'
    host.write_bytes(b'private corrupt input')
    report = state_review.review_snapshots(local, host)
    assert {'snapshot_missing', 'snapshot_unreadable_or_corrupt'} <= codes(report)
    assert not local.parent.exists()
    assert host.read_bytes() == b'private corrupt input'


def test_cli_outputs_sanitized_report_and_no_file(tmp_path, event, capsys):
    local = snapshot(tmp_path, 'local', event)
    host = snapshot(tmp_path, 'host', event)
    assert state_review.main(['--local-snapshot', str(local), '--host-snapshot', str(host)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['read_only'] is True and result['status'] == 'snapshots_consistent'


def test_snapshot_change_during_review_fails_closed(tmp_path, event, monkeypatch):
    local = snapshot(tmp_path, 'local', event)
    host = snapshot(tmp_path, 'host', event)
    original = state_review._hash_file
    calls = 0
    def changing_hash(path):
        nonlocal calls
        calls += 1
        return '0' * 64 if calls == 2 else original(path)
    monkeypatch.setattr(state_review, '_hash_file', changing_hash)
    assert 'snapshot_changed_during_review' in codes(state_review.review_snapshots(local, host))


def test_malformed_owned_snapshot_fails_closed_without_exception_text(tmp_path, event):
    local = snapshot(tmp_path, 'local', event, lambda store: owned(store, event))
    host = snapshot(tmp_path, 'host', event)
    data = copy.deepcopy(event['data'])
    data['customer'] = 'private-malformed-customer'
    mutate(local, 'UPDATE links SET snapshot=?', (json.dumps(data),))
    report = state_review.review_snapshots(local, host)
    assert 'invalid_link_snapshot' in codes(report)
    assert 'private-malformed-customer' not in json.dumps(report)


@pytest.mark.parametrize('prepare,reason', [
    (lambda store: store.execute('INSERT INTO rates VALUES(?,?)', ('private-quota', -1)), 'invalid_rate_ledger'),
    (lambda store: store.execute('INSERT INTO feed_health VALUES(?,?,?,?,?)',
                                 ('private-employee', 1, 100, None, 'unknown')), 'invalid_feed_health'),
    (lambda store: store.put('applied:orphan-private-booking', {}), 'orphaned_applied_baseline'),
    (lambda store: store.execute('INSERT INTO audit VALUES(?,?,?)',
                                 (100, 'valid_action', sqlite3.Binary(b'private-blob'))),
     'snapshot_unreadable_or_invalid'),
])
def test_malformed_auxiliary_state_fails_closed(tmp_path, event, prepare, reason):
    local = snapshot(tmp_path, 'local', event, prepare)
    host = snapshot(tmp_path, 'host', event)
    report = state_review.review_snapshots(local, host)
    assert reason in codes(report)
    assert report['snapshot_comparison_complete'] is False


def test_guard_attempt_time_is_preserved_even_when_values_match(tmp_path, event):
    local = snapshot(tmp_path, 'local', event, lambda store: store.put('task:bookings', 'attempted', 100))
    host = snapshot(tmp_path, 'host', event, lambda store: store.put('task:bookings', 'attempted', 200))
    report = state_review.review_snapshots(local, host)
    assert report['status'] == 'manual_reconciliation_required'
    assert report['comparison']['cache']['divergent_guards'] == 0
    assert report['comparison']['cache']['divergent_guard_timestamps'] == 1
    assert 'cache_guard_timestamps_must_be_retained' in differences(report)


def test_import_never_constructs_settings_or_store(monkeypatch):
    import importlib
    from booking_bridge.model import Settings
    def forbidden(*args, **kwargs):
        raise AssertionError('State review must not initialize configuration or a database')
    monkeypatch.setattr(Store, '__init__', forbidden)
    monkeypatch.setattr(Settings, 'load', forbidden)
    importlib.reload(state_review)
