"""Check a NEW held candidate against captured ingress and proven ownership.

All inputs must be standalone SQLite snapshots. This is a read-only preservation
check, not a migration, reconciliation approval, freshness assertion, or start
command. A passing report never releases a recovery hold or enables production.
"""
import argparse
from collections import Counter
import json
from pathlib import Path

from .model import digest
from .recovery import MARKER_SUFFIX, MAX_DATABASE_BYTES
from .state_review import SnapshotInvalid, _read_snapshot


def _rows(snapshot, table):
    return Counter(digest(row) for row in snapshot.tables[table])


def _contains(actual, expected):
    return not (expected - actual)


def review_cutover(current_host, candidate, owned_baseline, quota_origin):
    """Return only hashes, counts, and fixed codes; never expose rows or paths.

    ``owned_baseline`` is the previously reviewed, reconciled held stage with
    opaque client/booking ownership. ``quota_origin`` is its original execution
    snapshot, whose rate rows must be appended to the fresh host without deduping
    overlapping windows. Neither argument is automatically trusted as a remote
    fact: the operator must also review their existing provenance/readbacks.
    """
    report = {'schema_version': 1, 'read_only': True, 'inputs_modified': False,
              'preservation_passed': False, 'activation_ready': False,
              'worker_start_allowed': False, 'promotion_performed': False,
              'external_validation_performed': False, 'snapshots': {}, 'checks': []}
    snapshots = {}
    for role, path in (('current_host', current_host), ('candidate', candidate),
                       ('owned_baseline', owned_baseline), ('quota_origin', quota_origin)):
        try:
            path = Path(path)
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_DATABASE_BYTES:
                raise SnapshotInvalid('snapshot_missing_or_unsupported')
            snap = _read_snapshot(path)
            snapshots[role] = snap
            report['snapshots'][role] = snap.summary()
        except SnapshotInvalid as exc:
            report['snapshots'][role] = {'valid': False, 'reason': str(exc)}
        except (OSError, ValueError, TypeError):
            report['snapshots'][role] = {'valid': False, 'reason': 'snapshot_unreadable_or_invalid'}
    if len(snapshots) != 4:
        report['checks'].append({'code': 'all_standalone_snapshots_valid', 'ok': False})
        return report
    host, staged, baseline, quota = (snapshots[key] for key in
                                    ('current_host', 'candidate', 'owned_baseline', 'quota_origin'))

    def check(code, ok):
        report['checks'].append({'code': code, 'ok': bool(ok)})

    check('all_standalone_snapshots_valid', True)
    for table in ('events', 'booking_heads'):
        # Preserve every host field, including receipt state/reason and attempts.
        check('current_host_' + table + '_unchanged', _rows(staged, table) == _rows(host, table))
    for table in ('links', 'intents', 'clients', 'source_bindings'):
        check('current_host_' + table + '_preserved', _contains(_rows(staged, table), _rows(host, table)))
        check('historical_owned_' + table + '_preserved', _contains(_rows(staged, table), _rows(baseline, table)))
    for table in ('issues', 'feed_health', 'refresh', 'availability_observations'):
        check('current_host_' + table + '_unchanged', _rows(staged, table) == _rows(host, table))
    host_cache = {key: row for key, row in host.cache.items() if key != 'recovery-hold'}
    check('host_cache_values_and_freshness_preserved', all(staged.cache.get(key) == row
                                                         for key, row in host_cache.items()))
    applied = {key: row for key, row in baseline.cache.items() if key.startswith('applied:')}
    check('historical_applied_baselines_and_timestamps_preserved', bool(applied) and all(
        staged.cache.get(key) == row for key, row in applied.items()))
    required_rates = _rows(host, 'rates') + _rows(quota, 'rates')
    check('both_quota_windows_retained_without_deduplication', _contains(_rows(staged, 'rates'), required_rates))
    hold = staged.cache.get('recovery-hold', {}).get('decoded')
    check('embedded_recovery_hold_retained', isinstance(hold, dict) and
          hold.get('remote_reconciliation_required') is True and
          hold.get('budget_reconciliation_required') is True and
          hold.get('worker_start_allowed') is False)
    # Do not reopen a WAL-header snapshot with ordinary mode=ro here: SQLite can
    # create -wal/-shm sidecars despite the read-only SQL connection. The worker's
    # recovery gate unconditionally blocks either an embedded hold or a marker.
    marker = Path(str(candidate) + MARKER_SUFFIX)
    check('recovery_gate_blocks_worker', 'recovery-hold' in staged.cache or marker.exists() or marker.is_symlink())
    check('historical_ownership_is_nonempty', any(row['target'] is not None for row in baseline.links.values()))
    check('uncertain_remote_intents_absent', all(row['state'] == 'done' for row in staged.intents.values()))
    check('conflicted_heads_absent', not any(row['conflicted'] for row in staged.heads.values()))
    report['preservation_passed'] = all(row['ok'] for row in report['checks'])
    report['operator_review_counts'] = {
        'queued_or_working_receipts': sum(row['state'] in ('queued', 'working') for row in staged.events.values()),
        'dead_or_review_receipts': sum(row['state'] in ('dead', 'review') for row in staged.events.values()),
        'open_incidents': sum(row['resolved'] == 0 for row in staged.tables['issues']),
        'source_feed_backoff_or_stopped': sum(row['state'] in ('backoff', 'stopped') for row in staged.tables['feed_health'])}
    report['remaining_requirements'] = [
        'verify_snapshot_capture_lineage_and_freshness_separately',
        'authoritative_remote_ownership_and_uncertain_intent_readbacks',
        'reconcile_external_rest_budget_files_and_floors',
        'review_every_new_receipt_without_blind_backlog_replay',
        'refresh_calendar_snapshots_without_fabricating_timestamps',
        'complete_profile_calendar_subscription_and_production_evidence_review',
        'explicit_separate_database_promotion_and_hold_release_review']
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('current-host', 'candidate', 'owned-baseline', 'quota-origin'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args(argv)
    report = review_cutover(args.current_host, args.candidate, args.owned_baseline, args.quota_origin)
    print(json.dumps(report, sort_keys=True))
    return 0 if report['preservation_passed'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
