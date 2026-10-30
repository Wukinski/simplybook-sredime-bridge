"""Offline latency and safety contracts; no claims about remote import timing."""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from booking_bridge.api import create_app
from booking_bridge.calendar import bounds, feed_version, make_feed
from booking_bridge.model import BELGRADE, Review, Settings
from booking_bridge.preflight import inspect
from booking_bridge.scheduler import Scheduler
from booking_bridge.store import Store
from booking_bridge.tests.test_calendar import booking, prime


EMPLOYEE = 'synthetic-employee-A'


def fast_scheduler(settings, store, gateway, worker, monkeypatch):
    settings.reads_enabled = True
    scheduler = Scheduler(settings, store, gateway, worker)
    for name in ('snapshot_buffers', 'schedule_step', 'poll_source', 'refresh_source', 'monitor'):
        monkeypatch.setattr(scheduler, name, lambda *args: None)
    monkeypatch.setattr(worker, 'reconcile_all', lambda *args: None)
    return scheduler


def test_signed_hint_triggers_read_after_ten_seconds_and_preserves_inflight_hint(
        settings, store, gateway, worker, now, monkeypatch):
    scheduler = fast_scheduler(settings, store, gateway, worker, monkeypatch)
    store.put('task:bookings', True, now)
    store.put('sb-change-hint', True, now+1)
    calls = []
    def read(*args):
        calls.append(args)
        if len(calls) == 1:
            store.put('sb-change-hint', True, now+11)
        return []
    monkeypatch.setattr(gateway, 'bookings', read)
    scheduler.tick(now+9)
    assert not calls
    scheduler.tick(now+10)
    assert len(calls) == 1
    assert store.get('bookings-hint-applied')[1] == now+1
    scheduler.tick(now+19)
    assert len(calls) == 1
    scheduler.tick(now+20)
    assert len(calls) == 2


def test_acceleration_budget_keeps_hint_and_does_not_disable_fallback(
        settings, store, gateway, worker, now, monkeypatch):
    scheduler = fast_scheduler(settings, store, gateway, worker, monkeypatch)
    store.put('task:bookings', True, now)
    store.put('sb-change-hint', True, now+1)
    for _ in range(60):
        assert store.rate('sb-accelerated-snapshots', 60, now=now)
    calls = []
    monkeypatch.setattr(gateway, 'bookings', lambda *args: calls.append(args) or [])
    scheduler.tick(now+10)
    assert not calls and store.get('bookings-hint-applied')[1] == 0
    scheduler.tick(now+300)
    assert len(calls) == 1


def live_refresh(settings, store, gateway, worker, now, request):
    prime(settings, store, now, [booking()])
    settings.mode = 'pilot'
    settings.approvals['sredime_refresh'] = True
    settings.export_urls = {EMPLOYEE: 'https://example.invalid/private'}
    return Scheduler(settings, store, gateway, worker, request=request)


def test_burst_refresh_has_immediate_first_and_durable_trailing_batch(settings, store, gateway, worker, now):
    calls = []
    scheduler = live_refresh(settings, store, gateway, worker, now, lambda *args: calls.append(args))
    store.refresh(EMPLOYEE, now)
    scheduler.refresh_source(now)
    for offset in range(1, 5):
        store.refresh(EMPLOYEE, now+offset)
        scheduler.refresh_source(now+offset)
    assert len(calls) == 1
    # Reconstruct both objects to prove coalescing survives process restart.
    restored = Store(store.path)
    scheduler = Scheduler(settings, restored, gateway, worker, request=lambda *args: calls.append(args))
    scheduler.refresh_source(now+5)
    assert len(calls) == 2 and not restored.rows('SELECT * FROM refresh')


def test_change_during_post_is_not_lost(settings, store, gateway, worker, now):
    calls = []
    def request(*args):
        calls.append(args)
        if len(calls) == 1:
            store.refresh(EMPLOYEE, now+1)
    scheduler = live_refresh(settings, store, gateway, worker, now, request)
    store.refresh(EMPLOYEE, now)
    scheduler.refresh_source(now)
    assert store.rows('SELECT * FROM refresh') == [{'employee': EMPLOYEE, 'due': now+5}]
    scheduler.refresh_source(now+4)
    assert len(calls) == 1
    scheduler.refresh_source(now+5)
    assert len(calls) == 2 and not store.rows('SELECT * FROM refresh')


