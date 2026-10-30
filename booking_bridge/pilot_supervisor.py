"""Opt-in local occupancy publisher; preparing this module starts no service.

The account facade is unconditionally read-only. Only minimal validated packets
cross pinned SSH. No booking executor, callback lease, native refresh or ACK is
constructed here. Durable failure reservations bound retries across restarts.
"""
import argparse
import json
import math
import signal
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

from provider_assignment.core import Failure, lock
from service_importer.import_services import atomic_json

from .model import HOME, Review, Settings, Temporary, digest
from .pilot_exchange import _scope
from .pilot_publish import SSHReceiver, publish_packet

STATUS_FILE = 'publisher-status.json'
MAX_STATUS_BYTES = 8192
HEARTBEAT_MAX_AGE = 120
PHASES = {'starting', 'capturing', 'publishing', 'waiting', 'backoff', 'stopped', 'blocked'}
REASONS = {'starting', 'publishing', 'published', 'read_unavailable', 'transport_unavailable',
           'capture_deadline_exceeded', 'capture_requires_review', 'publish_requires_review',
           'unexpected_failure', 'retry_budget_exhausted', 'operator_stop', 'operator_reset',
           'clock_invalid', 'attempt_interrupted'}
FIELDS = {'schema_version', 'profile', 'phase', 'reason', 'updated_at', 'started_at',
          'last_success_at', 'oldest_snapshot_at', 'freshness_seconds', 'consecutive_failures',
          'next_attempt_at', 'cycles', 'capture_seconds', 'automatic_booking_sync_enabled',
          'credentials_transferred', 'remote_import_confirmed'}


class _Stopped(Exception):
    pass


class _Deadline(Exception):
    pass


def _number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def read_status(path):
    """Read only; invalid or missing state never becomes a fresh success."""
    try:
        if path.stat().st_size > MAX_STATUS_BYTES:
            raise ValueError()
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError()
                result[key] = value
            return result
        value = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique)
        if (not isinstance(value, dict) or set(value) != FIELDS or
                type(value['schema_version']) is not int or value['schema_version'] != 1 or
                not isinstance(value['profile'], str) or len(value['profile']) != 64 or
                any(c not in '0123456789abcdef' for c in value['profile']) or
                value['phase'] not in PHASES or value['reason'] not in REASONS or
                any(not _number(value[k]) for k in ('updated_at', 'started_at', 'last_success_at',
                    'oldest_snapshot_at', 'freshness_seconds', 'next_attempt_at', 'capture_seconds')) or
                value['freshness_seconds'] <= 0 or
                any(type(value[k]) is not int or value[k] < 0
                    for k in ('consecutive_failures', 'cycles')) or
                any(value[k] is not False for k in ('automatic_booking_sync_enabled',
                    'credentials_transferred', 'remote_import_confirmed')) or
                value['started_at'] > value['updated_at'] or
                value['last_success_at'] > value['updated_at'] or
                value['oldest_snapshot_at'] > value['last_success_at'] or
                bool(value['oldest_snapshot_at']) != bool(value['last_success_at'])):
            raise ValueError()
        return value
    except (OSError, ValueError, TypeError, KeyError):
        raise Review('publisher_status_unavailable_or_invalid') from None


def check_status(path, *, now=None):
    """Process/remote-packet freshness, never proof of native import or booking sync."""
    now = time.time() if now is None else now
    try:
        status = read_status(path)
    except Review:
        return {'healthy': False, 'reason': 'publisher_status_unavailable_or_invalid'}
    reason = 'published'
    if not _number(now) or any(status[k] > now for k in
            ('updated_at', 'started_at', 'last_success_at', 'oldest_snapshot_at')):
        reason = 'publisher_clock_invalid'
    elif status['phase'] in ('stopped', 'blocked'):
        reason = 'publisher_not_running'
    elif now - status['updated_at'] > HEARTBEAT_MAX_AGE:
        reason = 'publisher_heartbeat_stale'
    elif not status['last_success_at'] or not status['oldest_snapshot_at']:
        reason = 'publisher_no_remote_success'
    elif (now - status['last_success_at'] > status['freshness_seconds'] or
          now - status['oldest_snapshot_at'] > status['freshness_seconds']):
        reason = 'publisher_remote_snapshot_stale'
    elif status['phase'] == 'backoff':
        reason = 'publisher_retry_pending'
    return {'healthy': reason == 'published', 'reason': reason,
            'phase': status['phase'], 'consecutive_failures': status['consecutive_failures'],
            'automatic_booking_sync_enabled': False, 'remote_import_confirmed': False}


def validate_options(settings, *, interval=300, max_failures=3, capture_timeout=180):
    _scope(settings)
    freshness = min(settings.snapshot_max_age, settings.schedule_max_age)
    if (type(interval) is not int or not 60 <= interval <= 3600 or
            type(max_failures) is not int or not 1 <= max_failures <= 10 or
            type(capture_timeout) is not int or not 30 <= capture_timeout <= 600 or
            interval + capture_timeout + 60 >= freshness):
        raise Review('invalid_publisher_supervision_bounds')
    return freshness


