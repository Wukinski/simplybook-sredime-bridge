import json
from pathlib import Path
import sqlite3

import pytest

from booking_bridge import watchdog_checks as checks
from booking_bridge import watchdog_resolve as resolver
from booking_bridge.model import Settings
from booking_bridge.store import Store


def booking(identifier=1001, **fields):
    value = {'id': identifier, 'provider_id': 81, 'service_id': 91, 'client_id': 777001,
             'start_datetime': '2026-10-23 10:00:00', 'end_datetime': '2026-10-23 11:00:00',
             'status': 'confirmed', 'name': 'PRIVATE NAME', 'email': 'private@example.invalid',
             'notes': 'PRIVATE NOTE', 'url': 'https://private.invalid/token'}
    value.update(fields)
    return value


def prepare(store, now, tmp_path, *, bookings=None):
    store.put('bookings', bookings or [booking(), booking(1002)], now)
    store.put('buffers', {'91': 0}, now)
    store.put('heartbeat', True, now)
    observation = checks.collect_observation(store.path, now=now, provider_capacities={81: 1})
    path = tmp_path / 'observation.json'
    path.write_text(json.dumps(observation), encoding='utf-8')
    return path, observation


def test_email_prefix_resolves_overlap_to_actual_calendar_ids(store, now, tmp_path):
    path, observation = prepare(store, now, tmp_path)
    finding = next(row for row in observation['findings'] if row['code'] == 'provider_overlap_confirmed')
    result = resolver.resolve_reference(store.path, path, finding['reference'][:16])
    assert result['status'] == 'resolved' and result['operator_only'] is result['read_only'] is True
    assert result['finding_codes'] == ['provider_overlap_confirmed']
    bookings = [row for row in result['matches'] if row['kind'] == 'target_booking']
    assert {row['booking_id'] for row in bookings} == {1001, 1002}
    assert all(row['provider_id'] == 81 and row['service_id'] == 91 for row in bookings)
    assert all(row['start'] == '2026-10-23T08:00:00+00:00' for row in bookings)
    assert result['booking_snapshot_at'] == now and result['live_readback_performed'] is False


def test_full_booking_reference_and_uppercase_prefix_are_accepted(store, now, tmp_path):
    path, observation = prepare(store, now, tmp_path)
    ref = observation['bookings'][0]['id_ref']
    full = resolver.resolve_reference(store.path, path, ref)
    prefix = resolver.resolve_reference(store.path, path, ref[:16].upper())
    assert full['matches'] == prefix['matches']
    assert full['matches'][0]['booking_id'] in (1001, 1002)


def test_lookup_never_exposes_contacts_client_ids_notes_or_paths(store, now, tmp_path):
    path, observation = prepare(store, now, tmp_path)
    finding = next(row for row in observation['findings'] if row['code'] == 'provider_overlap_confirmed')
    output = json.dumps(resolver.resolve_reference(store.path, path, finding['reference']))
    for private in ('PRIVATE', 'private@example.invalid', '777001', 'https://private.invalid',
                    'client_id', str(store.path), str(path)):
        assert private not in output


def test_source_event_maps_to_source_booking_without_payload_or_event_id(store, now, event, tmp_path):
    store.ingest(event, now=now - 20)
    store.finish(event['id'], 'review', 'client_mapping_or_consent_missing')
    path, observation = prepare(store, now, tmp_path)
    finding = next(row for row in observation['findings'] if row['code'] == 'source_event_review')
    result = resolver.resolve_reference(store.path, path, finding['reference'][:16])
    assert result['matches'] == [{'kind': 'source_event', 'booking_id': event['data']['id'],
                                  'status': 'review', 'code': 'client_mapping_or_consent_missing'}]
    assert event['id'] not in json.dumps(result)


def test_untrusted_event_or_issue_reason_never_reaches_output(store, now, event, tmp_path):
    store.ingest(event, now=now - 20)
    store.finish(event['id'], 'review', 'PRIVATE CUSTOMER SECRET')
    store.issue('https://private.invalid/key', 'PRIVATE CUSTOMER SECRET', now)
    path, observation = prepare(store, now, tmp_path)
    for code in ('source_event_review', 'open_runtime_incident'):
        finding = next(row for row in observation['findings'] if row['code'] == code)
        result = resolver.resolve_reference(store.path, path, finding['reference'])
        assert result['status'] == 'resolved'
        assert 'PRIVATE' not in json.dumps(result) and 'private.invalid' not in json.dumps(result)
        assert result['matches'][0]['code'] in ('source_event_review', 'runtime_incident_requires_review')


def test_owned_link_and_unresolved_intent_refs_identify_source_and_target(store, now, event, tmp_path):
    store.ingest(event, now=now)
    store.execute('INSERT INTO links VALUES(?,?,?,?,?)',
                  (event['data']['id'], 1001, now, json.dumps(event['data']), 'active'))
    store.put('applied:' + event['data']['id'], dict(booking(), **{'PRIVATE': 'SECRET'}), now)
    store.execute('INSERT INTO intents VALUES(?,?,?,?,?,?,?,?,?)',
                  (event['data']['id'], event['id'], 'cancel', 1001, '{}', '[]', 'started', None, now))
    path, observation = prepare(store, now, tmp_path)
    finding = next(row for row in observation['findings'] if row['code'] == 'unresolved_remote_intent')
    result = resolver.resolve_reference(store.path, path, finding['reference'])
    assert result['matches'] == [{'kind': 'owned_link', 'booking_id': event['data']['id'],
                                  'target_booking_id': 1001, 'provider_id': 81, 'service_id': 91,
                                  'start': '2026-10-23T08:00:00+00:00', 'end': '2026-10-23T09:00:00+00:00',
                                  'status': 'active'}]
    assert 'PRIVATE' not in json.dumps(result) and 'client_id' not in json.dumps(result)


