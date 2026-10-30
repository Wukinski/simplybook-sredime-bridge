import json
import sqlite3
from pathlib import Path

import pytest

from booking_bridge import watchdog_keeper as keeper
from booking_bridge.model import Review


@pytest.fixture
def wal_database(tmp_path):
    path = tmp_path/'synthetic.sqlite'
    with sqlite3.connect(path) as connection:
        assert connection.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal'
        connection.execute('CREATE TABLE application_rows (id INTEGER PRIMARY KEY,value TEXT)')
        connection.execute('INSERT INTO application_rows VALUES(1,?)', ('synthetic',))
    return path


def read_rows(path):
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True) as connection:
        return connection.execute('SELECT * FROM application_rows').fetchall()


def test_missing_database_fails_without_creating_file_or_parent(tmp_path):
    missing = tmp_path/'missing-parent'/'missing.sqlite'
    with pytest.raises(Review, match='existing_database_required'):
        with keeper.open_lease(missing):
            raise AssertionError('Missing database must never be created')
    assert not missing.parent.exists()


def test_keeper_initializes_wal_metadata_after_last_writer_closed(wal_database):
    before = read_rows(wal_database)
    with keeper.open_lease(wal_database) as lease:
        assert lease.isolation_level is None
        assert lease.execute('PRAGMA query_only').fetchone() == (1,)
        assert Path(str(wal_database)+'-shm').is_file()
        assert read_rows(wal_database) == before
        assert read_rows(wal_database) == before
        assert not lease.in_transaction
    assert read_rows(wal_database) == before


def test_mode_ro_and_query_only_forbid_application_writes(wal_database):
    with keeper.open_lease(wal_database) as lease:
        with pytest.raises(sqlite3.OperationalError):
            lease.execute('INSERT INTO application_rows VALUES(2,?)', ('must-not-write',))
        assert not lease.in_transaction
    assert read_rows(wal_database) == [(1, 'synthetic')]


def test_idle_keeper_does_not_block_writes_or_truncate_checkpoint(wal_database):
    with keeper.open_lease(wal_database) as lease:
        with sqlite3.connect(wal_database, isolation_level=None) as writer:
            writer.execute('INSERT INTO application_rows VALUES(2,?)', ('new-synthetic',))
            assert writer.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone() == (0, 0, 0)
            keeper.touch_lease(lease)
            assert not lease.in_transaction
            assert read_rows(wal_database) == [(1, 'synthetic'), (2, 'new-synthetic')]
            writer.execute('INSERT INTO application_rows VALUES(3,?)', ('another-synthetic',))
            assert writer.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone() == (0, 0, 0)
    assert len(read_rows(wal_database)) == 3


def test_helper_executes_only_fixed_select_and_query_only_pragmas(wal_database, monkeypatch):
    statements, options = [], []
    actual_connect = sqlite3.connect
    class LoggedConnection:
        def __init__(self, connection):
            self.connection = connection
        @property
        def in_transaction(self):
            return self.connection.in_transaction
        def execute(self, statement):
            statements.append(statement)
            return self.connection.execute(statement)
        def close(self):
            self.connection.close()
    def connect(database_uri, **kwargs):
        options.append((database_uri, kwargs))
        return LoggedConnection(actual_connect(database_uri, **kwargs))
    monkeypatch.setattr(keeper.sqlite3, 'connect', connect)
    with keeper.open_lease(wal_database) as lease:
        keeper.touch_lease(lease)
    assert options[0][0].endswith('?mode=ro')
    assert options[0][1]['isolation_level'] is None and options[0][1]['timeout'] == 2
    assert set(statements) == {'PRAGMA query_only=ON', 'PRAGMA query_only', keeper.READ_QUERY}


def test_wait_stop_is_interruptible_and_connection_is_closed(wal_database, monkeypatch):
    leases, reports = [], []
    actual_touch = keeper.touch_lease
    def touched(connection):
        leases.append(connection)
        return actual_touch(connection)
    monkeypatch.setattr(keeper, 'touch_lease', touched)
    class Stop:
        def wait(self, seconds):
            assert seconds == 30
            return True
    assert keeper.run_keeper(wal_database, stop=Stop(), report=reports.append) == 0
    assert reports == [{'reader_keeper': True, 'ready': True, 'application_writes': 0},
                       {'reader_keeper': True, 'stopped': True, 'application_writes': 0}]
    with pytest.raises(sqlite3.ProgrammingError):
        leases[0].execute('SELECT 1')


def test_once_probe_is_sanitized_and_does_not_leave_long_read_transaction(wal_database, capsys):
    before = read_rows(wal_database)
    assert keeper.main(['--database', str(wal_database), '--once']) == 0
    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert output[0]['ready'] is True and output[-1]['stopped'] is True
    assert str(wal_database) not in json.dumps(output)
    assert read_rows(wal_database) == before


@pytest.mark.parametrize('body', [b'', b'SYNTHETIC_PRIVATE_INVALID_DATABASE'])
def test_uninitialized_or_corrupt_database_fails_closed_without_private_output(tmp_path, capsys, body):
    path = tmp_path/'private-name.sqlite'
    path.write_bytes(body)
    assert keeper.main(['--database', str(path), '--once']) == 2
    output = capsys.readouterr().out
    assert 'SYNTHETIC_PRIVATE' not in output and str(path) not in output
    assert json.loads(output)['ready'] is False
    assert path.read_bytes() == body


def test_external_read_transaction_is_rejected_instead_of_pin_checkpoint(wal_database):
    with keeper.open_lease(wal_database) as lease:
        lease.execute('BEGIN')
        with pytest.raises(Review, match='transaction_not_allowed'):
            keeper.touch_lease(lease)
