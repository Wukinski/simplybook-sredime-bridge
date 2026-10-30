import copy
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from booking_bridge.model import Review
from booking_bridge.pilot_publish import SSHReceiver, publish_packet, run_cycles
from booking_bridge.tests.test_pilot_exchange import scoped, seed


@pytest.fixture(autouse=True)
def publisher_scope(scoped):
    return scoped


def receiver(tmp_path):
    key, hosts = tmp_path/'key', tmp_path/'known_hosts'
    key.write_text('synthetic-key')
    hosts.write_text('synthetic-host')
    return SSHReceiver('pilot.example.test', key, hosts)


def packet_for(settings, store, now):
    from booking_bridge.pilot_exchange import build_packet
    seed(settings, store, now)
    return build_packet(settings, store, now=now)


def receipt(packet, **overrides):
    value = {'accepted': True, 'duplicate': False,
             'source_employee_id': packet['source_employee_id'],
             'target_provider_id': packet['target_provider_id'],
             'feed_version': packet['feed_version'],
             'occupancy_events': 16, 'remote_import_confirmed': False}
    value.update(overrides)
    return value


def test_publish_validates_locally_then_sends_only_packet_over_pinned_ssh(settings, store, now, tmp_path):
    from booking_bridge.pilot_exchange import validate_packet
    packet = packet_for(settings, store, now)
    info = validate_packet(settings, packet, now=now)
    called = []
    def run(command, **kwargs):
        called.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps(receipt(packet, occupancy_events=info['occupancy_events'])).encode(), stderr=b'')
    result = publish_packet(settings, packet, receiver(tmp_path), now=now, run=run)
    command, options = called[0]
    assert 'StrictHostKeyChecking=yes' in command
    assert 'IdentitiesOnly=yes' in command and 'BatchMode=yes' in command
    assert command[-1].endswith('python -m booking_bridge.pilot_exchange --read-only --stdin')
    assert isinstance(options['input'], bytes) and json.loads(options['input']) == packet
    assert options.get('shell') is not True and options['timeout'] <= 60
    assert settings.webhook_secret.encode() not in options['input']
    assert result['remote_import_confirmed'] is False


def test_nonminimal_payload_never_reaches_network(settings, store, now, tmp_path):
    packet = packet_for(settings, store, now)
    packet['credentials'] = 'sensitive-marker'
    def forbidden(*args, **kwargs): raise AssertionError('Invalid data crossed transport boundary')
    with pytest.raises(Review, match='nonminimal'):
        publish_packet(settings, packet, receiver(tmp_path), now=now, run=forbidden)


@pytest.mark.parametrize('host,container', [('host;whoami','worker'), ('-ProxyCommand=bad','worker'),
                                          ('host','worker;touch bad'), ('host','$(bad)')])
def test_ssh_destination_cannot_inject_shell_or_ssh_options(tmp_path, host, container):
    target = receiver(tmp_path)
    target = SSHReceiver(host, target.identity, target.known_hosts, container=container)
    with pytest.raises(Review, match='destination'):
        target.command()


@pytest.mark.parametrize('change', [{'feed_version': '0'*64}, {'source_employee_id': 'wrong'},
                                   {'target_provider_id': 1000},
                                   {'remote_import_confirmed': True}, {'private_payload': 'must-not-print'},
                                   {'accepted': 1}, {'duplicate': 'yes'}, {'occupancy_events': True}])
def test_untrusted_or_wrong_remote_receipt_is_not_reported_as_success(settings, store, now, tmp_path, change):
    from booking_bridge.pilot_exchange import validate_packet
    packet = packet_for(settings, store, now);info = validate_packet(settings, packet, now=now)
    reply = receipt(packet, occupancy_events=info['occupancy_events']);reply.update(change)
    def run(*args, **kwargs):return SimpleNamespace(returncode=0,stdout=json.dumps(reply).encode(),stderr=b'')
    with pytest.raises(Review, match='receipt_mismatch'):
        publish_packet(settings, packet, receiver(tmp_path), now=now, run=run)


def test_remote_failure_does_not_echo_stderr_or_retry(settings, store, now, tmp_path):
    packet = packet_for(settings, store, now);calls=[]
    def run(*args, **kwargs):
        calls.append(1)
        return SimpleNamespace(returncode=1,stdout=b'private-response',stderr=b'secret-password')
    with pytest.raises(Review, match='^pilot_publish_remote_rejected$'):
        publish_packet(settings, packet, receiver(tmp_path), now=now, run=run)
    assert len(calls)==1


def test_bounded_cycles_stop_on_failure_without_extra_capture_or_publication(settings, store):
    calls=[]
    def capture(*args, **kwargs):calls.append('capture');return {'capture_seconds':1}, {'safe': True}
    def publish(*args, **kwargs):calls.append('publish');raise Review('synthetic_failure')
    with pytest.raises(Review, match='synthetic_failure'):
        run_cycles(settings,store,None,None,cycles=3,interval=30,capture_fn=capture,publish_fn=publish)
    assert calls==['capture','publish']


@pytest.mark.parametrize('cycles,interval', [(0,30),(121,30),(True,30),(1,9),(1,3601)])
def test_invalid_background_run_bounds_make_no_calls(settings, store, cycles, interval):
    def forbidden(*args, **kwargs):raise AssertionError('Capture should not start')
    with pytest.raises(Review):run_cycles(settings,store,None,None,cycles=cycles,interval=interval,capture_fn=forbidden)
