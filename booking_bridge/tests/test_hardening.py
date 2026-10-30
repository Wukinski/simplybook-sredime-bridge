import copy
import hashlib
import hmac
import json
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from booking_bridge.api import create_app
from booking_bridge.store import Store
from booking_bridge.worker import Worker
from conftest import changed, state


@pytest.mark.parametrize('order', ['newer_first', 'older_queued_first', 'both_queued'])
def test_ignored_newer_snapshot_prevents_older_write(settings, store, gateway, event, now, order):
    settings.allowed_employees = ['synthetic-employee-A']
    newer = changed(event, 3)
    newer['data']['employee']['id'] = 'outside-pilot'
    worker = Worker(settings, store, gateway)
    if order == 'newer_first':
        store.ingest(newer); worker.once(now+300)
        store.ingest(event)
    elif order == 'older_queued_first':
        store.ingest(event); store.ingest(newer)
    else:
        store.ingest(newer); store.ingest(event)
    while worker.once(now+300):
        pass
    assert not gateway.calls
    assert state(store, event)['state'] == 'stale'
    assert store.rows('SELECT created FROM booking_heads')[0]['created'] > now


def test_ignored_version_survives_restart_and_retry(settings, store, gateway, event, now):
    newer = changed(event, 3); newer['data']['employee']['id'] = 'outside-pilot'
    store.ingest(newer); Worker(settings, store, gateway).once(now+300)
    store.ingest(event)
    store.finish(event['id'], 'review', 'historical_review')
    restarted = Store(store.path); restarted.recover(); restarted.retry(event['id'])
    Worker(settings, restarted, gateway).once(now+300)
    assert state(restarted, event)['state'] == 'stale'
    assert not gateway.calls


def test_test_delivery_cannot_advance_real_head(settings, store, gateway, event, now):
    newer = changed(event, 3); newer['test'] = True
    store.ingest(newer); store.ingest(event)
    worker = Worker(settings, store, gateway)
    worker.once(now+300); worker.once(now+300)
    assert state(store, event)['state'] == 'done'
    assert store.rows('SELECT created FROM booking_heads')[0]['created'] == now


def test_migration_backfills_ignored_heads_without_losing_rows(store, event, now):
    newer = changed(event, 3); newer['data']['employee']['id'] = 'outside-pilot'
    store.ingest(newer); store.finish(newer['id'], 'ignored')
    store.execute('DELETE FROM booking_heads')
    store.execute('PRAGMA user_version=0')
    migrated = Store(store.path)
    assert migrated.rows('SELECT event FROM booking_heads') == [{'event': newer['id']}]
    assert state(migrated, newer)['state'] == 'ignored'
    assert len(Store(store.path).rows('SELECT * FROM booking_heads')) == 1


def test_equal_timestamp_outside_scope_still_conflicts(store, settings, gateway, event, now):
    other = copy.deepcopy(event); other['id'] = 'f'*32; other['data']['employee']['id'] = 'outside-pilot'
    store.ingest(other); store.finish(other['id'], 'ignored'); store.ingest(event)
    Worker(settings, store, gateway).once(now)
    assert state(store, event)['reason'] == 'equal_timestamp_conflicting_snapshots'
    assert not gateway.calls


def test_locked_ingress_returns_503_without_ack_or_partial_head(settings, store, event):
    store.timeout = .15
    body = json.dumps(event).encode()
    headers = {'X-SrediMe-Signature': 'sha256=' + hmac.new(settings.webhook_secret.encode(), body, hashlib.sha256).hexdigest()}
    with TestClient(create_app(settings, store)) as client:
        blocker = sqlite3.connect(store.path, isolation_level=None)
        blocker.execute('BEGIN IMMEDIATE')
        try:
            started = time.monotonic()
            response = client.post('/sredime/webhook', content=body, headers=headers)
            elapsed = time.monotonic() - started
            assert response.status_code == 503 and elapsed < 1.5
            assert 'received' not in response.json()
            assert client.get('/health/live').status_code == 200
        finally:
            blocker.rollback(); blocker.close()
    assert not store.rows('SELECT id FROM events')
    assert not store.rows('SELECT booking FROM booking_heads')


def test_baseline_range_uses_company_date(worker, store, gateway, event, now, monkeypatch):
    event['data'].update(start_at='2026-10-23T00:30:00+02:00', end_at='2026-10-23T01:30:00+02:00')
    calls = []
    original = gateway.bookings
    def inventory(start, end):
        calls.append((start, end)); return original(start, end)
    monkeypatch.setattr(gateway, 'bookings', inventory)
    store.ingest(event); worker.once(now)
    assert calls == [('2026-10-23', '2026-10-23')]