def test_post_attempts_obey_rolling_hour_even_after_restart(settings, store, gateway, worker, now):
    calls = []
    scheduler = live_refresh(settings, store, gateway, worker, now, lambda *args: calls.append(args))
    for offset in range(0, 3600, 30):
        # Keep snapshots fresh; actual network is replaced by an in-memory recorder.
        if offset % 600 == 0:
            prime(settings, store, now+offset, [booking()])
        store.refresh(EMPLOYEE, now+offset)
        scheduler.refresh_source(now+offset)
    assert len(calls) == 60
    assert len(store.rows('SELECT * FROM refresh')) == 1


def test_stale_or_incomplete_feed_cannot_trigger_early_import(settings, store, gateway, worker, now):
    calls = []
    scheduler = live_refresh(settings, store, gateway, worker, now, lambda *args: calls.append(args))
    store.execute('DELETE FROM cache WHERE key=?', ('schedule:' + EMPLOYEE,))
    store.refresh(EMPLOYEE, now)
    scheduler.refresh_source(now)
    assert not calls and store.rows('SELECT * FROM refresh')


def test_pending_refresh_from_previous_version_can_complete(settings, store, gateway, worker, now):
    calls = []
    scheduler = live_refresh(settings, store, gateway, worker, now, lambda *args: calls.append(args))
    store.execute('INSERT INTO refresh VALUES(?,?)', (EMPLOYEE, now))
    scheduler.refresh_source(now)
    assert len(calls) == 1 and not store.rows('SELECT * FROM refresh')


def test_manual_refresh_requires_admin_and_employee_scope(settings, store):
    headers = {'X-API-Key': settings.admin_key}
    with TestClient(create_app(settings, store)) as client:
        url = '/ops/availability/' + EMPLOYEE + '/refresh'
        assert client.post(url).status_code == 401
        assert client.post('/ops/availability/unknown/refresh', headers=headers).status_code == 404
        assert client.post(url, headers=headers).status_code == 202
        assert client.post(url, headers=headers).status_code == 429
        assert store.get('schedule-request:' + EMPLOYEE)[0] is True
        assert not store.rows('SELECT * FROM intents')


def test_telemetry_correlates_exact_fetched_version_without_claiming_import(settings, store, gateway, worker, now, monkeypatch):
    # The fixed fixture bookings must stay inside the tested horizon even when
    # this suite is run months later. Advance API and scheduler clocks together.
    current = [now]
    monkeypatch.setattr('booking_bridge.api.time.time', lambda: current[0])
    prime(settings, store, now, [booking()])
    scheduler = Scheduler(settings, store, gateway, worker)
    scheduler.queue_if_feed_changed(EMPLOYEE, now)
    headers = {'X-API-Key': settings.admin_key}
    with TestClient(create_app(settings, store)) as client:
        assert client.get('/ops/availability').status_code == 401
        report = client.get('/ops/availability', headers=headers).json()
        assert report['subminute_verified'] is False
        assert report['employees'][0]['current_version_fetched'] is False
        feed = client.get('/ics/' + EMPLOYEE + '/' + settings.feed_tokens[EMPLOYEE] + '.ics')
        assert feed.status_code == 200
        assert store.get('feed-last-served:' + EMPLOYEE)[0]['version'] == feed_version(feed.content)
        report = client.get('/ops/availability', headers=headers).json()
        assert report['employees'][0]['current_version_fetched'] is True
        assert report['employees'][0]['import_confirmed'] is False
        current[0] = now + 1
        store.put('bookings', [booking(start_datetime='2026-10-23 12:00:00',
                                       end_datetime='2026-10-23 13:00:00')], now+1)
        scheduler.queue_if_feed_changed(EMPLOYEE, now+1)
        report = client.get('/ops/availability', headers=headers).json()
        assert report['employees'][0]['current_version_fetched'] is False


