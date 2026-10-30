"""Deterministic local stages; no simulated receipt is a real provider guarantee."""
import copy
import json
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from booking_bridge.api import create_app
from booking_bridge.calendar import make_feed
from booking_bridge.diagnostics import ReadOnlyGateway
from booking_bridge.latency import employee_latency
from booking_bridge.model import Review
from booking_bridge.scheduler import Scheduler
from booking_bridge.store import Store
from booking_bridge.tests.test_calendar import booking, prime

EMPLOYEE = 'synthetic-employee-A'


def scheduler_fixture(settings, store, gateway, worker, now, request=None):
    prime(settings, store, now, [booking()])
    settings.mode = 'pilot'
    settings.approvals['sredime_refresh'] = True
    settings.export_urls = {EMPLOYEE: 'https://example.invalid/private'}
    return Scheduler(settings, store, gateway, worker, request=request or (lambda *args: None))


def test_second_change_is_not_forced_to_wait_a_minute(settings, store, gateway, worker, now):
    calls = []
    scheduler = scheduler_fixture(settings, store, gateway, worker, now, lambda *args: calls.append(args))
    store.refresh(EMPLOYEE, now)
    scheduler.refresh_source(now)
    store.refresh(EMPLOYEE, now+1)
    scheduler.refresh_source(now+1)
    assert len(calls) == 1
    Scheduler(settings, Store(store.path), gateway, worker, request=lambda *args: calls.append(args)).refresh_source(now+5)
    assert len(calls) == 2
    assert len(store.rows('SELECT * FROM rates WHERE key=?', ('sredime-post:' + EMPLOYEE,))) == 2


def test_exhausted_refresh_quota_persists_due_time_and_reports_delay(settings, store, gateway, worker, now):
    calls = []
    scheduler = scheduler_fixture(settings, store, gateway, worker, now, lambda *args: calls.append(args))
    for i in range(60):
        assert store.rate('sredime-post:' + EMPLOYEE, 60, now=now+i)
    store.refresh(EMPLOYEE, now+61)
    scheduler.refresh_source(now+61)
    assert not calls
    assert store.rows('SELECT due FROM refresh')[0]['due'] == now+3600
    assert store.rows("SELECT reason FROM issues WHERE key=? AND resolved=0", ('refresh-quota:' + EMPLOYEE,))
    # Simulate restart without resetting the rolling-hour counter.
    prime(settings, store, now+3600, [booking()])
    restored = Scheduler(settings, Store(store.path), gateway, worker, request=lambda *args: calls.append(args))
    restored.refresh_source(now+3599)
    assert not calls
    restored.refresh_source(now+3600)
    assert len(calls) == 1
    assert not store.rows('SELECT * FROM issues WHERE key=? AND resolved=0', ('refresh-quota:' + EMPLOYEE,))


def test_publish_and_notification_are_one_transaction(store, now):
    with store.connect() as conn:
        conn.execute("CREATE TRIGGER reject_refresh BEFORE INSERT ON refresh BEGIN SELECT RAISE(ABORT,'synthetic'); END")
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        store.publish_feed(EMPLOYEE, 'version-a', 1, now)
    assert store.get('feed-ready:' + EMPLOYEE)[0] is None
    assert store.get('feed-hash:' + EMPLOYEE)[0] is None
    assert not store.rows('SELECT * FROM availability_observations')