def test_scoped_uncertain_create_does_not_stop_another_employee(settings, store, worker, gateway, event, now):
    from test_calendar import prime
    from booking_bridge.calendar import make_feed
    from booking_bridge.model import Review
    prime(settings, store, now)
    gateway.timeout_after_create = True
    store.ingest(event); worker.once(now)
    with pytest.raises(Review, match='uncertain'): make_feed(settings, store, 'synthetic-employee-A', now)
    assert make_feed(settings, store, 'synthetic-employee-B', now)[1] == 0


def test_uncertain_move_pauses_old_new_and_actual_employee(settings, store, worker, event, now):
    from test_calendar import prime
    from booking_bridge.calendar import make_feed
    from booking_bridge.model import Review
    settings.employees['synthetic-employee-C'] = {'id': 83}
    settings.allowed_employees.append('synthetic-employee-C')
    prime(settings, store, now)
    store.ingest(event)
    row = store.claim(now)
    old = copy.deepcopy(event['data'])
    old['employee']['id'] = 'synthetic-employee-B'
    store.execute('INSERT INTO links VALUES(?,?,?,?,?)', (row['booking'], 1001, now-60, json.dumps(old), 'active'))
    worker.intent(row, 'edit', 1001, {'provider_id': 81}, [])
    worker.observe_intent_scope(row['booking'], {'provider_id': 83})
    for employee in settings.allowed_employees:
        with pytest.raises(Review, match='uncertain'): make_feed(settings, store, employee, now)


def test_scoped_drift_affects_previous_and_actual_employee_only(settings, store, worker, gateway, event, now):
    from test_calendar import prime, booking
    from booking_bridge.calendar import make_feed
    from booking_bridge.scheduler import Scheduler
    from booking_bridge.model import Review
    settings.employees['synthetic-employee-C'] = {'id': 83}
    settings.allowed_employees.append('synthetic-employee-C')
    store.ingest(event); worker.once(now)
    prime(settings, store, now)
    gateway.items[1001]['provider_id'] = 82
    Scheduler(settings, store, gateway, worker).snapshot_bookings(now)
    for employee in ('synthetic-employee-A', 'synthetic-employee-B'):
        with pytest.raises(Review, match='source_drift'): make_feed(settings, store, employee, now)
    assert make_feed(settings, store, 'synthetic-employee-C', now)[1] == 0


def test_unknown_legacy_scope_still_stops_all_feeds(settings, store, now):
    from test_calendar import prime
    from booking_bridge.calendar import make_feed
    from booking_bridge.model import Review
    prime(settings, store, now)
    store.issue('drift:legacy', 'unscoped_historical_issue', now)
    for employee in settings.allowed_employees:
        with pytest.raises(Review, match='source_drift'): make_feed(settings, store, employee, now)


def test_async_ingress_keeps_health_responsive_and_deduplicates(settings, store, event, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    entered, release = threading.Event(), threading.Event()
    original = store.ingest
    def delayed(value):
        entered.set()
        if not release.wait(3): raise AssertionError('Test ingress did not release')
        return original(value)
    monkeypatch.setattr(store, 'ingest', delayed)
    body = json.dumps(event).encode()
    headers = {'X-SrediMe-Signature': 'sha256=' + hmac.new(settings.webhook_secret.encode(), body, hashlib.sha256).hexdigest()}
    with TestClient(create_app(settings, store)) as client, ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(client.post, '/sredime/webhook', content=body, headers=headers)
        try:
            assert entered.wait(2)
            started = time.monotonic()
            assert client.get('/health/live').status_code == 200
            assert time.monotonic()-started < 1
        finally:
            release.set()
        assert first.result(timeout=3).status_code == 202
        assert client.post('/sredime/webhook', content=body, headers=headers).status_code == 202
    assert len(store.rows('SELECT id FROM events')) == 1


def test_newer_outside_scope_during_preflight_prevents_dispatch(worker, store, gateway, event, now, monkeypatch):
    newer = changed(event, 3); newer['data']['employee']['id'] = 'outside-pilot'
    def check_slot(desired, target=None): store.ingest(newer)
    monkeypatch.setattr(gateway, 'ensure_available', check_slot)
    store.ingest(event); worker.once(now+300)
    assert state(store, event)['state'] == 'stale'
    assert not gateway.calls and not store.rows('SELECT * FROM intents')


def test_missing_employee_is_review_not_silently_ignored(worker, store, gateway, event, now):
    event['data'].pop('employee')
    store.ingest(event); worker.once(now)
    assert state(store, event)['reason'] == 'missing_employee_id'
    assert state(store, event)['state'] == 'review' and not gateway.calls
