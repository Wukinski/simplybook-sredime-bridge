import json
import os
from dataclasses import replace
from types import SimpleNamespace

import pytest

from booking_bridge.production_monitor import MonitorConfig, local_state_ready, main, monitor_once


@pytest.fixture
def config():
    return MonitorConfig(live_url='https://bridge.example.test/health/live',
                         ready_url='https://bridge.example.test/health/ready',
                         admin_key='private-monitor-key',
                         alert_url='https://alerts.example.test/private-marker')


class Reply:
    def __init__(self, status):
        self.status_code = status
        self.closed = False

    @property
    def text(self):
        raise AssertionError('Response bodies must not be read')

    def close(self):
        self.closed = True


def test_health_uses_verified_https_without_redirects_and_key_only_on_readiness(config):
    calls, replies = [], []
    def get(url, **kwargs):
        calls.append((url, kwargs))
        reply = Reply(200)
        replies.append(reply)
        return reply
    result = monitor_once(config, http_get=get)
    assert result['healthy'] is True and result['alert'] == 'not_requested'
    assert len(calls) == 2 and all(reply.closed for reply in replies)
    assert 'headers' not in calls[0][1]
    assert calls[1][1]['headers'] == {'X-API-Key': config.admin_key}
    assert all(row[1]['allow_redirects'] is False and row[1]['verify'] is True for row in calls)
    assert config.admin_key not in json.dumps(result) and 'example.test' not in json.dumps(result)


@pytest.mark.parametrize('url', ['http://bridge.example.test/ready', 'https://user:secret@example.test/ready',
                               'https://example.test/ready?token=secret', 'https://example.test/ready#fragment',
                               'https://example.test:invalid/ready', ''])
def test_invalid_configuration_does_not_dispatch_any_network_request(config, url):
    def forbidden(*args, **kwargs):
        raise AssertionError('Invalid configuration crossed network boundary')
    with pytest.raises(ValueError, match='monitor_configuration_invalid'):
        monitor_once(replace(config, ready_url=url), http_get=forbidden)


def test_redirect_and_exception_are_fixed_failures_without_exception_text(config):
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        if len(calls) == 1:
            return Reply(302)
        raise RuntimeError('private-body private-monitor-key https://sensitive.invalid')
    result = monitor_once(config, http_get=get)
    assert result['healthy'] is False
    assert [row['reason'] for row in result['checks']] == ['liveness_unavailable', 'readiness_unavailable']
    assert 'private' not in json.dumps(result) and 'sensitive' not in json.dumps(result)


def test_alert_is_disabled_by_default_and_explicit_alert_contains_only_fixed_codes(config):
    posted = []
    def post(url, **kwargs):
        posted.append((url, kwargs))
        return Reply(202)
    get = lambda *args, **kwargs: Reply(503)
    result = monitor_once(config, http_get=get, http_post=post)
    assert result['alert'] == 'not_requested' and posted == []
    result = monitor_once(config, http_get=get, http_post=post, send_alert=True)
    assert result['alert'] == 'sent' and len(posted) == 1
    body = posted[0][1]['json']
    assert body == {'service': 'booking_bridge', 'healthy': False,
                    'reasons': ['liveness_unavailable', 'readiness_unavailable']}
    assert 'headers' not in posted[0][1] and posted[0][1]['allow_redirects'] is False
    assert config.admin_key not in json.dumps(posted)


def test_healthy_monitor_never_sends_an_alert(config):
    def forbidden(*args, **kwargs):
        raise AssertionError('No healthy alert should be sent')
    result = monitor_once(config, send_alert=True, http_get=lambda *a, **k: Reply(200), http_post=forbidden)
    assert result['healthy'] is True and result['alert'] == 'not_needed'


def test_disk_backup_and_tls_thresholds_identify_attention_without_exposing_paths(config, tmp_path, now):
    backup = tmp_path / 'private-backup.sqlite'
    backup.write_bytes(b'synthetic-nonempty-backup')
    os.utime(backup, (now - 8000, now - 8000))
    selected = replace(config, disk_path=tmp_path, min_free_bytes=100, min_free_percent=10,
                       backup_path=backup, tls_host='bridge.example.test')
    result = monitor_once(selected, clock=lambda: now, http_get=lambda *a, **k: Reply(200),
                          disk_usage=lambda p: SimpleNamespace(total=1000, free=80),
                          tls_expiry=lambda host, timeout: now + 2 * 86400)
    assert [row['reason'] for row in result['checks'][-3:]] == ['disk_space_low', 'backup_stale', 'tls_expiring']
    assert 'private-backup' not in json.dumps(result) and str(tmp_path) not in json.dumps(result)


def test_future_backup_and_unverified_tls_fail_closed(config, tmp_path, now):
    backup = tmp_path / 'backup.sqlite'
    backup.write_bytes(b'backup')
    os.utime(backup, (now + 600, now + 600))
    def failed_tls(*args):
        raise RuntimeError('private-certificate-host')
    result = monitor_once(replace(config, backup_path=backup, tls_host='bridge.example.test'),
                          clock=lambda: now, http_get=lambda *a, **k: Reply(200), tls_expiry=failed_tls)
    assert [row['reason'] for row in result['checks'][-2:]] == ['backup_timestamp_future', 'tls_check_unavailable']
    assert 'private-certificate-host' not in json.dumps(result)


def test_local_state_check_never_creates_missing_database(tmp_path, now):
    missing = tmp_path / 'absent' / 'bridge.sqlite'
    assert local_state_ready(missing, now=now) is False
    assert not missing.parent.exists()


def test_local_state_reuses_current_incident_and_freshness_rules_without_mutation(store, now):
    store.put('heartbeat', True, now)
    store.put('health', {'open_issues': 0, 'old_queued': 0}, now)
    baseline = store.path.read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError('Local state healthcheck must not request HTTP')
    report = monitor_once(MonitorConfig(local_state=store.path), clock=lambda: now, http_get=forbidden)
    assert report['healthy'] is True and store.path.read_bytes() == baseline
    assert local_state_ready(store.path, now=now + 121) is False
    store.issue('new-incident', 'synthetic_error', now)
    assert local_state_ready(store.path, now=now) is False


def test_cli_missing_configuration_is_sanitized_and_has_failure_exit(monkeypatch, capsys):
    for key in ('BRIDGE_MONITOR_LIVE_URL', 'BRIDGE_MONITOR_READY_URL', 'BRIDGE_MONITOR_ADMIN_KEY'):
        monkeypatch.delenv(key, raising=False)
    assert main([]) == 2
    output = json.loads(capsys.readouterr().out)
    assert output['checks'] == [{'check': 'configuration', 'ok': False, 'reason': 'monitor_configuration_invalid'}]


@pytest.mark.parametrize('hold', ['embedded', 'adjacent'])
def test_recent_health_cannot_make_a_quarantined_restore_healthy(store, now, hold):
    store.put('heartbeat', True, now)
    store.put('health', {'open_issues': 0, 'old_queued': 0}, now)
    if hold == 'embedded':
        store.put('recovery-hold', {'remote_reconciliation_required': True}, now)
    else:
        from pathlib import Path
        Path(str(store.path) + '.recovery.json').write_text('{"worker_start_allowed":false}')
    assert store.is_ready(now) is False  # The shared readiness gate also honors restore holds.
    before = store.path.read_bytes()
    report = monitor_once(MonitorConfig(local_state=store.path), clock=lambda: now)
    assert report['healthy'] is False
    assert report['checks'] == [{'check': 'worker_state', 'ok': False, 'reason': 'worker_state_not_ready'}]
    assert store.path.read_bytes() == before