def test_durable_history_keeps_baseline_changes_and_first_fetch_times(store, now):
    assert store.publish_feed(EMPLOYEE, 'a', 1, now)
    assert not store.publish_feed(EMPLOYEE, 'a', 1, now+1)
    assert store.publish_feed(EMPLOYEE, 'b', 2, now+2)
    store.observe_feed_fetch(EMPLOYEE, 'b', 2, now+7)
    store.observe_feed_fetch(EMPLOYEE, 'b', 2, now+20)
    restored = Store(store.path)
    rows = restored.rows('SELECT * FROM availability_observations ORDER BY id')
    assert [r['kind'] for r in rows] == ['baseline', 'change']
    assert rows[-1]['fetched'] == now+7
    metrics = employee_latency(restored, EMPLOYEE, now+21)
    assert metrics['seven_day_observations']['changes'] == 1
    assert metrics['seven_day_observations']['fetched_under_60'] == 1
    assert metrics['latest']['ready_to_fetch_seconds'] == 5
    assert metrics['latest']['import_confirmed'] is False
    assert metrics['source_commit_time_known'] is False
    assert metrics['remote_import_time_known'] is False


def test_unchanged_legacy_feed_gets_one_baseline_not_false_change(store, now):
    store.put('feed-hash:' + EMPLOYEE, 'a', now-100)
    store.publish_feed(EMPLOYEE, 'a', 1, now)
    assert store.rows('SELECT kind FROM availability_observations') == [{'kind': 'baseline'}]
    assert not store.publish_feed(EMPLOYEE, 'a', 1, now+5)


def test_superseded_versions_and_exact_sixty_second_boundary_are_not_reported_as_passes(store, now):
    store.publish_feed(EMPLOYEE, 'baseline', 1, now)
    store.publish_feed(EMPLOYEE, 'a', 1, now+1)
    store.publish_feed(EMPLOYEE, 'b', 1, now+2)
    store.observe_feed_fetch(EMPLOYEE, 'b', 1, now+62)
    metrics = employee_latency(store, EMPLOYEE, now+63)
    assert metrics['seven_day_observations'] == {
        'changes': 2, 'fetched_under_60': 0, 'fetched_at_or_over_60': 1,
        'superseded_without_observed_fetch': 1, 'pending_at_or_over_60': 0}
    assert metrics['latest']['fetch_deadline_missed'] is True


def test_repeated_content_version_uses_latest_occurrence(store, now):
    store.publish_feed(EMPLOYEE, 'a', 1, now)
    store.observe_feed_fetch(EMPLOYEE, 'a', 1, now+1)
    store.publish_feed(EMPLOYEE, 'b', 1, now+2)
    store.publish_feed(EMPLOYEE, 'a', 1, now+3)
    store.observe_feed_fetch(EMPLOYEE, 'a', 1, now+8)
    rows = store.rows('SELECT ready,fetched FROM availability_observations WHERE version=? ORDER BY id', ('a',))
    assert rows == [{'ready': now, 'fetched': now+1}, {'ready': now+3, 'fetched': now+8}]


def test_clock_rollback_is_not_reported_as_successful_fast_delivery(store, now):
    store.publish_feed(EMPLOYEE, 'baseline', 1, now)
    store.publish_feed(EMPLOYEE, 'new', 1, now+10)
    store.observe_feed_fetch(EMPLOYEE, 'new', 1, now+11)
    result = employee_latency(store, EMPLOYEE, now+9)
    assert result['latest']['clock_anomaly'] is True
    assert result['latest']['ready_to_fetch_seconds'] is None
    assert result['latest']['fetch_deadline_missed'] is None
    assert result['seven_day_observations']['fetched_under_60'] == 0
    store.execute('UPDATE availability_observations SET scheduled=? WHERE version=?', (now+20, 'new'))
    result = employee_latency(store, EMPLOYEE, now+15)
    assert result['latest']['clock_anomaly'] is True
    assert result['seven_day_observations']['fetched_under_60'] == 0


def test_history_retention_preserves_latest_per_employee(store, now):
    store.publish_feed('other', 'x', 1, now-8*86400)
    store.publish_feed(EMPLOYEE, 'a', 1, now-8*86400)
    store.publish_feed(EMPLOYEE, 'b', 1, now)
    assert store.rows('SELECT employee,version FROM availability_observations ORDER BY id') == [
        {'employee': 'other', 'version': 'x'}, {'employee': EMPLOYEE, 'version': 'b'}]


