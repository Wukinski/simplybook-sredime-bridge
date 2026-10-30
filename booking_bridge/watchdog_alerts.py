"""Diagnostic-only email to one approved recipient, with a durable separate outbox.

No model text becomes a header, address, command or arbitrary mail body. SMTP
acceptance is not inbox delivery, and an ambiguous DATA outcome is never retried.
"""
import hashlib
import json
import math
import os
import re
import smtplib
import sqlite3
import ssl
import stat
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import format_datetime
from pathlib import Path

from provider_assignment.core import Failure, lock
from .model import Review

RECIPIENT = 'aaaazzzz.5226@gmail.com'
SEVERITIES = {'info': 1, 'warning': 2, 'critical': 3}
SEVERITY_TEXT = {'info': 'OBAVEŠTENJE', 'warning': 'UPOZORENJE', 'critical': 'KRITIČNO'}
FINDING_TEXT = {
    'observation_schema_invalid': 'Format dijagnostičkog snimka nije ispravan.',
    'database_missing': 'Baza za proveru nije dostupna.',
    'database_schema_unsupported': 'Verzija šeme baze nije podržana.',
    'database_schema_invalid': 'Šema baze nije ispravna.',
    'database_unavailable': 'Baza nije mogla da se pročita.',
    'collection_scan_limit': 'Dostignuto je ograničenje dijagnostičkog pregleda.',
    'collection_data_invalid': 'Podaci za pregled nisu ispravni.',
    'booking_evidence_insufficient': 'Nema dovoljno dokaza za proveru rezervacija.',
    'provider_capacity_unverified': 'Kapacitet zaposlenog nije potvrđen.',
    'provider_overlap_confirmed': 'Utvrđeno je preklapanje rezervacija.',
    'provider_overlap_candidate': 'Pronađen je kandidat za preklapanje rezervacija.',
    'duplicate_booking_candidate': 'Pronađen je kandidat za duplu rezervaciju.',
    'duplicate_target_booking_record': 'Pronađen je ponovljen zapis target rezervacije.',
    'conflicting_target_booking_record': 'Target zapisi rezervacije nisu usklađeni.',
    'owned_baseline_missing': 'Nedostaje sačuvana osnova owned rezervacije.',
    'owned_target_not_in_snapshot': 'Owned target rezervacija nije u snimku.',
    'owned_target_diverged': 'Owned target rezervacija razlikuje se od sačuvanog stanja.',
    'owned_cancel_state_diverged': 'Status otkazivanja owned rezervacije nije usklađen.',
    'owned_source_state_inconsistent': 'Izvorno stanje owned rezervacije nije usklađeno.',
    'unresolved_remote_intent': 'Postoji neizvestan udaljeni upis koji zahteva pregled.',
    'source_queue_aged': 'Događaji u izvornom redu čekaju predugo.',
    'source_event_review': 'Izvorni događaj čeka ručni pregled.',
    'source_event_dead': 'Izvorni događaj je iscrpeo dozvoljene pokušaje.',
    'source_event_future': 'Vreme izvornog događaja je u budućnosti.',
    'open_runtime_incident': 'Postoji otvoren operativni incident.',
    'overlap_scan_limit': 'Pregled preklapanja dostigao je svoje ograničenje.',
    'collector_input_unavailable': 'Ulazni dijagnostički snimak nije dostupan.',
    'collector_input_stale': 'Ulazni dijagnostički snimak je zastareo.',
    'collector_input_invalid': 'Ulazni dijagnostički snimak nije ispravan.',
    'model_unavailable': 'Dijagnostički model nije dostupan.',
    'model_response_invalid': 'Odgovor dijagnostičkog modela nije prošao proveru.',
    'model_self_test_failed': 'Dnevna sintetička provera dijagnostičkog modela nije uspela.',
    'qwen_review_candidate': 'Dijagnostički model je izdvojio nalaz za pregled operatera.',
    'diagnostic_test': 'Ovo je izričito zatražena probna dijagnostička poruka.',
}
for _prefix, _label in (
    ('booking_snapshot', 'Snimak rezervacija'), ('service_buffers', 'Snimak zaštitnih intervala'),
    ('worker_heartbeat', 'Signal rada worker-a')):
    for _suffix, _description in (('missing', 'nedostaje'), ('stale', 'je zastareo'),
                                   ('future', 'ima vreme u budućnosti'), ('invalid', 'nije ispravan')):
        FINDING_TEXT[_prefix + '_' + _suffix] = _label + ' ' + _description + '.'

