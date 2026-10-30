"""Reconcile one proven completed pilot into a NEW held staging database.

Raw signed ingress events and booking heads remain authoritative and unchanged.
The native-ID local projections are retained as audit evidence, never as new
routing aliases. No account call, credential transfer, live migration or replay.
"""
import argparse
import json
import os
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from .model import Review, company_time, digest, stamp
from .recovery import (_available, _bytes, _encode, _exclusive_write, _inspect_database,
                       _json, _online_snapshot, _sha, _write_reserved, MARKER_SUFFIX)

STEPS = ('resync', 'move', 'cancel')
KINDS = ('employee', 'service', 'customer')


def _require(condition, code):
    if not condition:
        raise Review('trial_reconciliation_' + code)


def _load(path):
    value = _json(_bytes(path, 4 * 1024 * 1024))
    _require(isinstance(value, dict), 'proof_format_invalid')
    return value


def _cache(connection, key):
    row = connection.execute('SELECT value,updated FROM cache WHERE key=?', (key,)).fetchone()
    _require(row is not None, 'receipt_missing')
    return _json(row['value']), row['updated']


def _single(connection, sql, parameters):
    rows = connection.execute(sql, parameters).fetchall()
    _require(len(rows) == 1, 'expected_single_record')
    return dict(rows[0])


def _source_ids(data):
    return {kind: (data.get(kind) or {}).get('id') for kind in KINDS}


def _projection(raw, aliases, *, native=False):
    result = {key: raw[key] for key in ('id', 'type', 'created_at', 'test')}
    result['data'] = {key: raw['data'][key] for key in ('id', 'status', 'start_at', 'end_at', 'duration')}
    ids = aliases['canonical_source_ids'] if native else aliases['actual_source_ids']
    result['data'].update({kind: {'id': ids[kind]} for kind in KINDS})
    if not native:
        for kind in ('employee', 'service'):
            result['data'][kind]['external_id'] = aliases['external_ids'][kind]
    return result


def _binding(aliases, journal, cycle):
    _require(set(aliases) == {'schema_version', 'source_booking_id', 'anchor_event_id', 'anchor_host_hash',
             'actual_source_ids', 'canonical_source_ids', 'target_ids', 'external_ids', 'native_readback'} and
             type(aliases['schema_version']) is int and aliases['schema_version'] == 1, 'binding_invalid')
    booking = aliases['source_booking_id']
    _require(isinstance(booking, str) and re.fullmatch('[A-Za-z0-9_-]{1,128}', booking), 'booking_invalid')
    for key in ('actual_source_ids', 'canonical_source_ids'):
        ids = aliases[key]
        _require(isinstance(ids, dict) and set(ids) == set(KINDS) and all(
            isinstance(value, str) and re.fullmatch('[A-Za-z0-9_-]{1,128}', value) for value in ids.values()), 'identity_invalid')
    target = aliases['target_ids']
    _require(isinstance(target, dict) and set(target) == {'provider', 'service', 'client'} and all(
        type(value) is int and value > 0 for value in target.values()), 'target_invalid')
    _require(aliases['external_ids'] == {'employee': str(target['provider']), 'service': str(target['service'])}, 'external_ids_changed')
    canonical = aliases['canonical_source_ids']
    _require(journal.get('employee_id') == canonical['employee'] and journal.get('service_id') == canonical['service'] and
             journal.get('target_client_id') == target['client'] and journal.get('production_enabled') is False, 'journal_scope_changed')
    customer = journal.get('customer', {})
    _require(customer.get('source_customer_id') == canonical['customer'] and customer.get('target_client_id') == target['client'] and
             customer.get('status') == 'verified' and all(customer.get(key) is True for key in
             ('email_matches', 'phone_matches', 'native_parent_id_matches')), 'customer_identity_unverified')
    proof = aliases['native_readback']
    _require(isinstance(proof, dict) and proof.get('booking_id') == booking and all(
        proof.get(kind + '_id') == canonical[kind] for kind in KINDS) and all(
        proof.get(key) is True for key in ('single_employee', 'single_service',
            'customer_native_parent_id_matches', 'same_booking_identity_verified')) and
        proof.get('employee_external_id') == str(target['provider']) and proof.get('service_external_id') == str(target['service']),
        'same_booking_identity_unverified')
    stamp(proof['verified_at_utc'])
    previous = None
    for step in ('create', *STEPS):
        entry = journal.get(step, {})
        _require(entry.get('status') == 'confirmed' and str(entry.get('booking_id')) == booking and
                 entry.get('source_customer_id') == canonical['customer'], 'native_step_unverified')
        confirmed = stamp(entry['confirmed_at']).timestamp()
        _require(previous is None or confirmed >= previous, 'native_step_order_changed')
        previous = confirmed
    _require(all(journal['create'].get(key) == journal['resync'].get(key) for key in ('date', 'start', 'end')),
             'resync_not_original_interval')
    _require(type(proof.get('status')) is int and proof['status'] == 1 and
             type(proof.get('duration')) is int and proof['duration'] > 0 and
             company_time(proof['start_at']) == journal['create']['date'] + ' ' + journal['create']['start'] + ':00' and
             company_time(proof['end_at']) == journal['create']['date'] + ' ' + journal['create']['end'] + ':00',
             'native_identity_interval_changed')
    _require(cycle.get('source_booking_id') == booking and cycle.get('target_ids') == target and
             cycle.get('source_signed_ids') == aliases['actual_source_ids'] and cycle.get('source_native_ids') == canonical and
             cycle.get('controlled_cycle_verified') is True and cycle.get('cleanup_verified_by_independent_native_readback') is True and
             cycle.get('unresolved_local_intents') == 0 and cycle.get('source_callback_active') is False,
             'completed_cycle_unverified')
    _require(isinstance(cycle.get('phases'), list) and [p.get('phase') for p in cycle['phases']] == list(STEPS), 'phase_order_changed')
    return booking, canonical, target