def test_ambiguous_prefix_fails_before_database_access(store, now, tmp_path, monkeypatch):
    path, observation = prepare(store, now, tmp_path)
    observation['findings'] = [dict(observation['findings'][0], reference='a' * 16 + suffix * 48)
                               for suffix in ('0', '1')]
    path.write_text(json.dumps(observation), encoding='utf-8')
    monkeypatch.setattr(resolver, '_read_database', lambda path: pytest.fail('Ambiguous reference must not access DB'))
    result = resolver.resolve_reference(store.path, path, 'a' * 16)
    assert result['status'] == 'ambiguous' and result['code'] == 'reference_prefix_ambiguous'
    assert result['matches'] == []


@pytest.mark.parametrize('reference', ['short', 'a' * 15, 'a' * 63, 'z' * 16, 'https://PRIVATE.invalid'])
def test_invalid_reference_has_no_raw_echo_or_input_access(tmp_path, reference):
    result = resolver.resolve_reference(tmp_path / 'missing.sqlite', tmp_path / 'missing.json', reference)
    assert result['code'] == 'reference_invalid' and result['requested_reference'] is None
    assert reference not in json.dumps(result)


def test_unknown_reference_is_not_guessed_from_database(store, now, tmp_path, monkeypatch):
    path, observation = prepare(store, now, tmp_path)
    monkeypatch.setattr(resolver, '_read_database', lambda path: pytest.fail('Unknown observation ref must not access DB'))
    result = resolver.resolve_reference(store.path, path, 'f' * 64)
    assert result['status'] == 'not_found' and result['code'] == 'observation_reference_not_found'


def test_global_freshness_finding_has_no_invented_calendar_match(store, now, tmp_path):
    path, _ = prepare(store, now, tmp_path)
    store.put('bookings', [booking()], now - 1000)
    observation = checks.collect_observation(store.path, now=now)
    path.write_text(json.dumps(observation), encoding='utf-8')
    finding = next(row for row in observation['findings'] if row['code'] == 'booking_snapshot_stale')
    result = resolver.resolve_reference(store.path, path, finding['reference'][:16])
    assert result['status'] == 'insufficient_evidence' and result['code'] == 'finding_has_no_entity_references'


def test_missing_or_corrupt_input_fails_closed_without_initializing_files(tmp_path):
    missing_db, missing_obs = tmp_path / 'missing-parent' / 'db.sqlite', tmp_path / 'missing.json'
    result = resolver.resolve_reference(missing_db, missing_obs, 'a' * 16)
    assert result['code'] == 'observation_unavailable'
    assert not missing_db.parent.exists()
    missing_obs.write_text('PRIVATE CORRUPT JSON', encoding='utf-8')
    result = resolver.resolve_reference(missing_db, missing_obs, 'a' * 16)
    assert result['code'] == 'observation_invalid' and 'PRIVATE' not in json.dumps(result)


def test_existing_database_and_wal_are_unchanged(store, now, tmp_path, monkeypatch):
    path, observation = prepare(store, now, tmp_path)
    ref = checks.entity_ref('target_booking', 1001)
    writer = sqlite3.connect(store.path)
    try:
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute('UPDATE cache SET value=? WHERE key=?', (json.dumps([booking()]), 'bookings'))
        writer.commit()
        wal = Path(str(store.path) + '-wal')
        before = store.path.read_bytes(), wal.read_bytes()
        monkeypatch.setattr(Store, '__init__', lambda *a, **k: pytest.fail('No Store initialization'))
        monkeypatch.setattr(Settings, 'load', lambda *a, **k: pytest.fail('No settings initialization'))
        result = resolver.resolve_reference(store.path, path, ref)
        assert result['status'] == 'resolved'
        assert (store.path.read_bytes(), wal.read_bytes()) == before
    finally:
        writer.close()


def test_conflicting_cached_identity_is_not_arbitrarily_selected(store, now, tmp_path):
    path, observation = prepare(store, now, tmp_path)
    ref = checks.entity_ref('target_booking', 1001)
    store.put('bookings', [booking(), booking(start_datetime='2026-10-23 10:15:00')], now)
    result = resolver.resolve_reference(store.path, path, ref)
    assert result['status'] == 'ambiguous' and result['code'] == 'database_reference_ambiguous'
    assert result['matches'] == []


def test_saved_observation_can_be_partially_resolved_after_cache_eviction(store, now, tmp_path):
    path, observation = prepare(store, now, tmp_path)
    finding = next(row for row in observation['findings'] if row['code'] == 'provider_overlap_confirmed')
    store.put('bookings', [booking()], now)
    result = resolver.resolve_reference(store.path, path, finding['reference'])
    assert result['status'] == 'partial' and result['unresolved_references']
    assert {row.get('booking_id') for row in result['matches'] if row['kind'] == 'target_booking'} == {1001}


def test_cli_only_prints_sanitized_lookup_result(store, now, tmp_path, capsys):
    path, observation = prepare(store, now, tmp_path)
    ref = observation['bookings'][0]['id_ref']
    assert resolver.main(['--database', str(store.path), '--observation', str(path), '--reference', ref[:16]]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'resolved' and result['operator_only'] is True
