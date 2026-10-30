import copy
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from booking_bridge.cutover_review import main, review_cutover
from booking_bridge.model import stamp
from booking_bridge.store import Store


def sql(path, statement, args=()):
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(statement, args)


@pytest.fixture
def snapshots(tmp_path, event):
    event = copy.deepcopy(event)
    event['data']['status'] = -101
    event['data']['customer']['email'] = 'PRIVATE_CONTACT_MUST_NOT_PRINT@example.invalid'
    moment = stamp(event['created_at']).timestamp()
    host = Store(tmp_path/'host-working.sqlite')
    host.ingest(event, moment)
    host.finish(event['id'], 'done')
    host.put('bookings', [], 123)
    host.put('task:private-guard', {'preserve': True}, 124)
    host.issue('private-incident-key', 'private-reason', 125)
    host.execute('INSERT INTO rates VALUES(?,?)', ('shared-window', 126))
    current = tmp_path/'current.sqlite'
    host.backup(current)
    candidate = tmp_path/'candidate.sqlite'
    host.backup(candidate)
    staged = Store(candidate)
    booking = event['data']['id']
    staged.execute('INSERT INTO links VALUES(?,?,?,?,?)',
                   (booking, 501, moment, json.dumps(event['data']), 'canceled'))
    staged.execute('INSERT INTO clients VALUES(?,?)', (event['data']['customer']['id'], 71))
    staged.execute('INSERT INTO intents VALUES(?,?,?,?,?,?,?,?,?)',
                   (booking, event['id'], 'cancel', 501, '{}', '[]', 'done', 501, moment))
    staged.put('applied:'+booking, {'provider_id': 81, 'service_id': 91, 'client_id': 71,
                                  'start_datetime': '2026-10-23 10:00:00',
                                  'end_datetime': '2026-10-23 11:00:00'}, 127)
    staged.put('recovery-hold', {'worker_start_allowed': False, 'remote_reconciliation_required': True,
                               'budget_reconciliation_required': True}, 128)
    staged.execute('INSERT INTO rates VALUES(?,?)', ('shared-window', 126))
    baseline = tmp_path/'baseline.sqlite'
    staged.backup(baseline)
    # Remove WAL sidecars from the candidate through the supported backup path.
    prepared = tmp_path/'prepared.sqlite'
    staged.backup(prepared)
    quota = Store(tmp_path/'quota-working.sqlite')
    quota.execute('INSERT INTO rates VALUES(?,?)', ('shared-window', 126))
    quota_path = tmp_path/'quota.sqlite'
    quota.backup(quota_path)
    return current, prepared, baseline, quota_path


def failed(report):
    return {row['code'] for row in report['checks'] if not row['ok']}


def test_preservation_pass_is_read_only_and_never_authorizes_activation(snapshots, tmp_path):
    before = {path: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
              for path in snapshots}
    files = set(tmp_path.rglob('*'))
    report = review_cutover(*snapshots)
    assert report['preservation_passed'] is True
    assert report['activation_ready'] is report['worker_start_allowed'] is report['promotion_performed'] is False
    assert report['operator_review_counts']['open_incidents'] == 1
    assert before == {path: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
                      for path in snapshots}
    assert files == set(tmp_path.rglob('*'))
    text = json.dumps(report)
    for private in ('PRIVATE_CONTACT', 'private-incident-key', 'private-reason', str(snapshots[0])):
        assert private not in text


@pytest.mark.parametrize('problem,expected', [
    ('quota_deduplication', 'both_quota_windows_retained_without_deduplication'),
    ('refreshed_cache_timestamp', 'host_cache_values_and_freshness_preserved'),
    ('removed_hold', 'embedded_recovery_hold_retained'),
    ('changed_host_receipt_state', 'current_host_events_unchanged'),
    ('missing_client', 'historical_owned_clients_preserved'),
    ('uncertain_intent', 'uncertain_remote_intents_absent'),
    ('dropped_incident', 'current_host_issues_unchanged'),
])
def test_unsafe_cutover_changes_are_reported(snapshots, problem, expected):
    candidate = snapshots[1]
    if problem == 'quota_deduplication':
        sql(candidate, 'DELETE FROM rates WHERE rowid=(SELECT MAX(rowid) FROM rates)')
    elif problem == 'refreshed_cache_timestamp':
        sql(candidate, "UPDATE cache SET updated=9999999999 WHERE key='bookings'")
    elif problem == 'removed_hold':
        sql(candidate, "DELETE FROM cache WHERE key='recovery-hold'")
    elif problem == 'changed_host_receipt_state':
        sql(candidate, "UPDATE events SET state='queued'")
    elif problem == 'missing_client':
        sql(candidate, 'DELETE FROM clients')
    elif problem == 'uncertain_intent':
        sql(candidate, "UPDATE intents SET state='started'")
    else:
        sql(candidate, 'DELETE FROM issues')
    report = review_cutover(*snapshots)
    assert report['preservation_passed'] is False
    assert expected in failed(report)


def test_new_host_receipt_cannot_be_lost_by_reusing_old_candidate(snapshots, event):
    new = copy.deepcopy(event)
    new['id'] = 'f'*32
    new['data']['id'] = 'new-private-booking'
    host = Store(snapshots[0])
    host.ingest(new)
    refreshed = snapshots[0].with_name('fresh-current.sqlite')
    host.backup(refreshed)
    report = review_cutover(refreshed, *snapshots[1:])
    assert report['preservation_passed'] is False
    assert {'current_host_events_unchanged', 'current_host_booking_heads_unchanged'} <= failed(report)
    assert 'new-private-booking' not in json.dumps(report)


def test_rewritten_event_hash_never_passes(snapshots):
    sql(snapshots[1], "UPDATE events SET hash=?", ('0'*64,))
    report = review_cutover(*snapshots)
    assert report['preservation_passed'] is False
    assert report['snapshots']['candidate']['reason'] == 'event_hash_mismatch'


def test_preserved_new_queue_is_reported_for_review_and_never_replayed(snapshots, event):
    new = copy.deepcopy(event)
    new['id'] = 'e'*32
    new['data']['id'] = 'new-private-pending-booking'
    refreshed = []
    for path in snapshots[:2]:
        store = Store(path)
        store.ingest(new, now=3000000000)
        output = path.with_name('new-'+path.name)
        store.backup(output)
        refreshed.append(output)
    report = review_cutover(*refreshed, *snapshots[2:])
    assert report['preservation_passed'] is True
    assert report['operator_review_counts']['queued_or_working_receipts'] == 1
    assert report['activation_ready'] is report['worker_start_allowed'] is False
    with closing(sqlite3.connect(refreshed[1].resolve().as_uri()+'?immutable=1&mode=ro', uri=True)) as connection:
        assert connection.execute('SELECT state FROM events WHERE id=?', (new['id'],)).fetchone() == ('queued',)


def test_missing_paths_are_not_created_or_echoed(tmp_path, capsys):
    paths = [tmp_path/('PRIVATE_'+str(i)+'.sqlite') for i in range(4)]
    args = [part for key, path in zip(('current-host', 'candidate', 'owned-baseline', 'quota-origin'), paths)
            for part in ('--'+key, str(path))]
    assert main(args) == 2
    assert all(not path.exists() for path in paths)
    assert 'PRIVATE_' not in capsys.readouterr().out