def _validate(host, local, aliases, journal, cycle, readbacks):
    booking, canonical, target = _binding(aliases, journal, cycle)
    binding_hash = digest(aliases)
    events, provenance = [], []
    previous_created = -1
    for phase in cycle['phases']:
        step = phase['phase']
        event_id = phase['local_event']['id']
        _require(re.fullmatch('[a-f0-9]{32}', event_id) is not None, 'event_id_invalid')
        h = _single(host, 'SELECT * FROM events WHERE id=?', (event_id,))
        l = _single(local, 'SELECT * FROM events WHERE id=?', (event_id,))
        raw, normalized = _json(h['payload']), _json(l['payload'])
        receipt, receipt_at = _cache(local, 'pilot-source-receipt:' + event_id)
        ack, _ = _cache(host, 'pilot-local-ack:' + event_id)
        request = receipt['request']
        _require(h['booking'] == l['booking'] == booking and raw['data']['id'] == normalized['data']['id'] == booking and
                 raw['id'] == normalized['id'] == event_id and raw.get('test') is False and
                 h['state'] == l['state'] == 'done' and h['attempts'] == 0 and l['attempts'] == 1 and
                 h['reason'] == 'applied_by_local_pilot_executor' and
                 h['created'] == l['created'] == stamp(raw['created_at']).timestamp() and
                 h['received'] == l['received'] and h['created'] > previous_created, 'event_state_changed')
        previous_created = h['created']
        _require(digest(raw) == h['hash'] and digest(normalized) == l['hash'] and
                 _source_ids(raw['data']) == aliases['actual_source_ids'] and
                 _source_ids(normalized['data']) == canonical and
                 all(str(raw['data'][kind].get('external_id')) == aliases['external_ids'][kind]
                     for kind in ('employee', 'service')), 'event_hash_or_identity_changed')
        _require(normalized == _projection(raw, aliases, native=True) and
                 receipt['source_hash'] == digest(_projection(raw, aliases)) and
                 raw['data']['duration'] == aliases['native_readback']['duration'] and
                 (stamp(raw['data']['end_at']) - stamp(raw['data']['start_at'])).total_seconds() == raw['data']['duration'] * 60 and
                 all(raw['data']['service'].get(key, 0) == 0 for key in
                     ('cleanup_duration', 'start_duration', 'end_duration')), 'projection_not_proven')
        expected_request = {'booking': booking, 'customer': canonical['customer'], 'step': step, 'event_id': event_id,
            'actual_source_ids': aliases['actual_source_ids'], 'binding_hash': binding_hash,
            'anchor_event_id': aliases['anchor_event_id'], 'anchor_host_hash': aliases['anchor_host_hash']}
        _require(request == expected_request and receipt['host_hash'] == h['hash'] and receipt['local_hash'] == l['hash'] and
                 receipt['binding_hash'] == binding_hash and receipt['original_source_ids'] == aliases['actual_source_ids'] and
                 receipt['host_created'] == h['created'] and receipt['host_received'] == h['received'], 'collector_receipt_changed')
        readback = readbacks[step]
        actual = readback['booking']
        state = 'canceled' if step == 'cancel' else 'confirmed'
        native = journal['move' if step == 'cancel' else step]
        _require(raw['type'] == 'booking.updated' and raw['data']['status'] == (-101 if step == 'cancel' else 1) and
                 actual.get('id') == cycle['target_booking_id'] and actual.get('provider_id') == target['provider'] and
                 actual.get('service_id') == target['service'] and actual.get('client_id') == target['client'] and
                 actual.get('status') == state and (step != 'cancel' or actual.get('is_confirmed') is False) and
                 actual.get('start_datetime') == company_time(raw['data']['start_at']) == journal['create']['date'] + ' ' + native['start'] + ':00' and
                 actual.get('end_datetime') == company_time(raw['data']['end_at']) == journal['create']['date'] + ' ' + native['end'] + ':00',
                 'target_readback_changed')
        _require(readback.get('event_id') == event_id and readback.get('source_booking_id') == booking and
                 readback.get('read_only') is True and readback.get('transport') == 'simplybook_rest_admin', 'readback_provenance_changed')
        observed = stamp(readback['observed_at_utc']).timestamp()
        done = stamp(readback['local_done_observed_at_utc']).timestamp()
        _require(h['received'] <= done <= observed and ack == {**expected_request, 'host_hash': h['hash'], 'local_hash': l['hash'],
                 'target_booking_id': actual['id'], 'readback_hash': digest(readback), 'readback_at': observed,
                 'done_observed_at': done, 'target_status': state}, 'host_ack_changed')
        _require(phase['actual_target_readback'] == readback and phase['host_acknowledged'] is True and
                 phase['host_event']['id'] == event_id and phase['host_event']['state'] == 'done' and
                 phase['local_event']['state'] == 'done' and phase['local_event']['attempts'] == 1, 'cycle_phase_changed')
        events.append((h, l, raw, normalized, {'value': receipt, 'updated': receipt_at}))
        provenance.append({'step': step, 'event_id': event_id, 'host_hash': h['hash'], 'local_hash': l['hash'],
                           'source_hash': receipt['source_hash'], 'readback_hash': digest(readback)})
    _require(events[0][0]['id'] == aliases['anchor_event_id'] and events[0][0]['hash'] == aliases['anchor_host_hash'], 'anchor_changed')
    ids = {e[0]['id'] for e in events}
    for connection in (host, local):
        _require({r[0] for r in connection.execute('SELECT id FROM events WHERE booking=?', (booking,))} == ids, 'other_booking_events_require_review')
    h, l, raw, normalized, _ = events[-1]
    for connection, event in ((host, raw), (local, normalized)):
        head = _single(connection, 'SELECT * FROM booking_heads WHERE booking=?', (booking,))
        _require(head['event'] == h['id'] and head['created'] == h['created'] and head['conflicted'] == 0 and
                 head['snapshot_hash'] == digest({'data': event['data'], 'deleted': False}), 'booking_head_changed')
    link = _single(local, 'SELECT * FROM links WHERE booking=?', (booking,))
    target_id = cycle['target_booking_id']
    _require(type(target_id) is int and target_id > 0 and link['target'] == target_id and link['state'] == 'canceled' and
             link['version'] == h['created'] and _json(link['snapshot']) == normalized['data'], 'canceled_ownership_changed')
    intent = _single(local, 'SELECT * FROM intents WHERE booking=?', (booking,))
    _require(intent['event'] == h['id'] and intent['kind'] == 'cancel' and intent['state'] == 'done' and
             intent['target'] == intent['result'] == target_id and
             not local.execute("SELECT 1 FROM intents WHERE state!='done'").fetchone(), 'intent_not_resolved')
    _require(not local.execute('SELECT 1 FROM links WHERE target IS NOT NULL AND booking!=?', (booking,)).fetchone() and
             not local.execute('SELECT 1 FROM intents WHERE booking!=?', (booking,)).fetchone(),
             'additional_local_ownership_requires_review')
    _require(_single(local, 'SELECT * FROM clients WHERE source=?', (canonical['customer'],))['target'] == target['client'], 'client_binding_changed')
    applied, applied_at = _cache(local, 'applied:' + booking)
    readback = readbacks['cancel']['booking']
    _require(all(applied.get(key) == readback[key] for key in
             ('provider_id', 'service_id', 'client_id', 'start_datetime', 'end_datetime')), 'applied_baseline_changed')
    _require(not host.execute('SELECT 1 FROM links WHERE booking=? OR target=?', (booking, target_id)).fetchone() and
             not host.execute('SELECT 1 FROM intents WHERE booking=? OR target=?', (booking, target_id)).fetchone() and
             not host.execute('SELECT 1 FROM clients WHERE source=? OR target=?', (aliases['actual_source_ids']['customer'], target['client'])).fetchone(),
             'destination_ownership_collision')
    return {'booking': booking, 'target_id': target_id, 'client': target['client'], 'raw_snapshot': raw['data'],
            'version': h['created'], 'intent': intent, 'applied': applied, 'applied_at': applied_at,
            'binding_hash': binding_hash, 'provenance': provenance,
            'local_audit': {'events': [event[1] for event in events], 'link': link,
                            'head': _single(local, 'SELECT * FROM booking_heads WHERE booking=?', (booking,)),
                            'receipts': [event[4] for event in events], 'canonical_client': canonical['customer']}}