ASSESSMENTS = {'no_additional_issue': 'Model nije izdvojio dodatni problem.',
               'operator_review': 'Potreban je pregled operatera.',
               'insufficient_evidence': 'Nema dovoljno dokaza za pouzdan zaključak.'}
CONFIDENCES = {'low': 'niska', 'medium': 'srednja', 'high': 'visoka'}
RECOMMENDATIONS = {
    'review_booking_overlap': 'Pregledati moguće preklapanje rezervacija.',
    'review_duplicate_candidate': 'Pregledati kandidata za duplu rezervaciju.',
    'review_source_target_mismatch': 'Uporediti izvorno i target stanje.',
    'review_queue': 'Pregledati red događaja.',
    'review_snapshot_freshness': 'Proveriti svežinu snimka.',
    'review_intent': 'Pregledati neizvestan upis uz stvarni readback.',
    'review_monitor_configuration': 'Pregledati podešavanja dijagnostičkog nadzora.',
}
SMTP_REASONS = {'smtp_accepted', 'smtp_connect_failed', 'smtp_tls_failed', 'smtp_auth_rejected',
                'smtp_envelope_rejected', 'smtp_data_rejected', 'smtp_outcome_uncertain',
                'smtp_secret_unavailable', 'smtp_sender_failed', 'interrupted_smtp_attempt'}
APP_ID = 0x414C5254


def _require(condition, code='diagnostic_alert_input_invalid'):
    if not condition:
        raise Review(code)


def _moment(value):
    value = time.time() if value is None else value
    _require(type(value) in (int, float) and math.isfinite(value) and value > 0, 'diagnostic_alert_clock_invalid')
    return value


