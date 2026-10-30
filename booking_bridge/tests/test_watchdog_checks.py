import copy
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from booking_bridge import watchdog_checks as checks
from booking_bridge.model import Settings
from booking_bridge.store import Store


def booking(identifier=1001, **fields):
    value = {'id': identifier, 'provider_id': 81, 'service_id': 91, 'client_id': 777001,
             'status': 'confirmed', 'start_datetime': '2026-10-23 10:00:00',
             'end_datetime': '2026-10-23 11:00:00', 'name': 'PRIVATE NAME MARKER',
             'email': 'private-person@example.invalid', 'notes': 'PRIVATE NOTE MARKER',
             'secret_url': 'https://private.invalid/token-marker'}
    value.update(fields)
    return value


def prime(store, now, bookings=None, *, buffer=0, bookings_at=None, buffers_at=None, heartbeat_at=None):
    store.put('bookings', bookings or [], now if bookings_at is None else bookings_at)
    store.put('buffers', {'91': buffer, '92': 0}, now if buffers_at is None else buffers_at)
    store.put('heartbeat', True, now if heartbeat_at is None else heartbeat_at)


def collect(store, now, *, capacities=True):
    return checks.collect_observation(store.path, now=now,
                                      provider_capacities={81: 1} if capacities else None)


def codes(observation):
    return {row['code'] for row in observation['findings']}


def owned(store, now, *, target=1001, state='active', source_status=1, baseline=True, applied_at=None):
    source = {'id': 'private-source-booking', 'status': source_status, 'customer': {'id': 'PRIVATE CUSTOMER ID'},
              'notes': 'PRIVATE SOURCE NOTE'}
    store.execute('INSERT INTO links VALUES(?,?,?,?,?)',
                  (source['id'], target, now, json.dumps(source), state))
    if baseline:
        desired = {'provider_id': 81, 'service_id': 91, 'client_id': 777001,
                   'start_datetime': '2026-10-23 10:00:00', 'end_datetime': '2026-10-23 11:00:00'}
        store.put('applied:' + source['id'], desired, now if applied_at is None else applied_at)


def test_capacity_one_overlap_is_confirmed_using_fresh_buffered_inventory(store, now):
    prime(store, now, [booking(), booking(1002, start_datetime='2026-10-23 10:30:00',
                                        end_datetime='2026-10-23 11:30:00')])
    result = collect(store, now)
    assert result['health']['database_status'] == 'ok'
    assert 'provider_overlap_confirmed' in codes(result)
    finding = next(row for row in result['findings'] if row['code'] == 'provider_overlap_confirmed')
    assert finding['severity'] == 'error'
    assert finding['evidence']['overlap_seconds'] == 1800
    assert finding['evidence']['certainty'] == 'confirmed'
    assert checks.evaluate_observation(result) == result['findings']


def test_after_buffer_creates_occupied_overlap(store, now):
    prime(store, now, [booking(), booking(1002, start_datetime='2026-10-23 11:05:00',
                                        end_datetime='2026-10-23 11:35:00')], buffer=10)
    result = collect(store, now)
    finding = next(row for row in result['findings'] if row['code'] == 'provider_overlap_confirmed')
    assert finding['evidence']['overlap_seconds'] == 300


@pytest.mark.parametrize('start,buffer', [('11:00:00', 0), ('11:10:00', 10)])
def test_adjacent_effective_intervals_do_not_overlap(store, now, start, buffer):
    prime(store, now, [booking(), booking(1002, start_datetime='2026-10-23 ' + start,
                                        end_datetime='2026-10-23 12:00:00')], buffer=buffer)
    assert 'provider_overlap_confirmed' not in codes(collect(store, now))


def test_canceled_is_excluded_and_pending_is_occupied(store, now):
    prime(store, now, [booking(status='canceled'), booking(1002, status='pending')])
    assert 'provider_overlap_confirmed' not in codes(collect(store, now))
    prime(store, now, [booking(), booking(1002, status='pending')])
    assert 'provider_overlap_confirmed' in codes(collect(store, now))


def test_different_providers_are_not_a_capacity_conflict(store, now):
    prime(store, now, [booking(), booking(1002, provider_id=82)])
    assert not {'provider_overlap_confirmed', 'provider_overlap_candidate'} & codes(collect(store, now))


def test_unverified_capacity_is_only_an_overlap_candidate(store, now):
    prime(store, now, [booking(), booking(1002)])
    result = collect(store, now, capacities=False)
    assert {'provider_overlap_candidate', 'provider_capacity_unverified'} <= codes(result)
    assert 'provider_overlap_confirmed' not in codes(result)


