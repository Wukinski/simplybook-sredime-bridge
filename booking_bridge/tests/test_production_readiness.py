import copy
import hashlib
import json
from datetime import datetime, timezone

import pytest

from booking_bridge.model import Review
from booking_bridge.production_readiness import (GATES, MAX_AGE, inspect_evidence,
                                                profile_digest, template)
from booking_bridge.tests.test_preflight import configured


def evidence_for(settings, directory, now):
    directory.mkdir(exist_ok=True)
    data = template(settings)
    artifact = directory/'review.txt'
    artifact.write_text('Synthetic operator-reviewed evidence. Not a live attestation.')
    for code in GATES:
        data['checks'][code] = {'status': 'verified', 'reviewed': True, 'artifact': 'review.txt',
            'sha256': hashlib.sha256(artifact.read_bytes()).hexdigest(),
            'observed_at': datetime.fromtimestamp(now, timezone.utc).isoformat()}
    path = directory/'readiness.json'
    path.write_text(json.dumps(data))
    return path, data


def test_pending_template_cannot_grant_production(settings, tmp_path, now):
    path = tmp_path/'readiness.json'
    path.write_text(json.dumps(template(settings)))
    report = inspect_evidence(settings, path, now=now)
    assert report['ready'] is False
    assert report['checks'][0]['ok'] is True
    assert {row['status'] for row in report['checks'][1:]} == {'pending'}
    assert report['external_validation_performed'] is False


def test_evidence_binds_exact_profile_without_exposing_configuration(settings, tmp_path, now):
    path, data = evidence_for(settings, tmp_path, now)
    before = path.read_bytes()
    assert inspect_evidence(settings, path, now=now)['ready'] is True
    settings.policies['pending'] = 'wait'
    assert inspect_evidence(settings, path, now=now)['ready'] is False
    assert path.read_bytes() == before
    output = json.dumps(inspect_evidence(settings, path, now=now))
    assert str(path) not in output and settings.webhook_secret not in output
    assert 'synthetic-employee' not in output


@pytest.mark.parametrize('field,value', [
    ('mode', 'production'), ('reads_enabled', True), ('require_subminute_availability', True),
    ('snapshot_max_age', 300)])
def test_execution_policy_changes_invalidate_evidence(settings, field, value):
    before = profile_digest(settings)
    setattr(settings, field, value)
    assert profile_digest(settings) != before


@pytest.mark.parametrize('change,expected', [
    ({'reviewed': False}, 'invalid'),
    ({'artifact': '../outside.txt'}, 'invalid'),
    ({'sha256': '0'*64}, 'changed'),
    ({'observed_at': '2000-01-01T00:00:00+00:00'}, 'expired'),
    ({'observed_at': '2099-01-01T00:00:00+00:00'}, 'expired'),
    ({'observed_at': '2026-01-01'}, 'invalid')])
def test_unreviewed_changed_traversal_and_stale_artifacts_block(settings, tmp_path, now, change, expected):
    path, data = evidence_for(settings, tmp_path, now)
    data['checks']['activation'].update(change)
    path.write_text(json.dumps(data))
    report = inspect_evidence(settings, path, now=now)
    assert report['ready'] is False
    row = next(r for r in report['checks'] if r['code'] == 'production_activation')
    assert row['status'] == expected


def test_artifact_is_rechecked_after_success(settings, tmp_path, now):
    path, _ = evidence_for(settings, tmp_path, now)
    assert inspect_evidence(settings, path, now=now)['ready']
    (tmp_path/'review.txt').write_text('changed after review')
    assert not inspect_evidence(settings, path, now=now)['ready']


def test_malformed_or_duplicate_manifest_is_redacted(settings, tmp_path, now):
    path = tmp_path/'readiness.json'
    for body in ('[]', 'null', '{"raw":"SECRET_VALUE","raw":0}'):
        path.write_text(body)
        report = inspect_evidence(settings, path, now=now)
        assert not report['ready']
        assert 'SECRET_VALUE' not in json.dumps(report)


def test_production_preflight_keeps_latency_gate_even_with_all_reviewed_evidence(settings, store, tmp_path, now):
    from booking_bridge.preflight import inspect
    from booking_bridge.store import Store
    Store(settings.state/'bridge.sqlite')
    configured_env = configured(settings)
    settings.require_subminute_availability = True
    path, _ = evidence_for(settings, tmp_path/'evidence', now)
    report = inspect(settings, 'production', configured_env, readiness_path=path, now=now)
    assert report['configuration_ready'] is False
    assert {'runtime_configuration', 'subminute_availability_transport'} <= {
        row['code'] for row in report['checks'] if not row['ok']}
    assert all(row['ok'] for row in report['checks'] if row['code'].startswith('production_'))


def test_existing_configuration_approvals_alone_never_allow_production(settings, store):
    from booking_bridge.preflight import inspect
    report = inspect(settings, 'production', configured(settings))
    assert report['configuration_ready'] is False
    assert next(r for r in report['checks'] if r['code'] == 'production_evidence_manifest')['ok'] is False


def test_production_worker_blocks_before_claiming_any_event(settings, store, gateway, worker, event, now, monkeypatch):
    settings.mode = 'production'
    monkeypatch.delenv('BRIDGE_PRODUCTION_READINESS_FILE', raising=False)
    store.ingest(event, now)
    before = store.rows('SELECT state,attempts FROM events')
    with pytest.raises(Review, match='production_evidence'):
        worker.once(now)
    assert store.rows('SELECT state,attempts FROM events') == before
    assert not gateway.calls


def test_production_transport_cannot_bypass_evidence_with_direct_write(settings, monkeypatch):
    from booking_bridge.simplybook import Gateway
    configured(settings)
    settings.mode = 'production'
    monkeypatch.delenv('BRIDGE_PRODUCTION_READINESS_FILE', raising=False)
    gateway = object.__new__(Gateway)
    gateway.settings = settings
    class Forbidden:
        def request(self, *args, **kwargs):
            raise AssertionError('No write may escape without reviewed production evidence')
    gateway.transport = Forbidden()
    with pytest.raises(Review, match='production_evidence'):
        gateway.write('POST', '/admin/bookings', {})


def test_complete_review_can_pass_offline_but_never_claims_external_validation(settings, tmp_path, now):
    from booking_bridge.preflight import inspect
    from booking_bridge.store import Store
    env = configured(settings)
    settings.mode = 'production'
    Store(settings.state/'bridge.sqlite')
    path, _ = evidence_for(settings, tmp_path/'evidence', now)
    report = inspect(settings, 'production', env, readiness_path=path, now=now)
    assert report['configuration_ready'] is True
    assert report['external_validation_performed'] is False


def test_own_started_intent_does_not_block_reviewed_transport_write(settings, tmp_path, monkeypatch):
    import time
    from booking_bridge.simplybook import Gateway
    from booking_bridge.store import Store
    configured(settings)
    settings.mode = 'production'
    store = Store(settings.state/'bridge.sqlite')
    store.execute("INSERT INTO intents VALUES('synthetic','e','create',NULL,'{}','[]','started',NULL,0)")
    path, _ = evidence_for(settings, tmp_path/'evidence', time.time())
    monkeypatch.setenv('BRIDGE_PRODUCTION_READINESS_FILE', str(path))
    gateway = object.__new__(Gateway)
    gateway.settings = settings
    calls = []
    class Transport:
        def request(self, *args):
            calls.append(args)
            return {'id': 123}
    gateway.transport = Transport()
    assert gateway.write('POST', '/admin/bookings', {}) == {'id': 123}
    assert len(calls) == 1
