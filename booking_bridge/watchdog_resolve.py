"""Operator-only lookup of diagnostic references. Never invoked by the model.

Reads an existing SQLite database and a saved sanitized collector observation.
Displays calendar IDs and fixed diagnostic codes, without client identity,
payloads, contacts, notes or private URLs. No network, retries or mutations.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sqlite3
import time

from . import watchdog_checks as checks


REFERENCE = re.compile(r'(?:[a-fA-F0-9]{16}|[a-fA-F0-9]{64})')
BOOKING_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}')
EVENT_CODES = {state: 'source_event_' + state for state in checks.STATES}
# These are trusted application codes, never arbitrary text from a database.
REASON_CODES = frozenset({
    'webhook_processing_delayed', 'booking_snapshot_stale', 'schedule_snapshot_stale', 'service_buffers_stale',
    'source_booking_changed_in_simplybook', 'known_booking_moved_outside_allowlist',
    'unresolved_remote_intent', 'unexpected_worker_error', 'unexpected_scheduler_error',
    'create_outcome_unknown_manual_link_required', 'create_result_requires_review',
    'cancel_outcome_requires_review', 'approve_outcome_requires_review', 'edit_outcome_requires_review',
    'client_mapping_or_consent_missing', 'service_timing_resources_not_verified', 'service_duration_mismatch',
    'provider_not_assigned_to_service', 'status_requires_business_review', 'missing_employee_id',
    'unmapped_employees', 'unmapped_services', 'client_mapping_changed',
    'pilot_client_or_service_outside_isolation', 'equal_timestamp_conflicting_snapshots',
    'source_booking_edited_in_simplybook', 'source_booking_canceled_in_simplybook',
    'reactivation_requires_manual_review', 'cross_scope_employee_move', 'preexisting_exact_booking_requires_link_review',
})
REQUIRED = {
    'cache': {'key', 'value', 'updated'}, 'links': {'booking', 'target', 'state'},
    'events': {'id', 'booking', 'state', 'reason'}, 'issues': {'key', 'reason', 'resolved'},
    'intents': {'booking', 'state'},
}


class _Unavailable(Exception):
    def __init__(self, code):
        self.code = code


def _source_id(value):
    return isinstance(value, str) and bool(BOOKING_ID.fullmatch(value))


def _positive(value):
    return type(value) is int and value > 0


def _references(observation):
    refs = set()
    for finding in observation['findings']:
        refs.add(finding['reference'])
        refs.update(finding['evidence']['refs'])
    for row in observation['bookings']:
        refs.update(row[key] for key in ('id_ref', 'provider_ref', 'service_ref'))
    for row in observation['owned_links']:
        refs.update((row['source_ref'], row['target_ref']))
        if row['applied'] is not None:
            refs.update((row['applied']['provider_ref'], row['applied']['service_ref']))
    health = observation['health']
    refs.update(health['intent_refs'])
    refs.update(health['issue_refs'])
    refs.update(row['reference'] for row in health['event_alerts'])
    refs.update(row['provider_ref'] for row in health['provider_capacities'])
    return refs


def _observation(path):
    path = Path(path)
    try:
        if path.is_symlink():
            raise _Unavailable('observation_invalid')
        with path.open('rb') as handle:
            body = handle.read(checks.MAX_OBSERVATION_BYTES + 1)
        if len(body) > checks.MAX_OBSERVATION_BYTES:
            raise _Unavailable('observation_invalid')
        value = checks._json(body.decode('utf-8'))
        checks._validate_observation(value)
        return value
    except _Unavailable:
        raise
    except OSError:
        raise _Unavailable('observation_unavailable') from None
    except (checks._Invalid, ValueError, TypeError, KeyError, RecursionError):
        raise _Unavailable('observation_invalid') from None


class _Catalog:
    def __init__(self):
        self.rows, self.conflicted = {}, set()

    def add(self, namespace, identifier, row, *, prefer_new=False, keep_existing=False):
        reference = checks.entity_ref(namespace, identifier)
        identity = (namespace, json.dumps(identifier, sort_keys=True))
        records = self.rows.setdefault(reference, {})
        old = records.get(identity)
        if old is not None and old != row and not (prefer_new or keep_existing):
            self.conflicted.add(reference)
        if old is None or prefer_new:
            records[identity] = row


def _read_database(path):
    path = Path(path)
    if not path.is_file():
        raise _Unavailable('database_missing')
    catalog, snapshot_at = _Catalog(), None
    conn = None
    deadline, steps = time.monotonic() + 2, 0
    def progress():
        nonlocal steps
        steps += 1000
        return int(steps > checks.MAX_VM_STEPS or time.monotonic() > deadline)
    try:
        conn = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=.5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA query_only=ON')
        conn.execute('PRAGMA trusted_schema=OFF')
        conn.set_progress_handler(progress, 1000)
        conn.execute('BEGIN')
        if conn.execute('PRAGMA user_version').fetchone()[0] != 1:
            raise _Unavailable('database_schema_unsupported')
        for table, columns in REQUIRED.items():
            kind = conn.execute('SELECT type FROM sqlite_master WHERE name=?', (table,)).fetchone()
            if kind is None or kind[0] != 'table' or not columns <= {
                    row['name'] for row in conn.execute('PRAGMA table_info(' + table + ')')}:
                raise _Unavailable('database_schema_invalid')
        caches = checks._rows(conn, 'SELECT key,CASE WHEN length(value)<=? THEN value ELSE NULL END AS value,updated '
                              "FROM cache WHERE key='bookings' OR key LIKE 'applied:%' ORDER BY key",
                              (checks.MAX_JSON_BYTES,))
        baseline = {}
        for row in caches:
            value = checks._json(row['value'])
            if row['key'] == 'bookings':
                checks._require(isinstance(value, list))
                if len(value) > checks.MAX_BOOKINGS:
                    raise checks._Limit()
                snapshot_at = row['updated'] if checks._number(row['updated']) else None
                for booking in value:
                    checks._require(isinstance(booking, dict) and all(_positive(booking.get(key)) for key in
                                    ('id', 'provider_id', 'service_id')) and
                                    booking.get('status') in ('confirmed', 'pending', 'canceled'))
                    start, end = checks._interval(booking.get('start_datetime'), booking.get('end_datetime'))
                    catalog.add('target_booking', booking['id'], {
                        'kind': 'target_booking', 'booking_id': booking['id'], 'provider_id': booking['provider_id'],
                        'service_id': booking['service_id'], 'start': start, 'end': end, 'status': booking['status']})
                    catalog.add('provider', booking['provider_id'], {'kind': 'provider', 'provider_id': booking['provider_id']})
                    catalog.add('service', booking['service_id'], {'kind': 'service', 'service_id': booking['service_id']})
            else:
                baseline[row['key'][len('applied:'):]] = value
        for event in checks._rows(conn, 'SELECT id,booking,state,reason FROM events ORDER BY id'):
            checks._require(checks._identifier(event['id']) and event['state'] in checks.STATES)
            if not _source_id(event['booking']):
                continue
            catalog.add('source_booking', event['booking'], {'kind': 'source_booking', 'booking_id': event['booking']},
                        keep_existing=True)
            catalog.add('source_event', event['id'], {
                'kind': 'source_event', 'booking_id': event['booking'], 'status': event['state'],
                'code': event['reason'] if event['reason'] in REASON_CODES else EVENT_CODES[event['state']]})
        for link in checks._rows(conn, 'SELECT booking,target,state FROM links ORDER BY booking'):
            checks._require(link['state'] in checks.LINK_STATES and (link['target'] is None or _positive(link['target'])))
            if not _source_id(link['booking']):
                continue
            row = {'kind': 'owned_link', 'booking_id': link['booking'],
                   'target_booking_id': link['target'], 'status': link['state']}
            value = baseline.get(link['booking'])
            if isinstance(value, dict) and checks._baseline(value) is not None:
                start, end = checks._interval(value.get('start_datetime'), value.get('end_datetime'))
                row.update(provider_id=value['provider_id'], service_id=value['service_id'], start=start, end=end)
                catalog.add('provider', value['provider_id'], {'kind': 'provider', 'provider_id': value['provider_id']})
                catalog.add('service', value['service_id'], {'kind': 'service', 'service_id': value['service_id']})
            catalog.add('source_booking', link['booking'], row, prefer_new=True)
            if link['target'] is not None:
                catalog.add('target_booking', link['target'], {'kind': 'target_booking', 'booking_id': link['target'],
                            'status': 'not_in_cached_snapshot'}, keep_existing=True)
        for intent in checks._rows(conn, 'SELECT booking,state FROM intents ORDER BY booking'):
            checks._require(intent['state'] in ('started', 'done'))
            if _source_id(intent['booking']):
                catalog.add('source_booking', intent['booking'], {'kind': 'source_booking', 'booking_id': intent['booking']},
                            keep_existing=True)
        for issue in checks._rows(conn, 'SELECT key,reason,resolved FROM issues ORDER BY key'):
            checks._require(checks._identifier(issue['key']) and type(issue['resolved']) is int and issue['resolved'] in (0, 1))
            catalog.add('issue', issue['key'], {'kind': 'issue', 'status': 'resolved' if issue['resolved'] else 'open',
                        'code': issue['reason'] if issue['reason'] in REASON_CODES else 'runtime_incident_requires_review'})
        return catalog, snapshot_at
    except _Unavailable:
        raise
    except checks._Limit:
        raise _Unavailable('database_scan_limit') from None
    except (checks._Invalid, ValueError, TypeError, KeyError, RecursionError, OverflowError):
        raise _Unavailable('database_data_invalid') from None
    except (sqlite3.DatabaseError, OSError):
        raise _Unavailable('database_unavailable') from None
    finally:
        if conn is not None:
            conn.close()


def resolve_reference(database, observation, reference):
    """Return only operator calendar identifiers and safe, fixed diagnostics."""
    report = {'schema_version': 1, 'operator_only': True, 'read_only': True,
              'evidence_scope': 'local_cached_state', 'live_readback_performed': False,
              'status': 'invalid', 'code': 'reference_invalid', 'requested_reference': None,
              'matched_reference': None, 'observation_collected_at': None, 'booking_snapshot_at': None,
              'finding_codes': [], 'matches': [], 'unresolved_references': []}
    if not isinstance(reference, str) or not REFERENCE.fullmatch(reference):
        return report
    reference = reference.lower()
    report['requested_reference'] = reference
    try:
        value = _observation(observation)
        report['observation_collected_at'] = value['collected_at']
        candidates = sorted(ref for ref in _references(value) if ref.startswith(reference))
        if len(candidates) != 1:
            report.update(status='ambiguous' if candidates else 'not_found',
                          code='reference_prefix_ambiguous' if candidates else 'observation_reference_not_found')
            return report
        resolved = candidates[0]
        report['matched_reference'] = resolved
        findings = [row for row in value['findings'] if row['reference'] == resolved]
        report['finding_codes'] = sorted({row['code'] for row in findings})
        targets = sorted({ref for row in findings for ref in row['evidence']['refs']}) if findings else [resolved]
        if not targets:
            report.update(status='insufficient_evidence', code='finding_has_no_entity_references')
            return report
        catalog, report['booking_snapshot_at'] = _read_database(database)
        matches = {}
        for target in targets:
            records = catalog.rows.get(target, {})
            if target in catalog.conflicted or len(records) > 1:
                report.update(status='ambiguous', code='database_reference_ambiguous', matches=[])
                return report
            if not records:
                report['unresolved_references'].append(target)
            for row in records.values():
                matches[json.dumps(row, sort_keys=True)] = row
        report['matches'] = [matches[key] for key in sorted(matches)]
        report.update(status=('partial' if report['unresolved_references'] else 'resolved') if matches else 'not_found',
                      code=('reference_partially_resolved' if report['unresolved_references'] else 'reference_resolved')
                      if matches else 'database_reference_not_found')
    except _Unavailable as exc:
        report.update(status='unavailable', code=exc.code, matches=[])
    except (OSError, ValueError, TypeError, KeyError):
        report.update(status='unavailable', code='reference_lookup_unavailable', matches=[])
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--observation', type=Path, required=True)
    parser.add_argument('--reference', required=True)
    args = parser.parse_args(argv)
    report = resolve_reference(args.database, args.observation, args.reference)
    print(json.dumps(report, sort_keys=True))
    return 0 if report['status'] == 'resolved' else 2


if __name__ == '__main__':
    raise SystemExit(main())