def test_history_route_is_authenticated_scoped_and_bounded(settings, store, now):
    store.publish_feed(EMPLOYEE, 'a', 1, now)
    store.publish_feed('outside', 'private-other-version', 1, now)
    with TestClient(create_app(settings, store)) as client:
        url = '/ops/availability/' + EMPLOYEE + '/history'
        headers = {'X-API-Key': settings.admin_key}
        assert client.get(url).status_code == 401
        assert client.get('/ops/availability/outside/history', headers=headers).status_code == 404
        assert client.get(url+'?limit=201', headers=headers).status_code == 422
        report = client.get(url, headers=headers).json()
        assert len(report['observations']) == 1
        assert report['import_confirmed'] is False
        assert report['measurement_scope'] == 'feed_ready_to_http_fetch'
        assert 'private-other-version' not in json.dumps(report)


def test_unfetched_feed_opens_deadline_incident_and_real_fetch_resolves_it(settings, store, gateway, worker, now):
    scheduler = scheduler_fixture(settings, store, gateway, worker, now)
    settings.reads_enabled = True
    store.publish_feed(EMPLOYEE, 'a', 1, now)
    scheduler.monitor(now+60)
    assert store.rows('SELECT * FROM issues WHERE key=? AND resolved=0', ('availability-fetch:' + EMPLOYEE,))
    store.observe_feed_fetch(EMPLOYEE, 'a', 1, now+61)
    scheduler.monitor(now+62)
    assert not store.rows('SELECT * FROM issues WHERE key=? AND resolved=0', ('availability-fetch:' + EMPLOYEE,))
    assert employee_latency(store, EMPLOYEE, now+62)['latest']['fetch_deadline_missed'] is True


def test_queue_age_guard_uses_ten_second_local_budget(settings, store, gateway, worker, event, now):
    store.ingest(event, now)
    scheduler = Scheduler(settings, store, gateway, worker)
    scheduler.monitor(now+11)
    assert store.rows("SELECT * FROM issues WHERE key='queue-age' AND resolved=0")
    worker.once(now+12)
    scheduler.monitor(now+13)
    assert not store.rows("SELECT * FROM issues WHERE key='queue-age' AND resolved=0")


def test_source_copy_without_outbound_change_does_not_waste_refresh_quota(settings, store, gateway, worker, event, now):
    scheduler = scheduler_fixture(settings, store, gateway, worker, now)
    scheduler.queue_if_feed_changed(EMPLOYEE, now)
    scheduler.refresh_source(now)
    assert len(store.rows('SELECT * FROM rates WHERE key=?', ('sredime-post:' + EMPLOYEE,))) == 1
    settings.mode = 'simulation'
    store.ingest(event, now)
    worker.once(now+1)
    assert store.get('feed-recheck:' + EMPLOYEE)[0] is True
    scheduler.recheck_feeds(now+2)
    assert not store.rows('SELECT * FROM refresh')
    assert len(store.rows('SELECT * FROM availability_observations WHERE employee=?', (EMPLOYEE,))) == 1


def test_failed_feed_recheck_stays_pending_until_fresh_snapshot(settings, store, gateway, worker, now):
    scheduler = Scheduler(settings, store, gateway, worker)
    store.put('feed-recheck:' + EMPLOYEE, True, now)
    scheduler.recheck_feeds(now+1)
    assert store.get('task:feed-recheck:' + EMPLOYEE)[0] is None
    prime(settings, store, now+2, [booking()])
    scheduler.recheck_feeds(now+2)
    assert store.get('task:feed-recheck:' + EMPLOYEE)[1] == now
    assert store.rows('SELECT * FROM refresh')


