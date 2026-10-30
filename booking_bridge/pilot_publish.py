"""Finite local pilot capture and PII-free occupancy publication over pinned SSH.

SimplyBook credentials stay in the local REST client. The receiver only gets a
validated availability packet; it never receives credentials, client contacts,
raw account responses, or browser state. This does not start a booking worker.
"""
import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path

from provider_assignment.core import lock
from .model import HOME, Review, Settings

MAX_PACKET = 1_000_000
MAX_REPLY = 16_384
REPLY_KEYS = {'accepted', 'duplicate', 'source_employee_id', 'target_provider_id', 'feed_version',
              'occupancy_events', 'remote_import_confirmed'}


@dataclass(frozen=True)
class SSHReceiver:
    host: str
    identity: Path
    known_hosts: Path
    user: str = 'root'
    container: str = 'booking-bridge-pilot-worker-1'
    executable: str = 'ssh'

    def command(self):
        if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.:-]{0,252}', self.host or '') or
                not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}', self.user or '') or
                not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', self.container or '')):
            raise Review('invalid_pilot_ssh_destination')
        if not self.identity.is_file() or not self.known_hosts.is_file():
            raise Review('pinned_ssh_access_files_required')
        # Only the validated container identifier enters the remote shell. No
        # token, packet, credential or user-provided command is interpolated.
        remote = ('docker exec -i ' + self.container +
                  ' python -m booking_bridge.pilot_exchange --read-only --stdin')
        return [self.executable, '-i', str(self.identity.resolve()),
                '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes',
                '-o', 'UserKnownHostsFile=' + str(self.known_hosts.resolve()),
                '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
                self.user + '@' + self.host, remote]


def publish_packet(settings, packet, receiver, *, now=None, run=subprocess.run):
    from .pilot_exchange import validate_packet
    validation = validate_packet(settings, packet, now=now)
    body = json.dumps(packet, ensure_ascii=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    if len(body) > MAX_PACKET:
        raise Review('pilot_packet_too_large')
    command = receiver.command()
    try:
        # Bytes avoid PowerShell/Windows newline translation. SSH stdin is the
        # only data channel; command arguments never contain the packet.
        response = run(command, input=body, capture_output=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise Review('pilot_publish_transport_unavailable') from None
    if response.returncode != 0 or len(response.stdout) > MAX_REPLY:
        raise Review('pilot_publish_remote_rejected')
    try:
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError()
                result[key] = value
            return result
        result = json.loads(response.stdout, object_pairs_hook=unique)
        if (not isinstance(result, dict) or set(result) != REPLY_KEYS or
                result['accepted'] is not True or type(result['duplicate']) is not bool or
                result['source_employee_id'] != validation['source_employee_id'] or
                type(result['target_provider_id']) is not int or
                result['target_provider_id'] != validation['target_provider_id'] or
                result['feed_version'] != validation['feed_version'] or
                type(result['occupancy_events']) is not int or
                result['occupancy_events'] != validation['occupancy_events'] or
                result['remote_import_confirmed'] is not False):
            raise ValueError()
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise Review('pilot_publish_receipt_mismatch') from None
    return result


def run_cycles(settings, store, gateway, receiver, *, cycles=1, interval=300,
               capture_fn=None, publish_fn=publish_packet, clock=time.time, sleep=time.sleep,
               report=None):
    if type(cycles) is not int or not 1 <= cycles <= 120:
        raise Review('bounded_pilot_cycles_required')
    if type(interval) is not int or not 10 <= interval <= 3600:
        raise Review('invalid_pilot_publish_interval')
    if capture_fn is None:
        from .pilot_snapshot import capture_packet
        capture_fn = capture_packet
    results = []
    for index in range(cycles):
        started = clock()
        capture, packet = capture_fn(settings, store, gateway, clock=clock)
        receipt = publish_fn(settings, packet, receiver, now=clock())
        result = {'cycle': index + 1, 'capture_seconds': capture['capture_seconds'],
                  'accepted': receipt['accepted'], 'duplicate': receipt['duplicate'],
                  'source_employee_id': receipt['source_employee_id'],
                  'feed_version': receipt['feed_version'],
                  'occupancy_events': receipt['occupancy_events'],
                  'account_mutations': 0, 'credentials_transferred': False,
                  'automatic_booking_sync_enabled': False,
                  'remote_import_confirmed': False}
        results.append(result)
        if report:
            report(result)
        if index + 1 < cycles:
            sleep(max(0, interval - (clock() - started)))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--read-only', action='store_true', required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--host', default='169.58.118.33')
    parser.add_argument('--identity', type=Path, default=HOME/'secrets/vps_pilot_ed25519')
    parser.add_argument('--known-hosts', type=Path, default=HOME/'secrets/vps_known_hosts')
    parser.add_argument('--container', default='booking-bridge-pilot-worker-1')
    parser.add_argument('--cycles', type=int, default=1)
    parser.add_argument('--interval', type=int, default=300)
    args = parser.parse_args()
    try:
        if not args.config.is_file():
            raise Review('explicit_pilot_configuration_required')
        if args.env_file:
            from dotenv import load_dotenv
            if not args.env_file.is_file():
                raise Review('pilot_environment_file_missing')
            load_dotenv(args.env_file)
        settings = replace(Settings.load(args.config, read_only=True, isolated_profile=True),
                           state=args.state.resolve())
        receiver = SSHReceiver(args.host, args.identity, args.known_hosts, container=args.container)
        receiver.command()  # Validate destination before account reads.
        from .diagnostics import ReadOnlyGateway
        from .store import Store
        with lock(settings.state/'pilot-read-snapshot.lock'):
            run_cycles(settings, Store(settings.state/'bridge.sqlite'), ReadOnlyGateway(settings),
                       receiver, cycles=args.cycles, interval=args.interval,
                       report=lambda row: print(json.dumps(row), flush=True))
        return 0
    except KeyboardInterrupt:
        print(json.dumps({'stopped': True, 'reason': 'operator_interrupt'}))
        return 130
    except Review as exc:
        print(json.dumps({'stopped': True, 'reason': str(exc)}))
        return 2
    except Exception:
        # Provider/parser/transport errors may carry credential URLs or payloads.
        print(json.dumps({'stopped': True, 'reason': 'pilot_publish_failed'}))
        return 2


if __name__ == '__main__':
    sys.exit(main())
