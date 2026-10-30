import json
import threading
from pathlib import Path

import pytest

from booking_bridge import pilot_supervisor as supervisor
from booking_bridge.model import Review, Settings, Temporary
from booking_bridge.pilot_publish import SSHReceiver
from booking_bridge.tests.test_pilot_exchange import scoped, seed


class Timer:
    def __init__(self, now):
        self.now = now
        self.waits = []

    def clock(self):
        return self.now

    def wait(self, delay):
        self.waits.append(delay)
        self.now += delay
        return False


@pytest.fixture
def runtime(scoped, store, now, tmp_path):
    receiver = SSHReceiver('synthetic.example.test', tmp_path/'key', tmp_path/'hosts')
    timer, stop = Timer(now), threading.Event()
    calls = []

    def capture(settings, store, gateway, clock):
        from booking_bridge.pilot_exchange import build_packet
        calls.append('capture')
        seed(settings, store, clock())
        return {'capture_seconds': 1}, build_packet(settings, store, now=clock())

    def publish(settings, packet, receiver, now):
        calls.append('publish')
        return {'accepted': True}

    def run(**kwargs):
        options = dict(capture_fn=capture, publish_fn=publish,
                       gateway_factory=lambda before_read: None, stop=stop,
                       clock=timer.clock, monotonic=timer.clock, wait=timer.wait)
        options.update(kwargs)
        return supervisor.run_supervisor(scoped, store, receiver, **options)

    return scoped, receiver, timer, stop, calls, run


def status_path(settings):
    return settings.state / supervisor.STATUS_FILE


def test_success_uses_remote_receipt_and_preserves_snapshot_times(runtime):
    settings, receiver, timer, stop, calls, run = runtime
    observations = []

    def report(row):
        if row['phase'] == 'waiting':
            observations.append(supervisor.check_status(status_path(settings), now=timer.now))
            stop.set()

    assert run(report=report) == 0
    assert calls == ['capture', 'publish']
    status = supervisor.read_status(status_path(settings))
    assert observations[0]['healthy'] is True
    assert status['last_success_at'] == status['oldest_snapshot_at'] == timer.now
    assert status['phase'] == 'stopped'
    assert supervisor.check_status(status_path(settings), now=timer.now)['healthy'] is False
    assert status['automatic_booking_sync_enabled'] is False
    assert status['credentials_transferred'] is False
    assert status['remote_import_confirmed'] is False


def test_failed_capture_never_publishes_and_retries_are_bounded(runtime):
    settings, receiver, timer, stop, calls, run = runtime

    def failed_capture(*args, **kwargs):
        calls.append('failed_capture')
        raise Temporary('private-provider-payload')

    reports = []
    assert run(capture_fn=failed_capture, report=reports.append) == 2
    assert calls == ['failed_capture'] * 3
    status = supervisor.read_status(status_path(settings))
    assert status['phase'] == 'blocked' and status['consecutive_failures'] == 3
    assert status['last_success_at'] == status['oldest_snapshot_at'] == 0
    assert 'private-provider-payload' not in json.dumps(reports) + status_path(settings).read_text()
    with pytest.raises(Review, match='operator_reset_required'):
        run(capture_fn=failed_capture)
    assert calls == ['failed_capture'] * 3


def test_transport_failure_recaptures_instead_of_replaying_cached_packet(runtime):
    settings, receiver, timer, stop, calls, run = runtime
    packets = []

    def publish(settings, packet, receiver, now):
        packets.append(packet)
        if len(packets) == 1:
            raise Review('pilot_publish_transport_unavailable')
        stop.set()

    assert run(publish_fn=publish) == 0
    assert len(packets) == 2
    assert packets[1]['captured_at'] > packets[0]['captured_at']
    assert packets[1]['entries'][0]['updated'] > packets[0]['entries'][0]['updated']
    assert supervisor.read_status(status_path(settings))['consecutive_failures'] == 0


@pytest.mark.parametrize('error', [Review('pilot_publish_receipt_mismatch'),
                                 Review('pilot_publish_remote_rejected'),
                                 RuntimeError('secret=https://private.invalid/token')])
def test_unknown_receipt_or_unexpected_error_stops_without_retry_or_private_text(runtime, error):
    settings, receiver, timer, stop, calls, run = runtime
    reports = []

    def publish(*args, **kwargs):
        calls.append('failed_publish')
        raise error

    assert run(publish_fn=publish, report=reports.append) == 2
    assert calls == ['capture', 'failed_publish']
    status = supervisor.read_status(status_path(settings))
    assert status['last_success_at'] == 0
    assert status['phase'] == 'blocked'
    assert str(error) not in json.dumps(reports) + status_path(settings).read_text()


