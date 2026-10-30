"""Explicit read-only availability capture while the booking worker is simulation.

Used for the small availability-import pilot before live booking synchronization
is enabled. No source polling, refresh POSTs, booking mutations or inbox processing.
"""
import argparse
import json
import tempfile
import time
from pathlib import Path

from provider_assignment.core import lock
from .calendar import make_feed
from .diagnostics import ReadOnlyGateway
from .model import Review, Settings, affected_sources
from .pilot_exchange import _scope, build_packet, import_packet
from .scheduler import Scheduler
from .store import Store
from .worker import matches


class NoWorker:
    def once(self, *args, **kwargs):
        raise Review('snapshot_job_must_not_process_bookings')


class CaptureView:
    """Fresh staged data with the real destination's ownership and safety fences."""
    def __init__(self, staged, destination, employee):
        self.staged, self.destination = staged, destination
        self.keys = {'bookings', 'buffers', 'schedule:' + employee}

    def get(self, key):
        return self.staged.get(key) if key in self.keys else self.destination.get(key)

    def rows(self, sql, args=()):
        return self.destination.rows(sql, args)


def _review_owned_bookings(settings, store, gateway, owned, bookings, clock):
    """Stage reads without losing the destination's ownership drift protection.

    Baselines predate the account read. check_drift compares them again in the
    destination transaction, so a concurrent executor cannot have its new state
    cleared by older evidence. No booking, link, intent or inbox row is changed.
    """
    by_id = {booking['id']: booking for booking in bookings}
    for link, applied in owned:
        # Keep the scheduler's compatibility with historical ownership records
        # that have no applied snapshot; exclusion alone never infers identity.
        if not applied:
            continue
        actual = by_id.get(link['target'])
        if actual is None:
            # Absence from a rolling inventory is not evidence of cancellation.
            actual = gateway.detail(link['target'])
        canceled = actual.get('status') == 'canceled'
        drifted = canceled != (link['state'] == 'canceled') or (not canceled and not matches(actual, applied))
        snapshot = json.loads(link['snapshot']) if link['snapshot'] else {}
        scope = affected_sources(settings, snapshot,
            provider_ids=(applied.get('provider_id'), actual.get('provider_id')))
        if not store.check_drift(link, applied, drifted, scope, clock()):
            raise Review('pilot_owned_booking_changed_during_capture')


def capture_packet(settings, store, gateway, clock=time.time):
    """Stage a full read generation; a failed read never freshens published data."""
    employee, _, _ = _scope(settings)
    started = clock()
    owned = [(link, store.get('applied:' + link['booking'])[0])
             for link in store.rows('SELECT * FROM links WHERE target IS NOT NULL')]
    # This also isolates old in-progress schedule jobs and their retry backoff.
    # The account gateway still shares the existing persistent transport quota.
    with tempfile.TemporaryDirectory(prefix='pilot-capture-', dir=store.path.parent) as directory:
        staged = Store(Path(directory) / 'capture.sqlite')
        scheduler = Scheduler(settings, staged, gateway, NoWorker(), clock=clock)
        scheduler.snapshot_bookings(clock())
        scheduler.snapshot_buffers(clock())
        staged.put('schedule-request:' + employee, True, clock())
        # Max 60-day horizon, one employee: reference + at most ten calendar weeks.
        for _ in range(12):
            scheduler.schedule_step(clock())
            if staged.get('schedule:' + employee)[1] >= staged.get('schedule-request:' + employee)[1]:
                break
        else:
            raise Review('pilot_schedule_capture_incomplete')
        _review_owned_bookings(settings, store, gateway, owned, staged.get('bookings')[0], clock)
        packet = build_packet(settings, CaptureView(staged, store, employee), now=clock())
    accepted = import_packet(settings, store, packet, now=clock())
    return {'read_only_account_access': True, 'account_mutations': 0,
            'booking_worker_mode': settings.mode, 'source_employee_id': employee,
            'outbound_occupancy_events': accepted['occupancy_events'],
            'feed_version': accepted['feed_version'],
            'capture_seconds': round(clock() - started, 3),
            'remote_import_confirmed': False}, packet


def capture(settings, store, gateway, clock=time.time):
    return capture_packet(settings, store, gateway, clock)[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--read-only', action='store_true', required=True)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--state', type=Path)
    args = parser.parse_args()
    settings = Settings.load(args.config, read_only=True, isolated_profile=True)
    if args.state:
        from dataclasses import replace
        settings = replace(settings, state=args.state)
    with lock(settings.state / 'pilot-read-snapshot.lock'):
        report = capture(settings, Store(settings.state / 'bridge.sqlite'), ReadOnlyGateway(settings))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
