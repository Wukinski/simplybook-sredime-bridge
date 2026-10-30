"""Bounded, deterministic diagnostics. No network, repairs or booking writes.

Only the collector opens the existing SQLite database. Its output is an explicit
allowlist of hashes, times, fixed states and diagnostic evidence for a separate
reporting process. A model must never receive the database or raw cache records.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import time

from .model import Review, local_stamp, stamp


MAX_ROWS = 5000
MAX_BOOKINGS = 2000
MAX_JSON_BYTES = 4_000_000
MAX_RAW_SCAN_BYTES = 8_000_000
MAX_OBSERVATION_BYTES = 2_000_000
MAX_PAIRS = 20000
MAX_FINDINGS = 500
MAX_VM_STEPS = 1_000_000
REF = re.compile('[a-f0-9]{64}')
STATES = ('dead', 'done', 'ignored', 'queued', 'review', 'stale', 'test', 'working')
SNAPSHOT_STATES = ('fresh', 'missing', 'stale', 'future', 'invalid')
LINK_STATES = ('active', 'canceled', 'new', 'no_show', 'waiting')
SOURCE_STATES = ('active', 'pending', 'canceled', 'no_show', 'unknown')
DATABASE_STATES = ('ok', 'missing', 'schema_unsupported', 'schema_invalid', 'unavailable', 'scan_limit', 'data_invalid')
FINDING_CODES = frozenset({
    'observation_schema_invalid', 'database_missing', 'database_schema_unsupported',
    'database_schema_invalid', 'database_unavailable', 'collection_scan_limit', 'collection_data_invalid',
    'booking_snapshot_missing', 'booking_snapshot_stale', 'booking_snapshot_future', 'booking_snapshot_invalid',
    'service_buffers_missing', 'service_buffers_stale', 'service_buffers_future', 'service_buffers_invalid',
    'worker_heartbeat_missing', 'worker_heartbeat_stale', 'worker_heartbeat_future', 'worker_heartbeat_invalid',
    'booking_evidence_insufficient', 'provider_capacity_unverified', 'provider_overlap_confirmed',
    'provider_overlap_candidate', 'duplicate_booking_candidate', 'duplicate_target_booking_record',
    'conflicting_target_booking_record', 'owned_baseline_missing', 'owned_target_not_in_snapshot',
    'owned_target_diverged', 'owned_cancel_state_diverged', 'owned_source_state_inconsistent',
    'unresolved_remote_intent', 'source_queue_aged', 'source_event_review', 'source_event_dead',
    'source_event_future', 'open_runtime_incident', 'overlap_scan_limit',
})
COLUMNS = {
    'cache': {'key', 'value', 'updated'},
    'links': {'booking', 'target', 'version', 'snapshot', 'state'},
    'events': {'id', 'state', 'received'},
    'intents': {'booking', 'state'},
    'issues': {'key', 'resolved'},
}


class _Invalid(Exception):
    pass


class _Limit(Exception):
    pass


def entity_ref(kind, identifier):
    """Stable, namespace-separated reference; raw IDs never leave collection."""
    return hashlib.sha256(json.dumps([kind, identifier], separators=(',', ':')).encode()).hexdigest()


def _number(value, *, nonnegative=True):
    try:
        return type(value) in (int, float) and math.isfinite(value) and (not nonnegative or value >= 0)
    except OverflowError:
        return False


def _identifier(value):
    return ((type(value) is int and value > 0) or
            (isinstance(value, str) and 0 < len(value) <= 1024 and value == value.strip() and
             not any(ord(char) < 32 or ord(char) == 127 for char in value)))


def _require(ok):
    if not ok:
        raise _Invalid()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


def _invalid_constant(_value):
    raise _Invalid()


def _json(value):
    _require(isinstance(value, str) and len(value.encode('utf-8')) <= MAX_JSON_BYTES)
    try:
        return json.loads(value, object_pairs_hook=_unique, parse_constant=_invalid_constant)
    except (ValueError, TypeError, RecursionError):
        raise _Invalid() from None


def _moment(value):
    try:
        _require(isinstance(value, str) and len(value) <= 64)
        return local_stamp(value).isoformat()
    except (Review, ValueError, OverflowError):
        raise _Invalid() from None


def _interval(start, end):
    start, end = _moment(start), _moment(end)
    _require(stamp(end) > stamp(start))
    return start, end


def _baseline(value):
    if not isinstance(value, dict):
        return None
    try:
        _require(all(type(value.get(key)) is int and value[key] > 0 for key in ('provider_id', 'service_id')))
        start, end = _interval(value.get('start_datetime'), value.get('end_datetime'))
    except _Invalid:
        return None
    return {'provider_ref': entity_ref('provider', value['provider_id']),
            'service_ref': entity_ref('service', value['service_id']), 'start': start, 'end': end}


def _snapshot(value=None, now=None, max_age=None):
    if value is None:
        return {'status': 'missing', 'updated_at': None, 'age_seconds': None}
    updated = value['updated']
    if not _number(updated):
        return {'status': 'invalid', 'updated_at': None, 'age_seconds': None}
    age = now - updated
    status = 'future' if age < 0 else ('stale' if age > max_age else 'fresh')
    return {'status': status, 'updated_at': updated, 'age_seconds': round(age, 3)}


def _empty(now, capacities):
    return {
        'schema_version': 1, 'collected_at': now,
        'health': {
            'database_status': 'unavailable', 'database_schema_version': None, 'scan_complete': False,
            'snapshots': {key: _snapshot() for key in ('bookings', 'buffers', 'heartbeat')},
            'event_counts': {key: 0 for key in STATES}, 'event_alerts': [],
            'intent_refs': [], 'issue_refs': [], 'provider_capacities': capacities, 'errors': [],
            'counts': {'bookings': 0, 'owned_links': 0, 'events': 0, 'intents': 0, 'issues': 0},
        },
        'bookings': [], 'owned_links': [], 'findings': [],
    }


def _capacities(values):
    _require(values is None or isinstance(values, dict))
    values = {} if values is None else values
    _require(len(values) <= MAX_ROWS)
    result = []
    for provider, capacity in values.items():
        _require(type(provider) is int and provider > 0 and type(capacity) is int and 0 < capacity <= 1000)
        result.append({'provider_ref': entity_ref('provider', provider), 'capacity': capacity})
    return sorted(result, key=lambda row: row['provider_ref'])


def _rows(conn, sql, args=()):
    rows, size = [], 0
    for row in conn.execute(sql + ' LIMIT ?', (*args, MAX_ROWS + 1)):
        if len(rows) >= MAX_ROWS:
            raise _Limit()
        size += sum(len(value.encode('utf-8')) if isinstance(value, str) else len(value)
                    for value in row if isinstance(value, (str, bytes)))
        if size > MAX_RAW_SCAN_BYTES:
            raise _Limit()
        rows.append(row)
    return rows


def _collect(conn, observation, now, *, snapshot_max_age, buffers_max_age, heartbeat_max_age, queue_max_age):
    health = observation['health']
    version = conn.execute('PRAGMA user_version').fetchone()[0]
    if version != 1:
        health['database_status'] = 'schema_unsupported'
        return
    health['database_schema_version'] = 1
    for table, columns in COLUMNS.items():
        kind = conn.execute('SELECT type FROM sqlite_master WHERE name=?', (table,)).fetchone()
        if kind is None or kind[0] != 'table' or not columns <= {
                row['name'] for row in conn.execute('PRAGMA table_info(' + table + ')')}:
            health['database_status'] = 'schema_invalid'
            return
    caches = _rows(conn, 'SELECT key,CASE WHEN length(value)<=? THEN value ELSE NULL END AS value,updated '
                         "FROM cache WHERE key IN ('bookings','buffers','heartbeat') OR key LIKE 'applied:%' ORDER BY key",
                   (MAX_JSON_BYTES,))
    cache = {}
    for row in caches:
        _require(isinstance(row['key'], str) and row['key'] not in cache)
        cache[row['key']] = {'value': _json(row['value']), 'updated': row['updated']}
    for key, age in [('bookings', snapshot_max_age), ('buffers', buffers_max_age), ('heartbeat', heartbeat_max_age)]:
        health['snapshots'][key] = _snapshot(cache.get(key), now, age)
    raw_bookings = cache.get('bookings', {}).get('value', [])
    buffers = cache.get('buffers', {}).get('value', {})
    _require(isinstance(raw_bookings, list) and isinstance(buffers, dict))
    if len(raw_bookings) > MAX_BOOKINGS or len(buffers) > MAX_ROWS:
        raise _Limit()
    for service, buffer in buffers.items():
        _require(isinstance(service, str) and service.isdigit() and int(service) > 0 and
                 type(buffer) is int and 0 <= buffer <= 10080)
    if 'heartbeat' in cache and cache['heartbeat']['value'] is not True:
        if health['snapshots']['heartbeat']['status'] == 'fresh':
            health['snapshots']['heartbeat']['status'] = 'invalid'
        health['errors'].append('worker_heartbeat_invalid')
    for raw in raw_bookings:
        _require(isinstance(raw, dict) and all(type(raw.get(key)) is int and raw[key] > 0
                 for key in ('id', 'provider_id', 'service_id')) and
                 raw.get('status') in ('confirmed', 'pending', 'canceled'))
        start, end = _interval(raw.get('start_datetime'), raw.get('end_datetime'))
        buffer = buffers.get(str(raw['service_id']))
        if buffer is None and raw['status'] != 'canceled' and 'buffers' in cache:
            if health['snapshots']['buffers']['status'] == 'fresh':
                health['snapshots']['buffers']['status'] = 'invalid'
            health['errors'].append('service_buffers_invalid')
        observation['bookings'].append({
            'id_ref': entity_ref('target_booking', raw['id']),
            'provider_ref': entity_ref('provider', raw['provider_id']),
            'service_ref': entity_ref('service', raw['service_id']),
            'start': start, 'end': end, 'status': raw['status'], 'buffer_minutes': buffer,
        })
    links = _rows(conn, 'SELECT booking,target,version,state,length(snapshot) AS snapshot_size,CASE WHEN length(snapshot)<=? THEN snapshot ELSE NULL '
                        'END AS snapshot FROM links ORDER BY booking', (MAX_JSON_BYTES,))
    seen_sources, seen_targets = set(), set()
    for row in links:
        _require(_identifier(row['booking']) and row['booking'] not in seen_sources and row['state'] in LINK_STATES and
                 _number(row['version']))
        seen_sources.add(row['booking'])
        if row['target'] is None:
            continue
        _require(type(row['target']) is int and row['target'] > 0 and row['target'] not in seen_targets)
        seen_targets.add(row['target'])
        _require(row['snapshot_size'] is None or row['snapshot_size'] <= MAX_JSON_BYTES)
        source = _json(row['snapshot']) if row['snapshot'] is not None else {}
        _require(isinstance(source, dict))
        status = source.get('status')
        _require(status is None or type(status) is int)
        source_state = ('canceled' if status in (-2, -101, -901) else
                        {1: 'active', 0: 'pending', -902: 'no_show'}.get(status, 'unknown'))
        applied_entry = cache.get('applied:' + row['booking'])
        applied = applied_entry['value'] if applied_entry else None
        if applied_entry is not None:
            _require(_number(applied_entry['updated']))
        observation['owned_links'].append({
            'source_ref': entity_ref('source_booking', row['booking']),
            'target_ref': entity_ref('target_booking', row['target']),
            # The target read must postdate both source version and applied baseline.
            'state': row['state'], 'version': max(row['version'], applied_entry['updated'] if applied_entry else 0),
            'source_state': source_state,
            'applied': _baseline(applied),
        })
    events = _rows(conn, 'SELECT id,state,received FROM events ORDER BY id')
    for row in events:
        _require(_identifier(row['id']) and row['state'] in STATES and _number(row['received']))
        health['event_counts'][row['state']] += 1
        age = round(now - row['received'], 3)
        if row['state'] in ('review', 'dead') or (row['state'] in ('queued', 'working') and
                                                 (age > queue_max_age or age < 0)):
            health['event_alerts'].append({'reference': entity_ref('source_event', row['id']),
                                            'state': row['state'], 'age_seconds': age})
    intents = _rows(conn, 'SELECT booking,state FROM intents ORDER BY booking')
    for row in intents:
        _require(_identifier(row['booking']) and row['state'] in ('started', 'done'))
        if row['state'] != 'done':
            health['intent_refs'].append(entity_ref('source_booking', row['booking']))
    issues = _rows(conn, 'SELECT key,resolved FROM issues ORDER BY key')
    for row in issues:
        _require(_identifier(row['key']) and type(row['resolved']) is int and row['resolved'] in (0, 1))
        if row['resolved'] == 0:
            health['issue_refs'].append(entity_ref('issue', row['key']))
    health['counts'] = {'bookings': len(raw_bookings), 'owned_links': len(observation['owned_links']),
                        'events': len(events), 'intents': len(intents), 'issues': len(issues)}
    booking_snapshot = health['snapshots']['bookings']
    if booking_snapshot['status'] == 'fresh' and any(
            link['version'] > booking_snapshot['updated_at'] for link in observation['owned_links']):
        # Fresh wall-clock age does not make a pre-write inventory current. Keep
        # its real timestamps, but project the same effective status as findings.
        booking_snapshot['status'] = 'stale'
    observation['bookings'].sort(key=lambda row: (row['provider_ref'], row['start'], row['id_ref']))
    observation['owned_links'].sort(key=lambda row: row['source_ref'])
    health['database_status'], health['scan_complete'] = 'ok', True
    health['errors'] = sorted(set(health['errors']))


def collect_observation(database, *, now=None, snapshot_max_age=900, buffers_max_age=4500,
                        heartbeat_max_age=120, queue_max_age=10, provider_capacities=None):
    """Read existing state once; output contains no raw identifiers or payloads."""
    now = time.time() if now is None else now
    _require(_number(now))
    _require(all(_number(value) and value > 0 for value in
                 (snapshot_max_age, buffers_max_age, heartbeat_max_age, queue_max_age)))
    observation = _empty(now, _capacities(provider_capacities))
    health = observation['health']
    path = Path(database)
    conn = None
    interrupted = False
    steps = 0
    deadline = time.monotonic() + 2
    def progress():
        nonlocal steps, interrupted
        steps += 1000
        interrupted = steps > MAX_VM_STEPS or time.monotonic() > deadline
        return int(interrupted)
    try:
        if not path.is_file():
            health['database_status'] = 'missing'
        else:
            conn = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=.5, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA query_only=ON')
            conn.execute('PRAGMA trusted_schema=OFF')
            conn.set_progress_handler(progress, 1000)
            conn.execute('BEGIN')
            _collect(conn, observation, now, snapshot_max_age=snapshot_max_age, buffers_max_age=buffers_max_age,
                     heartbeat_max_age=heartbeat_max_age, queue_max_age=queue_max_age)
    except _Limit:
        health['database_status'] = 'scan_limit'
    except (_Invalid, ValueError, TypeError, OverflowError, KeyError, Review, RecursionError):
        health['database_status'] = 'data_invalid'
    except (sqlite3.DatabaseError, OSError):
        health['database_status'] = 'scan_limit' if interrupted else 'unavailable'
    finally:
        if conn is not None:
            conn.close()
    if health['database_status'] != 'ok':
        health['scan_complete'] = False
        observation['bookings'], observation['owned_links'] = [], []
    reserve = min(MAX_OBSERVATION_BYTES // 3, MAX_FINDINGS * 1200)
    if len(json.dumps(observation, allow_nan=False).encode()) > MAX_OBSERVATION_BYTES - reserve:
        health['database_status'], health['scan_complete'] = 'scan_limit', False
        observation['bookings'], observation['owned_links'] = [], []
        health['event_alerts'], health['intent_refs'], health['issue_refs'] = [], [], []
    observation['findings'] = evaluate_observation(observation)
    if len(json.dumps(observation, allow_nan=False).encode()) > MAX_OBSERVATION_BYTES:
        health['database_status'], health['scan_complete'] = 'scan_limit', False
        observation['bookings'], observation['owned_links'] = [], []
        health['event_alerts'], health['intent_refs'], health['issue_refs'] = [], [], []
        observation['findings'] = []
        observation['findings'] = evaluate_observation(observation)
    return observation


def _ref_ok(value):
    return isinstance(value, str) and bool(REF.fullmatch(value))


def _validate_observation(value):
    _require(isinstance(value, dict) and set(value) == {
        'schema_version', 'collected_at', 'health', 'bookings', 'owned_links', 'findings'})
    _require(type(value['schema_version']) is int and value['schema_version'] == 1 and _number(value['collected_at']))
    _require(len(json.dumps(value, allow_nan=False).encode()) <= MAX_OBSERVATION_BYTES)
    health = value['health']
    _require(isinstance(health, dict) and set(health) == {
        'database_status', 'database_schema_version', 'scan_complete', 'snapshots', 'event_counts',
        'event_alerts', 'intent_refs', 'issue_refs', 'provider_capacities', 'errors', 'counts'})
    _require(health['database_status'] in DATABASE_STATES and (health['database_schema_version'] is None or
             (type(health['database_schema_version']) is int and health['database_schema_version'] == 1)) and
             type(health['scan_complete']) is bool and isinstance(health['snapshots'], dict) and
             set(health['snapshots']) == {'bookings', 'buffers', 'heartbeat'})
    for row in health['snapshots'].values():
        _require(isinstance(row, dict) and set(row) == {'status', 'updated_at', 'age_seconds'} and
                 row['status'] in SNAPSHOT_STATES and (row['updated_at'] is None or _number(row['updated_at'])) and
                 (row['age_seconds'] is None or _number(row['age_seconds'], nonnegative=False)))
        if row['status'] == 'missing':
            _require(row['updated_at'] is None and row['age_seconds'] is None)
        elif row['status'] != 'invalid':
            _require(row['updated_at'] is not None and row['age_seconds'] is not None and
                     abs(value['collected_at'] - row['updated_at'] - row['age_seconds']) <= .001 and
                     ((row['age_seconds'] < 0) == (row['status'] == 'future')))
    _require(isinstance(health['event_counts'], dict) and set(health['event_counts']) == set(STATES) and
             all(type(count) is int and count >= 0 for count in health['event_counts'].values()))
    _require(isinstance(health['counts'], dict) and set(health['counts']) == {
        'bookings', 'owned_links', 'events', 'intents', 'issues'} and
        all(type(count) is int and 0 <= count <= MAX_ROWS for count in health['counts'].values()))
    for key in ('intent_refs', 'issue_refs'):
        _require(isinstance(health[key], list) and len(health[key]) <= MAX_ROWS and all(_ref_ok(ref) for ref in health[key]))
    _require(isinstance(health['errors'], list) and all(code in FINDING_CODES for code in health['errors']))
    _require(isinstance(health['event_alerts'], list) and len(health['event_alerts']) <= MAX_ROWS)
    for row in health['event_alerts']:
        _require(isinstance(row, dict) and set(row) == {'reference', 'state', 'age_seconds'} and
                 _ref_ok(row['reference']) and row['state'] in ('queued', 'working', 'review', 'dead') and
                 _number(row['age_seconds'], nonnegative=False))
    _require(isinstance(health['provider_capacities'], list) and len(health['provider_capacities']) <= MAX_ROWS)
    seen_capacities = set()
    for row in health['provider_capacities']:
        _require(isinstance(row, dict) and set(row) == {'provider_ref', 'capacity'} and _ref_ok(row['provider_ref']) and
                 type(row['capacity']) is int and 0 < row['capacity'] <= 1000 and row['provider_ref'] not in seen_capacities)
        seen_capacities.add(row['provider_ref'])
    _require(isinstance(value['bookings'], list) and len(value['bookings']) <= MAX_BOOKINGS)
    for row in value['bookings']:
        _require(isinstance(row, dict) and set(row) == {
            'id_ref', 'provider_ref', 'service_ref', 'start', 'end', 'status', 'buffer_minutes'} and
            all(_ref_ok(row[key]) for key in ('id_ref', 'provider_ref', 'service_ref')) and
            row['status'] in ('confirmed', 'pending', 'canceled') and
            (row['buffer_minutes'] is None or (type(row['buffer_minutes']) is int and 0 <= row['buffer_minutes'] <= 10080)))
        _require(_interval(row['start'], row['end']) == (row['start'], row['end']))
    _require(isinstance(value['owned_links'], list) and len(value['owned_links']) <= MAX_ROWS)
    source_refs, target_refs = set(), set()
    for row in value['owned_links']:
        _require(isinstance(row, dict) and set(row) == {
            'source_ref', 'target_ref', 'state', 'version', 'source_state', 'applied'} and
            _ref_ok(row['source_ref']) and _ref_ok(row['target_ref']) and row['state'] in LINK_STATES and
            row['source_state'] in SOURCE_STATES and _number(row['version']))
        _require(row['source_ref'] not in source_refs and row['target_ref'] not in target_refs)
        source_refs.add(row['source_ref']); target_refs.add(row['target_ref'])
        baseline = row['applied']
        if baseline is not None:
            _require(isinstance(baseline, dict) and set(baseline) == {'provider_ref', 'service_ref', 'start', 'end'} and
                     _ref_ok(baseline['provider_ref']) and _ref_ok(baseline['service_ref']) and
                     _interval(baseline['start'], baseline['end']) == (baseline['start'], baseline['end']))
    _require(isinstance(value['findings'], list) and len(value['findings']) <= MAX_FINDINGS)
    for finding in value['findings']:
        _require(isinstance(finding, dict) and set(finding) == {'code', 'severity', 'reference', 'evidence'} and
                 finding['code'] in FINDING_CODES and finding['severity'] in ('error', 'warning', 'info') and
                 _ref_ok(finding['reference']) and isinstance(finding['evidence'], dict))
        evidence = finding['evidence']
        _require(set(evidence) <= {'certainty', 'refs', 'age_seconds', 'count', 'evidence_fresh',
                                   'comparison_fields', 'overlap_seconds'} and
                 evidence.get('certainty') in ('operational', 'insufficient', 'candidate', 'confirmed') and
                 isinstance(evidence.get('refs'), list) and len(evidence['refs']) <= 10 and
                 all(_ref_ok(ref) for ref in evidence['refs']))
        for key in ('age_seconds', 'overlap_seconds'):
            if key in evidence:
                _require(evidence[key] is None or _number(evidence[key], nonnegative=key != 'age_seconds'))
        if 'count' in evidence:
            _require(type(evidence['count']) is int and evidence['count'] >= 0)
        if 'evidence_fresh' in evidence:
            _require(type(evidence['evidence_fresh']) is bool)
        if 'comparison_fields' in evidence:
            _require(isinstance(evidence['comparison_fields'], list) and all(
                field in ('provider_ref', 'service_ref', 'start', 'end') for field in evidence['comparison_fields']))


def _finding(code, refs=(), *, severity='warning', **evidence):
    references = sorted(set(refs))
    return {'code': code, 'severity': severity,
            'reference': entity_ref('finding', [code, references]), 'evidence': dict(evidence, refs=references)}


def _evaluate(value):
    findings = []
    health = value['health']
    status = health['database_status']
    if status != 'ok' or not health['scan_complete']:
        code = {'missing': 'database_missing', 'schema_unsupported': 'database_schema_unsupported',
                'schema_invalid': 'database_schema_invalid', 'unavailable': 'database_unavailable',
                'scan_limit': 'collection_scan_limit', 'data_invalid': 'collection_data_invalid'}.get(
                    status, 'collection_data_invalid')
        return [_finding(code, severity='error', certainty='operational'),
                _finding('booking_evidence_insufficient', certainty='insufficient', evidence_fresh=False)]
    for code in health['errors']:
        findings.append(_finding(code, certainty='operational'))
    for key, prefix in [('bookings', 'booking_snapshot'), ('buffers', 'service_buffers'), ('heartbeat', 'worker_heartbeat')]:
        snapshot = health['snapshots'][key]
        if snapshot['status'] != 'fresh':
            findings.append(_finding(prefix + '_' + snapshot['status'], certainty='operational',
                                     age_seconds=snapshot['age_seconds']))
    fresh = all(health['snapshots'][key]['status'] == 'fresh' for key in ('bookings', 'buffers'))
    snapshot_at = health['snapshots']['bookings']['updated_at']
    newer_owned = [link for link in value['owned_links'] if snapshot_at is not None and link['version'] > snapshot_at]
    if newer_owned:
        fresh = False
        for link in newer_owned:
            findings.append(_finding('booking_snapshot_stale', [link['source_ref'], link['target_ref']],
                                     certainty='operational', age_seconds=health['snapshots']['bookings']['age_seconds']))
    if not fresh:
        findings.append(_finding('booking_evidence_insufficient', certainty='insufficient', evidence_fresh=False))
    for alert in health['event_alerts']:
        state = alert['state']
        code = ('source_event_future' if alert['age_seconds'] < 0 else
                {'review': 'source_event_review', 'dead': 'source_event_dead'}.get(state, 'source_queue_aged'))
        findings.append(_finding(code, [alert['reference']], severity='error' if state in ('review', 'dead') else 'warning',
                                 age_seconds=alert['age_seconds'], certainty='operational'))
    for reference in health['intent_refs']:
        findings.append(_finding('unresolved_remote_intent', [reference], severity='error', certainty='operational'))
    for reference in health['issue_refs']:
        findings.append(_finding('open_runtime_incident', [reference], severity='error', certainty='operational'))
    by_id = {}
    for booking in value['bookings']:
        old = by_id.get(booking['id_ref'])
        if old is not None:
            findings.append(_finding('duplicate_target_booking_record' if old == booking else
                                     'conflicting_target_booking_record', [booking['id_ref']],
                                     severity='error', certainty='operational'))
            if old != booking:
                fresh = False
                findings.append(_finding('booking_evidence_insufficient', certainty='insufficient', evidence_fresh=False))
        else:
            by_id[booking['id_ref']] = booking
    for link in value['owned_links']:
        references = [link['source_ref'], link['target_ref']]
        baseline = link['applied']
        if baseline is None:
            findings.append(_finding('owned_baseline_missing', references, severity='error', certainty='operational'))
        source_canceled = link['source_state'] == 'canceled'
        expected_canceled = link['state'] == 'canceled'
        if link['source_state'] != 'unknown' and source_canceled != expected_canceled:
            findings.append(_finding('owned_source_state_inconsistent', references, severity='error', certainty='operational'))
        actual = by_id.get(link['target_ref'])
        if actual is None:
            findings.append(_finding('owned_target_not_in_snapshot', references, certainty='insufficient',
                                     evidence_fresh=fresh))
        elif fresh:
            canceled = actual['status'] == 'canceled'
            if canceled != expected_canceled:
                findings.append(_finding('owned_cancel_state_diverged', references, severity='error',
                                         certainty='confirmed', evidence_fresh=True))
            elif not canceled and baseline is not None:
                fields = [key for key in ('provider_ref', 'service_ref', 'start', 'end') if actual[key] != baseline[key]]
                if fields:
                    findings.append(_finding('owned_target_diverged', references, severity='error',
                                             certainty='confirmed', comparison_fields=fields, evidence_fresh=True))
    capacities = {row['provider_ref']: row['capacity'] for row in health['provider_capacities']}
    providers = defaultdict(list)
    for booking in by_id.values():
        if booking['status'] != 'canceled':
            providers[booking['provider_ref']].append(booking)
    pairs = 0
    unknown_capacities = set()
    for provider, bookings in sorted(providers.items()):
        active = []
        for booking in sorted(bookings, key=lambda row: (row['start'], row['id_ref'])):
            start = stamp(booking['start']).timestamp()
            end = stamp(booking['end']).timestamp() + (booking['buffer_minutes'] or 0) * 60
            active = [(other, other_end) for other, other_end in active if other_end > start]
            for other, other_end in active:
                pairs += 1
                if pairs > MAX_PAIRS:
                    findings.append(_finding('overlap_scan_limit', certainty='insufficient', count=MAX_PAIRS))
                    return findings
                refs = [provider, booking['id_ref'], other['id_ref']]
                duplicate = all(booking[key] == other[key] for key in ('provider_ref', 'service_ref', 'start', 'end'))
                if duplicate:
                    findings.append(_finding('duplicate_booking_candidate', refs, certainty='candidate', evidence_fresh=fresh))
                capacity = capacities.get(provider)
                if capacity is None:
                    unknown_capacities.add(provider)
                if capacity == 1 and fresh and booking['buffer_minutes'] is not None and other['buffer_minutes'] is not None:
                    code, certainty, severity = 'provider_overlap_confirmed', 'confirmed', 'error'
                elif capacity is not None and capacity > 1:
                    continue
                else:
                    code, certainty, severity = 'provider_overlap_candidate', 'candidate' if fresh else 'insufficient', 'warning'
                overlap = min(end, other_end) - start
                findings.append(_finding(code, refs, severity=severity, certainty=certainty,
                                         overlap_seconds=round(overlap, 3), evidence_fresh=fresh))
            active.append((booking, end))
    for provider in sorted(unknown_capacities):
        findings.append(_finding('provider_capacity_unverified', [provider], certainty='insufficient'))
    return findings


def evaluate_observation(observation):
    """Recompute findings from sanitized evidence; never perform an action."""
    try:
        _validate_observation(observation)
        findings = _evaluate(observation)
    except (_Invalid, ValueError, TypeError, KeyError, OverflowError, Review, RecursionError):
        return [_finding('observation_schema_invalid', severity='error', certainty='insufficient')]
    unique = {row['reference']: row for row in findings}
    if len(unique) > MAX_FINDINGS:
        selected = sorted(unique.values(), key=lambda row: (row['severity'] != 'error', row['code'], row['reference']))[:MAX_FINDINGS - 1]
        selected.append(_finding('overlap_scan_limit', certainty='insufficient', count=MAX_FINDINGS))
        return sorted(selected, key=lambda row: (row['code'], row['reference']))
    return sorted(unique.values(), key=lambda row: (row['code'], row['reference']))


def write_observation(output, observation, *, database=None):
    """Atomically replace only the explicit projection file, never the database."""
    _validate_observation(observation)
    path = Path(output)
    if path.suffix.lower() != '.json':
        raise ValueError('watchdog_output_must_be_json')
    if database is not None and path.resolve() in {
            Path(str(database) + suffix).resolve() for suffix in ('', '-wal', '-shm', '-journal')}:
        raise ValueError('watchdog_output_cannot_replace_database')
    body = (json.dumps(observation, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()
    if len(body) > MAX_OBSERVATION_BYTES:
        raise ValueError('watchdog_projection_too_large')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.watchdog-', suffix='.tmp', delete=False) as handle:
            temporary = Path(handle.name)
            os.chmod(temporary, 0o600)
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _capacity(value):
    try:
        provider, capacity = (int(part) for part in value.split(':'))
        if provider <= 0 or capacity != 1:
            raise ValueError()
    except (ValueError, TypeError):
        raise argparse.ArgumentTypeError('capacity must be a reviewed positive provider ID followed by :1') from None
    return provider, capacity


def _interval_seconds(value):
    try:
        result = int(value)
        if not 5 <= result <= 3600:
            raise ValueError()
        return result
    except ValueError:
        raise argparse.ArgumentTypeError('interval must be an integer from 5 to 3600') from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--interval', type=_interval_seconds, default=30)
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--capacity', type=_capacity, action='append', default=[], metavar='PROVIDER_ID:1')
    args = parser.parse_args(argv)
    capacities = dict(args.capacity)
    from provider_assignment.core import Failure, lock
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with lock(args.output.parent / '.watchdog-collector.lock'):
            while True:
                observation = collect_observation(args.database, provider_capacities=capacities)
                write_observation(args.output, observation, database=args.database)
                if args.once:
                    print(json.dumps({'projection_written': True, 'findings': len(observation['findings'])}))
                    return 0
                time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0
    except (Failure, OSError, ValueError, _Invalid):
        print(json.dumps({'projection_written': False, 'reason': 'watchdog_collector_stopped'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
