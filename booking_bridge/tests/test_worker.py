import copy
import json

import pytest

from booking_bridge.model import Review, Temporary, Uncertain
from booking_bridge.store import Store
from booking_bridge.worker import Worker
from conftest import changed, state


def test_create_dedupe_and_customer_mapping(worker, store, gateway, event, now):
    assert store.ingest(event)
    assert not store.ingest(event)
    worker.once(now)
    assert state(store, event)['state'] == 'done'
    assert len(gateway.items) == 1
    sent = gateway.calls[0][2]
    assert sent['provider_id'] == 81  # requested:false never invokes Any Employee.
    assert sent['client_id'] == 71
    assert set(sent) == {'provider_id', 'service_id', 'client_id', 'start_datetime', 'end_datetime', 'count'}
    assert store.rows('SELECT target FROM links')[0]['target'] == 1001


@pytest.mark.parametrize('change', ['time', 'employee', 'service', 'all'])
def test_edits_keep_target(worker, store, gateway, event, now, change):
    store.ingest(event); worker.once(now)
    next_event = changed(event, 2)
    if change in ('time', 'all'):
        next_event['data'].update(start_at='2026-10-24T13:00:00+02:00', end_at='2026-10-24T14:00:00+02:00')
    if change in ('employee', 'all'):
        next_event['data']['employee'].update(id='synthetic-employee-B', external_id='test-provider-82')
    if change in ('service', 'all'):
        next_event['data']['service'].update(id='synthetic-service-B', external_id='test-service-92')
    store.ingest(next_event); worker.once(now+180)
    assert state(store, next_event)['state'] == 'done'
    assert list(gateway.items) == [1001]
    assert gateway.calls[-1][0] == 'edit'
    if change in ('employee', 'all'):
        assert store.get('feed-recheck:synthetic-employee-A')[0] is True
        assert store.get('feed-recheck:synthetic-employee-B')[0] is True


@pytest.mark.parametrize('status', [-2, -101, -901])
def test_cancel_and_tombstone(worker, store, gateway, event, now, status):
    store.ingest(event); worker.once(now)
    cancel = changed(event, 2, status=status)
    store.ingest(cancel); worker.once(now+180)
    assert gateway.items[1001]['status'] == 'canceled'
    assert store.rows('SELECT target,state FROM links') == [{'target': 1001, 'state': 'canceled'}]
    assert state(store, cancel)['state'] == 'done'


def test_hard_delete_with_minimum_snapshot(worker, store, gateway, event, now):
    store.ingest(event); worker.once(now)
    deleted = changed(event, 2, status=1)
    deleted['type'] = 'booking.deleted'
    deleted['data'] = {k: deleted['data'][k] for k in ('id', 'status', 'employee')}
    store.ingest(deleted); worker.once(now+180)
    assert gateway.items[1001]['status'] == 'canceled'


def test_pending_confirmation_and_no_show(worker, store, gateway, event, now):
    pending = copy.deepcopy(event); pending['data']['status'] = 0
    store.ingest(pending); worker.once(now)
    assert len(gateway.items) == 1
    assert json.loads(store.rows('SELECT snapshot FROM links')[0]['snapshot'])['status'] == 0
    confirm = changed(event, 2)
    gateway.items[1001]['status'] = 'pending'
    store.ingest(confirm); worker.once(now+180)
    assert gateway.calls[-1][0] == 'approve'
    no_show = changed(event, 3, status=-902)
    store.ingest(no_show); worker.once(now+240)
    assert store.rows('SELECT state FROM links')[0]['state'] == 'no_show'
    assert gateway.items[1001]['status'] == 'confirmed'


@pytest.mark.parametrize('status', [-1, -9000, 123])
def test_internal_unknown_status_review(worker, store, gateway, event, now, status):
    event['data']['status'] = status
    store.ingest(event); worker.once(now)
    assert state(store, event)['state'] == 'review'
    assert not gateway.calls
    assert json.loads(state(store, event)['payload'])['data']['status'] == status


def test_unapproved_business_rules_do_not_guess(worker, settings, store, gateway, event, now):
    settings.policies = {}
    event['data']['status'] = 0
    store.ingest(event); worker.once(now)
    assert state(store, event)['state'] == 'review'
    assert not gateway.calls