def test_exact_interval_duplicates_remain_distinct_candidates(store, now):
    prime(store, now, [booking(), booking(1002)])
    result = collect(store, now)
    assert {'duplicate_booking_candidate', 'provider_overlap_confirmed'} <= codes(result)
    candidate = next(row for row in result['findings'] if row['code'] == 'duplicate_booking_candidate')
    assert candidate['evidence']['certainty'] == 'candidate'


def test_duplicate_cache_record_is_not_counted_as_two_actual_bookings(store, now):
    prime(store, now, [booking(), booking()])
    result = collect(store, now)
    assert 'duplicate_target_booking_record' in codes(result)
    assert 'provider_overlap_confirmed' not in codes(result)


def test_conflicting_cache_record_disables_confirmed_conflicts(store, now):
    prime(store, now, [booking(), booking(service_id=92), booking(1002)])
    result = collect(store, now)
    assert 'conflicting_target_booking_record' in codes(result)
    assert 'provider_overlap_confirmed' not in codes(result)


@pytest.mark.parametrize('times,expected', [
    ({'bookings_at': -901}, 'booking_snapshot_stale'),
    ({'buffers_at': -4501}, 'service_buffers_stale'),
    ({'bookings_at': 1}, 'booking_snapshot_future'),
    ({'buffers_at': 1}, 'service_buffers_future'),
])
def test_stale_or_future_data_never_confirms_a_booking_conflict(store, now, times, expected):
    prime(store, now, [booking(), booking(1002)], **{key: now + offset for key, offset in times.items()})
    result = collect(store, now)
    assert expected in codes(result)
    assert 'booking_evidence_insufficient' in codes(result)
    assert 'provider_overlap_confirmed' not in codes(result)
    assert 'provider_overlap_candidate' in codes(result)


def test_missing_snapshots_and_heartbeat_are_explicit(store, now):
    result = collect(store, now)
    assert {'booking_snapshot_missing', 'service_buffers_missing', 'worker_heartbeat_missing',
            'booking_evidence_insufficient'} <= codes(result)
    assert result['bookings'] == []


def test_unknown_service_buffer_cannot_confirm_conflict(store, now):
    prime(store, now, [booking(service_id=999), booking(1002)])
    result = collect(store, now)
    assert 'service_buffers_invalid' in codes(result)
    assert 'provider_overlap_confirmed' not in codes(result)


@pytest.mark.parametrize('changes,expected', [
    ({'provider_id': 82}, 'owned_target_diverged'),
    ({'service_id': 92}, 'owned_target_diverged'),
    ({'start_datetime': '2026-10-23 10:15:00'}, 'owned_target_diverged'),
    ({'status': 'canceled'}, 'owned_cancel_state_diverged'),
])
def test_owned_divergence_uses_applied_baseline_and_cancel_state(store, now, changes, expected):
    prime(store, now, [booking(**changes)])
    owned(store, now)
    assert expected in codes(collect(store, now))


def test_canceled_owned_booking_matches_canceled_target(store, now):
    prime(store, now, [booking(status='canceled')])
    owned(store, now, state='canceled', source_status=-101)
    assert not {'owned_target_diverged', 'owned_cancel_state_diverged', 'owned_source_state_inconsistent'} & codes(collect(store, now))


def test_stale_snapshot_does_not_confirm_owned_divergence(store, now):
    prime(store, now, [booking(provider_id=82)], bookings_at=now - 901)
    owned(store, now - 1000)
    result = collect(store, now)
    assert 'booking_evidence_insufficient' in codes(result)
    assert not {'owned_target_diverged', 'owned_cancel_state_diverged'} & codes(result)


def test_target_snapshot_predating_applied_write_is_insufficient(store, now):
    prime(store, now, [booking(provider_id=82)], bookings_at=now - 1)
    owned(store, now - 100, applied_at=now)
    result = collect(store, now)
    assert {'booking_snapshot_stale', 'booking_evidence_insufficient'} <= codes(result)
    assert 'owned_target_diverged' not in codes(result)
    assert result['health']['snapshots']['bookings'] == {
        'status': 'stale', 'updated_at': now - 1, 'age_seconds': 1,
    }


def test_new_inventory_after_applied_write_restores_effective_freshness(store, now):
    prime(store, now, [booking(provider_id=82)], bookings_at=now - 1)
    owned(store, now - 100, applied_at=now)
    assert collect(store, now)['health']['snapshots']['bookings']['status'] == 'stale'
    # The next authoritative cache generation includes the completed owned write.
    store.put('bookings', [booking()], now)
    result = collect(store, now + 1)
    assert result['health']['snapshots']['bookings'] == {
        'status': 'fresh', 'updated_at': now, 'age_seconds': 1,
    }
    assert not {'booking_snapshot_stale', 'booking_evidence_insufficient', 'owned_target_diverged'} & codes(result)


