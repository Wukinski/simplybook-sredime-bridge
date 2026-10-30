import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from booking_bridge import reconcile_trial
from booking_bridge.model import Review, digest
from booking_bridge.recovery import recovery_start_allowed
from booking_bridge.store import Store


def save(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')


def snapshot_rows(path, table):
    with sqlite3.connect(path) as connection:
        return connection.execute('SELECT * FROM ' + table + ' ORDER BY rowid').fetchall()


@pytest.fixture
def trial(tmp_path):
    host = Store(tmp_path/'host.sqlite')
    local = Store(tmp_path/'local.sqlite')
    aliases = {'schema_version': 1, 'source_booking_id': 'synthetic-owned-booking',
               'anchor_event_id': '1'*32, 'anchor_host_hash': None,
               'actual_source_ids': {'employee': 'opaque-E', 'service': 'opaque-S', 'customer': 'opaque-C'},
               'canonical_source_ids': {'employee': '101', 'service': '202', 'customer': '303'},
               'target_ids': {'provider': 81, 'service': 91, 'client': 71},
               'external_ids': {'employee': '81', 'service': '91'},
               'native_readback': {'verified_at_utc': '2026-10-27T12:00:02Z',
                   'booking_id': 'synthetic-owned-booking', 'employee_id': '101', 'service_id': '202', 'customer_id': '303',
                   'employee_external_id': '81', 'service_external_id': '91', 'status': 1, 'duration': 30,
                   'start_at': '2026-10-28T14:00:00+01:00', 'end_at': '2026-10-28T14:30:00+01:00',
                   'single_employee': True, 'single_service': True, 'customer_native_parent_id_matches': True,
                   'same_booking_identity_verified': True}}
    journal = {'employee_id': '101', 'service_id': '202', 'target_client_id': 71, 'production_enabled': False,
               'customer': {'source_customer_id': '303', 'target_client_id': 71, 'status': 'verified',
                            'email_matches': True, 'phone_matches': True, 'native_parent_id_matches': True}}
    journal['create'] = {'status': 'confirmed', 'booking_id': 'synthetic-owned-booking',
                         'source_customer_id': '303', 'date': '2026-10-28', 'start': '14:00', 'end': '14:30',
                         'confirmed_at': '2026-10-27T11:59:00Z'}
    cycle = {'source_booking_id': 'synthetic-owned-booking', 'target_booking_id': 501,
             'target_ids': aliases['target_ids'], 'source_signed_ids': aliases['actual_source_ids'],
             'source_native_ids': aliases['canonical_source_ids'], 'controlled_cycle_verified': True,
             'cleanup_verified_by_independent_native_readback': True, 'unresolved_local_intents': 0,
             'source_callback_active': False, 'phases': []}
    items = []
    for index, step in enumerate(reconcile_trial.STEPS):
        created = datetime(2026, 10, 27, 12, index*10, tzinfo=timezone.utc)
        start, end = ('14:00', '14:30') if step == 'resync' else ('15:00', '15:30')
        raw = {'id': str(index+1)*32, 'type': 'booking.updated', 'created_at': created.isoformat(), 'test': False,
               'data': {'id': 'synthetic-owned-booking', 'status': -101 if step == 'cancel' else 1,
                        'start_at': '2026-10-28T'+start+':00+01:00', 'end_at': '2026-10-28T'+end+':00+01:00', 'duration': 30,
                        'employee': {'id': 'opaque-E', 'external_id': '81'},
                        'service': {'id': 'opaque-S', 'external_id': '91'},
                        'customer': {'id': 'opaque-C', 'email': 'SYNTHETIC_RAW_CONTACT_MUST_NOT_PRINT'}}}
        host.ingest(raw, created.timestamp()+1)
        host.execute("UPDATE events SET state='done',reason='applied_by_local_pilot_executor' WHERE id=?", (raw['id'],))
        if index == 0:
            aliases['anchor_host_hash'] = digest(raw)
        normalized = reconcile_trial._projection(raw, aliases, native=True)
        local.ingest(normalized, created.timestamp()+1)
        local.execute("UPDATE events SET state='done',attempts=1 WHERE id=?", (raw['id'],))
        readback = {'event_id': raw['id'], 'source_booking_id': 'synthetic-owned-booking',
                    'observed_at_utc': (created+timedelta(seconds=6)).isoformat(),
                    'local_done_observed_at_utc': (created+timedelta(seconds=5)).isoformat(),
                    'transport': 'simplybook_rest_admin', 'read_only': True,
                    'booking': {'id': 501, 'provider_id': 81, 'service_id': 91, 'client_id': 71,
                                'start_datetime': '2026-10-28 '+start+':00', 'end_datetime': '2026-10-28 '+end+':00',
                                'status': 'canceled' if step == 'cancel' else 'confirmed', 'is_confirmed': step != 'cancel'}}
        save(tmp_path/('target-readback-'+step+'.json'), readback)
        journal[step] = {**journal['create'], 'start': start, 'end': end,
                         'confirmed_at': (created+timedelta(seconds=1)).isoformat()}
        cycle['phases'].append({'phase': step, 'local_event': {'id': raw['id'], 'state': 'done', 'attempts': 1},
                                'host_event': {'id': raw['id'], 'state': 'done'}, 'actual_target_readback': readback,
                                'host_acknowledged': True})
        items.append((raw, normalized, readback, created))
    for step, (raw, normalized, readback, created) in zip(reconcile_trial.STEPS, items):
        request = {'booking': 'synthetic-owned-booking', 'customer': '303', 'step': step, 'event_id': raw['id'],
                   'actual_source_ids': aliases['actual_source_ids'], 'binding_hash': digest(aliases),
                   'anchor_event_id': aliases['anchor_event_id'], 'anchor_host_hash': aliases['anchor_host_hash']}
        receipt = {'request': request, 'host_hash': digest(raw), 'local_hash': digest(normalized),
                   'host_created': created.timestamp(), 'host_received': created.timestamp()+1,
                   'original_source_ids': aliases['actual_source_ids'], 'source_hash': digest(reconcile_trial._projection(raw, aliases)),
                   'binding_hash': digest(aliases)}
        local.put('pilot-source-receipt:'+raw['id'], receipt, created.timestamp()+2)
        ack = {**request, 'host_hash': digest(raw), 'local_hash': digest(normalized), 'target_booking_id': 501,
               'readback_hash': digest(readback), 'readback_at': created.timestamp()+6,
               'done_observed_at': created.timestamp()+5, 'target_status': readback['booking']['status']}
        host.put('pilot-local-ack:'+raw['id'], ack, created.timestamp()+7)
    raw, normalized, readback, created = items[-1]
    local.execute('INSERT INTO links VALUES(?,?,?,?,?)',
                  ('synthetic-owned-booking', 501, created.timestamp(), json.dumps(normalized['data']), 'canceled'))
    local.execute('INSERT INTO clients VALUES(?,?)', ('303', 71))
    local.execute('INSERT INTO intents VALUES(?,?,?,?,?,?,?,?,?)',
                  ('synthetic-owned-booking', raw['id'], 'cancel', 501, '{}', '[]', 'done', 501, created.timestamp()+3))
    local.put('applied:synthetic-owned-booking', {key: readback['booking'][key] for key in
              ('provider_id', 'service_id', 'client_id', 'start_datetime', 'end_datetime')}, created.timestamp()-100)
    host.put('unrelated-cache-guard', {'preserve': True}, 123)
    host.issue('feed:legacy-employee', 'booking_snapshot_stale', 50)
    host.execute('INSERT INTO rates VALUES(?,?)', ('identical-window', 1234))
    local.execute('INSERT INTO rates VALUES(?,?)', ('identical-window', 1234))
    unrelated = {**items[0][0], 'id': '9'*32, 'data': {**items[0][0]['data'], 'id': 'unrelated-booking'}}
    host.ingest(unrelated, 200)
    host.execute("UPDATE events SET state='ignored',reason='employee_outside_allowlist' WHERE id=?", (unrelated['id'],))
    for name, value in (('binding', aliases), ('journal', journal), ('cycle', cycle)):
        save(tmp_path/(name+'.json'), value)
    output = tmp_path/'stage.sqlite'

    def run():
        return reconcile_trial.prepare(host.path, local.path, tmp_path/'binding.json', tmp_path/'journal.json',
                                        tmp_path/'cycle.json', tmp_path, output, now=2000000000)

    return host, local, tmp_path, output, run


def test_staging_preserves_raw_host_history_and_adds_only_proven_canceled_ownership(trial):
    host, local, directory, output, run = trial
    host_before = {table: snapshot_rows(host.path, table) for table in
                   ('events', 'booking_heads', 'cache', 'rates', 'issues', 'refresh', 'audit')}
    local_before = {table: snapshot_rows(local.path, table) for table in
                    ('events', 'booking_heads', 'links', 'clients', 'intents', 'cache', 'rates')}
    report = run()
    assert {table: snapshot_rows(host.path, table) for table in host_before} == host_before
    assert {table: snapshot_rows(local.path, table) for table in local_before} == local_before
    assert snapshot_rows(output, 'events') == host_before['events']
    assert snapshot_rows(output, 'booking_heads') == host_before['booking_heads']
    assert snapshot_rows(output, 'issues') == host_before['issues']
    assert snapshot_rows(output, 'rates') == [('identical-window', 1234), ('identical-window', 1234)]
    with sqlite3.connect(output) as connection:
        connection.row_factory = sqlite3.Row
        link = dict(connection.execute('SELECT * FROM links').fetchone())
        assert link['state'] == 'canceled' and link['target'] == 501
        assert json.loads(link['snapshot'])['employee']['id'] == 'opaque-E'
        assert [tuple(r) for r in connection.execute('SELECT * FROM clients')] == [('opaque-C', 71)]
        assert [tuple(r) for r in connection.execute('SELECT state,result FROM intents')] == [('done', 501)]
        cache = {r[0]: (r[1], r[2]) for r in connection.execute('SELECT * FROM cache')}
        for key, value, updated in host_before['cache']:
            assert cache[key] == (value, updated)
        audit = json.loads(cache['reconciliation:trial:synthetic-owned-booking'][0])
        assert audit['local_projection_audit_only']['events'] == [dict(zip(
            ('id', 'booking', 'created', 'payload', 'hash', 'state', 'reason', 'attempts', 'due', 'received'), row))
            for row in local_before['events']]
        assert audit['local_projection_audit_only']['canonical_client'] == '303'
    assert recovery_start_allowed(output) is False
    copied = directory/'copied-alone.sqlite'
    copied.write_bytes(output.read_bytes())
    assert recovery_start_allowed(copied) is False
    assert report['original_event_hashes_rewritten'] == 0
    assert report['verified_projection_pairs'] == 3
    assert 'SYNTHETIC_RAW_CONTACT' not in json.dumps(report)
    assert report['snapshot_freshness_not_renewed'] is True


@pytest.mark.parametrize('problem', ['host_hash', 'local_hash', 'collector_hash', 'ack_hash', 'binding_identity',
                                    'canceled_link', 'unresolved_intent', 'head_hash', 'readback_target',
                                    'journal_customer', 'additional_ownership'])
def test_changed_proof_or_ownership_never_publishes_staging_file(trial, problem):
    host, local, directory, output, run = trial
    if problem == 'host_hash':
        host.execute('UPDATE events SET hash=? WHERE id=?', ('0'*64, '1'*32))
    elif problem == 'local_hash':
        local.execute('UPDATE events SET hash=? WHERE id=?', ('0'*64, '1'*32))
    elif problem in ('collector_hash', 'ack_hash'):
        store, key = (local, 'pilot-source-receipt:') if problem == 'collector_hash' else (host, 'pilot-local-ack:')
        value, updated = store.get(key+'1'*32)
        value['host_hash'] = '0'*64
        store.put(key+'1'*32, value, updated)
    elif problem == 'binding_identity':
        path = directory/'binding.json'; value = json.loads(path.read_text()); value['actual_source_ids']['customer'] = 'wrong-C'; save(path, value)
    elif problem == 'canceled_link':
        local.execute("UPDATE links SET state='active'")
    elif problem == 'unresolved_intent':
        local.execute("UPDATE intents SET state='uncertain'")
    elif problem == 'head_hash':
        host.execute("UPDATE booking_heads SET snapshot_hash=? WHERE booking='synthetic-owned-booking'", ('0'*64,))
    elif problem == 'readback_target':
        path = directory/'target-readback-cancel.json'; value = json.loads(path.read_text()); value['booking']['id'] = 999; save(path, value)
    elif problem == 'journal_customer':
        path = directory/'journal.json'; value = json.loads(path.read_text()); value['customer']['source_customer_id'] = 'wrong-C'; save(path, value)
    else:
        local.execute('INSERT INTO links VALUES(?,?,?,?,?)', ('another-owned', 999, 1000, '{}', 'active'))
    with pytest.raises(Review):
        run()
    assert not output.exists()
    assert not Path(str(output)+'.recovery.json').exists()
    assert not Path(str(output)+'.reconciliation.json').exists()


def test_prepared_stage_is_never_overwritten_or_reexecuted(trial):
    host, local, directory, output, run = trial
    run()
    before = output.read_bytes()
    with pytest.raises(Review, match='output_exists'):
        run()
    assert output.read_bytes() == before


def test_cli_failure_does_not_expose_private_paths_or_payloads(tmp_path, capsys):
    args = []
    for name in ('host-snapshot', 'local-snapshot', 'binding', 'journal', 'cycle', 'readbacks-dir', 'output'):
        args.extend(['--'+name, str(tmp_path/('PRIVATE_'+name))])
    assert reconcile_trial.main(args) == 2
    output = capsys.readouterr().out
    assert 'PRIVATE_' not in output
    assert json.loads(output)['prepared'] is False