def test_background_inventory_yields_booking_work_between_pages(settings, store, gateway, worker, event, now):
    order = []
    class Inventory:
        company = settings.salon
        base = 'https://user-api-v2.simplybook.me'
        calls = 0

        def request(self, method, path, body=None):
            assert method == 'GET'
            number = int(parse_qs(urlsplit(path).query)['page'][0])
            self.calls += 1
            order.append('page-' + str(number))
            if number == 1:
                store.ingest(event, now)
            else:
                assert store.rows('SELECT state FROM events')[0]['state'] == 'done'
                assert len(gateway.items) == 1
            return {'data': [{'id': 90+number, 'buffer_time_after': 0}],
                    'metadata': {'page': number, 'pages_count': 2, 'items_count': 2}}

    def yield_work():
        order.append('checkpoint')
        worker.once(now+1)
    readonly = ReadOnlyGateway(settings, Inventory(), before_read=yield_work)
    Scheduler(settings, store, readonly, worker).snapshot_buffers(now)
    assert order == ['checkpoint', 'page-1', 'checkpoint', 'page-2']
    assert store.get('buffers')[0] == {'91': 0, '92': 0}
    with pytest.raises(Review, match='writes_forbidden'):
        readonly.create({})


def test_outdated_snapshot_cannot_raise_or_clear_drift_after_yielded_source_write(settings, store, gateway, worker, event, now, monkeypatch):
    store.ingest(event, now)
    worker.once(now)
    prime(settings, store, now)
    key = 'drift:' + event['data']['id']
    store.issue(key, 'existing_drift', now, scope=[EMPLOYEE])
    before = copy.deepcopy(gateway.items[1001])
    def read(*args):
        newer = dict(store.get('applied:' + event['data']['id'])[0], end_datetime='2026-10-23 14:00:00')
        store.put('applied:' + event['data']['id'], newer, now+1)
        store.execute('UPDATE links SET version=version+1')
        return [before]
    monkeypatch.setattr(gateway, 'bookings', read)
    Scheduler(settings, store, gateway, worker).snapshot_bookings(now)
    assert store.rows('SELECT reason FROM issues WHERE key=? AND resolved=0', (key,)) == [{'reason': 'existing_drift'}]


def test_real_clock_stamps_refresh_acceptance_after_http_completion(settings, store, gateway, worker, now):
    clock = [now]
    def request(*args):
        clock[0] = now+8
    scheduler = scheduler_fixture(settings, store, gateway, worker, now, request)
    scheduler.clock = lambda: clock[0]
    scheduler.queue_if_feed_changed(EMPLOYEE, now)
    scheduler.refresh_source(now)
    row = store.rows('SELECT * FROM availability_observations WHERE employee=?', (EMPLOYEE,))[0]
    assert row['ready'] == now and row['scheduled'] == now+8
    assert row['fetched'] is None


def test_temporary_refresh_failure_retries_after_five_seconds_and_keeps_receipts_honest(settings, store, gateway, worker, now):
    from booking_bridge.model import Temporary
    attempts = []
    def request(*args):
        attempts.append(args)
        if len(attempts) == 1:
            raise Temporary('synthetic_unavailable')
    scheduler = scheduler_fixture(settings, store, gateway, worker, now, request)
    scheduler.queue_if_feed_changed(EMPLOYEE, now)
    scheduler.refresh_source(now)
    assert store.rows('SELECT scheduled FROM availability_observations')[0]['scheduled'] is None
    assert store.rows('SELECT due FROM refresh')[0]['due'] == now+5
    restored = Scheduler(settings, Store(store.path), gateway, worker, request=request)
    restored.refresh_source(now+4)
    assert len(attempts) == 1
    restored.refresh_source(now+5)
    assert len(attempts) == 2
    assert store.get('refresh-failures:' + EMPLOYEE)[0] == 0
    assert store.rows('SELECT scheduled,fetched FROM availability_observations')[0] == {'scheduled': now+5, 'fetched': None}