def test_wait_policy(worker, settings, store, gateway, event, now):
    settings.policies['pending'] = 'wait'
    event['data']['status'] = 0
    store.ingest(event); worker.once(now)
    assert store.rows('SELECT state FROM links')[0]['state'] == 'waiting'
    assert not gateway.calls


def test_out_of_order_latest_cancel_wins(worker, store, gateway, event, now):
    store.ingest(changed(event, 3, status=-901)); store.ingest(event)
    worker.once(now+300); worker.once(now+300)
    assert state(store, event)['state'] == 'stale'
    assert not gateway.calls
    assert store.rows('SELECT state FROM links')[0]['state'] == 'canceled'


def test_late_older_event_cannot_undo_update(worker, store, gateway, event, now):
    newer = changed(event, 3, start_at='2026-10-24T10:00:00+02:00', end_at='2026-10-24T11:00:00+02:00')
    store.ingest(newer); worker.once(now+240)
    store.ingest(event); worker.once(now+240)
    assert state(store, event)['state'] == 'stale'
    assert len(gateway.calls) == 1


def test_equal_timestamp_conflict_needs_review(worker, store, gateway, event, now):
    duplicate_time = copy.deepcopy(event)
    duplicate_time['id'] = 'f' * 32
    duplicate_time['data']['status'] = -901
    store.ingest(event); store.ingest(duplicate_time)
    worker.once(now); worker.once(now)
    assert not gateway.calls
    assert state(store, event)['reason'] == 'equal_timestamp_conflicting_snapshots'


def test_test_true_never_writes_or_supersedes_real(worker, store, gateway, event, now):
    test = changed(event, 2); test['test'] = True
    store.ingest(test); store.ingest(event)
    worker.once(now+180); worker.once(now+180)
    assert state(store, test)['state'] == 'test'
    assert len(gateway.items) == 1


@pytest.mark.parametrize('problem', ['employee', 'service', 'external', 'client', 'consent', 'duration', 'missing_time', 'timing', 'resources'])
def test_missing_or_unmapped_is_review(worker, settings, store, gateway, event, now, problem):
    if problem == 'employee': event['data']['employee']['id'] = 'unknown'
    if problem == 'service': event['data']['service']['id'] = 'unknown'
    if problem == 'external': event['data']['service']['external_id'] = 'unexpected'
    if problem == 'client': event['data']['customer'] = {'id': 'unmapped-customer'}
    if problem == 'consent': settings.approvals['client_mapping'] = False
    if problem == 'duration': event['data']['duration'] = 90
    if problem == 'missing_time': event['data']['start_at'] = None
    if problem == 'timing': settings.services['synthetic-service-A']['timing_verified'] = False
    if problem == 'resources': settings.services['synthetic-service-A']['resources_verified'] = False
    store.ingest(event); worker.once(now)
    assert state(store, event)['state'] in ('review', 'ignored')
    assert not gateway.calls


def test_different_people_cannot_share_client(worker, settings, store, gateway, event, now):
    settings.clients['another-person'] = 71
    store.ingest(event); worker.once(now)
    assert state(store, event)['reason'] == 'different_customers_share_target_client'
    assert not gateway.calls


def test_pilot_move_to_nonallowed_employee_does_not_write(worker, settings, store, gateway, event, now):
    store.ingest(event); worker.once(now)
    settings.allowed_employees = ['synthetic-employee-A']
    moved = changed(event, 2)
    moved['data']['employee'].update(id='synthetic-employee-B', external_id='test-provider-82')
    store.ingest(moved); worker.once(now+180)
    assert state(store, moved)['state'] == 'ignored'
    assert len(gateway.calls) == 1
    assert store.rows("SELECT 1 FROM issues WHERE key LIKE 'scope:%' AND resolved=0")


def test_conflict_keeps_employee_and_requires_human(worker, store, gateway, event, now):
    gateway.items[999] = {'id': 999, 'provider_id': 81, 'status': 'confirmed', 'service_id': 92, 'client_id': 79,
                          'start_datetime': '2026-10-23 10:30:00', 'end_datetime': '2026-10-23 11:30:00'}
    store.ingest(event); worker.once(now)
    assert state(store, event)['reason'] == 'slot_conflict_or_unavailable'
    assert not gateway.calls