def test_pre_cancel_inventory_is_effectively_stale_until_cancel_read_is_captured(store, now):
    prime(store, now, [booking()], bookings_at=now - 1)
    owned(store, now, state='canceled', source_status=-101, applied_at=now - 100)
    result = collect(store, now)
    assert result['health']['snapshots']['bookings']['status'] == 'stale'
    assert 'booking_evidence_insufficient' in codes(result)
    assert 'owned_cancel_state_diverged' not in codes(result)
    store.put('bookings', [booking(status='canceled')], now)
    result = collect(store, now + 1)
    assert result['health']['snapshots']['bookings']['status'] == 'fresh'
    assert not {'booking_snapshot_stale', 'owned_cancel_state_diverged'} & codes(result)


def test_absence_from_rolling_inventory_does_not_prove_cancellation(store, now):
    prime(store, now, [])
    owned(store, now)
    result = collect(store, now)
    assert 'owned_target_not_in_snapshot' in codes(result)
    assert 'owned_cancel_state_diverged' not in codes(result)


def test_missing_baseline_and_inconsistent_source_state_are_reported(store, now):
    prime(store, now, [booking()])
    owned(store, now, source_status=-101, baseline=False)
    assert {'owned_baseline_missing', 'owned_source_state_inconsistent'} <= codes(collect(store, now))


def test_queue_reviews_dead_intents_and_incidents_are_reported_without_raw_data(store, now, event):
    prime(store, now)
    store.ingest(event, now=now - 11)
    review = copy.deepcopy(event); review['id'] = 'f' * 32; review['data']['id'] = 'private-review-booking'
    dead = copy.deepcopy(event); dead['id'] = 'e' * 32; dead['data']['id'] = 'private-dead-booking'
    store.ingest(review, now=now); store.finish(review['id'], 'review', 'PRIVATE REASON')
    store.ingest(dead, now=now); store.finish(dead['id'], 'dead', 'PRIVATE DEAD REASON')
    store.execute('INSERT INTO intents VALUES(?,?,?,?,?,?,?,?,?)',
                  (event['data']['id'], event['id'], 'cancel', 1001, '{}', '[]', 'started', None, now))
    store.issue('https://private.invalid/issue-token', 'PRIVATE ISSUE REASON', now)
    result = collect(store, now)
    assert {'source_queue_aged', 'source_event_review', 'source_event_dead',
            'unresolved_remote_intent', 'open_runtime_incident'} <= codes(result)
    assert result['health']['event_counts']['queued'] == 1
    assert result['health']['event_counts']['review'] == 1


def test_projection_has_no_contact_names_notes_urls_or_raw_ids(store, now):
    prime(store, now, [booking()])
    owned(store, now)
    result = collect(store, now)
    text = json.dumps(result)
    for private in ('PRIVATE NAME MARKER', 'private-person@example.invalid', 'PRIVATE NOTE MARKER',
                    'https://private.invalid', '777001', 'PRIVATE CUSTOMER ID', 'private-source-booking',
                    'PRIVATE SOURCE NOTE', str(store.path)):
        assert private not in text
    assert 'client_id' not in text and 'payload' not in text
    for finding in result['findings']:
        assert checks.REF.fullmatch(finding['reference'])


def test_collection_is_deterministic_and_database_bytes_are_unchanged(store, now, monkeypatch):
    prime(store, now, [booking()])
    before = store.path.read_bytes(), store.path.stat().st_mtime_ns
    def forbidden(*args, **kwargs):
        pytest.fail('Collector must never initialize configuration or Store')
    monkeypatch.setattr(Store, '__init__', forbidden)
    monkeypatch.setattr(Settings, 'load', forbidden)
    first = collect(store, now)
    assert first == collect(store, now)
    assert (store.path.read_bytes(), store.path.stat().st_mtime_ns) == before


def test_collector_reads_committed_uncheckpointed_wal_without_changing_db_or_wal(store, now):
    prime(store, now, [])
    writer = sqlite3.connect(store.path)
    try:
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute('UPDATE cache SET value=? WHERE key=?', (json.dumps([booking(), booking(1002)]), 'bookings'))
        writer.commit()
        wal = Path(str(store.path) + '-wal')
        assert wal.exists()
        before = store.path.read_bytes(), wal.read_bytes()
        result = collect(store, now)
        assert 'provider_overlap_confirmed' in codes(result)
        assert (store.path.read_bytes(), wal.read_bytes()) == before
    finally:
        writer.close()


