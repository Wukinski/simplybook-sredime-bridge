import json
import time

import pytest
from fastapi.testclient import TestClient

from booking_bridge.api import create_app


@pytest.mark.parametrize('hold', ['embedded', 'adjacent'])
def test_api_readiness_rejects_restored_state_even_with_fresh_health(settings, store, hold):
    now = time.time()
    store.put('heartbeat', True, now)
    store.put('health', {'open_issues': 0, 'old_queued': 0}, now)
    assert store.is_ready(now) is True
    if hold == 'embedded':
        store.put('recovery-hold', {'remote_reconciliation_required': True}, now)
    else:
        from pathlib import Path
        Path(str(store.path) + '.recovery.json').write_text('{}')
    with TestClient(create_app(settings, store)) as client:
        assert client.get('/health/live').status_code == 200
        response = client.get('/health/ready', headers={'X-API-Key': settings.admin_key})
        assert response.status_code == 503
        assert response.json() == {'detail': 'operator_attention_required'}


def test_readiness_sees_incident_newer_than_health_summary(settings, store):
    store.put('heartbeat', True)
    store.put('health', {'open_issues': 0, 'old_queued': 0})
    with TestClient(create_app(settings, store)) as client:
        headers = {'X-API-Key': settings.admin_key}
        assert client.get('/health/ready').status_code == 401
        assert client.get('/health/ready', headers=headers).status_code == 200
        store.issue('new-incident', 'synthetic_failure')
        response = client.get('/health/ready', headers=headers)
        assert response.status_code == 503
        assert response.json() == {'detail': 'operator_attention_required'}
        assert client.get('/health/live').status_code == 200
        store.execute('UPDATE issues SET resolved=1')
        assert client.get('/health/ready', headers=headers).status_code == 200


@pytest.mark.parametrize('key', ['health', 'heartbeat'])
@pytest.mark.parametrize('condition', ['missing', 'stale', 'future'])
def test_readiness_requires_both_fresh_timestamps(settings, store, key, condition):
    now = time.time()
    store.put('heartbeat', True, now)
    store.put('health', {'open_issues': 0, 'old_queued': 0}, now)
    if condition == 'missing':
        store.execute('DELETE FROM cache WHERE key=?', (key,))
    else:
        store.execute('UPDATE cache SET updated=? WHERE key=?',
                      (now - 121 if condition == 'stale' else now + 60, key))
    with TestClient(create_app(settings, store)) as client:
        assert client.get('/health/ready', headers={'X-API-Key': settings.admin_key}).status_code == 503


@pytest.mark.parametrize('value', [None, [], {}, {'open_issues': 0},
    {'open_issues': False, 'old_queued': 0}, {'open_issues': '0', 'old_queued': 0},
    {'open_issues': 1, 'old_queued': 0}, {'open_issues': 0, 'old_queued': 1}])
def test_malformed_or_unhealthy_summary_is_not_ready(store, value):
    now = time.time()
    store.put('heartbeat', True, now)
    store.put('health', value, now)
    assert store.is_ready(now) is False


def test_invalid_cached_json_fails_closed(store):
    store.put('heartbeat', True)
    store.put('health', {})
    store.execute("UPDATE cache SET value='invalid-json' WHERE key='health'")
    assert store.is_ready() is False


def test_readiness_accepts_exact_freshness_boundary(store):
    store.put('heartbeat', True, 1000)
    store.put('health', {'open_issues': 0, 'old_queued': 0}, 1000)
    assert store.is_ready(now=1120) is True
    assert store.is_ready(now=1120.01) is False
