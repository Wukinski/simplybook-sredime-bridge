"""Store-only pilot monitoring; received source events are never consumed here.

The public API owns durable webhook receipt. This process only maintains its
heartbeat and local queue/incident health while a separate, scoped executor is
prepared. It does not construct an account gateway, a worker or a scheduler, and
does not send alerts or make any other network requests.
"""
import argparse
import json
import time

from provider_assignment.core import Failure, lock

from .calendar import make_feed
from .model import Review, Settings
from .store import Store

STALE_FEED_REASONS = ('booking_snapshot_stale', 'schedule_snapshot_stale', 'service_buffers_stale')


def _positive_id(value):
    return type(value) is int and value > 0


def _validate_profile(settings):
    if (settings.mode != 'simulation' or settings.reads_enabled is not False or
            settings.approvals.get('pilot_scope_reviewed') is not True):
        raise Review('explicit_receiver_pilot_profile_required')
    employees = settings.allowed_employees
    if (not isinstance(employees, list) or len(employees) != 1 or
            not isinstance(employees[0], str) or not employees[0] or
            not isinstance(settings.employees, dict) or
            set(settings.employees) != set(employees) or
            not isinstance(settings.employees[employees[0]], dict) or
            not _positive_id(settings.employees[employees[0]].get('id'))):
        raise Review('single_employee_receiver_scope_required')
    services = settings.services
    allowed = settings.pilot_service_ids
    if (not isinstance(services, dict) or not services or
            not isinstance(allowed, list) or not allowed or
            any(not _positive_id(value) for value in allowed) or
            len(set(allowed)) != len(allowed) or
            any(not isinstance(source, str) or not source or
                not isinstance(row, dict) or not _positive_id(row.get('id')) or
                row['id'] not in allowed for source, row in services.items()) or
            {row['id'] for row in services.values()} != set(allowed)):
        raise Review('explicit_test_services_receiver_scope_required')


def monitor_once(settings, store, now=None):
    """Update local health only, preserving every event, link and remote intent."""
    _validate_profile(settings)
    now = time.time() if now is None else now
    # Keep the normal monitor's ten-second backlog threshold visible. Delayed
    # execution is an incident; a healthy receiver is not proof of synchronization.
    store.put('heartbeat', True, now)
    aged = store.rows(
        "SELECT COUNT(*) AS n FROM events WHERE state IN ('queued','working') AND received<?",
        (now - 10,))[0]['n']
    if aged:
        store.issue('queue-age', 'webhook_processing_delayed', now)
    else:
        store.execute("UPDATE issues SET resolved=1 WHERE key='queue-age'")
    # A finite local publisher may stop while the receiver remains alive. Validate
    # only cached data so readiness fails promptly without any provider request.
    for employee in settings.allowed_employees:
        key = 'feed:' + employee
        try:
            make_feed(settings, store, employee, now)
        except Review as error:
            existing = store.rows('SELECT reason,resolved FROM issues WHERE key=?', (key,))
            if (not existing or existing[0]['resolved'] or
                    existing[0]['reason'] in STALE_FEED_REASONS):
                store.issue(key, str(error), now)
        else:
            # Freshness must not resolve a manual hold or an unrelated safety
            # incident stored under the same feed key. Match import_packet policy.
            store.execute("UPDATE issues SET resolved=1 WHERE key=? AND reason IN "
                          "('booking_snapshot_stale','schedule_snapshot_stale','service_buffers_stale')", (key,))
    issues = store.rows('SELECT COUNT(*) AS n FROM issues WHERE resolved=0')[0]['n']
    store.put('health', {'open_issues': issues, 'old_queued': aged}, now)
    return {'receiver_only': True, 'mode': settings.mode, 'reads_enabled': False,
            'old_queued': aged, 'open_issues': issues, 'events_processed': 0,
            'account_reads': 0, 'account_mutations': 0}


def _interval(value):
    try:
        seconds = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError('interval must be an integer from 1 to 60') from None
    if not 1 <= seconds <= 60:
        raise argparse.ArgumentTypeError('interval must be an integer from 1 to 60')
    return seconds


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once', action='store_true', help='Monitor once and exit without processing the inbox')
    parser.add_argument('--interval', type=_interval, default=1, help='Local check interval in seconds (1-60)')
    args = parser.parse_args(argv)
    settings = Settings.load(read_only=True)
    # Reject the profile before Store initialization/migrations or lock creation.
    _validate_profile(settings)
    with lock(settings.state / 'worker.lock'):
        store = Store(settings.state / 'bridge.sqlite')
        if not args.once:
            print('Pilot receiver monitor started; inbox processing disabled.', flush=True)
        while True:
            result = monitor_once(settings, store)
            if args.once:
                print(json.dumps(result))
                return 0
            time.sleep(args.interval)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('Receiver monitor stopped; queued events and intents are retained.')
    except (Review, Failure) as exc:
        print('Stopped safely: ' + str(exc))
        raise SystemExit(2)