def test_timeout_after_success_never_recreates(worker, store, gateway, event, now):
    gateway.timeout_after_create = True
    store.ingest(event); worker.once(now)
    assert len(gateway.items) == 1
    assert state(store, event)['state'] == 'review'
    worker.reconcile_all(now+60)
    assert store.get('candidates:' + event['data']['id'])[0] == [1001]
    with pytest.raises(Review, match='reconcile_intent'):
        store.retry(event['id'])
    newer = changed(event, 2)
    store.ingest(newer); worker.once(now+180)
    assert state(store, newer)['state'] == 'review'
    assert len(gateway.calls) == 1


def test_restart_after_result_before_record_recovers(worker, settings, store, gateway, event, now):
    store.ingest(event)
    row = store.claim(now)
    desired = {'service_id': 91, 'provider_id': 81, 'client_id': 71,
               'start_datetime': '2026-10-23 10:00:00', 'end_datetime': '2026-10-23 11:00:00', 'count': 1}
    worker.intent(row, 'create', None, desired, [])
    target = gateway.create(desired)
    store.execute('UPDATE intents SET result=?', (target,))
    restarted = Store(store.path)
    restarted.recover()
    new_worker = Worker(settings, restarted, gateway)
    new_worker.once(now+60)
    assert state(store, event)['state'] == 'done'
    assert len(gateway.calls) == 1


def test_restart_after_unknown_create_preserves_uncertainty(worker, settings, store, gateway, event, now):
    gateway.timeout_after_create = True
    store.ingest(event); worker.once(now)
    store.execute("UPDATE events SET state='working'")
    restarted = Store(store.path); restarted.recover()
    Worker(settings, restarted, gateway).once(now+60)
    assert len(gateway.calls) == 1
    assert state(store, event)['state'] == 'review'


def test_read_outage_retries_durably(worker, store, gateway, event, now):
    gateway.fail_read = True
    store.ingest(event); worker.once(now)
    assert state(store, event)['state'] == 'queued'
    assert state(store, event)['due'] > now
    gateway.fail_read = False
    worker.once(now+60)
    assert state(store, event)['state'] == 'done'


def test_retry_exhaustion_and_manual_retry(worker, settings, store, gateway, event, now):
    settings.max_attempts = 1; gateway.fail_read = True
    store.ingest(event); worker.once(now)
    assert state(store, event)['state'] == 'dead'
    gateway.fail_read = False; store.retry(event['id']); worker.once(now+60)
    assert state(store, event)['state'] == 'done'


def test_remote_drift_does_not_get_silently_overwritten(worker, store, gateway, event, now):
    store.ingest(event); worker.once(now)
    gateway.items[1001]['provider_id'] = 82
    update = changed(event, 2, start_at='2026-10-24T10:00:00+02:00', end_at='2026-10-24T11:00:00+02:00')
    store.ingest(update); worker.once(now+180)
    assert state(store, update)['reason'] == 'source_booking_edited_in_simplybook'
    assert len(gateway.calls) == 1


def test_booking_id_and_event_id_are_distinct(worker, store, event, now):
    store.ingest(event); worker.once(now)
    assert store.rows('SELECT booking FROM links')[0]['booking'] == 'synthetic-booking-A'
    assert store.rows('SELECT id FROM events')[0]['id'] == event['id']


def test_ingest_collision(store, event):
    store.ingest(event)
    event['data']['status'] = -901
    with pytest.raises(Review): store.ingest(event)


def test_backup_includes_committed_wal(store, event, tmp_path):
    store.ingest(event)
    path = tmp_path / 'backup.sqlite'; store.backup(path)
    restored = Store(path)
    assert state(restored, event)['state'] == 'queued'


def test_later_known_snapshot_resolves_obsolete_status_review(worker, store, gateway, event, now):
    unknown = copy.deepcopy(event); unknown['data']['status'] = -777
    store.ingest(unknown); worker.once(now)
    assert state(store, unknown)['state'] == 'review'
    known = changed(event, 2)
    store.ingest(known); worker.once(now+180)
    assert state(store, known)['state'] == 'done'
    assert state(store, unknown)['state'] == 'stale'
    assert not store.rows("SELECT * FROM issues WHERE key LIKE 'event:%' AND resolved=0")
