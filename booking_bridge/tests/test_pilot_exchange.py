import copy
import json
from datetime import timedelta

import pytest

from booking_bridge.calendar import bounds, feed_version, make_feed
from booking_bridge.model import BELGRADE, Review, Settings
from booking_bridge.pilot_exchange import (MAX_PACKET_BYTES, build_packet, decode_packet,
                                         import_packet, validate_packet)
from booking_bridge.pilot_snapshot import capture_packet
from booking_bridge.store import Store


@pytest.fixture
def scoped(settings):
    settings.allowed_employees = ['11772']
    settings.employees = {'11772': {'id': 9, 'external_id': '9'}}
    settings.services = {'233160': {'id': 496, 'external_id': '496', 'duration': 30}}
    settings.pilot_service_ids = [496]
    settings.schedule_service_ids = {'11772': 496}
    settings.horizon_days = 7
    settings.approvals.update(pilot_read_snapshots=True, pilot_scope_reviewed=True,
                              schedule_reference_verified=True)
    return settings


def seed(settings, store, now):
    first, last = bounds(now, settings.horizon_days)
    day = first.astimezone(BELGRADE).date()
    booking = {'id': 101, 'provider_id': 9, 'service_id': 496, 'client_id': 1,
               'start_datetime': f'{day} 10:00:00', 'end_datetime': f'{day} 10:30:00',
               'status': 'confirmed', 'email': 'DO_NOT_EXPORT_EMAIL',
               'phone': 'DO_NOT_EXPORT_PHONE', 'name': 'DO_NOT_EXPORT_NAME'}
    # Other providers/services must never cross the local publisher boundary.
    bookings = [booking, {**booking, 'id': 102, 'provider_id': 1000},
                {**booking, 'id': 103, 'service_id': 1000, 'status': 'canceled'},
                {**booking, 'id': 104, 'status': 'canceled'}]
    columns = {}
    while day < last.astimezone(BELGRADE).date():
        columns[str(day)] = {'date': str(day), 'from': '09:00:00', 'to': '17:00:00',
                             'is_day_off': False, 'breaktimes': [], 'blocked': [],
                             'notes': [{'id': 11, 'from': '12:00:00', 'to': '12:15:00',
                                        'time_blocked': True, 'provider_id': 9,
                                        'text': 'DO_NOT_EXPORT_NOTE', 'client_email': 'DO_NOT_EXPORT_EMAIL'},
                                       {'id': 12, 'from': '13:00:00', 'to': '13:15:00',
                                        'time_blocked': False, 'text': 'DO_NOT_EXPORT_NOTE'}],
                             'notes_text': 'DO_NOT_EXPORT_COLUMN'}
        day += timedelta(days=1)
    store.put('bookings', bookings, now)
    store.put('buffers', {'496': 0, '1000': 99}, now)
    store.put('schedule:11772', columns, now)


@pytest.fixture
def packet(scoped, store, now):
    seed(scoped, store, now)
    return build_packet(scoped, store, now=now)


def dump(store):
    # Includes unrelated cache, inbox and quota state; ignore SQLite implementation metadata.
    names = [r['name'] for r in store.rows("SELECT name FROM sqlite_master WHERE type='table' AND name!='sqlite_sequence'")]
    return {name: store.rows('SELECT * FROM ' + name + ' ORDER BY rowid') for name in names}


def receiver(tmp_path):
    return Store(tmp_path / 'receiver' / 'bridge.sqlite')


def test_export_only_contains_whitelisted_test_occupancy(scoped, packet, now):
    encoded = json.dumps(packet)
    assert 'DO_NOT_EXPORT' not in encoded
    assert 'client_id' not in encoded and 'client_email' not in encoded
    entries = {e['key']: e['value'] for e in packet['entries']}
    assert [r['id'] for r in entries['bookings']] == [101]
    assert entries['buffers'] == {'496': 0}
    assert all(len(day['notes']) == 1 for day in entries['schedule:11772'].values())
    assert validate_packet(scoped, packet, now=now)['occupancy_events'] > 0


