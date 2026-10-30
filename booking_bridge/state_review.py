"""Compare standalone SQLite snapshots without migration, credentials or writes.

This module deliberately never constructs Settings or Store. A successful review
means the snapshots were compared; it does not authorize execution or migration.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3

from .model import Review, digest, stamp


COLUMNS = {
    'events': {'id', 'booking', 'created', 'payload', 'hash', 'state', 'reason',
               'attempts', 'due', 'received'},
    'booking_heads': {'booking', 'created', 'event', 'snapshot_hash', 'conflicted'},
    'links': {'booking', 'target', 'version', 'snapshot', 'state'},
    'intents': {'booking', 'event', 'kind', 'target', 'desired', 'baseline', 'state', 'result', 'started'},
    'clients': {'source', 'target'},
    'source_bindings': {'employee', 'uid', 'booking'},
    'cache': {'key', 'value', 'updated'},
    'issues': {'key', 'reason', 'created', 'updated', 'resolved'},
    'rates': {'key', 'at'},
    'feed_health': {'employee', 'failures', 'due', 'last_ok', 'state'},
    'refresh': {'employee', 'due'},
    'audit': {'at', 'action', 'reference'},
    'availability_observations': {'id', 'employee', 'version', 'kind', 'ready', 'scheduled', 'fetched'},
}
EVENT_STATES = ('dead', 'done', 'ignored', 'queued', 'review', 'stale', 'test', 'working')
LINK_STATES = ('active', 'canceled', 'new', 'no_show', 'waiting')
TERMINAL_EVENTS = {'done', 'ignored', 'stale', 'test'}
DESIRED_FIELDS = ('service_id', 'provider_id', 'client_id', 'start_datetime', 'end_datetime')
GUARD_PREFIXES = ('applied:', 'feed-scope:', 'candidates:', 'client-intent:',
                  'refresh-attempt:', 'refresh-failures:', 'refresh-generation:',
                  'refresh-pending-since:', 'refresh-scheduled:', 'schedule-job:',
                  'schedule-request:', 'schedule-backoff', 'task:', 'source-feed:')


class SnapshotInvalid(Exception):
    """The argument is always a fixed, public reason code."""


def _require(ok, code):
    if not ok:
        raise SnapshotInvalid(code)


def _identifier(value):
    return isinstance(value, str) and bool(value) and value == value.strip() and not any(
        ord(char) < 32 or ord(char) == 127 for char in value)


def _time(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _target(value):
    return type(value) is int and value > 0


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, 'duplicate_json_key')
        result[key] = value
    return result


def _json(value):
    try:
        return json.loads(value, object_pairs_hook=_unique, parse_constant=_invalid_json_constant)
    except (ValueError, TypeError):
        raise SnapshotInvalid('invalid_json') from None


def _invalid_json_constant(_value):
    raise SnapshotInvalid('invalid_json')


def _hash_file(path):
    result = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def _ref(kind, value):
    return digest({'kind': kind, 'value': value})[:24]


def _indexed(rows, key, code):
    result = {}
    for row in rows:
        value = row[key]
        _require(_identifier(value) and value not in result, code)
        result[value] = row
    return result


def _desired(value):
    return (isinstance(value, dict) and
            all(_target(value.get(key)) for key in DESIRED_FIELDS[:3]) and
            all(isinstance(value.get(key), str) and value[key] for key in DESIRED_FIELDS[3:]))


@dataclass
class Snapshot:
    sha256: str
    tables: dict
    events: dict
    heads: dict
    links: dict
    clients: dict
    bindings: dict
    intents: dict
    cache: dict

    def summary(self):
        event_states = Counter(row['state'] for row in self.events.values())
        return {
            'valid': True, 'sha256': self.sha256, 'schema_version': 1,
            'tables': {table: len(self.tables[table]) for table in sorted(COLUMNS)},
            'event_states': {state: event_states[state] for state in EVENT_STATES},
            'conflicted_heads': sum(row['conflicted'] for row in self.heads.values()),
            'terminal_tombstones': sum(_tombstone(self.events[row['event']]['decoded'])
                                       for row in self.heads.values()),
            'owned_links': sum(row['target'] is not None for row in self.links.values()),
            'applied_baselines': sum(key.startswith('applied:') for key in self.cache),
            'unresolved_intents': sum(row['state'] != 'done' for row in self.intents.values()),
            'open_issues': sum(row['resolved'] == 0 for row in self.tables['issues']),
            'cache_guards': sum(_guard(key) for key in self.cache),
            'quota_rows': len(self.tables['rates']),
            'quota_keys': len({row['key'] for row in self.tables['rates']}),
        }


def _tombstone(event):
    return event['type'] == 'booking.deleted' or event['data']['status'] in (-2, -101, -901)


def _guard(key):
    return key.startswith(GUARD_PREFIXES)


def _validate(tables, sha256):
    events = _indexed(tables['events'], 'id', 'invalid_event_identity')
    grouped = defaultdict(list)
    for event_id, row in events.items():
        value = _json(row['payload'])
        _require(isinstance(value, dict) and isinstance(value.get('data'), dict), 'invalid_event_payload')
        data = value['data']
        _require(bool(re.fullmatch('[a-f0-9]{32}', event_id)) and value.get('id') == event_id and
                 _identifier(row['booking']) and data.get('id') == row['booking'], 'event_identity_mismatch')
        _require(value.get('type') in ('booking.created', 'booking.updated', 'booking.deleted') and
                 type(data.get('status')) is int and type(value.get('test', False)) is bool,
                 'invalid_event_payload')
        try:
            created = stamp(value.get('created_at')).timestamp()
        except Review:
            raise SnapshotInvalid('invalid_event_timestamp') from None
        _require(_time(row['created']) and abs(row['created'] - created) < 0.000001,
                 'event_timestamp_mismatch')
        _require(row['hash'] == digest(value), 'event_hash_mismatch')
        _require(row['state'] in EVENT_STATES, 'invalid_event_state')
        _require(type(row['attempts']) is int and row['attempts'] >= 0 and
                 _time(row['due']) and _time(row['received']), 'invalid_event_counters')
        for kind in ('employee', 'service', 'customer'):
            entity = data.get(kind)
            _require(entity is None or isinstance(entity, dict), 'invalid_event_identity')
            if isinstance(entity, dict) and 'id' in entity:
                _require(_identifier(entity['id']), 'invalid_event_identity')
        row['decoded'] = value
        row['snapshot_digest'] = digest({'data': data, 'deleted': value['type'] == 'booking.deleted'})
        if not value.get('test', False):
            grouped[row['booking']].append(row)

    heads = _indexed(tables['booking_heads'], 'booking', 'invalid_booking_head')
    _require(set(heads) == set(grouped), 'booking_head_missing_or_orphaned')
    for booking, row in heads.items():
        event = events.get(row['event'])
        _require(event is not None and event['booking'] == booking and
                 not event['decoded'].get('test', False) and row['created'] == event['created'] and
                 row['snapshot_hash'] == event['snapshot_digest'] and
                 type(row['conflicted']) is int and row['conflicted'] in (0, 1), 'booking_head_mismatch')
        latest = max(item['created'] for item in grouped[booking])
        tied = {item['snapshot_digest'] for item in grouped[booking] if item['created'] == latest}
        _require(row['created'] == latest and (len(tied) == 1 or row['conflicted'] == 1),
                 'booking_head_not_authoritative')

    cache = _indexed(tables['cache'], 'key', 'invalid_cache_key')
    for row in cache.values():
        row['decoded'] = _json(row['value'])
        _require(_time(row['updated']), 'invalid_cache_timestamp')
    links = _indexed(tables['links'], 'booking', 'invalid_link_identity')
    targets = set()
    for booking, row in links.items():
        _require(row['state'] in LINK_STATES and _time(row['version']), 'invalid_link_state')
        _require(row['target'] is None or _target(row['target']), 'invalid_link_target')
        if row['target'] is not None:
            _require(row['target'] not in targets, 'duplicate_link_target')
            targets.add(row['target'])
        value = _json(row['snapshot']) if row['snapshot'] is not None else None
        _require(value is None or (isinstance(value, dict) and value.get('id') == booking),
                 'link_snapshot_identity_mismatch')
        if value is not None:
            for kind in ('employee', 'service', 'customer'):
                entity = value.get(kind)
                _require(entity is None or (isinstance(entity, dict) and
                         ('id' not in entity or _identifier(entity['id']))), 'invalid_link_snapshot')
        row['decoded'] = value
        _require(booking in heads and row['version'] <= heads[booking]['created'], 'link_head_mismatch')
        applied = cache.get('applied:' + booking)
        if applied is not None:
            _require(_desired(applied['decoded']), 'invalid_applied_baseline')
    for key, row in cache.items():
        if key.startswith('applied:'):
            link = links.get(key[len('applied:'):])
            _require(link is not None and link['target'] is not None and _desired(row['decoded']),
                     'orphaned_applied_baseline')

    client_rows = _indexed(tables['clients'], 'source', 'invalid_client_mapping')
    clients = {key: row['target'] for key, row in client_rows.items()}
    _require(all(_target(target) for target in clients.values()) and
             len(set(clients.values())) == len(clients), 'invalid_client_target')
    bindings = {}
    for row in tables['source_bindings']:
        key = (row['employee'], row['uid'])
        _require(all(_identifier(value) for value in (*key, row['booking'])) and key not in bindings,
                 'invalid_source_binding')
        _require(row['booking'] in links, 'source_binding_ownership_missing')
        bindings[key] = row['booking']
    intents = _indexed(tables['intents'], 'booking', 'invalid_intent_identity')
    for booking, row in intents.items():
        event = events.get(row['event'])
        _require(event is not None and event['booking'] == booking and row['kind'] in
                 ('create', 'edit', 'cancel', 'approve') and row['state'] in ('started', 'done'),
                 'invalid_intent_state')
        _require(_time(row['started']) and all(value is None or _target(value) for value in
                 (row['target'], row['result'])), 'invalid_intent_target')
        _require(row['state'] != 'done' or _target(row['result']), 'invalid_completed_intent_result')
        _require(row['target'] is None or row['result'] is None or row['target'] == row['result'],
                 'intent_target_result_mismatch')
        desired, baseline = _json(row['desired']), _json(row['baseline'])
        _require(isinstance(baseline, list) and all(_target(value) for value in baseline) and
                 (desired == {} if row['kind'] == 'cancel' else _desired(desired)), 'invalid_intent_baseline')
        row['desired_decoded'], row['baseline_decoded'] = desired, baseline
    _indexed(tables['issues'], 'key', 'invalid_issue_identity')
    for row in tables['issues']:
        _require(row['resolved'] in (0, 1) and _time(row['created']) and _time(row['updated']), 'invalid_issue_state')
    for row in tables['rates']:
        _require(_identifier(row['key']) and _time(row['at']), 'invalid_rate_ledger')
    _indexed(tables['refresh'], 'employee', 'invalid_refresh_guard')
    for row in tables['refresh']:
        _require(_identifier(row['employee']) and _time(row['due']), 'invalid_refresh_guard')
    _indexed(tables['feed_health'], 'employee', 'invalid_feed_health')
    for row in tables['feed_health']:
        _require(_identifier(row['employee']) and type(row['failures']) is int and row['failures'] >= 0 and
                 _time(row['due']) and (row['last_ok'] is None or _time(row['last_ok'])) and
                 row['state'] in ('new', 'ok', 'backoff', 'stopped'), 'invalid_feed_health')
    for row in tables['audit']:
        _require(_time(row['at']) and _identifier(row['action']) and _identifier(row['reference']),
                 'invalid_audit_evidence')
    observation_ids = set()
    for row in tables['availability_observations']:
        _require(_target(row['id']) and row['id'] not in observation_ids and _identifier(row['employee']) and
                 _identifier(row['version']) and row['kind'] in ('baseline', 'change') and
                 _time(row['ready']) and all(value is None or _time(value) for value in
                 (row['scheduled'], row['fetched'])), 'invalid_availability_observation')
        observation_ids.add(row['id'])
    return Snapshot(sha256, tables, events, heads, links, clients, bindings, intents, cache)


def _read_snapshot(path):
    """Read a complete backup file. Live SQLite files/sidecars are not accepted."""
    path = Path(path)
    try:
        _require(path.is_file(), 'snapshot_missing')
        _require(not any(Path(str(path) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')),
                 'snapshot_sidecars_present')
        before = _hash_file(path)
        uri = path.resolve().as_uri() + '?mode=ro&immutable=1'
        conn = sqlite3.connect(uri, uri=True, timeout=1, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('PRAGMA query_only=ON')
            conn.execute('PRAGMA trusted_schema=OFF')
            conn.execute('BEGIN')
            _require(conn.execute('PRAGMA quick_check').fetchone()[0] == 'ok', 'snapshot_corrupt')
            _require(conn.execute('PRAGMA user_version').fetchone()[0] == 1, 'snapshot_schema_version_unsupported')
            tables = {}
            for table, columns in COLUMNS.items():
                schema = conn.execute('SELECT type FROM sqlite_master WHERE name=?', (table,)).fetchone()
                _require(schema is not None and schema['type'] == 'table', 'snapshot_schema_invalid')
                actual = {row['name'] for row in conn.execute('PRAGMA table_info(' + table + ')')}
                _require(columns == actual, 'snapshot_schema_invalid')
                tables[table] = [dict(row) for row in conn.execute('SELECT * FROM ' + table)]
                for row in tables[table]:
                    json.dumps(row, allow_nan=False)
        finally:
            conn.close()
        _require(before == _hash_file(path) and not any(Path(str(path) + suffix).exists()
                 for suffix in ('-wal', '-shm', '-journal')), 'snapshot_changed_during_review')
        return _validate(tables, before)
    except SnapshotInvalid:
        raise
    except sqlite3.DatabaseError:
        raise SnapshotInvalid('snapshot_unreadable_or_corrupt') from None
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        raise SnapshotInvalid('snapshot_unreadable_or_invalid') from None


class Findings:
    def __init__(self):
        self.rows = defaultdict(list)

    def add(self, code, scope, *, kind=None, value=None):
        self.rows[(code, scope)].append(_ref(kind, value) if kind else None)

    def report(self):
        return [{'code': code, 'scope': scope, 'count': len(values),
                 'references': sorted({value for value in values if value is not None})[:20]}
                for (code, scope), values in sorted(self.rows.items())]


def _compare(local, host, blockers, differences):
    shared = local.events.keys() & host.events.keys()
    for event_id in sorted(shared):
        left, right = local.events[event_id], host.events[event_id]
        if left['hash'] != right['hash']:
            blockers.add('event_id_payload_collision', 'both', kind='event', value=event_id)
        elif left['state'] != right['state']:
            code = ('local_terminal_host_pending_requires_ack_review' if
                    left['state'] in TERMINAL_EVENTS and right['state'] in ('queued', 'working') else
                    'event_state_differs_preserve_host_receipt')
            differences.add(code, 'both', kind='event', value=event_id)
    for booking in sorted(local.heads.keys() & host.heads.keys()):
        left, right = local.heads[booking], host.heads[booking]
        if left['created'] == right['created'] and left['snapshot_hash'] != right['snapshot_hash']:
            blockers.add('equal_timestamp_booking_snapshot_conflict', 'both', kind='booking', value=booking)
        elif any(left[key] != right[key] for key in ('created', 'event', 'snapshot_hash', 'conflicted')):
            differences.add('booking_head_differs_preserve_latest_and_tombstones', 'both', kind='booking', value=booking)
    for scope, snap, other in [('local', local, host), ('host', host, local)]:
        for booking, head in sorted(snap.heads.items()):
            if head['conflicted']:
                blockers.add('booking_head_conflicted', scope, kind='booking', value=booking)
        for booking, link in sorted(snap.links.items()):
            target = link['target']
            if target is not None:
                if link['decoded'] is None or 'applied:' + booking not in snap.cache:
                    blockers.add('owned_link_missing_applied_baseline', scope, kind='booking', value=booking)
                else:
                    customer = (link['decoded'].get('customer') or {}).get('id')
                    baseline = snap.cache['applied:' + booking]['decoded']
                    if not customer or snap.clients.get(customer) != baseline['client_id']:
                        blockers.add('ownership_client_mapping_missing_or_conflicting', scope,
                                     kind='booking', value=booking)
                other_link = other.links.get(booking)
                if not other_link or other_link['target'] is None:
                    blockers.add('ownership_missing_on_other_snapshot', scope, kind='booking', value=booking)
            other_link = other.links.get(booking)
            if other_link and target != other_link['target']:
                blockers.add('booking_target_identity_conflict', scope, kind='booking', value=booking)
            elif other_link and any(link[key] != other_link[key] for key in ('version', 'snapshot', 'state')):
                differences.add('owned_link_history_differs', scope, kind='booking', value=booking)
        for booking, intent in sorted(snap.intents.items()):
            if intent['state'] != 'done':
                blockers.add('unresolved_remote_intent_requires_readback', scope, kind='booking', value=booking)
        for issue in snap.tables['issues']:
            if issue['resolved'] == 0:
                blockers.add('open_incident_requires_review', scope, kind='issue', value=issue['key'])
        for row in snap.tables['feed_health']:
            if row['failures'] or row['state'] in ('backoff', 'stopped'):
                blockers.add('source_feed_recovery_guard_active', scope, kind='employee', value=row['employee'])
    for kind, left_rows, right_rows in [('booking', {key: row['target'] for key, row in local.links.items()
                                                    if row['target'] is not None},
                                        {key: row['target'] for key, row in host.links.items()
                                         if row['target'] is not None}),
                                       ('client', local.clients, host.clients)]:
        reverse = {target: source for source, target in right_rows.items()}
        for source, target in sorted(left_rows.items()):
            if source in right_rows and right_rows[source] != target:
                blockers.add(kind + '_mapping_target_conflict', 'both', kind=kind, value=source)
            if target in reverse and reverse[target] != source:
                blockers.add(kind + '_target_has_different_source_keys', 'both', kind=kind, value=source)
    for key in sorted(local.bindings.keys() & host.bindings.keys()):
        if local.bindings[key] != host.bindings[key]:
            blockers.add('source_binding_identity_conflict', 'both', kind='binding', value=key)
    for booking in sorted(local.intents.keys() & host.intents.keys()):
        left, right = local.intents[booking], host.intents[booking]
        if left['event'] == right['event'] and any(left[key] != right[key] for key in
                ('kind', 'target', 'desired_decoded', 'baseline_decoded', 'result')):
            blockers.add('intent_evidence_conflict', 'both', kind='booking', value=booking)
    shared_cache = local.cache.keys() & host.cache.keys()
    divergent_guards = 0
    divergent_guard_timestamps = 0
    for key in sorted(shared_cache):
        if local.cache[key]['decoded'] != host.cache[key]['decoded'] and _guard(key):
            divergent_guards += 1
            blockers.add('cache_guard_conflict_requires_review', 'both', kind='cache', value=key)
        if _guard(key) and local.cache[key]['updated'] != host.cache[key]['updated']:
            divergent_guard_timestamps += 1
            differences.add('cache_guard_timestamps_must_be_retained', 'both', kind='cache', value=key)
    return {
        'events': {'shared': len(shared), 'local_only': len(local.events.keys() - host.events.keys()),
                   'host_only': len(host.events.keys() - local.events.keys()),
                   'matching_payload_hashes': sum(local.events[key]['hash'] == host.events[key]['hash'] for key in shared),
                   'payload_collisions': sum(local.events[key]['hash'] != host.events[key]['hash'] for key in shared),
                   'host_pending_to_preserve': sum(row['state'] in ('queued', 'working') for row in host.events.values()),
                   'host_receipts_to_preserve': len(host.events)},
        'booking_heads': {'shared': len(local.heads.keys() & host.heads.keys()),
                          'local_only': len(local.heads.keys() - host.heads.keys()),
                          'host_only': len(host.heads.keys() - local.heads.keys())},
        'links': {'shared': len(local.links.keys() & host.links.keys()),
                  'local_only': len(local.links.keys() - host.links.keys()),
                  'host_only': len(host.links.keys() - local.links.keys())},
        'clients': {'shared': len(local.clients.keys() & host.clients.keys()),
                    'local_only': len(local.clients.keys() - host.clients.keys()),
                    'host_only': len(host.clients.keys() - local.clients.keys())},
        'source_bindings': {'shared': len(local.bindings.keys() & host.bindings.keys()),
                           'local_only': len(local.bindings.keys() - host.bindings.keys()),
                           'host_only': len(host.bindings.keys() - local.bindings.keys())},
        'cache': {'shared': len(shared_cache),
                  'local_only': len(local.cache.keys() - host.cache.keys()),
                  'host_only': len(host.cache.keys() - local.cache.keys()),
                  'divergent_values': sum(local.cache[key]['decoded'] != host.cache[key]['decoded'] for key in shared_cache),
                  'divergent_guards': divergent_guards,
                  'divergent_guard_timestamps': divergent_guard_timestamps},
        'rate_quotas': {'local_rows': len(local.tables['rates']), 'host_rows': len(host.tables['rates']),
                        'conservative_rows_to_retain': len(local.tables['rates']) + len(host.tables['rates']),
                        'deduplication_allowed': False, 'timestamps_must_be_preserved': True},
    }


def review_snapshots(local_snapshot, host_snapshot):
    """Return sanitized evidence and a manual plan; never modify either input."""
    blockers, differences = Findings(), Findings()
    snapshots, summaries = {}, {}
    for scope, path in [('local', local_snapshot), ('host', host_snapshot)]:
        try:
            snap = _read_snapshot(path)
            snapshots[scope] = snap
            summaries[scope] = snap.summary()
        except SnapshotInvalid as exc:
            code = str(exc)
            summaries[scope] = {'valid': False, 'reason': code}
            blockers.add(code, scope)
    comparison = None
    if len(snapshots) == 2:
        comparison = _compare(snapshots['local'], snapshots['host'], blockers, differences)
        for table in COLUMNS:
            # These digests are internal only; neither raw rows nor values leave this function.
            left = snapshots['local'].tables[table]
            right = snapshots['host'].tables[table]
            if sorted(digest(row) for row in left) != sorted(digest(row) for row in right):
                differences.add('table_evidence_differs', 'both', kind='table', value=table)
    blocking = blockers.report()
    differing = differences.report()
    return {
        'report_version': 1, 'read_only': True, 'inputs_modified': False,
        'external_validation_performed': False, 'automatic_migration_allowed': False,
        'activation_ready': False, 'snapshot_comparison_complete': comparison is not None,
        'status': 'blocked' if blocking else ('manual_reconciliation_required' if differing else 'snapshots_consistent'),
        'manual_reconciliation_required': bool(blocking or differing),
        'snapshots': summaries, 'comparison': comparison, 'blockers': blocking, 'differences': differing,
        'plan': [
            'retain_original_snapshots_and_host_receipts',
            'preserve_host_queued_events_without_local_state_overwrite',
            'review_exact_identity_keys_without_namespace_aliases',
            'preserve_owned_links_applied_baselines_and_client_bindings',
            'preserve_booking_heads_and_terminal_tombstones',
            'resolve_uncertain_intents_by_authoritative_readback_before_retry',
            'retain_both_quota_ledgers_conservatively_until_original_windows_expire',
            'retain_guard_evidence_and_rebuild_freshness_from_new_reads',
            'perform_separate_review_before_any_migration_or_activation',
        ],
        'limitations': ['offline_snapshots_only', 'no_merge_or_sql_generated', 'no_remote_ownership_validation',
                        'sqlite_quotas_only_external_credential_budgets_not_compared'],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description='Read-only comparison of local and host SQLite backup snapshots')
    parser.add_argument('--local-snapshot', type=Path, required=True)
    parser.add_argument('--host-snapshot', type=Path, required=True)
    args = parser.parse_args(argv)
    report = review_snapshots(args.local_snapshot, args.host_snapshot)
    print(json.dumps(report, sort_keys=True))
    return 0 if report['status'] == 'snapshots_consistent' else 2


if __name__ == '__main__':
    raise SystemExit(main())
