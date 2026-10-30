"""One-shot sanitized monitoring; alerts require an explicit --send-alert action.

The default checks configured HTTPS liveness/readiness. --local-state is a
network-free container healthcheck that opens an existing SQLite database read
only. This command never constructs an account gateway or migrates state.
"""
import argparse
import json
import math
import os
import re
import shutil
import socket
import sqlite3
import ssl
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import requests


@dataclass(frozen=True)
class MonitorConfig:
    live_url: str = ''
    ready_url: str = ''
    admin_key: str = ''
    alert_url: str = ''
    timeout: int = 5
    disk_path: Path | None = None
    min_free_bytes: int = 1_073_741_824
    min_free_percent: int = 10
    backup_path: Path | None = None
    backup_max_age: int = 7200
    tls_host: str = ''
    tls_min_days: int = 7
    local_state: Path | None = None

    def validate(self, *, send_alert=False):
        numeric = ((self.timeout, 1, 30), (self.min_free_bytes, 0, 2**63 - 1),
                   (self.min_free_percent, 0, 100), (self.backup_max_age, 1, 31_536_000),
                   (self.tls_min_days, 0, 365))
        if any(type(v) is not int or not low <= v <= high for v, low, high in numeric):
            raise ValueError('monitor_configuration_invalid')
        if self.local_state is None:
            _https_url(self.live_url)
            _https_url(self.ready_url)
            if not isinstance(self.admin_key, str) or not self.admin_key or any(c in self.admin_key for c in '\r\n'):
                raise ValueError('monitor_configuration_invalid')
        if self.tls_host and (not isinstance(self.tls_host, str) or
                              not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', self.tls_host)):
            raise ValueError('monitor_configuration_invalid')
        if send_alert:
            _https_url(self.alert_url)


def _https_url(value):
    try:
        parsed = urlsplit(value)
        if (not isinstance(value, str) or parsed.scheme != 'https' or not parsed.hostname or
                parsed.username or parsed.password or parsed.fragment or parsed.query or
                any(c.isspace() for c in value) or not 1 <= (parsed.port or 443) <= 65535):
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ValueError('monitor_configuration_invalid') from None


def _row(name, reason='ok'):
    return {'check': name, 'ok': reason == 'ok', 'reason': reason}


def _http_status(url, *, timeout, headers=None, request=None, body=None):
    """No redirects or response bodies; all exceptions become a fixed code."""
    response = None
    try:
        options = dict(timeout=(min(3, timeout), timeout), allow_redirects=False,
                       stream=True, verify=True)
        if headers:
            options['headers'] = headers
        if body is not None:
            options['json'] = body
        response = request(url, **options)
        return response.status_code
    except Exception:
        return None
    finally:
        if response is not None:
            try:
                response.close()
            except Exception:
                pass


class _ReadOnlyState:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        # Path.as_uri quotes '?'/'#' in filenames before adding SQLite's mode.
        conn = sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('BEGIN')
            yield conn
        finally:
            conn.close()


def local_state_ready(path, *, now=None):
    from .store import Store
    from .recovery import recovery_start_allowed
    try:
        return (recovery_start_allowed(path) and
                Store.is_ready(_ReadOnlyState(path), time.time() if now is None else now))
    except (OSError, sqlite3.Error, ValueError, TypeError):
        return False


def certificate_expiry(host, timeout):
    """Verify the public certificate chain and hostname before reading expiry."""
    context = ssl.create_default_context()
    with socket.create_connection((host, 443), timeout=timeout) as raw:
        with context.wrap_socket(raw, server_hostname=host) as connection:
            return ssl.cert_time_to_seconds(connection.getpeercert()['notAfter'])


def monitor_once(config, *, send_alert=False, clock=time.time, http_get=None,
                 http_post=None, disk_usage=shutil.disk_usage, tls_expiry=certificate_expiry):
    config.validate(send_alert=send_alert)
    now = clock()
    if type(now) not in (int, float) or not math.isfinite(now) or now <= 0:
        raise ValueError('monitor_configuration_invalid')
    checks = []
    if config.local_state is not None:
        checks.append(_row('worker_state', 'ok' if local_state_ready(config.local_state, now=now)
                           else 'worker_state_not_ready'))
    else:
        live = _http_status(config.live_url, timeout=config.timeout, request=http_get or requests.get)
        ready = _http_status(config.ready_url, timeout=config.timeout,
                             headers={'X-API-Key': config.admin_key}, request=http_get or requests.get)
        checks.extend([_row('liveness', 'ok' if live == 200 else 'liveness_unavailable'),
                       _row('readiness', 'ok' if ready == 200 else 'readiness_unavailable')])
    if config.disk_path is not None:
        try:
            usage = disk_usage(config.disk_path)
            enough = (usage.total > 0 and usage.free >= config.min_free_bytes and
                      100 * usage.free / usage.total >= config.min_free_percent)
            reason = 'ok' if enough else 'disk_space_low'
        except Exception:
            reason = 'disk_check_unavailable'
        checks.append(_row('disk', reason))
    if config.backup_path is not None:
        try:
            path = Path(config.backup_path)
            stat = path.stat()
            age = now - stat.st_mtime
            reason = ('backup_invalid' if not path.is_file() or stat.st_size <= 0 else
                      'backup_timestamp_future' if age < -5 else
                      'backup_stale' if age > config.backup_max_age else 'ok')
        except OSError:
            reason = 'backup_unavailable'
        checks.append(_row('backup', reason))
    if config.tls_host:
        try:
            expiry = tls_expiry(config.tls_host, config.timeout)
            valid = type(expiry) in (int, float) and math.isfinite(expiry)
            reason = ('tls_check_unavailable' if not valid else
                      'ok' if expiry - now >= config.tls_min_days * 86400 else 'tls_expiring')
        except Exception:
            reason = 'tls_check_unavailable'
        checks.append(_row('tls', reason))
    healthy = all(row['ok'] for row in checks)
    report = {'healthy': healthy, 'checks': checks, 'alert': 'not_requested'}
    if send_alert:
        report['alert'] = 'not_needed'
        if not healthy:
            # The body is built from fixed codes, never exception text, URLs,
            # credentials, certificate subjects, paths, or HTTP response data.
            body = {'service': 'booking_bridge', 'healthy': False,
                    'reasons': [row['reason'] for row in checks if not row['ok']]}
            status = _http_status(config.alert_url, timeout=config.timeout, body=body,
                                  request=http_post or requests.post)
            report['alert'] = 'sent' if type(status) is int and 200 <= status < 300 else 'failed'
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--local-state', type=Path, help='Read existing worker health without network access')
    parser.add_argument('--timeout', type=int, default=5)
    parser.add_argument('--disk-path', type=Path)
    parser.add_argument('--min-free-bytes', type=int, default=1_073_741_824)
    parser.add_argument('--min-free-percent', type=int, default=10)
    parser.add_argument('--backup-path', type=Path)
    parser.add_argument('--backup-max-age', type=int, default=7200)
    parser.add_argument('--tls', action='store_true')
    parser.add_argument('--tls-min-days', type=int, default=7)
    parser.add_argument('--send-alert', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.env_file:
            if not args.env_file.is_file():
                raise ValueError()
            from dotenv import load_dotenv
            load_dotenv(args.env_file)
        tls_host = os.getenv('BRIDGE_MONITOR_TLS_HOST', '') if args.tls else ''
        if args.tls and not tls_host:
            raise ValueError()
        config = MonitorConfig(
            live_url=os.getenv('BRIDGE_MONITOR_LIVE_URL', ''),
            ready_url=os.getenv('BRIDGE_MONITOR_READY_URL', ''),
            admin_key=os.getenv('BRIDGE_MONITOR_ADMIN_KEY', ''),
            alert_url=os.getenv('BRIDGE_MONITOR_ALERT_URL', ''), timeout=args.timeout,
            disk_path=args.disk_path, min_free_bytes=args.min_free_bytes,
            min_free_percent=args.min_free_percent, backup_path=args.backup_path,
            backup_max_age=args.backup_max_age, tls_host=tls_host,
            tls_min_days=args.tls_min_days, local_state=args.local_state)
        report = monitor_once(config, send_alert=args.send_alert)
    except Exception:
        print(json.dumps({'healthy': False, 'checks': [_row('configuration', 'monitor_configuration_invalid')],
                          'alert': 'not_sent'}))
        return 2
    print(json.dumps(report))
    return 0 if report['healthy'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