def test_receive_preserves_timestamps_and_unrelated_state(scoped, packet, tmp_path, now):
    target = receiver(tmp_path)
    target.put('unrelated', {'keep': True}, now - 1)
    target.rate('sredime-post:11772', 60, now=now - 10)
    target.issue('feed:11772', 'booking_snapshot_stale', now - 1)
    result = import_packet(scoped, target, packet, now=now + 1)
    assert result['accepted'] and result['duplicate'] is False
    assert result['remote_import_confirmed'] is False
    for entry in packet['entries']:
        assert target.get(entry['key']) == (entry['value'], entry['updated'])
    assert target.get('unrelated') == ({'keep': True}, now - 1)
    assert target.rows('SELECT * FROM rates') == [{'key': 'sredime-post:11772', 'at': now - 10}]
    assert target.rows('SELECT resolved FROM issues WHERE key=?', ('feed:11772',)) == [{'resolved': 1}]
    assert not target.rows('SELECT * FROM events')
    assert not target.rows('SELECT * FROM intents')
    assert not target.rows('SELECT * FROM links')
    assert feed_version(make_feed(scoped, target, '11772', now + 1)[0]) == packet['feed_version']
    assert len(target.rows('SELECT * FROM refresh')) == 1


def test_duplicate_packet_is_idempotent_and_does_not_rejuvenate_snapshot(scoped, packet, tmp_path, now):
    target = receiver(tmp_path)
    import_packet(scoped, target, packet, now=now + 1)
    before = dump(target)
    result = import_packet(scoped, target, copy.deepcopy(packet), now=now + 10)
    assert result['duplicate'] is True
    assert dump(target) == before
    with pytest.raises(Review, match='stale'):
        import_packet(scoped, target, packet, now=now + scoped.snapshot_max_age + 1)
    assert dump(target) == before


@pytest.mark.parametrize('location', ['top', 'booking', 'schedule', 'note'])
def test_receiver_rejects_injected_pii_before_any_changes(scoped, packet, tmp_path, now, location):
    target = receiver(tmp_path)
    attack = copy.deepcopy(packet)
    if location == 'top': attack['admin_secret'] = 'DO_NOT_ACCEPT'
    elif location == 'booking': attack['entries'][0]['value'][0]['client_id'] = 1
    elif location == 'schedule': next(iter(attack['entries'][2]['value'].values()))['text'] = 'DO_NOT_ACCEPT'
    else: next(iter(attack['entries'][2]['value'].values()))['notes'][0]['text'] = 'DO_NOT_ACCEPT'
    before = dump(target)
    with pytest.raises(Review): import_packet(scoped, target, attack, now=now + 1)
    assert dump(target) == before


@pytest.mark.parametrize('field,value', [('source_employee_id', 'other'), ('target_provider_id', 999),
                                       ('target_provider_id', True), ('target_service_ids', [999]),
                                       ('target_service_ids', [True]), ('horizon_days', 60),
                                       ('schema_version', True), ('salon', 'other')])
def test_forged_scope_is_rejected(scoped, packet, tmp_path, now, field, value):
    target = receiver(tmp_path)
    attack = copy.deepcopy(packet); attack[field] = value
    with pytest.raises(Review, match='scope'): import_packet(scoped, target, attack, now=now)
    assert not target.rows('SELECT * FROM cache')


def test_forged_version_and_incomplete_schedule_are_rejected(scoped, packet, tmp_path, now):
    target = receiver(tmp_path)
    attack = copy.deepcopy(packet); attack['feed_version'] = '0' * 64
    with pytest.raises(Review, match='version_mismatch'): import_packet(scoped, target, attack, now=now)
    attack = copy.deepcopy(packet); attack['entries'][2]['value'].pop(next(iter(attack['entries'][2]['value'])))
    with pytest.raises(Review, match='coverage'): import_packet(scoped, target, attack, now=now)
    assert not target.rows('SELECT * FROM cache')


