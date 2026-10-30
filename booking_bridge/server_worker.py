"""Explicitly gated server worker; never enables production or installs services."""
import argparse
import json
import os
import signal
import threading
import time
from dataclasses import replace
from pathlib import Path

from provider_assignment.core import Failure, lock

from .model import Review, Settings, Uncertain


def run_loop(settings, store, worker, gateway, *, clock=time.time, sleep=time.sleep,
             stop=None, max_iterations=None):
    """Share the proven worker/scheduler instead of introducing a second executor."""
    from .scheduler import Scheduler
    from .recovery import recovery_start_allowed
    from .production_readiness import require_production_evidence
    if not recovery_start_allowed(store.path):
        raise Review('restored_state_requires_reconciliation')
    require_production_evidence(settings)
    if settings.mode == 'simulation':
        read_gateway = gateway
    else:
        from .diagnostics import ReadOnlyGateway
        from provider_assignment.client import Client
        def prioritize_bookings():
            store.put('heartbeat', True)
            worker.once()
            scheduler.recheck_feeds(clock())
            scheduler.refresh_source(clock())
        read_gateway = ReadOnlyGateway(settings,
            Client(timeout=(2, 4), read_attempts=1), before_read=prioritize_bookings)
    scheduler = Scheduler(settings, store, read_gateway, worker, clock=clock)
    store.recover()
    iterations, last_tick = 0, None
    while stop is None or not stop.is_set():
        handled = worker.once()
        if last_tick is None or clock() - last_tick >= 1:
            scheduler.tick()
            last_tick = clock()
        iterations += 1
        if max_iterations is not None and iterations >= max_iterations:
            break
        if not handled:
            if stop is None:
                sleep(1)
            else:
                stop.wait(1)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--readiness', type=Path, required=True)
    parser.add_argument('--state', type=Path)
    args = parser.parse_args(argv)
    try:
        os.environ['BRIDGE_PRODUCTION_READINESS_FILE'] = str(args.readiness.resolve())
        settings = Settings.load(args.config, read_only=True, isolated_profile=True)
        if args.state:
            settings = replace(settings, state=args.state.resolve())
        if settings.mode != 'production':
            raise Review('explicit_production_profile_required')
        from .preflight import inspect
        if not inspect(settings, 'production', readiness_path=args.readiness)['configuration_ready']:
            raise Review('production_preflight_blocked')
        with lock(settings.state / 'worker.lock'):
            # Repeat after taking the singleton lock before recovering queued work.
            if not inspect(settings, 'production', readiness_path=args.readiness)['configuration_ready']:
                raise Review('production_preflight_blocked')
            from .store import Store
            from .simplybook import Gateway
            from .worker import Worker
            store = Store(settings.state/'bridge.sqlite')
            gateway = Gateway(settings)
            worker = Worker(settings, store, gateway)
            stop, previous = threading.Event(), {}
            def request_stop(signum, frame):
                stop.set()
            for name in ('SIGINT', 'SIGTERM', 'SIGBREAK'):
                signum = getattr(signal, name, None)
                if signum is not None:
                    previous[signum] = signal.signal(signum, request_stop)
            try:
                print(json.dumps({'worker': 'starting', 'mode': 'production'}), flush=True)
                run_loop(settings, store, worker, gateway, stop=stop)
                return 0
            finally:
                for signum, handler in previous.items():
                    signal.signal(signum, handler)
    except (Review, Failure, Uncertain):
        print(json.dumps({'stopped': True, 'reason': 'server_worker_review_required'}))
        return 2
    except KeyboardInterrupt:
        print(json.dumps({'stopped': True, 'reason': 'operator_stop'}))
        return 0
    except Exception:
        print(json.dumps({'stopped': True, 'reason': 'server_worker_unavailable'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