def test_missing_database_is_never_initialized(tmp_path, now):
    path = tmp_path / 'missing' / 'bridge.sqlite'
    result = checks.collect_observation(path, now=now)
    assert {'database_missing', 'booking_evidence_insufficient'} <= codes(result)
    assert not path.parent.exists()


@pytest.mark.parametrize('sql,code', [
    ('PRAGMA user_version=99', 'database_schema_unsupported'),
    ('DROP TABLE intents', 'database_schema_invalid'),
    ("UPDATE cache SET value='broken json' WHERE key='bookings'", 'collection_data_invalid'),
])
def test_invalid_schema_or_data_fails_closed_without_migration(store, now, sql, code):
    prime(store, now, [booking(), booking(1002)])
    store.execute(sql)
    before = store.path.read_bytes()
    result = collect(store, now)
    assert code in codes(result)
    assert 'provider_overlap_confirmed' not in codes(result)
    assert store.path.read_bytes() == before


def test_corrupt_database_does_not_echo_contents(tmp_path, now):
    path = tmp_path / 'bad.sqlite'
    path.write_bytes(b'PRIVATE CORRUPT DATA')
    result = checks.collect_observation(path, now=now)
    assert 'database_unavailable' in codes(result)
    assert 'PRIVATE CORRUPT DATA' not in json.dumps(result)


def test_bounded_scan_and_pair_limits_are_explicit(store, now, monkeypatch):
    prime(store, now, [booking(), booking(1002), booking(1003)])
    monkeypatch.setattr(checks, 'MAX_PAIRS', 1)
    assert 'overlap_scan_limit' in codes(collect(store, now))
    monkeypatch.setattr(checks, 'MAX_BOOKINGS', 1)
    result = collect(store, now)
    assert 'collection_scan_limit' in codes(result)
    assert not result['health']['scan_complete']
    assert 'provider_overlap_confirmed' not in codes(result)


def test_malformed_sanitized_envelope_cannot_echo_arbitrary_strings(store, now):
    prime(store, now)
    result = collect(store, now)
    result['bookings'] = [{'id_ref': 'PRIVATE RAW ID', 'notes': 'PRIVATE MALICIOUS NOTE'}]
    findings = checks.evaluate_observation(result)
    assert {row['code'] for row in findings} == {'observation_schema_invalid'}
    assert 'PRIVATE' not in json.dumps(findings)


def test_atomic_projection_roundtrip_and_reject_database_as_output(store, now, tmp_path):
    prime(store, now, [booking()])
    result = collect(store, now)
    output = tmp_path / 'observations' / 'latest.json'
    checks.write_observation(output, result, database=store.path)
    assert json.loads(output.read_text(encoding='utf-8')) == result
    assert not list(output.parent.glob('*.tmp'))
    with pytest.raises(ValueError):
        checks.write_observation(store.path, result, database=store.path)


def test_cli_once_writes_only_projection(store, now, tmp_path, capsys):
    prime(store, now, [booking()])
    output = tmp_path / 'observations' / 'latest.json'
    before = hashlib.sha256(store.path.read_bytes()).hexdigest()
    assert checks.main(['--database', str(store.path), '--output', str(output), '--once', '--capacity', '81:1']) == 0
    assert json.loads(capsys.readouterr().out)['projection_written'] is True
    assert hashlib.sha256(store.path.read_bytes()).hexdigest() == before
    assert json.loads(output.read_text(encoding='utf-8'))['schema_version'] == 1


def test_stale_incomplete_buffers_keep_both_age_and_contract_findings(store, now):
    prime(store, now, [booking(service_id=999), booking(1002)], buffers_at=now - 4501)
    result = collect(store, now)
    assert {'service_buffers_stale', 'service_buffers_invalid', 'booking_evidence_insufficient'} <= codes(result)
    assert 'provider_overlap_confirmed' not in codes(result)


def test_projection_size_limit_yields_small_insufficient_evidence_report(store, now, monkeypatch):
    prime(store, now, [booking(1000 + i) for i in range(20)])
    monkeypatch.setattr(checks, 'MAX_OBSERVATION_BYTES', 6000)
    result = collect(store, now)
    assert {'collection_scan_limit', 'booking_evidence_insufficient'} <= codes(result)
    assert len(json.dumps(result).encode()) < 6000
    assert result['bookings'] == []


def test_invalid_finding_payload_cannot_be_persisted_as_projection(store, now, tmp_path):
    prime(store, now)
    result = collect(store, now)
    result['findings'] = [{'code': 'database_missing', 'severity': 'error', 'reference': 'a' * 64,
                           'evidence': {'notes': 'PRIVATE INJECTED NOTE'}}]
    with pytest.raises(checks._Invalid):
        checks.write_observation(tmp_path / 'latest.json', result)
    assert not (tmp_path / 'latest.json').exists()