def prepare(host_snapshot, local_snapshot, binding_file, journal_file, cycle_file, readbacks_dir, output, *, now=None):
    """Build a held stage from immutable snapshots; never overwrite any output."""
    now = time.time() if now is None else now
    output = Path(output)
    marker = Path(str(output) + MARKER_SUFFIX)
    report_path = Path(str(output) + '.reconciliation.json')
    _available([output, marker, report_path])
    host_body, _ = _online_snapshot(host_snapshot)
    local_body, _ = _online_snapshot(local_snapshot)
    aliases, journal, cycle = map(_load, (binding_file, journal_file, cycle_file))
    readbacks = {step: _load(Path(readbacks_dir) / ('target-readback-' + step + '.json')) for step in STEPS}
    with closing(sqlite3.connect(':memory:')) as host, host, closing(sqlite3.connect(':memory:')) as local, local:
        for connection, body in ((host, host_body), (local, local_body)):
            connection.row_factory = sqlite3.Row
            connection.deserialize(body)
        proof = _validate(host, local, aliases, journal, cycle, readbacks)
        booking = proof['booking']
        hold = {'remote_reconciliation_required': True, 'budget_reconciliation_required': True,
                'worker_start_allowed': False, 'historical_trial_staging_only': True}
        host.execute('INSERT INTO links VALUES(?,?,?,?,?)', (booking, proof['target_id'], proof['version'], json.dumps(proof['raw_snapshot']), 'canceled'))
        host.execute('INSERT INTO clients VALUES(?,?)', (aliases['actual_source_ids']['customer'], proof['client']))
        intent = proof['intent']
        host.execute('INSERT INTO intents VALUES(?,?,?,?,?,?,?,?,?)', tuple(intent[k] for k in
            ('booking', 'event', 'kind', 'target', 'desired', 'baseline', 'state', 'result', 'started')))
        quotas = [tuple(row) for row in local.execute('SELECT key,at FROM rates')]
        host.executemany('INSERT INTO rates VALUES(?,?)', quotas)
        provenance = {'schema_version': 1, 'booking': booking, 'binding_hash': proof['binding_hash'],
                      'host_snapshot_sha256': _sha(host_body), 'local_snapshot_sha256': _sha(local_body),
                      'events': proof['provenance'], 'local_projection_audit_only': proof['local_audit']}
        for key, value, updated in (
            ('applied:' + booking, proof['applied'], proof['applied_at']),
            ('reconciliation:trial:' + booking, provenance, now), ('recovery-hold', hold, now)):
            _require(not host.execute('SELECT 1 FROM cache WHERE key=?', (key,)).fetchone(), 'destination_cache_collision')
            host.execute('INSERT INTO cache VALUES(?,?,?)', (key, json.dumps(value), updated))
        host.execute('INSERT INTO audit VALUES(?,?,?)', (now, 'verified_historical_trial_reconciliation', digest(booking)))
        host.commit()
        host.row_factory = None
        summary = _inspect_database(host)
        body = host.serialize()
    report = {'schema_version': 1, 'scope': 'one_completed_owned_trial_staging_only',
              'booking_reference': digest(booking), 'binding_hash': proof['binding_hash'],
              'host_snapshot_sha256': _sha(host_body), 'local_snapshot_sha256': _sha(local_body),
              'staged_database_sha256': _sha(body), 'database_summary': summary,
              'host_raw_events_preserved': True, 'host_booking_heads_preserved': True,
              'host_receipts_preserved': True, 'original_event_hashes_rewritten': 0,
              'verified_projection_pairs': 3, 'owned_canceled_links_added': 1,
              'opaque_client_bindings_added': 1, 'done_intents_added': 1,
              'local_quota_rows_appended_without_deduplication': len(quotas),
              'snapshot_freshness_not_renewed': True, 'live_writes': 0, 'worker_start_allowed': False,
              'remote_reconciliation_required': True, 'external_budget_reconciliation_required': True}
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        _exclusive_write(marker, _encode({**hold, 'staging_report_sha256': _sha(_encode(report))}))
    except BaseException:
        os.close(descriptor)
        raise
    _write_reserved(descriptor, body)
    _exclusive_write(report_path, _encode(report))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('host-snapshot', 'local-snapshot', 'binding', 'journal', 'cycle', 'readbacks-dir', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(prepare(args.host_snapshot, args.local_snapshot, args.binding, args.journal,
                                 args.cycle, args.readbacks_dir, args.output)))
        return 0
    except Review as error:
        print(json.dumps({'prepared': False, 'reason': str(error)}))
        return 2
    except Exception:
        print(json.dumps({'prepared': False, 'reason': 'trial_reconciliation_failed'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