def test_validation_wait_does_not_add_two_minutes_after_feed_recovers(settings, store, gateway, worker, now):
    calls = []
    scheduler = scheduler_fixture(settings, store, gateway, worker, now, lambda *args: calls.append(args))
    store.execute('DELETE FROM cache WHERE key=?', ('schedule:' + EMPLOYEE,))
    store.refresh(EMPLOYEE, now)
    scheduler.refresh_source(now)
    assert not calls
    assert store.rows('SELECT due FROM refresh')[0]['due'] == now+5
    prime(settings, store, now+1, [booking()])
    scheduler.refresh_source(now+5)
    assert len(calls) == 1


def test_background_task_recovers_in_ten_seconds_instead_of_waiting_full_hour(settings, store, gateway, worker, now):
    from booking_bridge.model import Temporary
    calls = []
    def read():
        calls.append(True)
        if len(calls) == 1:
            raise Temporary('synthetic_unavailable')
    Scheduler(settings, store, gateway, worker).run_task('buffers', 3600, now, read)
    restored = Scheduler(settings, Store(store.path), gateway, worker)
    restored.run_task('buffers', 3600, now+9, read)
    assert len(calls) == 1
    restored.run_task('buffers', 3600, now+10, read)
    assert len(calls) == 2
    assert not store.rows("SELECT * FROM issues WHERE key='task:buffers' AND resolved=0")


def test_persistent_background_failure_cannot_create_unbounded_recovery_traffic(settings, store, gateway, worker, now):
    from booking_bridge.model import Temporary
    calls = []
    def read():
        calls.append(True)
        raise Temporary('synthetic_unavailable')
    scheduler = Scheduler(settings, store, gateway, worker)
    for offset in range(0, 160, 10):
        scheduler.run_task('buffers', 3600, now+offset, read)
    assert len(calls) == 13  # Initial normal attempt plus 12 accelerated recoveries.
    Scheduler(settings, Store(store.path), gateway, worker).run_task('buffers', 3600, now+160, read)
    assert len(calls) == 13
    assert store.rows("SELECT * FROM issues WHERE key='task:buffers' AND resolved=0")


def test_booking_snapshot_retries_after_failure_without_needing_new_webhook(settings, store, gateway, worker, now, monkeypatch):
    from booking_bridge.tests.test_availability_latency import fast_scheduler
    from booking_bridge.model import Temporary
    scheduler = fast_scheduler(settings, store, gateway, worker, monkeypatch)
    calls = []
    def read(*args):
        calls.append(True)
        if len(calls) == 1:
            raise Temporary('synthetic_unavailable')
        return []
    monkeypatch.setattr(gateway, 'bookings', read)
    scheduler.tick(now)
    scheduler.tick(now+9)
    assert len(calls) == 1
    scheduler.tick(now+10)
    assert len(calls) == 2
    assert store.get('sb-change-hint')[0] is None
    assert not store.rows("SELECT * FROM issues WHERE key='task:bookings' AND resolved=0")


def test_fetch_of_old_version_cannot_clear_latest_deadline_warning(settings, store, gateway, worker, now):
    scheduler = scheduler_fixture(settings, store, gateway, worker, now)
    settings.reads_enabled = True
    store.publish_feed(EMPLOYEE, 'old', 1, now)
    store.publish_feed(EMPLOYEE, 'new', 1, now+1)
    store.observe_feed_fetch(EMPLOYEE, 'old', 1, now+65)
    scheduler.monitor(now+65)
    assert store.rows('SELECT * FROM issues WHERE key=? AND resolved=0', ('availability-fetch:' + EMPLOYEE,))
    assert employee_latency(store, EMPLOYEE, now+65)['latest']['fetched'] is None


@pytest.mark.parametrize('value', [0, 31, True, '5'])
def test_coalescing_interval_must_fit_local_latency_budget(settings, value):
    settings.refresh_coalesce_seconds = value
    with pytest.raises(Review, match='invalid_refresh_coalescing_interval'):
        settings.validate()