def profile_id(settings, receiver):
    # No credentials or private URLs enter the status. A changed scope/destination
    # requires explicit operator reset rather than reusing another run's success.
    return digest({'salon': settings.salon, 'employees': settings.employees,
                   'services': settings.services, 'allowed': settings.allowed_employees,
                   'pilot_services': settings.pilot_service_ids,
                   'schedule_services': settings.schedule_service_ids,
                   'horizon': settings.horizon_days, 'freshness': [settings.snapshot_max_age,
                    settings.schedule_max_age], 'host': receiver.host, 'user': receiver.user,
                   'container': receiver.container})


def initial_status(settings, receiver, now):
    return {'schema_version': 1, 'profile': profile_id(settings, receiver),
            'phase': 'starting', 'reason': 'starting', 'updated_at': now, 'started_at': now,
            'last_success_at': 0, 'oldest_snapshot_at': 0,
            'freshness_seconds': min(settings.snapshot_max_age, settings.schedule_max_age),
            'consecutive_failures': 0, 'next_attempt_at': 0, 'cycles': 0,
            'capture_seconds': 0, 'automatic_booking_sync_enabled': False,
            'credentials_transferred': False, 'remote_import_confirmed': False}


def reset_status(settings, receiver, path, *, now=None):
    """Explicit local operator recovery; old evidence remains in SQLite/journals."""
    now = time.time() if now is None else now
    status = initial_status(settings, receiver, now)
    status.update(phase='stopped', reason='operator_reset')
    atomic_json(path, status)


