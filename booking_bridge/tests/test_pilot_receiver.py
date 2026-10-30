import hashlib
import hmac
import json
import time
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from booking_bridge.api import create_app
from booking_bridge.calendar import bounds
from booking_bridge.model import BELGRADE, Review, Settings
from booking_bridge import pilot_receiver
from booking_bridge.store import Store


def prepare(settings):
    employee = settings.allowed_employees[0]
    settings.allowed_employees = [employee]
    settings.employees = {employee: settings.employees[employee]}
    settings.pilot_service_ids = [91, 92]
    settings.horizon_days = 7
    settings.schedule_service_ids = {employee: 91}
    settings.approvals.update(pilot_scope_reviewed=True, pilot_read_snapshots=True,
                              schedule_reference_verified=True)


def prime_feed(settings, store, now):
    first, last = bounds(now, settings.horizon_days)
    day = first.astimezone(BELGRADE).date()
    columns = {}
    while day < last.astimezone(BELGRADE).date():
        columns[str(day)] = {'date': str(day), 'from': '09:00:00', 'to': '17:00:00',
                             'is_day_off': False, 'breaktimes': [], 'blocked': [], 'notes': []}
        day += timedelta(days=1)
    store.put('schedule:' + settings.allowed_employees[0], columns, now)
    store.put('bookings', [], now)
    store.put('buffers', {'91': 0, '92': 0}, now)


