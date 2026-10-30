import json
import smtplib
import sqlite3
import ssl
from dataclasses import replace
from pathlib import Path

import pytest

from booking_bridge.model import Review
from booking_bridge.watchdog_alerts import (DiagnosticOutbox, RECIPIENT, SMTPConfig, SMTPResult,
                                          _message, send_smtp)


NOW = 1793199000


@pytest.fixture(autouse=True)
def no_real_smtp(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Real SMTP is forbidden in unit tests')
    monkeypatch.setattr(smtplib, 'SMTP', forbidden)
    monkeypatch.setattr(smtplib, 'SMTP_SSL', forbidden)


@pytest.fixture
def config(tmp_path):
    secret = tmp_path/'smtp-password'
    secret.write_text('SYNTHETIC_SMTP_PASSWORD_MUST_NOT_PRINT\n')
    secret.chmod(0o600)
    return SMTPConfig('smtp.synthetic.invalid', 465, 'synthetic-user', secret, 'bridge@synthetic.invalid')


@pytest.fixture
def outbox(tmp_path):
    return DiagnosticOutbox(tmp_path/'diagnostic-outbox.sqlite')


def finding(severity='warning', reference='a'*64, code='source_queue_aged'):
    return {'code': code, 'severity': severity, 'refs': [reference]}


def accepted(config, message):
    assert str(message['To']) == RECIPIENT
    assert not message.get('Cc') and not message.get('Bcc')
    assert 'SYNTHETIC_SMTP_PASSWORD' not in message.as_string()
    return SMTPResult('accepted', 'smtp_accepted')


def test_config_is_explicit_strict_tls_and_only_approved_recipient(config):
    env = {'BRIDGE_DIAGNOSTIC_SMTP_HOST': config.host, 'BRIDGE_DIAGNOSTIC_SMTP_PORT': '465',
           'BRIDGE_DIAGNOSTIC_SMTP_USER': config.username, 'BRIDGE_DIAGNOSTIC_SMTP_PASSWORD_FILE': str(config.password_file),
           'BRIDGE_DIAGNOSTIC_SMTP_FROM_ADDRESS': config.from_address}
    assert SMTPConfig.from_env(env) == config
    assert 'SYNTHETIC_SMTP_PASSWORD_MUST_NOT_PRINT' not in repr(config)
    for change in ({'BRIDGE_DIAGNOSTIC_SMTP_PORT': '25'},
                   {'BRIDGE_DIAGNOSTIC_SMTP_RECIPIENT': 'other@synthetic.invalid'},
                   {'BRIDGE_DIAGNOSTIC_SMTP_FROM_ADDRESS': 'sender@synthetic.invalid\r\nBcc: bad@synthetic.invalid'},
                   {'BRIDGE_DIAGNOSTIC_SMTP_HOST': 'smtp.invalid\nprivate'}):
        with pytest.raises(Review, match='not_configured'):
            SMTPConfig.from_env({**env, **change})


def test_missing_smtp_keeps_reserved_alert_without_attempt_or_email_claim(outbox, config):
    alert = outbox.reserve([finding()], now=NOW)
    result = outbox.send_one(replace(config, password_file=Path('missing-synthetic-secret')), now=NOW)
    assert result['state'] == 'not_configured' and result['smtp_accepted'] is False
    pending = outbox.pending(now=NOW)
    assert pending[0]['id'] == alert['id'] and pending[0]['attempts'] == 0


@pytest.mark.parametrize('content', ['', '\n', '   \r\n'])
def test_empty_or_whitespace_password_fails_configuration_before_attempt_reservation(outbox, config, content):
    config.password_file.write_text(content)
    env = {'BRIDGE_DIAGNOSTIC_SMTP_HOST': config.host, 'BRIDGE_DIAGNOSTIC_SMTP_PORT': '465',
           'BRIDGE_DIAGNOSTIC_SMTP_USER': config.username,
           'BRIDGE_DIAGNOSTIC_SMTP_PASSWORD_FILE': str(config.password_file),
           'BRIDGE_DIAGNOSTIC_SMTP_FROM_ADDRESS': config.from_address}
    with pytest.raises(Review, match='not_configured'):
        SMTPConfig.from_env(env)
    outbox.reserve([finding()], now=NOW)
    assert outbox.send_one(config, now=NOW)['state'] == 'not_configured'
    assert outbox.pending(now=NOW)[0]['attempts'] == 0
    with sqlite3.connect(outbox.path) as connection:
        assert connection.execute('SELECT COUNT(*) FROM alert_attempts').fetchone()[0] == 0


def test_plain_utf8_template_contains_only_fixed_diagnostic_text_and_references(outbox, config):
    summary = {'assessment': 'operator_review', 'confidence': 'high', 'recommendation_codes': ['review_queue']}
    alert = outbox.reserve([finding()], summary, now=NOW)
    seen = []
    def send(config, message):
        seen.append(message)
        return accepted(config, message)
    result = outbox.send_one(config, sender=send, now=NOW)
    assert result['state'] == 'accepted' and result['smtp_accepted'] is True
    assert result['inbox_delivery_verified'] is False
    message = seen[0]
    assert message.get_content_type() == 'text/plain' and message.get_content_charset() == 'utf-8'
    assert 'Nije izvršena automatska popravka' in message.get_content()
    assert 'source_queue_aged' in message.get_content() and 'a'*64 in message.get_content()
    assert 'Pregledati red događaja' in message.get_content()
    assert '<diagnostic-'+alert['id']+'@' in str(message['Message-ID'])


def test_model_self_test_failure_uses_fixed_diagnostic_template_without_repair(outbox, config):
    outbox.reserve([finding(code='model_self_test_failed')], now=NOW)
    seen = []
    def send(config, message):
        seen.append(message.get_content())
        return accepted(config, message)
    assert outbox.send_one(config, sender=send, now=NOW)['smtp_accepted'] is True
    assert 'Dnevna sintetička provera dijagnostičkog modela nije uspela' in seen[0]
    assert 'model_self_test_failed' in seen[0]
    assert 'Nije izvršena automatska popravka' in seen[0]


def test_explicit_test_email_selection_never_sends_critical_backlog_instead(outbox, config):
    critical = outbox.reserve([finding('critical')], now=NOW)
    test = outbox.reserve([finding('info', code='diagnostic_test')], now=NOW+1)
    seen = []
    def send(config, message):
        seen.append(message.get_content())
        return accepted(config, message)
    result = outbox.send_one(config, alert_id=test['id'], sender=send, now=NOW+1)
    assert result['id'] == test['id'] and result['smtp_accepted'] is True
    assert 'diagnostic_test' in seen[0] and 'source_queue_aged' not in seen[0]
    assert [row['id'] for row in outbox.pending(now=NOW+1)] == [critical['id']]
    # An exact selection never falls back to another pending row.
    result = outbox.send_one(config, alert_id=test['id'], sender=send, now=NOW+2)
    assert result['state'] == 'idle' and len(seen) == 1


@pytest.mark.parametrize('input_change', ['recipient', 'extra_field', 'unknown_code', 'raw_reference', 'raw_summary', 'unknown_recommendation'])
def test_untrusted_headers_payload_text_or_model_fields_cannot_enter_outbox(outbox, input_change):
    item, summary = finding(), None
    if input_change == 'recipient':
        item['recipient'] = 'bad@synthetic.invalid'
    elif input_change == 'extra_field':
        item['evidence'] = 'private provider payload'
    elif input_change == 'unknown_code':
        item['code'] = 'PRIVATE_PAYLOAD'
    elif input_change == 'raw_reference':
        item['refs'] = ['https://secret.invalid/token']
    elif input_change == 'raw_summary':
        summary = {'assessment': 'operator_review', 'confidence': 'high', 'recommendation_codes': [], 'text': 'secret'}
    else:
        summary = {'assessment': 'operator_review', 'confidence': 'high', 'recommendation_codes': ['run_shell_repair']}
    with pytest.raises(Review):
        outbox.reserve([item], summary, now=NOW)
    assert outbox.pending(now=NOW) == []


def test_dedupe_cooldown_survives_restart_and_escalation_is_immediate(outbox, config):
    first = outbox.reserve([finding('warning')], now=NOW)
    assert outbox.send_one(config, sender=accepted, now=NOW)['state'] == 'accepted'
    restarted = DiagnosticOutbox(outbox.path)
    assert restarted.reserve([finding('warning')], now=NOW+100)['reason'] == 'cooldown'
    higher = restarted.reserve([finding('critical')], now=NOW+101)
    assert higher['reserved'] and higher['id'] != first['id']
    assert restarted.send_one(config, sender=accepted, now=NOW+101)['state'] == 'accepted'
    assert restarted.reserve([finding('critical')], now=NOW+3702)['reserved'] is True


def test_escalation_supersedes_unsent_lower_severity(outbox):
    outbox.reserve([finding('info')], now=NOW)
    high = outbox.reserve([finding('critical')], now=NOW+1)
    assert [row['id'] for row in outbox.pending(now=NOW+1)] == [high['id']]


def test_missing_configuration_does_not_accumulate_identical_hourly_pending_alerts(outbox):
    first = outbox.reserve([finding()], now=NOW)
    result = outbox.reserve([finding()], now=NOW+4000)
    assert result == {'reserved': False, 'id': first['id'], 'reason': 'already_pending'}
    assert len(outbox.pending(now=NOW+4000)) == 1


def test_daily_reservations_are_capped_including_higher_severity(outbox):
    for index in range(10):
        assert outbox.reserve([finding(reference=f'{index:064x}')], now=NOW+index)['reserved']
    assert outbox.reserve([finding('critical', reference='f'*64)], now=NOW+10)['reason'] == 'daily_limit'
    assert len(outbox.pending(now=NOW+10)) == 10


def test_retries_and_backoff_are_bounded_and_persist_across_restart(outbox, config):
    alert = outbox.reserve([finding()], now=NOW)
    calls = []
    def unavailable(config, message):
        calls.append(1)
        return SMTPResult('retryable', 'smtp_connect_failed')
    assert outbox.send_one(config, sender=unavailable, now=NOW)['state'] == 'retry'
    assert outbox.send_one(config, sender=unavailable, now=NOW+59)['state'] == 'idle'
    restarted = DiagnosticOutbox(outbox.path)
    assert restarted.send_one(config, sender=unavailable, now=NOW+60)['state'] == 'retry'
    assert restarted.send_one(config, sender=unavailable, now=NOW+180)['state'] == 'exhausted'
    assert restarted.send_one(config, sender=unavailable, now=NOW+1000)['state'] == 'idle'
    assert calls == [1, 1, 1]


def test_actual_attempt_daily_cap_includes_retries(tmp_path, config):
    outbox = DiagnosticOutbox(tmp_path/'outbox.sqlite', max_alerts_per_day=2)
    outbox.reserve([finding()], now=NOW)
    unavailable = lambda config, message: SMTPResult('retryable', 'smtp_connect_failed')
    assert outbox.send_one(config, sender=unavailable, now=NOW)['state'] == 'retry'
    assert outbox.send_one(config, sender=unavailable, now=NOW+60)['state'] == 'retry'
    assert outbox.send_one(config, sender=unavailable, now=NOW+180)['state'] == 'daily_limit'


@pytest.mark.parametrize('outcome', ['uncertain', 'raise', 'invalid_result'])
def test_ambiguous_data_or_unknown_sender_result_never_retries_even_after_cooldown(outbox, config, outcome):
    outbox.reserve([finding()], now=NOW)
    def ambiguous(config, message):
        if outcome == 'raise':
            raise RuntimeError('SYNTHETIC_PRIVATE_SMTP_RESPONSE')
        if outcome == 'invalid_result':
            return SMTPResult('accepted', 'smtp_connect_failed')
        return SMTPResult('uncertain', 'smtp_outcome_uncertain')
    result = outbox.send_one(config, sender=ambiguous, now=NOW)
    assert result['state'] == 'uncertain' and result['smtp_accepted'] is None
    assert 'SYNTHETIC_PRIVATE' not in json.dumps(result)
    restarted = DiagnosticOutbox(outbox.path)
    assert restarted.pending(now=NOW+10000) == []
    assert restarted.reserve([finding()], now=NOW+10000)['reason'] == 'uncertain_requires_review'


def test_killed_smtp_attempt_is_uncertain_after_restart_and_not_replayed(outbox, config):
    outbox.reserve([finding()], now=NOW)
    def killed(config, message):
        raise SystemExit(99)
    with pytest.raises(SystemExit):
        outbox.send_one(config, sender=killed, now=NOW)
    restarted = DiagnosticOutbox(outbox.path)
    assert restarted.send_one(config, sender=accepted, now=NOW+10)['state'] == 'idle'
    with sqlite3.connect(outbox.path) as connection:
        assert connection.execute('SELECT state,last_reason FROM alert_outbox').fetchone() == ('uncertain', 'interrupted_smtp_attempt')


def test_outbox_refuses_booking_database_before_mutating_it(store):
    before = store.path.read_bytes()
    with pytest.raises(Review, match='separate_database'):
        DiagnosticOutbox(store.path)
    assert store.path.read_bytes() == before


class FakeSMTP:
    def __init__(self):
        self.calls = []
    def ehlo(self):
        self.calls.append('ehlo')
    def starttls(self, *, context):
        self.calls.append('starttls')
        assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
    def login(self, username, password):
        self.calls.append('login')
        assert password == 'SYNTHETIC_SMTP_PASSWORD_MUST_NOT_PRINT'
    def mail(self, address):
        self.calls.append('mail'); return 250, b'ok'
    def rcpt(self, address):
        self.calls.append('rcpt'); assert address == RECIPIENT; return 250, b'ok'
    def data(self, body):
        self.calls.append('data'); assert isinstance(body, bytes); return 250, b'accepted'
    def quit(self):
        self.calls.append('quit')
    def close(self):
        self.calls.append('close')


def message_for(config):
    payload = {'findings': [finding()], 'summary': None}
    return _message(config, {'id': 'a'*32, 'payload': json.dumps(payload), 'created': NOW, 'severity': 2})


@pytest.mark.parametrize('port', [465, 587])
def test_smtp_uses_verified_ssl_or_starttls_before_authentication(config, port):
    config = replace(config, port=port)
    smtp = FakeSMTP()
    def factory(host, port, **options):
        assert options['timeout'] == 20
        if port == 465:
            assert options['context'].check_hostname and options['context'].verify_mode == ssl.CERT_REQUIRED
        return smtp
    assert send_smtp(config, message_for(config), smtp_ssl_factory=factory, smtp_factory=factory) == SMTPResult('accepted', 'smtp_accepted')
    if port == 587:
        assert smtp.calls[:4] == ['ehlo', 'starttls', 'ehlo', 'login']
    assert smtp.calls[-4:] == ['mail', 'rcpt', 'data', 'quit']


@pytest.mark.parametrize('failure,expected', [('disconnect', 'uncertain'), ('temporary_rejection', 'retryable'),
                                          ('permanent_rejection', 'rejected'), ('quit_failure', 'accepted')])
def test_smtp_data_uncertainty_is_distinct_from_explicit_rejection(config, failure, expected):
    class FailedSMTP(FakeSMTP):
        def data(self, body):
            if failure == 'disconnect':
                raise smtplib.SMTPServerDisconnected('SYNTHETIC_PRIVATE_RESPONSE')
            if failure == 'temporary_rejection':
                raise smtplib.SMTPDataError(451, b'SYNTHETIC_PRIVATE_RESPONSE')
            if failure == 'permanent_rejection':
                raise smtplib.SMTPDataError(550, b'SYNTHETIC_PRIVATE_RESPONSE')
            return super().data(body)
        def quit(self):
            if failure == 'quit_failure':
                raise OSError('SYNTHETIC_PRIVATE_RESPONSE')
            super().quit()
    result = send_smtp(config, message_for(config), smtp_ssl_factory=lambda *a, **k: FailedSMTP())
    assert result.status == expected and 'SYNTHETIC_PRIVATE_RESPONSE' not in repr(result)


def test_starttls_failure_never_falls_back_to_clear_authentication(config):
    class FailedTLS(FakeSMTP):
        def starttls(self, *, context):
            self.calls.append('tls_failed')
            raise ssl.SSLCertVerificationError('synthetic certificate failure')
    smtp = FailedTLS()
    result = send_smtp(replace(config, port=587), message_for(config), smtp_factory=lambda *a, **k: smtp)
    assert result.status == 'retryable'
    assert 'login' not in smtp.calls and 'data' not in smtp.calls


def test_unexpected_data_reply_is_uncertain_instead_of_claimed_acceptance(config):
    class OddSMTP(FakeSMTP):
        def data(self, body):
            return 200, b'not the required final DATA response'
    result = send_smtp(config, message_for(config), smtp_ssl_factory=lambda *a, **k: OddSMTP())
    assert result == SMTPResult('uncertain', 'smtp_outcome_uncertain')