def _address(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', value) is not None


def _password(path):
    try:
        with Path(path).open('r', encoding='utf-8') as handle:
            value = handle.read(4097)
        _require(len(value.encode('utf-8')) <= 4096, 'diagnostic_smtp_not_configured')
        value = value.rstrip('\r\n')
        _require(value.strip() and not any(c in value for c in '\r\n\x00'), 'diagnostic_smtp_not_configured')
        return value
    except Exception:
        raise Review('diagnostic_smtp_not_configured') from None


@dataclass(frozen=True)
class SMTPConfig:
    host: str
    port: int
    username: str
    password_file: Path
    from_address: str
    recipient: str = RECIPIENT

    @classmethod
    def from_env(cls, environ=None, prefix='BRIDGE_DIAGNOSTIC_SMTP_'):
        environ = os.environ if environ is None else environ
        try:
            value = cls(host=environ[prefix+'HOST'], port=int(environ[prefix+'PORT']),
                        username=environ[prefix+'USER'], password_file=Path(environ[prefix+'PASSWORD_FILE']),
                        from_address=environ[prefix+'FROM_ADDRESS'], recipient=environ.get(prefix+'RECIPIENT', RECIPIENT))
            value.validate()
            return value
        except Exception:
            raise Review('diagnostic_smtp_not_configured') from None

    def validate(self):
        _require(isinstance(self.host, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', self.host) and
                 type(self.port) is int and self.port in (465, 587) and
                 isinstance(self.username, str) and self.username and len(self.username) <= 320 and
                 not any(c in self.username for c in '\r\n\x00') and _address(self.from_address) and
                 self.recipient == RECIPIENT, 'diagnostic_smtp_not_configured')
        path = Path(self.password_file)
        _require(not path.is_symlink() and path.is_file() and 0 < path.stat().st_size <= 4096,
                 'diagnostic_smtp_not_configured')
        if os.name != 'nt':
            _require(not stat.S_IMODE(path.stat().st_mode) & 0o077, 'diagnostic_smtp_not_configured')
        # Read only for validation, never retain this value on the dataclass.
        # Empty, whitespace-only, missing or malformed credentials must fail
        # before outbox attempt reservation as well as before any socket opens.
        _password(path)


@dataclass(frozen=True)
class SMTPResult:
    status: str
    reason: str

    def validate(self):
        allowed = {'accepted': {'smtp_accepted'},
                   'retryable': {'smtp_connect_failed', 'smtp_tls_failed', 'smtp_envelope_rejected', 'smtp_data_rejected'},
                   'rejected': {'smtp_auth_rejected', 'smtp_envelope_rejected', 'smtp_data_rejected', 'smtp_secret_unavailable'},
                   'uncertain': {'smtp_outcome_uncertain', 'smtp_sender_failed', 'interrupted_smtp_attempt'}}
        _require(self.status in allowed and self.reason in allowed[self.status])


def send_smtp(config, message, *, smtp_ssl_factory=None, smtp_factory=None):
    """Verified TLS only; uncertainty begins at DATA and is never blindly retried."""
    connection = None
    stage = 'connect'
    try:
        config.validate()
        _require(list(message.get_all('To', [])) == [RECIPIENT] and
                 list(message.get_all('From', [])) == [config.from_address] and
                 not message.get_all('Cc') and not message.get_all('Bcc'), 'diagnostic_alert_headers_invalid')
        password = _password(config.password_file)
        context = ssl.create_default_context()
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        if config.port == 465:
            connection = (smtp_ssl_factory or smtplib.SMTP_SSL)(config.host, config.port, timeout=20, context=context)
        else:
            connection = (smtp_factory or smtplib.SMTP)(config.host, config.port, timeout=20)
            connection.ehlo()
            connection.starttls(context=context)
            connection.ehlo()
        stage = 'auth'
        connection.login(config.username, password)
        stage = 'envelope'
        code, _ = connection.mail(config.from_address)
        if not 200 <= code < 300:
            return SMTPResult('retryable' if 400 <= code < 500 else 'rejected', 'smtp_envelope_rejected')
        code, _ = connection.rcpt(RECIPIENT)
        if not 200 <= code < 300:
            return SMTPResult('retryable' if 400 <= code < 500 else 'rejected', 'smtp_envelope_rejected')
        body = message.as_bytes(policy=SMTP)
        stage = 'data'
        code, _ = connection.data(body)
        if code == 250:
            return SMTPResult('accepted', 'smtp_accepted')
        if 400 <= code < 600:
            return SMTPResult('retryable' if code < 500 else 'rejected', 'smtp_data_rejected')
        return SMTPResult('uncertain', 'smtp_outcome_uncertain')
    except smtplib.SMTPAuthenticationError:
        return SMTPResult('rejected', 'smtp_auth_rejected')
    except smtplib.SMTPDataError as error:
        return SMTPResult('retryable' if 400 <= error.smtp_code < 500 else 'rejected', 'smtp_data_rejected')
    except ssl.SSLError:
        return SMTPResult('uncertain', 'smtp_outcome_uncertain') if stage == 'data' else SMTPResult('retryable', 'smtp_tls_failed')
    except Review:
        return SMTPResult('rejected', 'smtp_secret_unavailable')
    except Exception:
        return SMTPResult('uncertain', 'smtp_outcome_uncertain') if stage == 'data' else SMTPResult('retryable', 'smtp_connect_failed')
    finally:
        if connection is not None:
            try:
                connection.quit()
            except Exception:
                try:
                    connection.close()
                except Exception:
                    pass


def _normalize(findings, summary):
    _require(isinstance(findings, list) and len(findings) <= 64)
    normalized = []
    seen = set()
    for finding in findings:
        _require(isinstance(finding, dict) and set(finding) == {'code', 'severity', 'refs'})
        code, severity, refs = finding['code'], finding['severity'], finding['refs']
        _require(isinstance(code, str) and code in FINDING_TEXT and code not in seen and
                 isinstance(severity, str) and severity in SEVERITIES and isinstance(refs, list) and len(refs) <= 8 and
                 all(isinstance(ref, str) and re.fullmatch('[a-f0-9]{12,64}', ref) for ref in refs))
        seen.add(code)
        normalized.append({'code': code, 'severity': severity, 'refs': sorted(set(refs))})
    normalized.sort(key=lambda row: row['code'])
    if summary is not None:
        _require(isinstance(summary, dict) and set(summary) == {'assessment', 'confidence', 'recommendation_codes'} and
                 isinstance(summary['assessment'], str) and summary['assessment'] in ASSESSMENTS and
                 isinstance(summary['confidence'], str) and summary['confidence'] in CONFIDENCES and
                 isinstance(summary['recommendation_codes'], list) and len(summary['recommendation_codes']) <= 7 and
                 all(isinstance(code, str) and code in RECOMMENDATIONS for code in summary['recommendation_codes']))
        summary = {**summary, 'recommendation_codes': sorted(set(summary['recommendation_codes']))}
    return {'findings': normalized, 'summary': summary}


def _message(config, alert):
    payload = json.loads(alert['payload'])
    _normalize(payload['findings'], payload['summary'])
    severity = next(name for name, number in SEVERITIES.items() if number == alert['severity'])
    lines = ['Dijagnostika booking bridge sistema', '', 'Nivo: '+SEVERITY_TEXT[severity],
             'Vreme UTC: '+datetime.fromtimestamp(alert['created'], timezone.utc).isoformat(), '',
             'Ova poruka samo prijavljuje nalaz. Nije izvršena automatska popravka.', '']
    for finding in payload['findings']:
        lines.append('- '+FINDING_TEXT[finding['code']]+' ['+finding['code']+']')
        if finding['refs']:
            lines.append('  Reference: '+', '.join(finding['refs']))
    if payload['summary']:
        summary = payload['summary']
        lines.extend(['', ASSESSMENTS[summary['assessment']], 'Pouzdanost: '+CONFIDENCES[summary['confidence']]+'.'])
        lines.extend('- '+RECOMMENDATIONS[code] for code in summary['recommendation_codes'])
    lines.extend(['', 'SMTP prihvatanje poruke nije potvrda da je stigla u inbox.'])
    message = EmailMessage()
    message['From'], message['To'] = config.from_address, RECIPIENT
    message['Subject'] = 'Booking bridge: dijagnostika ['+SEVERITY_TEXT[severity]+']'
    message['Date'] = format_datetime(datetime.fromtimestamp(alert['created'], timezone.utc))
    message['Message-ID'] = '<diagnostic-'+alert['id']+'@'+config.from_address.rsplit('@', 1)[1]+'>'
    message.set_content('\n'.join(lines), charset='utf-8')
    return message


class DiagnosticOutbox:
    def __init__(self, path, *, max_alerts_per_day=10, cooldown_seconds=3600, max_attempts=3):
        _require(type(max_alerts_per_day) is int and 1 <= max_alerts_per_day <= 10 and
                 type(cooldown_seconds) is int and 60 <= cooldown_seconds <= 86400 and
                 type(max_attempts) is int and 1 <= max_attempts <= 3, 'diagnostic_alert_limits_invalid')
        self.path = Path(path)
        self.max_alerts_per_day, self.cooldown_seconds, self.max_attempts = max_alerts_per_day, cooldown_seconds, max_attempts
        _require(not self.path.is_symlink(), 'diagnostic_outbox_path_invalid')
        if self.path.exists():
            with sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro', uri=True) as conn:
                tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                _require(tables <= {'alert_outbox', 'alert_attempts'} and
                         conn.execute('PRAGMA application_id').fetchone()[0] in (0, APP_ID), 'diagnostic_outbox_separate_database_required')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(descriptor)
        with self._connect() as conn:
            conn.execute('PRAGMA application_id='+str(APP_ID))
            conn.execute('CREATE TABLE IF NOT EXISTS alert_outbox (id TEXT PRIMARY KEY,signature TEXT NOT NULL,severity INTEGER NOT NULL,payload TEXT NOT NULL,state TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL,attempts INTEGER NOT NULL,due REAL NOT NULL,last_reason TEXT)')
            conn.execute('CREATE TABLE IF NOT EXISTS alert_attempts (alert TEXT NOT NULL,attempt INTEGER NOT NULL,at REAL NOT NULL,state TEXT NOT NULL,reason TEXT,PRIMARY KEY(alert,attempt))')

    @contextmanager
    def _connect(self):
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

    def reserve(self, findings, summary=None, *, now=None):
        now = _moment(now)
        payload = _normalize(findings, summary)
        if not payload['findings']:
            return {'reserved': False, 'id': None, 'reason': 'no_findings'}
        signature = hashlib.sha256(json.dumps([{k: f[k] for k in ('code', 'refs')} for f in payload['findings']], sort_keys=True).encode()).hexdigest()
        severity = max(SEVERITIES[f['severity']] for f in payload['findings'])
        day = int(now // 86400) * 86400
        with self._connect() as conn:
            uncertain = conn.execute("SELECT MAX(severity) FROM alert_outbox WHERE signature=? AND state IN ('uncertain','sending')", (signature,)).fetchone()[0]
            if uncertain is not None and uncertain >= severity:
                return {'reserved': False, 'id': None, 'reason': 'uncertain_requires_review'}
            previous = conn.execute('SELECT * FROM alert_outbox WHERE signature=? ORDER BY created DESC LIMIT 1', (signature,)).fetchone()
            if previous and previous['severity'] >= severity and previous['state'] in ('pending', 'retry'):
                return {'reserved': False, 'id': previous['id'], 'reason': 'already_pending'}
            if previous and previous['severity'] >= severity and now - previous['created'] < self.cooldown_seconds:
                return {'reserved': False, 'id': previous['id'], 'reason': 'cooldown'}
            if conn.execute('SELECT COUNT(*) FROM alert_outbox WHERE created>=? AND created<?', (day, day+86400)).fetchone()[0] >= self.max_alerts_per_day:
                return {'reserved': False, 'id': None, 'reason': 'daily_limit'}
            identifier = uuid.uuid4().hex
            conn.execute('INSERT INTO alert_outbox VALUES(?,?,?,?,?,?,?,?,?,?)',
                         (identifier, signature, severity, json.dumps(payload), 'pending', now, now, 0, now, None))
            if previous and severity > previous['severity']:
                conn.execute("UPDATE alert_outbox SET state='superseded',updated=? WHERE signature=? AND id!=? AND state IN ('pending','retry')", (now, signature, identifier))
        return {'reserved': True, 'id': identifier, 'reason': 'queued'}

    def pending(self, *, now=None):
        now = _moment(now)
        with self._connect() as conn:
            return [dict(row) for row in conn.execute("SELECT id,state,severity,attempts,due,last_reason FROM alert_outbox WHERE state IN ('pending','retry') AND due<=? ORDER BY severity DESC,created", (now,))]

    def _record(self, alert_id, result, now):
        result.validate()
        with self._connect() as conn:
            row = conn.execute('SELECT * FROM alert_outbox WHERE id=?', (alert_id,)).fetchone()
            _require(row is not None and row['state'] == 'sending', 'diagnostic_alert_transition_invalid')
            state = ('exhausted' if row['attempts'] >= self.max_attempts else 'retry') if result.status == 'retryable' else result.status
            due = now + min(3600, 60 * 2**(row['attempts']-1)) if state == 'retry' else 0
            conn.execute('UPDATE alert_outbox SET state=?,updated=?,due=?,last_reason=? WHERE id=?', (state, now, due, result.reason, alert_id))
            conn.execute('UPDATE alert_attempts SET state=?,reason=? WHERE alert=? AND attempt=?', (state, result.reason, alert_id, row['attempts']))
        return {'id': alert_id, 'state': state, 'reason': result.reason,
                'smtp_accepted': True if state == 'accepted' else None if state == 'uncertain' else False,
                'inbox_delivery_verified': False}

    def record_fail(self, alert_id, reason=None, *, uncertain=False, now=None):
        reason = reason or ('smtp_outcome_uncertain' if uncertain else 'smtp_connect_failed')
        return self._record(alert_id, SMTPResult('uncertain' if uncertain else 'retryable', reason), _moment(now))

    def send_one(self, config, *, alert_id=None, sender=None, now=None):
        now = _moment(now)
        _require(alert_id is None or isinstance(alert_id, str) and re.fullmatch('[a-f0-9]{32}', alert_id),
                 'diagnostic_alert_id_invalid')
        try:
            config.validate()
        except Exception:
            return {'state': 'not_configured', 'reason': 'diagnostic_smtp_not_configured', 'smtp_accepted': False,
                    'inbox_delivery_verified': False}
        try:
            with lock(Path(str(self.path)+'.send.lock')):
                with self._connect() as conn:
                    # Only the singleton sender owns this lock. Leftover sending
                    # rows therefore belong to interrupted, ambiguous attempts.
                    conn.execute("UPDATE alert_attempts SET state='uncertain',reason='interrupted_smtp_attempt' WHERE alert IN (SELECT id FROM alert_outbox WHERE state='sending') AND state='sending'")
                    conn.execute("UPDATE alert_outbox SET state='uncertain',updated=?,last_reason='interrupted_smtp_attempt' WHERE state='sending'", (now,))
                    day = int(now // 86400)*86400
                    if conn.execute('SELECT COUNT(*) FROM alert_attempts WHERE at>=? AND at<?', (day, day+86400)).fetchone()[0] >= self.max_alerts_per_day:
                        return {'state': 'daily_limit', 'reason': 'daily_limit', 'smtp_accepted': False, 'inbox_delivery_verified': False}
                    query = "SELECT * FROM alert_outbox WHERE state IN ('pending','retry') AND due<=? AND attempts<?"
                    parameters = (now, self.max_attempts)
                    if alert_id is not None:
                        query += ' AND id=?'
                        parameters += (alert_id,)
                    row = conn.execute(query+' ORDER BY severity DESC,created LIMIT 1', parameters).fetchone()
                    if row is None:
                        return {'state': 'idle', 'reason': 'no_pending_alert', 'smtp_accepted': False, 'inbox_delivery_verified': False}
                    alert = dict(row)
                    conn.execute("UPDATE alert_outbox SET state='sending',attempts=attempts+1,updated=? WHERE id=?", (now, alert['id']))
                    conn.execute('INSERT INTO alert_attempts VALUES(?,?,?,?,?)', (alert['id'], alert['attempts']+1, now, 'sending', None))
                try:
                    result = (sender or send_smtp)(config, _message(config, alert))
                    _require(isinstance(result, SMTPResult))
                    result.validate()
                except Exception:
                    # The injected/real sender might have completed DATA before
                    # raising. An unknown exception/result must not cause replay.
                    result = SMTPResult('uncertain', 'smtp_sender_failed')
                return self._record(alert['id'], result, now)
        except Failure:
            return {'state': 'busy', 'reason': 'diagnostic_sender_busy', 'smtp_accepted': False,
                    'inbox_delivery_verified': False}