def test_failure_after_success_keeps_previous_remote_freshness(runtime):
    settings, receiver, timer, stop, calls, run = runtime
    publications = []

    def publish(settings, packet, receiver, now):
        publications.append(now)
        if len(publications) > 1:
            raise Review('pilot_publish_receipt_mismatch')

    assert run(publish_fn=publish) == 2
    assert len(publications) == 2
    status = supervisor.read_status(status_path(settings))
    assert status['last_success_at'] == status['oldest_snapshot_at'] == publications[0]
    assert status['last_success_at'] < timer.now


def test_restart_preserves_crash_reservation_and_cooldown(runtime):
    settings, receiver, timer, stop, calls, run = runtime

    def killed(*args, **kwargs):
        raise SystemExit(99)

    with pytest.raises(SystemExit):
        run(capture_fn=killed)
    status = supervisor.read_status(status_path(settings))
    assert status['phase'] == 'capturing' and status['consecutive_failures'] == 1
    resume_at = status['next_attempt_at']
    waited = []

    def wait(delay):
        waited.append(delay)
        assert not calls
        stop.set()
        return True

    assert run(wait=wait) == 0
    assert waited and resume_at > timer.now
    assert supervisor.read_status(status_path(settings))['consecutive_failures'] == 1


def test_deadline_is_checked_at_read_boundaries_and_stops_capture(runtime):
    settings, receiver, timer, stop, calls, run = runtime
    callbacks = []

    def capture(*args, **kwargs):
        calls.append('capture')
        timer.now += 181
        callbacks[0]()
        raise AssertionError('deadline must stop here')

    assert run(capture_fn=capture,
               gateway_factory=lambda before_read: callbacks.append(before_read),
               max_failures=1) == 2
    assert calls == ['capture']
    assert supervisor.read_status(status_path(settings))['reason'] == 'retry_budget_exhausted'


def test_operator_stop_interrupts_backoff(runtime):
    settings, receiver, timer, stop, calls, run = runtime

    def capture(*args, **kwargs):
        raise Temporary('read_unavailable')

    assert run(capture_fn=capture, wait=lambda seconds: True) == 0
    assert supervisor.read_status(status_path(settings))['phase'] == 'stopped'


@pytest.mark.parametrize('change', [{'updated_at': -1}, {'phase': []},
                                  {'consecutive_failures': True}, {'last_success_at': float('nan')},
                                  {'credentials_transferred': True}, {'raw_payload': 'private'}])
def test_invalid_status_fails_closed_without_rewriting(runtime, change):
    settings, receiver, timer, stop, calls, run = runtime
    value = supervisor.initial_status(settings, receiver, timer.now)
    value.update(change)
    status_path(settings).write_text(json.dumps(value))
    before = status_path(settings).read_bytes()
    assert supervisor.check_status(status_path(settings), now=timer.now)['healthy'] is False
    with pytest.raises(Review):
        run()
    assert not calls and status_path(settings).read_bytes() == before


@pytest.mark.parametrize('change,reason', [
    ({'updated_at': -121}, 'publisher_heartbeat_stale'),
    ({'last_success_at': -901}, 'publisher_remote_snapshot_stale'),
    ({'oldest_snapshot_at': -901}, 'publisher_remote_snapshot_stale'),
    ({'updated_at': 1}, 'publisher_clock_invalid'),
    ({'phase': 'backoff'}, 'publisher_retry_pending')])
def test_health_detects_kill_stale_source_clock_rollback_and_backoff(runtime, change, reason):
    settings, receiver, timer, stop, calls, run = runtime
    value = supervisor.initial_status(settings, receiver, timer.now)
    value.update(phase='waiting', reason='published', started_at=timer.now - 1000,
                 last_success_at=timer.now - 200, oldest_snapshot_at=timer.now - 200)
    for key, difference in change.items():
        value[key] = timer.now + difference if isinstance(difference, int) else difference
    value['oldest_snapshot_at'] = min(value['last_success_at'], value['oldest_snapshot_at'])
    status_path(settings).write_text(json.dumps(value))
    health = supervisor.check_status(status_path(settings), now=timer.now)
    assert health['healthy'] is False and health['reason'] == reason


def test_profile_change_requires_operator_reset_before_account_reads(runtime):
    settings, receiver, timer, stop, calls, run = runtime
    supervisor.reset_status(settings, receiver, status_path(settings), now=timer.now)
    settings.horizon_days += 1
    with pytest.raises(Review, match='profile_changed_reset_required'):
        run()
    assert not calls
    supervisor.reset_status(settings, receiver, status_path(settings), now=timer.now)
    stop.set()
    assert run() == 0