def test_signed_real_envelope_stays_queued_without_simulated_links(settings, store, event, monkeypatch):
    prepare(settings)
    # Even a complete, write-capable test mapping must never be executed by the
    # receiver. Deliberately configured alerts must not produce network requests.
    settings.alerts_url = 'https://alerts.example.invalid/receiver'
    settings.approvals['live_writes'] = True

    def forbidden(*args, **kwargs):
        raise AssertionError('Receiver must never construct account execution components')

    monkeypatch.setattr('booking_bridge.simplybook.Gateway.__init__', forbidden)
    monkeypatch.setattr('booking_bridge.simplybook.SimulatedGateway.__init__', forbidden)
    monkeypatch.setattr('booking_bridge.worker.Worker.__init__', forbidden)
    body = json.dumps(event).encode()
    signature = 'sha256=' + hmac.new(settings.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    with TestClient(create_app(settings, store)) as client:
        response = client.post('/sredime/webhook', content=body,
                               headers={'X-SrediMe-Signature': signature})
    assert response.status_code == 202
    before = store.rows('SELECT * FROM events')
    assert len(before) == 1 and before[0]['state'] == 'queued'
    assert json.loads(before[0]['payload'])['test'] is False
    moment = time.time() + 11
    prime_feed(settings, store, moment)
    result = pilot_receiver.monitor_once(settings, store, moment)
    assert store.rows('SELECT * FROM events') == before
    assert store.rows('SELECT * FROM links') == []
    assert store.rows('SELECT * FROM intents') == []
    assert store.rows('SELECT * FROM clients') == []
    assert store.get('heartbeat') == (True, moment)
    assert store.get('health') == ({'open_issues': 1, 'old_queued': 1}, moment)
    assert result == {'receiver_only': True, 'mode': 'simulation', 'reads_enabled': False,
                      'old_queued': 1, 'open_issues': 1, 'events_processed': 0,
                      'account_reads': 0, 'account_mutations': 0}


def test_monitor_preserves_working_intents_and_existing_incidents(settings, store, event, now):
    prepare(settings)
    store.ingest(event, now=now)
    store.execute("UPDATE events SET state='working',attempts=2")
    store.execute('INSERT INTO intents VALUES(?,?,?,?,?,?,?,?,?)',
                  (event['data']['id'], event['id'], 'create', None, '{}', '[]', 'started', None, now))
    store.issue('feed:test', 'booking_snapshot_stale', now)
    prime_feed(settings, store, now)
    events = store.rows('SELECT * FROM events')
    intents = store.rows('SELECT * FROM intents')
    pilot_receiver.monitor_once(settings, store, now + 11)
    assert store.rows('SELECT * FROM events') == events
    assert store.rows('SELECT * FROM intents') == intents
    assert store.get('health')[0] == {'open_issues': 3, 'old_queued': 1}
    assert store.is_ready(now + 11) is False


def test_empty_receiver_updates_health_and_resolves_old_queue_incident(settings, store, now):
    prepare(settings)
    store.issue('queue-age', 'webhook_processing_delayed', now - 20)
    prime_feed(settings, store, now)
    pilot_receiver.monitor_once(settings, store, now)
    assert store.get('heartbeat') == (True, now)
    assert store.get('health') == ({'open_issues': 0, 'old_queued': 0}, now)
    assert store.is_ready(now) is True


def test_fresh_imported_packet_is_healthy_then_expires_without_fetch_or_inbox_effects(settings, store, event, now, tmp_path):
    from booking_bridge.pilot_exchange import build_packet, import_packet
    prepare(settings)
    publisher = Store(tmp_path / 'publisher.sqlite')
    prime_feed(settings, publisher, now)
    packet = build_packet(settings, publisher, now=now)
    import_packet(settings, store, packet, now=now)
    store.ingest(event, now=now)
    before = store.rows('SELECT * FROM events')
    pilot_receiver.monitor_once(settings, store, now + 1)
    assert store.is_ready(now + 1) is True
    later = now + settings.snapshot_max_age + 1
    pilot_receiver.monitor_once(settings, store, later)
    assert store.is_ready(later) is False
    assert store.rows('SELECT reason,resolved FROM issues WHERE key=?',
                      ('feed:' + settings.allowed_employees[0],)) == [
                          {'reason': 'booking_snapshot_stale', 'resolved': 0}]
    assert store.rows('SELECT * FROM events') == before
    assert store.rows('SELECT * FROM links') == []
    assert store.rows('SELECT * FROM intents') == []
    # Local monitoring must not claim that the remote importer fetched anything.
    assert store.get('feed-last-served:' + settings.allowed_employees[0]) == (None, 0)


@pytest.mark.parametrize('reason,cleared', [
    ('booking_snapshot_stale', True), ('schedule_snapshot_stale', True),
    ('service_buffers_stale', True), ('manual_safety_hold', False),
    ('feed_paused_for_source_drift', False), ('feed_paused_for_uncertain_mutation', False),
])
def test_fresh_feed_only_clears_known_staleness_incidents(settings, store, now, reason, cleared):
    prepare(settings)
    prime_feed(settings, store, now)
    key = 'feed:' + settings.allowed_employees[0]
    store.issue(key, reason, now - 1)
    pilot_receiver.monitor_once(settings, store, now)
    assert store.rows('SELECT reason,resolved FROM issues WHERE key=?', (key,)) == [
        {'reason': reason, 'resolved': int(cleared)}]
    assert store.is_ready(now) is cleared


def test_missing_snapshot_does_not_overwrite_an_unrelated_feed_safety_incident(settings, store, now):
    prepare(settings)
    key = 'feed:' + settings.allowed_employees[0]
    store.issue(key, 'manual_safety_hold', now - 1)
    pilot_receiver.monitor_once(settings, store, now)
    assert store.rows('SELECT reason,resolved FROM issues WHERE key=?', (key,)) == [
        {'reason': 'manual_safety_hold', 'resolved': 0}]
    assert store.is_ready(now) is False


@pytest.mark.parametrize('field,value', [
    ('mode', 'pilot'), ('mode', 'production'),
    ('reads_enabled', True), ('reads_enabled', 0), ('reads_enabled', None),
    ('pilot_scope_reviewed', False), ('pilot_scope_reviewed', 1),
])
def test_invalid_execution_profile_rejected_before_store_effect(settings, store, field, value):
    prepare(settings)
    if field == 'pilot_scope_reviewed':
        settings.approvals[field] = value
    else:
        setattr(settings, field, value)
    with pytest.raises(Review, match='explicit_receiver_pilot_profile_required'):
        pilot_receiver.monitor_once(settings, store, 1000)
    assert store.rows('SELECT * FROM cache') == []
    assert store.rows('SELECT * FROM issues') == []


@pytest.mark.parametrize('invalid', [
    'no_employee', 'second_employee', 'unlisted_employee_mapping', 'missing_employee_mapping',
    'invalid_provider_id', 'no_services', 'no_pilot_services', 'service_outside_scope',
    'unused_pilot_service', 'invalid_service_id', 'duplicate_pilot_service',
])
def test_invalid_scope_rejected_before_store_effect(settings, store, invalid):
    prepare(settings)
    if invalid == 'no_employee': settings.allowed_employees = []
    elif invalid == 'second_employee': settings.allowed_employees.append('another-employee')
    elif invalid == 'unlisted_employee_mapping': settings.employees['another-employee'] = {'id': 82}
    elif invalid == 'missing_employee_mapping': settings.employees = {}
    elif invalid == 'invalid_provider_id': settings.employees[settings.allowed_employees[0]]['id'] = True
    elif invalid == 'no_services': settings.services = {}
    elif invalid == 'no_pilot_services': settings.pilot_service_ids = []
    elif invalid == 'service_outside_scope': settings.services['synthetic-service-A']['id'] = 999
    elif invalid == 'unused_pilot_service': settings.pilot_service_ids.append(999)
    elif invalid == 'invalid_service_id': settings.services['synthetic-service-A']['id'] = '91'
    elif invalid == 'duplicate_pilot_service': settings.pilot_service_ids.append(91)
    with pytest.raises(Review, match='receiver_scope_required'):
        pilot_receiver.monitor_once(settings, store, 1000)
    assert store.rows('SELECT * FROM cache') == []
    assert store.rows('SELECT * FROM issues') == []


def test_cli_once_is_bounded_and_loads_settings_without_live_validation(settings, store, monkeypatch, capsys):
    prepare(settings)
    calls = []
    monkeypatch.setattr(Settings, 'load', classmethod(lambda cls, **kwargs: calls.append(kwargs) or settings))
    monkeypatch.setattr(pilot_receiver, 'Store', lambda path: store)
    monkeypatch.setattr(pilot_receiver.time, 'sleep', lambda seconds: pytest.fail('Once must not sleep'))
    assert pilot_receiver.main(['--once']) == 0
    assert calls == [{'read_only': True}]
    assert json.loads(capsys.readouterr().out)['events_processed'] == 0


def test_cli_checks_scope_before_database_or_lock_creation(settings, monkeypatch):
    prepare(settings)
    settings.mode = 'pilot'
    monkeypatch.setattr(Settings, 'load', classmethod(lambda cls, **kwargs: settings))

    def forbidden(*args, **kwargs):
        raise AssertionError('Invalid profile must not initialize state')

    monkeypatch.setattr(pilot_receiver, 'Store', forbidden)
    monkeypatch.setattr(pilot_receiver, 'lock', forbidden)
    with pytest.raises(Review, match='explicit_receiver_pilot_profile_required'):
        pilot_receiver.main(['--once'])


@pytest.mark.parametrize('interval', ['0', '61', '-1', '1.5'])
def test_cli_rejects_unbounded_intervals_before_loading_settings(interval, monkeypatch):
    monkeypatch.setattr(Settings, 'load', classmethod(lambda cls, **kwargs: pytest.fail('No settings read expected')))
    with pytest.raises(SystemExit) as exc:
        pilot_receiver.main(['--once', '--interval', interval])
    assert exc.value.code == 2