def test_invalid_work_hours_rejected_even_with_valid_shapes(scoped, packet, tmp_path, now):
    target = receiver(tmp_path)
    attack = copy.deepcopy(packet)
    next(iter(attack['entries'][2]['value'].values()))['from'] = '18:00:00'
    with pytest.raises(Review, match='work_schedule'): import_packet(scoped, target, attack, now=now)
    assert not target.rows('SELECT * FROM cache')


@pytest.mark.parametrize('offset', [-1000, 1000])
def test_stale_or_future_envelope_rejected(scoped, packet, tmp_path, now, offset):
    target = receiver(tmp_path)
    attack = copy.deepcopy(packet); attack['captured_at'] += offset
    with pytest.raises(Review, match='stale_or_future'): import_packet(scoped, target, attack, now=now)
    assert not target.rows('SELECT * FROM cache')


def test_replay_and_timestamp_conflict_cannot_restore_old_occupancy(scoped, packet, tmp_path, now):
    target = receiver(tmp_path)
    later = copy.deepcopy(packet); later['captured_at'] += 10
    for e in later['entries']: e['updated'] += 10
    import_packet(scoped, target, later, now=now + 10)
    before = dump(target)
    with pytest.raises(Review, match='replay_rollback'): import_packet(scoped, target, packet, now=now + 11)
    attack = copy.deepcopy(later); attack['captured_at'] += 1
    attack['entries'][0]['value'][0]['id'] = 202
    # The sender can know a hash, but cannot rewrite a prior capture timestamp.
    from booking_bridge.pilot_exchange import _PacketView
    attack['feed_version'] = feed_version(make_feed(scoped, _PacketView(attack['entries']), '11772', now + 11)[0])
    with pytest.raises(Review, match='timestamp_conflict'): import_packet(scoped, target, attack, now=now + 11)
    assert dump(target) == before


def test_receiver_transaction_rolls_back_all_caches_and_refresh_on_publish_failure(scoped, packet, tmp_path, now, monkeypatch):
    target = receiver(tmp_path)
    target.put('unrelated', 'keep', now)
    before = dump(target)
    original = target._publish_feed
    def fail_after_metadata(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('simulated disk failure before commit')
    monkeypatch.setattr(target, '_publish_feed', fail_after_metadata)
    with pytest.raises(RuntimeError): import_packet(scoped, target, packet, now=now + 1)
    assert dump(target) == before


def test_existing_uncertain_mutation_still_fences_feed_and_rolls_back(scoped, packet, tmp_path, now):
    target = receiver(tmp_path)
    target.execute('INSERT INTO intents VALUES(?,?,?,?,?,?,?,?,?)',
                   ('source-booking', 'event', 'create', None, '{}', '{}', 'uncertain', None, now))
    before = dump(target)
    with pytest.raises(Review, match='uncertain_mutation'):
        import_packet(scoped, target, packet, now=now + 1)
    assert dump(target) == before


def test_json_decoder_rejects_duplicate_keys_nonfinite_and_oversize():
    for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'x' * (MAX_PACKET_BYTES + 1), b'\xff'):
        with pytest.raises(Review): decode_packet(raw)


def test_isolated_profile_does_not_overlay_default_csv_and_default_guard_remains(tmp_path, monkeypatch):
    from booking_bridge import model
    home = tmp_path / 'home'; (home / 'mappings').mkdir(parents=True)
    (home / 'mappings/employees.local.csv').write_text('sredime_id,simplybook_id\n11772,999\n', encoding='utf-8')
    profile = tmp_path / 'pilot.json'
    profile.write_text(json.dumps({'employees': {'11772': {'id': 9}}, 'mode': 'simulation'}), encoding='utf-8')
    monkeypatch.setattr(model, 'HOME', home)
    for name in ('BRIDGE_ENV_FILE', 'BRIDGE_CONFIG_FILE', 'BRIDGE_FEED_TOKENS', 'SREDIME_EXPORT_URLS'):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(Review, match='conflicting_employees'):
        Settings.load(profile, read_only=True)
    assert Settings.load(profile, read_only=True, isolated_profile=True).employees == {'11772': {'id': 9}}
    with pytest.raises(Review, match='requires_read_only'):
        Settings.load(profile, isolated_profile=True)