@pytest.mark.parametrize('kwargs', [{'interval': 30}, {'interval': 660},
                                   {'max_failures': 0}, {'capture_timeout': 601}])
def test_unsafe_cadence_rejected_before_state_or_reads(runtime, kwargs):
    settings, receiver, timer, stop, calls, run = runtime
    with pytest.raises(Review, match='supervision_bounds'):
        run(**kwargs)
    assert not calls and not status_path(settings).exists()


def test_check_cli_does_not_load_environment_config_store_or_gateway(tmp_path, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError('check must read only its status file')
    monkeypatch.setattr(Settings, 'load', forbidden)
    from booking_bridge.store import Store
    monkeypatch.setattr(Store, '__init__', forbidden)
    assert supervisor.main(['--check', '--state', str(tmp_path/'missing')]) == 2
    assert not (tmp_path/'missing').exists()
    assert json.loads(capsys.readouterr().out)['healthy'] is False


def test_cli_requires_explicit_run_profile_before_touching_state(tmp_path, capsys):
    assert supervisor.main(['--run', '--state', str(tmp_path/'unused')]) == 2
    assert not (tmp_path/'unused').exists()
    assert 'operator_review_required' in capsys.readouterr().out


def test_lock_contention_does_not_construct_store_or_overwrite_status(runtime, tmp_path, monkeypatch):
    settings, receiver, timer, stop, calls, run = runtime
    from provider_assignment.core import lock
    from booking_bridge.store import Store
    key, hosts = tmp_path/'key', tmp_path/'hosts'
    key.write_text('synthetic')
    hosts.write_text('synthetic')
    config = tmp_path/'config.json'
    config.write_text('{}')
    monkeypatch.setattr(Settings, 'load', lambda *args, **kwargs: settings)

    def forbidden(*args, **kwargs):
        raise AssertionError('Store must not initialize while lock is held')
    monkeypatch.setattr(Store, '__init__', forbidden)
    with lock(settings.state/'pilot-read-snapshot.lock'):
        assert supervisor.main(['--run', '--read-only', '--config', str(config),
                                '--state', str(settings.state), '--identity', str(key),
                                '--known-hosts', str(hosts)]) == 2
    assert not status_path(settings).exists()


def test_restart_after_killed_final_attempt_stays_blocked(runtime):
    settings, receiver, timer, stop, calls, run = runtime
    status = supervisor.initial_status(settings, receiver, timer.now)
    status.update(phase='capturing', consecutive_failures=3)
    status_path(settings).write_text(json.dumps(status))
    assert run() == 2
    assert not calls
    persisted = supervisor.read_status(status_path(settings))
    assert persisted['phase'] == 'blocked'
    assert persisted['reason'] == 'retry_budget_exhausted'


def test_huge_timestamp_is_rejected_as_invalid_status(runtime):
    settings, receiver, timer, stop, calls, run = runtime
    value = supervisor.initial_status(settings, receiver, timer.now)
    value['updated_at'] = 10 ** 1000
    status_path(settings).write_text(json.dumps(value))
    assert supervisor.check_status(status_path(settings), now=timer.now)['healthy'] is False
    assert not calls


def test_backoff_remains_unhealthy_during_restart_cooldown(runtime):
    settings, receiver, timer, stop, calls, run = runtime
    value = supervisor.initial_status(settings, receiver, timer.now)
    value.update(phase='backoff', reason='transport_unavailable',
                 consecutive_failures=1, next_attempt_at=timer.now + 300,
                 last_success_at=timer.now, oldest_snapshot_at=timer.now)
    status_path(settings).write_text(json.dumps(value))
    observed = []

    def wait(seconds):
        observed.append(supervisor.check_status(status_path(settings), now=timer.now))
        return True

    assert run(wait=wait) == 0
    assert not calls and observed[0]['healthy'] is False
    assert observed[0]['phase'] == 'backoff'


def test_heartbeat_updates_do_not_spam_console_reports(runtime):
    settings, receiver, timer, stop, calls, run = runtime
    reports = []
    waits = []

    def wait(seconds):
        timer.now += seconds
        waits.append(seconds)
        if len(waits) >= 10:
            return True
        return False

    assert run(wait=wait, report=reports.append) == 0
    assert len(waits) == 10
    assert len(reports) < len(waits)
    assert supervisor.read_status(status_path(settings))['updated_at'] == timer.now
