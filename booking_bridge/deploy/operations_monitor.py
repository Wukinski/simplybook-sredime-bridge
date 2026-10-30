"""Independent availability checks and fixed-recipient durable SMTP alerts.

Run the external configuration on an independent always-on executor. Running
this module on the booking VPS cannot detect or notify a total VPS outage.
The default performs checks and records them; SMTP needs --send-alert.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
import uuid

from provider_assignment.core import lock
from booking_bridge.model import Review
from booking_bridge.production_monitor import (MonitorConfig, _http_status, _https_url,
    certificate_expiry, monitor_once)
from booking_bridge.watchdog_alerts import RECIPIENT, SMTPConfig, SMTPResult, send_smtp
from booking_bridge.deploy.offhost_backup import atomic_json, private_json, require

APP_ID = 0x4F50534D
REASONS = {
    'liveness_unavailable': 'Javni servis nije dostupan.',
    'readiness_unavailable': 'Servis nije spreman za obradu rezervacija.',
    'worker_state_not_ready': 'Lokalni worker nije spreman za obradu rezervacija.',
    'disk_space_low': 'Na serveru nema dovoljno slobodnog prostora.',
    'disk_check_unavailable': 'Provera slobodnog prostora nije uspela.',
    'tls_expiring': 'TLS sertifikat uskoro ističe.',
    'tls_check_unavailable': 'TLS sertifikat nije mogao da se potvrdi.',
    'offhost_backup_failed': 'Poslednja off-host kopija nije uspešno potvrđena.',
    'offhost_backup_stale': 'Potvrđena off-host kopija je zastarela.',
    'offhost_backup_unavailable': 'Nema ispravnog izveštaja o off-host kopiji.',
    'offhost_restore_failed': 'Poslednja izolovana provera vraćanja kopije nije uspela.',
    'offhost_restore_stale': 'Izolovana provera vraćanja kopije nije skoro završena.',
    'offhost_restore_unavailable': 'Nema ispravnog izveštaja o proveri vraćanja kopije.',
    'monitor_check_unavailable': 'Operativna provera nije mogla da se izvrši.',
}


def backup_status_reason(path, max_age, now, *, restore_drill=False):
    kind = 'offhost_restore' if restore_drill else 'offhost_backup'
    try:
        data = private_json(path)
        completed = data.get('completed_at')
        if (data.get('schema_version') != 1 or data.get('status') != 'verified' or
                data.get('off_host_export_performed') is not True or
                data.get('remote_readback_verified') is not True or
                restore_drill and data.get('restore_drill_performed') is not True):
            return kind + '_failed'
        if type(completed) not in (int, float) or not math.isfinite(completed) or completed <= 0:
            return kind + '_unavailable'
        if not 0 <= now - completed <= max_age:
            return kind + '_stale'
        return 'ok'
    except Exception:
        return kind + '_unavailable'


def validate(config):
    required = {'scope', 'live_url', 'ready_url', 'admin_key_file', 'tls_host', 'tls_min_days',
                'local_state', 'disk_path', 'backup_status_file', 'backup_max_age',
                'restore_status_file', 'restore_max_age',
                'state_directory', 'smtp_env_file', 'failure_threshold', 'recovery_threshold'}
    require(isinstance(config, dict) and set(config) == required, 'operations_monitor_configuration_invalid')
    require(config['scope'] in ('external', 'host'), 'operations_monitor_configuration_invalid')
    require(all(type(config[key]) is int and 1 <= config[key] <= 10 for key in
                ('failure_threshold', 'recovery_threshold')), 'operations_monitor_configuration_invalid')
    require(type(config['tls_min_days']) is int and 1 <= config['tls_min_days'] <= 30,
            'operations_monitor_configuration_invalid')
    require(type(config['backup_max_age']) is int and 60 <= config['backup_max_age'] <= 604800,
            'operations_monitor_configuration_invalid')
    require(type(config['restore_max_age']) is int and 3600 <= config['restore_max_age'] <= 2678400,
            'operations_monitor_configuration_invalid')
    require(isinstance(config['state_directory'], str) and config['state_directory'],
            'operations_monitor_configuration_invalid')
    require(config['smtp_env_file'] is None or isinstance(config['smtp_env_file'], str),
            'operations_monitor_configuration_invalid')
    if config['scope'] == 'external':
        _https_url(config['live_url'])
        require(config['local_state'] is None and config['disk_path'] is None and
                config['backup_status_file'] is None and config['restore_status_file'] is None,
                'external_monitor_must_not_claim_vps_local_checks')
        require(isinstance(config['tls_host'], str) and
                re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', config['tls_host']),
                'operations_monitor_configuration_invalid')
        if config['ready_url']:
            _https_url(config['ready_url'])
            require(isinstance(config['admin_key_file'], str) and config['admin_key_file'],
                    'operations_monitor_configuration_invalid')
        else:
            require(config['admin_key_file'] is None, 'operations_monitor_configuration_invalid')
    else:
        require(config['live_url'] == '' and config['ready_url'] == '' and
                config['admin_key_file'] is None and config['tls_host'] == '',
                'operations_monitor_configuration_invalid')
        require(isinstance(config['local_state'], str) and config['local_state'] and
                isinstance(config['disk_path'], str) and config['disk_path'] and
                isinstance(config['backup_status_file'], str) and config['backup_status_file'] and
                isinstance(config['restore_status_file'], str) and config['restore_status_file'],
                'operations_monitor_configuration_invalid')
    return config


def probe(config, *, now=None, http_get=None, tls_expiry=certificate_expiry):
    config = validate(config)
    now = time.time() if now is None else now
    require(type(now) in (int, float) and math.isfinite(now) and now > 0,
            'operations_monitor_clock_invalid')
    if config['scope'] == 'host':
        report = monitor_once(MonitorConfig(local_state=Path(config['local_state']),
            disk_path=Path(config['disk_path'])), clock=lambda: now)
        checks = report['checks']
        reason = backup_status_reason(config['backup_status_file'], config['backup_max_age'], now)
        checks.append({'check': 'offhost_backup', 'ok': reason == 'ok', 'reason': reason})
        reason = backup_status_reason(config['restore_status_file'], config['restore_max_age'], now,
                                      restore_drill=True)
        checks.append({'check': 'offhost_restore', 'ok': reason == 'ok', 'reason': reason})
    else:
        import requests
        getter = http_get or requests.get
        live = _http_status(config['live_url'], timeout=5, request=getter)
        checks = [{'check': 'liveness', 'ok': live == 200,
                   'reason': 'ok' if live == 200 else 'liveness_unavailable'}]
        if config['ready_url']:
            # Optional authenticated readiness is separate from public liveness.
            # Deployment must arrange approved access; no ops key is exposed here.
            path = Path(config['admin_key_file'])
            require(not path.is_symlink() and path.is_file() and path.stat().st_size <= 1024,
                    'operations_monitor_configuration_invalid')
            if os.name != 'nt':
                require(stat.S_IMODE(path.stat().st_mode) & 0o077 == 0,
                        'operations_monitor_private_permissions_required')
            key = path.read_text(encoding='utf-8').rstrip('\r\n')
            require(len(key) >= 32 and not any(char in key for char in '\r\n\x00'),
                    'operations_monitor_configuration_invalid')
            ready = _http_status(config['ready_url'], timeout=5, request=getter,
                                 headers={'X-API-Key': key})
            checks.append({'check': 'readiness', 'ok': ready == 200,
                           'reason': 'ok' if ready == 200 else 'readiness_unavailable'})
        try:
            expiry = tls_expiry(config['tls_host'], 5)
            valid = type(expiry) in (int, float) and math.isfinite(expiry)
            reason = ('tls_check_unavailable' if not valid else
                      'ok' if expiry - now >= config['tls_min_days'] * 86400 else 'tls_expiring')
        except Exception:
            reason = 'tls_check_unavailable'
        checks.append({'check': 'tls', 'ok': reason == 'ok', 'reason': reason})
    require(all(row['reason'] == 'ok' or row['reason'] in REASONS for row in checks),
            'operations_monitor_check_invalid')
    return {'schema_version': 1, 'checked_at': now, 'scope': config['scope'],
            'healthy': all(row['ok'] for row in checks), 'checks': checks,
            'readiness_checked': config['scope'] == 'host' or bool(config['ready_url']),
            'repairs_enabled': False}


class MonitorOutbox:
    """Separate SQLite outbox; finite retries and no blind ambiguous replay."""
    def __init__(self, path):
        self.path = Path(path)
        require(not self.path.is_symlink(), 'operations_outbox_path_invalid')
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.path.exists():
            with sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True) as connection:
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                require(tables <= {'monitor_state', 'monitor_alerts', 'monitor_attempts'} and
                        connection.execute('PRAGMA application_id').fetchone()[0] in (0, APP_ID),
                        'operations_separate_outbox_required')
        else:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
        with self.connect() as connection:
            connection.execute('PRAGMA application_id=' + str(APP_ID))
            connection.execute('CREATE TABLE IF NOT EXISTS monitor_state (id INTEGER PRIMARY KEY CHECK(id=1),failures INTEGER,successes INTEGER,active TEXT)')
            connection.execute("INSERT OR IGNORE INTO monitor_state VALUES(1,0,0,'')")
            connection.execute('CREATE TABLE IF NOT EXISTS monitor_alerts (id TEXT PRIMARY KEY,signature TEXT,kind TEXT,reasons TEXT,state TEXT,created REAL,updated REAL,attempts INTEGER,due REAL,last_reason TEXT)')
            connection.execute('CREATE TABLE IF NOT EXISTS monitor_attempts (alert TEXT,attempt INTEGER,at REAL,state TEXT,reason TEXT,PRIMARY KEY(alert,attempt))')

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=2)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute('PRAGMA journal_mode=WAL')
            connection.execute('PRAGMA synchronous=FULL')
            connection.execute('BEGIN IMMEDIATE')
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def observe(self, report, *, failure_threshold=2, recovery_threshold=2):
        now = report['checked_at']
        reasons = sorted({row['reason'] for row in report['checks'] if not row['ok']})
        require(all(code in REASONS for code in reasons), 'operations_monitor_check_invalid')
        with self.connect() as connection:
            state = connection.execute('SELECT * FROM monitor_state WHERE id=1').fetchone()
            failures = 0 if report['healthy'] else state['failures'] + 1
            successes = state['successes'] + 1 if report['healthy'] else 0
            active = state['active']
            kind = None
            if not report['healthy'] and failures >= failure_threshold:
                kind = 'failed'
            elif report['healthy'] and active and successes >= recovery_threshold:
                kind = 'recovered'
                connection.execute("UPDATE monitor_alerts SET state='superseded',updated=? WHERE state IN ('pending','retry')", (now,))
            signature = hashlib.sha256(json.dumps([report['scope'], kind, reasons], sort_keys=True).encode()).hexdigest()
            reserved = False
            reason = 'threshold_not_reached'
            if kind:
                previous = connection.execute('SELECT * FROM monitor_alerts WHERE signature=? ORDER BY created DESC LIMIT 1', (signature,)).fetchone()
                uncertain = connection.execute("SELECT COUNT(*) FROM monitor_alerts WHERE signature=? AND state IN ('uncertain','sending')", (signature,)).fetchone()[0]
                day = int(now // 86400) * 86400
                count = connection.execute('SELECT COUNT(*) FROM monitor_alerts WHERE created>=? AND created<?', (day, day + 86400)).fetchone()[0]
                if uncertain:
                    reason = 'uncertain_requires_review'
                elif previous and previous['state'] in ('pending', 'retry'):
                    reason = 'already_pending'
                elif previous and now - previous['created'] < 3600:
                    reason = 'cooldown'
                elif count >= 10:
                    reason = 'daily_limit'
                else:
                    connection.execute('INSERT INTO monitor_alerts VALUES(?,?,?,?,?,?,?,?,?,?)',
                        (uuid.uuid4().hex, signature, kind, json.dumps(reasons), 'pending', now, now, 0, now, None))
                    reserved, reason = True, 'queued'
                active = signature if kind == 'failed' else ''
            connection.execute('UPDATE monitor_state SET failures=?,successes=?,active=? WHERE id=1',
                               (failures, successes, active))
            return {'reserved': reserved, 'reason': reason}

    @staticmethod
    def message(config, alert):
        reasons = json.loads(alert['reasons'])
        require(alert['kind'] in ('failed', 'recovered') and
                isinstance(reasons, list) and all(code in REASONS for code in reasons),
                'operations_monitor_check_invalid')
        recovered = alert['kind'] == 'recovered'
        message = EmailMessage()
        message['From'], message['To'] = config.from_address, RECIPIENT
        message['Subject'] = 'Booking bridge: ' + ('servis ponovo dostupan' if recovered else 'operativno upozorenje')
        message['Date'] = format_datetime(datetime.fromtimestamp(alert['created'], timezone.utc))
        message['Message-ID'] = '<operations-' + alert['id'] + '@' + config.from_address.rsplit('@', 1)[1] + '>'
        lines = ['Operativni nadzor booking bridge sistema', '',
                 'Vreme UTC: ' + datetime.fromtimestamp(alert['created'], timezone.utc).isoformat(),
                 'Provere ponovo prolaze.' if recovered else 'Potrebna je provera operatera.']
        lines.extend('- ' + REASONS[code] + ' [' + code + ']' for code in reasons)
        lines.extend(['', 'Nije izvršena automatska popravka.',
                      'SMTP prihvatanje nije dokaz prijema u inbox.'])
        message.set_content('\n'.join(lines), charset='utf-8')
        return message

    def send_one(self, config, *, now=None, sender=send_smtp):
        now = time.time() if now is None else now
        config.validate()
        with lock(Path(str(self.path) + '.send.lock')):
            with self.connect() as connection:
                connection.execute("UPDATE monitor_attempts SET state='uncertain',reason='interrupted_smtp_attempt' WHERE state='sending'")
                connection.execute("UPDATE monitor_alerts SET state='uncertain',updated=?,last_reason='interrupted_smtp_attempt' WHERE state='sending'", (now,))
                day = int(now // 86400) * 86400
                count = connection.execute('SELECT COUNT(*) FROM monitor_attempts WHERE at>=? AND at<?', (day, day + 86400)).fetchone()[0]
                if count >= 10:
                    return {'state': 'daily_limit', 'smtp_accepted': False}
                row = connection.execute("SELECT * FROM monitor_alerts WHERE state IN ('pending','retry') AND due<=? AND attempts<3 ORDER BY created LIMIT 1", (now,)).fetchone()
                if row is None:
                    return {'state': 'idle', 'smtp_accepted': False}
                alert = dict(row)
                connection.execute("UPDATE monitor_alerts SET state='sending',attempts=attempts+1,updated=? WHERE id=?", (now, alert['id']))
                connection.execute('INSERT INTO monitor_attempts VALUES(?,?,?,?,?)', (alert['id'], alert['attempts'] + 1, now, 'sending', None))
            try:
                result = sender(config, self.message(config, alert))
                require(isinstance(result, SMTPResult), 'operations_sender_result_invalid')
                result.validate()
            except Exception:
                result = SMTPResult('uncertain', 'smtp_sender_failed')
            attempts = alert['attempts'] + 1
            state = ('exhausted' if attempts >= 3 else 'retry') if result.status == 'retryable' else result.status
            due = now + 60 * 2 ** (attempts - 1) if state == 'retry' else 0
            with self.connect() as connection:
                connection.execute('UPDATE monitor_alerts SET state=?,updated=?,due=?,last_reason=? WHERE id=?',
                                   (state, now, due, result.reason, alert['id']))
                connection.execute('UPDATE monitor_attempts SET state=?,reason=? WHERE alert=? AND attempt=?',
                                   (state, result.reason, alert['id'], attempts))
            return {'state': state, 'reason': result.reason, 'smtp_accepted': state == 'accepted',
                    'inbox_delivery_verified': False}


def run(config, *, send_alert=False):
    config = validate(config)
    directory = Path(config['state_directory'])
    require(not directory.is_symlink(), 'operations_monitor_state_invalid')
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != 'nt':
        require(stat.S_IMODE(directory.stat().st_mode) & 0o077 == 0,
                'operations_monitor_private_permissions_required')
    try:
        report = probe(config)
    except Exception:
        report = {'schema_version': 1, 'checked_at': time.time(), 'scope': config['scope'],
                  'healthy': False, 'readiness_checked': False, 'repairs_enabled': False,
                  'checks': [{'check': 'monitor', 'ok': False, 'reason': 'monitor_check_unavailable'}]}
    outbox = MonitorOutbox(directory / 'monitor-alerts.sqlite')
    report['reservation'] = outbox.observe(report, failure_threshold=config['failure_threshold'],
                                         recovery_threshold=config['recovery_threshold'])
    report['alert'] = {'state': 'not_requested'}
    if send_alert:
        from dotenv import dotenv_values
        require(config['smtp_env_file'], 'operations_smtp_not_configured')
        values = dict(dotenv_values(config['smtp_env_file'], interpolate=False))
        smtp = SMTPConfig.from_env(values)
        report['alert'] = outbox.send_one(smtp)
    atomic_json(directory / 'monitor-status.json', report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--send-alert', action='store_true')
    args = parser.parse_args(argv)
    try:
        report = run(private_json(args.config), send_alert=args.send_alert)
        print(json.dumps(report))
        return 0 if report['healthy'] else 2
    except Exception:
        print(json.dumps({'healthy': False, 'reason': 'operations_monitor_requires_review',
                          'repairs_enabled': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