def test_failed_capture_keeps_old_snapshots_and_metadata_completely_unchanged(scoped, store, now):
    seed(scoped, store, now - 60)
    before = dump(store)
    class FailingAccount:
        def bookings(self, start, end): return []
        def services(self): raise Review('simulated_buffer_read_failure')
    with pytest.raises(Review, match='buffer_read_failure'):
        capture_packet(scoped, store, FailingAccount(), clock=lambda: now)
    assert dump(store) == before


def test_capture_ignores_old_schedule_jobs_and_returns_only_a_complete_packet(scoped, store, now):
    from booking_bridge.tests.test_pilot_snapshot import ReadAccount
    seed(scoped, store, now - 60)
    store.put('schedule-job:11772', {'bad': 'old job must not be reused'}, now)
    store.put('schedule-backoff', True, now)
    class Account(ReadAccount):
        def services(self): self.reads += 1; return [{'id': 496, 'buffer_time_after': 0}]
    account = Account()
    result, packet = capture_packet(scoped, store, account, clock=lambda: now + 1)
    assert result['account_mutations'] == 0
    assert validate_packet(scoped, packet, now=now + 1)['feed_version'] == result['feed_version']
    assert account.reads >= 4
    assert store.get('schedule-job:11772')[0] == {'bad': 'old job must not be reused'}


def test_producer_excludes_locally_owned_mirrors_and_receiver_cannot_echo_them(scoped, store, tmp_path, now):
    seed(scoped, store, now)
    store.execute('INSERT INTO links VALUES(?,?,?,?,?)', ('source-booking', 101, now, '{}', 'active'))
    before_link = store.rows('SELECT * FROM links')
    packet = build_packet(scoped, store, now=now)
    assert packet['entries'][0]['value'] == []
    target = receiver(tmp_path)
    result = import_packet(scoped, target, packet, now=now + 1)
    assert result['accepted'] and not target.get('bookings')[0]
    assert result['feed_version'] == feed_version(make_feed(scoped, target, '11772', now + 1)[0])
    assert store.rows('SELECT * FROM links') == before_link


@pytest.mark.parametrize('fence', ['intent', 'drift', 'scope'])
def test_producer_does_not_hide_unresolved_local_fences(scoped, store, now, fence):
    seed(scoped, store, now)
    if fence == 'intent':
        store.execute('INSERT INTO intents VALUES(?,?,?,?,?,?,?,?,?)',
                       ('source-booking', 'event', 'create', None, '{}', '{}', 'uncertain', None, now))
    else:
        store.issue(fence + ':source-booking', 'unresolved_source_change', now, scope=['11772'])
    before = dump(store)
    with pytest.raises(Review, match='feed_paused'):
        build_packet(scoped, store, now=now)
    assert dump(store) == before


def test_capture_staging_preserves_destination_ownership(scoped, store, tmp_path, now):
    seed(scoped, store, now - 60)
    booking = store.get('bookings')[0][0]
    store.execute('INSERT INTO links VALUES(?,?,?,?,?)', ('source-booking', 101, now, '{}', 'active'))
    from booking_bridge.tests.test_pilot_snapshot import ReadAccount
    class Account(ReadAccount):
        def bookings(self, start, end): self.reads += 1; return [booking]
        def services(self): self.reads += 1; return [{'id': 496, 'buffer_time_after': 0}]
    report, packet = capture_packet(scoped, store, Account(), clock=lambda: now + 1)
    assert packet['entries'][0]['value'] == []
    assert store.rows('SELECT target FROM links') == [{'target': 101}]
    target = receiver(tmp_path)
    assert import_packet(scoped, target, packet, now=now + 2)['feed_version'] == report['feed_version']


def test_capture_does_not_hide_preexisting_drift_behind_new_staging_store(scoped, store, now):
    seed(scoped, store, now - 60)
    store.issue('drift:source-booking', 'unresolved_source_change', now, scope=['11772'])
    before = dump(store)
    from booking_bridge.tests.test_pilot_snapshot import ReadAccount
    class Account(ReadAccount):
        def services(self): self.reads += 1; return [{'id': 496, 'buffer_time_after': 0}]
    with pytest.raises(Review, match='source_drift'):
        capture_packet(scoped, store, Account(), clock=lambda: now + 1)
    assert dump(store) == before