class ScheduleGateway:
    def __init__(self):
        self.calls = []
        self.closed = False

    def provider_schedule(self, provider, service, start, end):
        self.calls.append(('reference', provider, start, end))
        return {}

    def calendar_week(self, provider, start, reference):
        self.calls.append(('week', provider, start))
        return {str(start+timedelta(days=n)): {
            'date': str(start+timedelta(days=n)), 'from': '00:00:00', 'to': '24:00:00',
            'is_day_off': self.closed, 'breaktimes': [], 'blocked': [], 'notes': []} for n in range(7)}


def schedule_setup(settings, store, worker):
    settings.schedule_service_ids = {e: 91 for e in settings.allowed_employees}
    settings.approvals['schedule_reference_verified'] = True
    gateway = ScheduleGateway()
    return Scheduler(settings, store, gateway, worker), gateway


def test_schedule_is_one_read_per_step_and_restartable_with_complete_publication(settings, store, worker, now):
    scheduler, gateway = schedule_setup(settings, store, worker)
    scheduler.schedule_step(now)
    assert len(gateway.calls) == 1 and store.get('schedule:' + EMPLOYEE)[0] is None
    for offset in range(1, 35):
        # Recreate scheduler each tick, as after a process restart.
        scheduler = Scheduler(settings, Store(store.path), gateway, worker)
        before = len(gateway.calls)
        scheduler.schedule_step(now+offset)
        assert len(gateway.calls) - before <= 1
    first, last = bounds(now, settings.horizon_days)
    for employee in settings.allowed_employees:
        columns, updated = store.get('schedule:' + employee)
        from booking_bridge.calendar import schedule_blocks
        assert schedule_blocks(columns, first, last, settings.employees[employee]['id']) == []
        assert now <= updated <= now+35


def test_near_week_merge_never_renews_far_future_freshness(settings, store, worker, now):
    settings.allowed_employees = [EMPLOYEE]
    prime(settings, store, now)
    scheduler, gateway = schedule_setup(settings, store, worker)
    gateway.closed = True
    for offset in range(3):
        scheduler.schedule_step(now+1000+offset)
    columns, updated = store.get('schedule:' + EMPLOYEE)
    assert updated == now
    assert store.get('schedule-near:' + EMPLOYEE)[1] == now+1000
    assert any(c['is_day_off'] for c in columns.values())
    assert any(not c['is_day_off'] for c in columns.values())
    store.put('bookings', [], now+4501)
    with pytest.raises(Review, match='schedule_snapshot_stale'):
        make_feed(settings, store, EMPLOYEE, now+4501)


def test_manual_schedule_refresh_prioritizes_employee(settings, store, worker, now):
    prime(settings, store, now)
    scheduler, gateway = schedule_setup(settings, store, worker)
    store.put('schedule-request:synthetic-employee-B', True, now+1)
    scheduler.schedule_step(now+2)
    assert gateway.calls[0][1] == 82


def test_midnight_restarts_partial_scan_instead_of_publishing_wrong_horizon(settings, store, worker):
    instant = datetime(2026, 10, 24, 23, 59, tzinfo=BELGRADE).timestamp()
    scheduler, gateway = schedule_setup(settings, store, worker)
    scheduler.schedule_step(instant)
    scheduler.schedule_step(instant+120)
    assert [c[0] for c in gateway.calls] == ['reference', 'reference']
    assert store.get('schedule:' + EMPLOYEE)[0] is None


def test_default_subminute_requirement_blocks_ics_production(settings):
    assert Settings().require_subminute_availability is True
    settings.require_subminute_availability = True
    settings.mode = 'production'
    with pytest.raises(Review, match='subminute_availability_transport_not_available'):
        settings.validate()
    report = inspect(settings, 'production', environ={})
    assert {'code': 'subminute_availability_transport', 'ok': False} in report['checks']
    # Pilot remains available to measure the integration; this flag cannot certify it.
    settings.mode = 'simulation'
    settings.validate()