def run_supervisor(settings, store, receiver, *, interval=300, max_failures=3,
                   capture_timeout=180, capture_fn=None, publish_fn=publish_packet,
                   gateway_factory=None, stop=None, clock=time.time, monotonic=time.monotonic,
                   wait=None, report=None):
    """Run under the caller's snapshot lock; every retry captures a new generation.

    An attempt is reserved on disk BEFORE any reads. A killed/restarted process
    retains its failure count and cooldown. Terminal errors require explicit
    reset; service-manager restarts cannot silently clear the retry budget.
    """
    validate_options(settings, interval=interval, max_failures=max_failures,
                     capture_timeout=capture_timeout)
    if capture_fn is None:
        from .pilot_snapshot import capture_packet
        capture_fn = capture_packet
    stop = stop or threading.Event()
    wait = wait or stop.wait
    path = settings.state / STATUS_FILE
    status = read_status(path) if path.exists() else initial_status(settings, receiver, clock())
    if status['profile'] != profile_id(settings, receiver):
        raise Review('publisher_profile_changed_reset_required')
    if status['phase'] == 'blocked':
        raise Review('publisher_operator_reset_required')
    if any(status[k] > clock() for k in ('updated_at', 'last_success_at', 'oldest_snapshot_at')):
        raise Review('publisher_clock_invalid')
    status['started_at'] = clock()
    if status['consecutive_failures']:
        # A crash during a reserved attempt also remains an unhealthy retry.
        previous_reason = status['reason'] if status['phase'] == 'backoff' else 'attempt_interrupted'
        status.update(phase='backoff', reason=previous_reason)
    else:
        status.update(phase='starting', reason='starting')

    last_report = None

    def write(phase=None, reason=None):
        nonlocal last_report
        if phase:
            status['phase'] = phase
        if reason:
            status['reason'] = reason
        now = clock()
        clock_invalid = not _number(now) or now < status['updated_at']
        if clock_invalid:
            status.update(phase='blocked', reason='clock_invalid')
        else:
            status['updated_at'] = now
        atomic_json(path, status)
        event = {'phase': status['phase'], 'reason': status['reason'],
                 'cycles': status['cycles'], 'consecutive_failures': status['consecutive_failures']}
        if report and event != last_report:
            # Only fixed fields/reasons; never render exception/provider text.
            report(event)
            last_report = event
        if clock_invalid:
            raise Review('publisher_clock_invalid')

    def sleep_until(deadline):
        # Wall-clock changes must not extend an already reserved wait forever.
        until = monotonic() + max(0, deadline - clock())
        while monotonic() < until:
            if stop.is_set():
                raise _Stopped()
            write()
            if wait(max(0, min(5, until - monotonic()))):
                raise _Stopped()

    deadline = None
    def checkpoint():
        if stop.is_set():
            raise _Stopped()
        if deadline is not None and monotonic() >= deadline:
            raise _Deadline()
        write()

    if gateway_factory is None:
        def gateway_factory(before_read):
            from provider_assignment.client import Client
            from .diagnostics import ReadOnlyGateway
            return ReadOnlyGateway(settings, Client(timeout=(3, 5), read_attempts=1), before_read)

    gateway = None
    try:
        if status['consecutive_failures'] >= max_failures:
            write('blocked', 'retry_budget_exhausted')
            return 2
        write()
        sleep_until(status['next_attempt_at'])
        while not stop.is_set():
            started = monotonic()
            status['consecutive_failures'] += 1
            status['cycles'] += 1
            # Reserve the cooldown too: a crash cannot trigger immediate reads.
            status['next_attempt_at'] = clock() + interval
            write('capturing', 'starting')
            stage = 'capture'
            try:
                deadline = monotonic() + capture_timeout
                if gateway is None:
                    gateway = gateway_factory(checkpoint)
                checkpoint()
                capture, packet = capture_fn(settings, store, gateway, clock=clock)
                checkpoint()
                stage = 'publish'
                write('publishing', 'publishing')
                # publish_packet validates source timestamps and receipt itself.
                publish_fn(settings, packet, receiver, now=clock())
                status.update(last_success_at=clock(),
                              oldest_snapshot_at=min(e['updated'] for e in packet['entries']),
                              capture_seconds=capture['capture_seconds'], consecutive_failures=0)
                write('waiting', 'published')
            except _Deadline:
                failure = 'capture_deadline_exceeded'
            except Temporary:
                failure = 'read_unavailable'
            except Review as exc:
                if stage == 'publish' and str(exc) == 'pilot_publish_transport_unavailable':
                    failure = 'transport_unavailable'
                else:
                    write('blocked', stage + '_requires_review')
                    return 2
            except (_Stopped, KeyboardInterrupt):
                raise
            except Exception:
                write('blocked', 'unexpected_failure')
                return 2
            else:
                # Use monotonic elapsed time for cadence; no catch-up bursts.
                delay = max(10, interval - (monotonic() - started))
                status['next_attempt_at'] = clock() + delay
                write()
                sleep_until(status['next_attempt_at'])
                continue
            if status['consecutive_failures'] >= max_failures:
                write('blocked', 'retry_budget_exhausted')
                return 2
            delay = min(900, max(interval, 60 * 2 ** (status['consecutive_failures'] - 1)))
            status['next_attempt_at'] = clock() + delay
            write('backoff', failure)
            sleep_until(status['next_attempt_at'])
        write('stopped', 'operator_stop')
        return 0
    except (_Stopped, KeyboardInterrupt):
        write('stopped', 'operator_stop')
        return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--run', action='store_true')
    modes.add_argument('--check', action='store_true')
    modes.add_argument('--reset-failures', action='store_true')
    parser.add_argument('--read-only', action='store_true')
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--host', default='169.58.118.33')
    parser.add_argument('--identity', type=Path, default=HOME/'secrets/vps_pilot_ed25519')
    parser.add_argument('--known-hosts', type=Path, default=HOME/'secrets/vps_known_hosts')
    parser.add_argument('--container', default='booking-bridge-pilot-worker-1')
    parser.add_argument('--interval', type=int, default=300)
    parser.add_argument('--max-failures', type=int, default=3)
    parser.add_argument('--capture-timeout', type=int, default=180)
    args = parser.parse_args(argv)
    if args.check:
        result = check_status(args.state / STATUS_FILE)
        print(json.dumps(result))
        return 0 if result['healthy'] else 2
    try:
        if not args.read_only or not args.config or not args.config.is_file():
            raise Review('explicit_read_only_publisher_configuration_required')
        if args.env_file:
            from dotenv import load_dotenv
            if not args.env_file.is_file():
                raise Review('publisher_environment_file_missing')
            load_dotenv(args.env_file)
        settings = replace(Settings.load(args.config, read_only=True, isolated_profile=True),
                           state=args.state.resolve())
        validate_options(settings, interval=args.interval, max_failures=args.max_failures,
                         capture_timeout=args.capture_timeout)
        receiver = SSHReceiver(args.host, args.identity, args.known_hosts, container=args.container)
        receiver.command()
        # Same lock as the finite publisher: they cannot capture concurrently.
        with lock(settings.state / 'pilot-read-snapshot.lock'):
            if args.reset_failures:
                reset_status(settings, receiver, settings.state / STATUS_FILE)
                print(json.dumps({'reset': True, 'started': False}))
                return 0
            from .store import Store
            stop = threading.Event()
            def request_stop(signum, frame):
                stop.set()
            previous = {}
            for name in ('SIGINT', 'SIGTERM', 'SIGBREAK'):
                signum = getattr(signal, name, None)
                if signum is not None:
                    previous[signum] = signal.signal(signum, request_stop)
            try:
                return run_supervisor(settings, Store(settings.state/'bridge.sqlite'), receiver,
                    interval=args.interval, max_failures=args.max_failures,
                    capture_timeout=args.capture_timeout, stop=stop,
                    report=lambda row: print(json.dumps(row), flush=True))
            finally:
                for signum, handler in previous.items():
                    signal.signal(signum, handler)
    except (Review, Failure):
        print(json.dumps({'stopped': True, 'reason': 'publisher_operator_review_required'}))
        return 2
    except Exception:
        print(json.dumps({'stopped': True, 'reason': 'publisher_unexpected_failure'}))
        return 2


if __name__ == '__main__':
    sys.exit(main())
