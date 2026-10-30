import copy
from dataclasses import replace
import json
import smtplib
import sqlite3

import pytest

from booking_bridge.deploy import operations_monitor as runner
from booking_bridge.model import Review
from booking_bridge.watchdog_alerts import RECIPIENT, SMTPConfig, SMTPResult

NOW = 1793358000


@pytest.fixture(autouse=True)
def no_real_smtp(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError('Real SMTP forbidden in operations tests')
    monkeypatch.setattr(smtplib, 'SMTP', blocked)
    monkeypatch.setattr(smtplib, 'SMTP_SSL', blocked)


@pytest.fixture
def config(tmp_path):
    return {'scope': 'external', 'live_url': 'https://synthetic-booking.invalid/health/live',
            'ready_url': '', 'admin_key_file': None, 'tls_host': 'synthetic-booking.invalid',
            'tls_min_days': 2, 'local_state': None, 'disk_path': None, 'backup_status_file': None,
            'backup_max_age': 7200, 'state_directory': str(tmp_path / 'monitor'),
            'restore_status_file': None, 'restore_max_age': 172800,
            'smtp_env_file': None, 'failure_threshold': 2, 'recovery_threshold': 2}


@pytest.fixture
def smtp(tmp_path):
    password = tmp_path / 'password'
    password.write_text('SYNTHETIC_PASSWORD_DO_NOT_EMIT'); password.chmod(0o600)
    return SMTPConfig('smtp.synthetic.invalid', 465, 'synthetic', password, 'bridge@synthetic.invalid')


def report(*, healthy=False, now=NOW, code='liveness_unavailable'):
    return {'schema_version': 1, 'checked_at': now, 'scope': 'external', 'healthy': healthy,
            'checks': [{'check': 'liveness', 'ok': healthy, 'reason': 'ok' if healthy else code}],
            'repairs_enabled': False}


class Response:
    def __init__(self, status):
        self.status_code = status
        self.closed = False

    def close(self):
        self.closed = True


def test_public_probe_checks_liveness_and_tls_without_claiming_readiness(config):
    responses, calls = [], []
    def get(url, **options):
        calls.append((url, options)); response = Response(200); responses.append(response); return response
    result = runner.probe(config, now=NOW, http_get=get, tls_expiry=lambda *_: NOW + 7 * 86400)
    assert result['healthy'] and not result['readiness_checked']
    assert [row['check'] for row in result['checks']] == ['liveness', 'tls']
    assert calls[0][1]['verify'] is True and calls[0][1]['allow_redirects'] is False
    assert 'headers' not in calls[0][1] and all(response.closed for response in responses)
    assert 'synthetic-booking' not in json.dumps(result)


def test_auth_readiness_and_redirect_failures_are_distinct_fixed_codes(config, tmp_path):
    secret = tmp_path / 'admin-key'
    secret.write_text('x' * 40); secret.chmod(0o600)
    config.update(ready_url='https://synthetic-booking.invalid/health/ready', admin_key_file=str(secret))
    def get(url, **options):
        if url.endswith('/ready'):
            assert options['headers'] == {'X-API-Key': 'x' * 40}
            return Response(403)
        return Response(302)
    result = runner.probe(config, now=NOW, http_get=get, tls_expiry=lambda *_: NOW + 6 * 86400)
    assert not result['healthy'] and result['readiness_checked']
    assert {row['reason'] for row in result['checks']} == {'liveness_unavailable', 'readiness_unavailable', 'ok'}
    assert 'x' * 40 not in json.dumps(result)


@pytest.mark.parametrize('expiry', [NOW + 86400, float('nan'), None])
def test_short_certificate_and_invalid_expiry_are_reported(config, expiry):
    result = runner.probe(config, now=NOW, http_get=lambda *a, **k: Response(200), tls_expiry=lambda *_: expiry)
    assert not result['healthy']
    assert result['checks'][-1]['reason'] in ('tls_expiring', 'tls_check_unavailable')


def test_external_scope_cannot_claim_its_own_disk_is_the_vps(config):
    config['disk_path'] = '/'
    with pytest.raises(Review, match='must_not_claim_vps_local_checks'):
        runner.validate(config)


@pytest.mark.parametrize('changes,expected', [
    ({}, 'ok'), ({'remote_readback_verified': False}, 'offhost_backup_failed'),
    ({'off_host_export_performed': False}, 'offhost_backup_failed'),
    ({'status': 'running'}, 'offhost_backup_failed'),
    ({'completed_at': NOW - 7201}, 'offhost_backup_stale'),
    ({'completed_at': NOW + 1}, 'offhost_backup_stale'),
    ({'completed_at': None}, 'offhost_backup_unavailable'),
])
def test_backup_freshness_requires_verified_remote_copy(tmp_path, changes, expected):
    path = tmp_path / 'backup-status.json'
    data = {'schema_version': 1, 'status': 'verified', 'completed_at': NOW,
            'off_host_export_performed': True, 'remote_readback_verified': True}
    data.update(changes); path.write_text(json.dumps(data)); path.chmod(0o600)
    assert runner.backup_status_reason(path, 7200, NOW) == expected


def test_verified_backup_is_not_a_claim_of_recent_restore(tmp_path):
    path = tmp_path / 'backup-status.json'
    data = {'schema_version': 1, 'status': 'verified', 'completed_at': NOW,
            'off_host_export_performed': True, 'remote_readback_verified': True,
            'restore_drill_performed': False}
    path.write_text(json.dumps(data)); path.chmod(0o600)
    assert runner.backup_status_reason(path, 172800, NOW, restore_drill=True) == 'offhost_restore_failed'
    data['restore_drill_performed'] = True
    path.write_text(json.dumps(data))
    assert runner.backup_status_reason(path, 172800, NOW, restore_drill=True) == 'ok'
    assert runner.backup_status_reason(path, 172800, NOW + 172801, restore_drill=True) == 'offhost_restore_stale'


def accepted(config, message):
    assert message['To'] == RECIPIENT and message['From'] == config.from_address
    assert message.get('Cc') is None and message.get('Bcc') is None
    assert 'automatska popravka' in message.get_content()
    return SMTPResult('accepted', 'smtp_accepted')


def test_failure_threshold_restart_dedup_and_fixed_recipient(tmp_path, smtp):
    path = tmp_path / 'outbox.sqlite'
    first = runner.MonitorOutbox(path)
    assert not first.observe(report())['reserved']
    second = runner.MonitorOutbox(path)
    assert second.observe(report(now=NOW + 60))['reserved']
    assert second.observe(report(now=NOW + 120))['reason'] == 'already_pending'
    sent = second.send_one(smtp, now=NOW + 120, sender=accepted)
    assert sent['state'] == 'accepted' and not sent['inbox_delivery_verified']
    assert runner.MonitorOutbox(path).observe(report(now=NOW + 180))['reason'] == 'cooldown'
    assert second.send_one(smtp, now=NOW + 180, sender=accepted)['state'] == 'idle'
    with sqlite3.connect(path) as connection:
        assert connection.execute('SELECT COUNT(*) FROM monitor_attempts').fetchone()[0] == 1


def test_two_successes_supersede_unsent_failure_and_reserve_single_recovery(tmp_path, smtp):
    outbox = runner.MonitorOutbox(tmp_path / 'outbox.sqlite')
    outbox.observe(report(), failure_threshold=1)
    assert not outbox.observe(report(healthy=True, now=NOW + 60))['reserved']
    assert outbox.observe(report(healthy=True, now=NOW + 120))['reserved']
    assert not outbox.observe(report(healthy=True, now=NOW + 180))['reserved']
    messages = []
    def sender(config, message):
        messages.append(message); return accepted(config, message)
    assert outbox.send_one(smtp, now=NOW + 180, sender=sender)['state'] == 'accepted'
    assert len(messages) == 1 and 'ponovo dostupan' in messages[0]['Subject']
    with sqlite3.connect(outbox.path) as connection:
        assert dict(connection.execute('SELECT state,COUNT(*) FROM monitor_alerts GROUP BY state')) == {'accepted': 1, 'superseded': 1}


def test_uncertain_smtp_is_never_replayed_after_restart_or_cooldown(tmp_path, smtp):
    path = tmp_path / 'outbox.sqlite'
    outbox = runner.MonitorOutbox(path)
    outbox.observe(report(), failure_threshold=1)
    def uncertain(config, message):
        raise RuntimeError('SYNTHETIC_TRANSPORT_SECRET')
    result = outbox.send_one(smtp, now=NOW, sender=uncertain)
    assert result['state'] == 'uncertain' and 'SYNTHETIC' not in json.dumps(result)
    resumed = runner.MonitorOutbox(path)
    assert resumed.observe(report(now=NOW + 7200))['reason'] == 'uncertain_requires_review'
    assert resumed.send_one(smtp, now=NOW + 7200, sender=accepted)['state'] == 'idle'


def test_retry_backoff_and_exhaustion_are_bounded(tmp_path, smtp):
    outbox = runner.MonitorOutbox(tmp_path / 'outbox.sqlite')
    outbox.observe(report(), failure_threshold=1)
    def rejected(*_):
        return SMTPResult('retryable', 'smtp_connect_failed')
    assert outbox.send_one(smtp, now=NOW, sender=rejected)['state'] == 'retry'
    assert outbox.send_one(smtp, now=NOW + 59, sender=rejected)['state'] == 'idle'
    assert outbox.send_one(smtp, now=NOW + 60, sender=rejected)['state'] == 'retry'
    assert outbox.send_one(smtp, now=NOW + 179, sender=rejected)['state'] == 'idle'
    assert outbox.send_one(smtp, now=NOW + 180, sender=rejected)['state'] == 'exhausted'
    assert outbox.send_one(smtp, now=NOW + 360, sender=rejected)['state'] == 'idle'


def test_interrupted_sending_attempt_becomes_uncertain_before_any_new_send(tmp_path, smtp):
    outbox = runner.MonitorOutbox(tmp_path / 'outbox.sqlite')
    outbox.observe(report(), failure_threshold=1)
    with sqlite3.connect(outbox.path) as connection:
        identifier = connection.execute('SELECT id FROM monitor_alerts').fetchone()[0]
        connection.execute("UPDATE monitor_alerts SET state='sending',attempts=1")
        connection.execute('INSERT INTO monitor_attempts VALUES(?,?,?,?,?)', (identifier, 1, NOW, 'sending', None))
    assert outbox.send_one(smtp, now=NOW + 60, sender=accepted)['state'] == 'idle'
    with sqlite3.connect(outbox.path) as connection:
        assert connection.execute('SELECT state FROM monitor_alerts').fetchone()[0] == 'uncertain'
        assert connection.execute('SELECT state FROM monitor_attempts').fetchone()[0] == 'uncertain'


def test_ten_message_daily_limit_applies_across_restarts(tmp_path, smtp):
    path = tmp_path / 'outbox.sqlite'
    day = int(NOW // 86400) * 86400 + 1
    for number in range(10):
        outbox = runner.MonitorOutbox(path)
        moment = day + 3601 * number
        assert outbox.observe(report(now=moment), failure_threshold=1)['reserved']
        assert outbox.send_one(smtp, now=moment, sender=accepted)['state'] == 'accepted'
    outbox = runner.MonitorOutbox(path)
    assert outbox.observe(report(now=day + 36010), failure_threshold=1)['reason'] == 'daily_limit'
    assert outbox.send_one(smtp, now=day + 36010, sender=accepted)['state'] == 'daily_limit'


def test_outbox_rejects_booking_database_without_touching_it(store):
    before = store.path.read_bytes()
    with pytest.raises(Review, match='separate_outbox_required'):
        runner.MonitorOutbox(store.path)
    assert store.path.read_bytes() == before


def test_probe_run_without_send_flag_never_reads_smtp(config, monkeypatch):
    monkeypatch.setattr(runner, 'probe', lambda _: report())
    def forbidden(*_args, **_kwargs):
        raise AssertionError('No credential read permitted without send flag')
    monkeypatch.setattr(runner.SMTPConfig, 'from_env', forbidden)
    result = runner.run(config)
    assert result['alert']['state'] == 'not_requested'


def test_recipient_change_is_rejected_before_smtp(smtp):
    with pytest.raises(Review):
        replace(smtp, recipient='wrong@synthetic.invalid').validate()
