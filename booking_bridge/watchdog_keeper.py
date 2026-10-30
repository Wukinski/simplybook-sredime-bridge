"""Keep SQLite WAL reader metadata available for the isolated read-only collector.

Only this trusted helper receives a writable volume for SQLite's WAL/SHM
metadata. The existing application database itself opens mode=ro/query_only.
There are no application writes, schema repairs, account clients or networking.
"""
import argparse
import json
import signal
import sqlite3
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

from .model import Review

READ_QUERY = 'SELECT 1 FROM sqlite_master LIMIT 1'


def touch_lease(connection):
    """Finish one short read in autocommit mode; never pin a checkpoint snapshot."""
    if connection.in_transaction:
        raise Review('watchdog_keeper_transaction_not_allowed')
    try:
        rows = connection.execute(READ_QUERY).fetchall()
    except sqlite3.Error:
        raise Review('watchdog_keeper_read_unavailable') from None
    if not rows:
        raise Review('watchdog_keeper_database_uninitialized')
    if connection.in_transaction:
        raise Review('watchdog_keeper_transaction_not_allowed')


@contextmanager
def open_lease(database):
    """Open only an existing database, then hold its initialized reader handle."""
    database = Path(database)
    if database.is_symlink() or not database.is_file():
        raise Review('watchdog_keeper_existing_database_required')
    connection = None
    try:
        connection = sqlite3.connect(database.resolve().as_uri()+'?mode=ro', uri=True,
                                     isolation_level=None, timeout=2)
        connection.execute('PRAGMA query_only=ON')
        if connection.execute('PRAGMA query_only').fetchone()[0] != 1:
            raise Review('watchdog_keeper_read_only_required')
        touch_lease(connection)
        yield connection
    except sqlite3.Error:
        raise Review('watchdog_keeper_read_unavailable') from None
    finally:
        if connection is not None:
            connection.close()


def run_keeper(database, *, interval=30, stop=None, once=False, report=None):
    if type(interval) is not int or not 1 <= interval <= 300 or type(once) is not bool:
        raise Review('watchdog_keeper_interval_invalid')
    stop = stop or threading.Event()
    with open_lease(database) as connection:
        if report:
            report({'reader_keeper': True, 'ready': True, 'application_writes': 0})
        if not once:
            while not stop.wait(interval):
                touch_lease(connection)
    if report:
        report({'reader_keeper': True, 'stopped': True, 'application_writes': 0})
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, type=Path)
    parser.add_argument('--interval', type=int, default=30)
    parser.add_argument('--once', action='store_true', help='Probe availability and close; does not keep a reader alive')
    args = parser.parse_args(argv)
    stop = threading.Event()
    previous = {}
    def request_stop(signum, frame):
        stop.set()
    try:
        for name in ('SIGINT', 'SIGTERM', 'SIGBREAK'):
            signum = getattr(signal, name, None)
            if signum is not None:
                previous[signum] = signal.signal(signum, request_stop)
        return run_keeper(args.database, interval=args.interval, stop=stop, once=args.once,
                          report=lambda row: print(json.dumps(row), flush=True))
    except Review as error:
        print(json.dumps({'ready': False, 'reason': str(error), 'application_writes': 0}))
        return 2
    except Exception:
        print(json.dumps({'ready': False, 'reason': 'watchdog_keeper_unavailable', 'application_writes': 0}))
        return 2
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


if __name__ == '__main__':
    sys.exit(main())