def test_receiver_cli_rejects_private_extra_before_creating_destination_database(scoped, packet, monkeypatch, capsys):
    import io
    import sys
    from types import SimpleNamespace
    from booking_bridge import pilot_exchange
    packet['client_email'] = 'DO_NOT_PRINT_PRIVATE_VALUE'
    monkeypatch.setattr(sys, 'argv', ['pilot_exchange', '--read-only', '--stdin'])
    monkeypatch.setattr(sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(json.dumps(packet).encode())))
    monkeypatch.setattr(Settings, 'load', lambda **kwargs: scoped)
    assert pilot_exchange.main() == 1
    output = capsys.readouterr().out
    assert 'DO_NOT_PRINT_PRIVATE_VALUE' not in output
    assert json.loads(output)['accepted'] is False
    assert not (scoped.state / 'bridge.sqlite').exists()


def test_off_day_time_fields_cannot_be_used_to_smuggle_free_text(scoped, packet, now):
    day = next(iter(packet['entries'][2]['value'].values()))
    day['is_day_off'] = True
    day['from'] = 'DO_NOT_ACCEPT_PRIVATE_TEXT'
    with pytest.raises(Review, match='invalid_packet_time'):
        validate_packet(scoped, packet, now=now)


@pytest.mark.parametrize('bad_time', ['24:00:99', '25:00', '12:65'])
def test_even_off_day_unused_time_fields_must_be_real_times(scoped, packet, now, bad_time):
    day = next(iter(packet['entries'][2]['value'].values()))
    day['is_day_off'] = True
    day['from'] = bad_time
    with pytest.raises(Review, match='invalid_packet_time'):
        validate_packet(scoped, packet, now=now)


def test_export_filters_boundary_day_outside_horizon_and_receiver_rejects_injection(scoped, store, now):
    seed(scoped, store, now)
    _, last = bounds(now, scoped.horizon_days)
    outside_day = last.astimezone(BELGRADE).date()
    bookings = store.get('bookings')[0]
    bookings.append({**bookings[0], 'id': 999, 'start_datetime': f'{outside_day} 10:00:00',
                     'end_datetime': f'{outside_day} 10:30:00'})
    store.put('bookings', bookings, now)
    packet = build_packet(scoped, store, now=now)
    assert [r['id'] for r in packet['entries'][0]['value']] == [101]
    injected = {k: bookings[-1][k] for k in ('id', 'provider_id', 'service_id', 'start_datetime', 'end_datetime', 'status')}
    packet['entries'][0]['value'].append(injected)
    with pytest.raises(Review, match='outside_horizon'):
        validate_packet(scoped, packet, now=now)


def test_active_nonpilot_service_on_test_provider_fails_closed(scoped, store, now):
    seed(scoped, store, now)
    bookings = store.get('bookings')[0]
    bookings.append({**bookings[0], 'id': 999, 'service_id': 1000})
    store.put('bookings', bookings, now)
    before = dump(store)
    with pytest.raises(Review, match='provider_booking_outside_test_service_scope'):
        build_packet(scoped, store, now=now)
    assert dump(store) == before


def test_capture_of_nonpilot_service_does_not_freshen_previously_published_snapshot(scoped, store, now):
    seed(scoped, store, now - 60)
    booking = {**store.get('bookings')[0][0], 'id': 999, 'service_id': 1000}
    before = dump(store)
    from booking_bridge.tests.test_pilot_snapshot import ReadAccount
    class Account(ReadAccount):
        def bookings(self, start, end): self.reads += 1; return [booking]
        def services(self):
            self.reads += 1
            return [{'id': 496, 'buffer_time_after': 0}, {'id': 1000, 'buffer_time_after': 0}]
    with pytest.raises(Review, match='provider_booking_outside_test_service_scope'):
        capture_packet(scoped, store, Account(), clock=lambda: now + 1)
    assert dump(store) == before
