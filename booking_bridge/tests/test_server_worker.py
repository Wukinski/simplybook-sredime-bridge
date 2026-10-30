import json

import pytest
from fastapi.testclient import TestClient

from booking_bridge.api import create_app
from booking_bridge.model import Review
from booking_bridge.server_worker import main, run_loop
from booking_bridge.simplybook import SimulatedGateway
from booking_bridge.store import Store
from booking_bridge.worker import Worker
from booking_bridge.tests.test_api import signed


def test_ingress_original_create_is_durable_before_shared_worker_loop(settings, store, worker, gateway, event, now):
    body = json.dumps(event).encode()
    with TestClient(create_app(settings, store)) as client:
        for _ in range(2):
            assert client.post('/sredime/webhook', content=body, headers=signed(settings, body)).status_code == 202
        assert not gateway.calls
        assert store.rows('SELECT state FROM events') == [{'state': 'queued'}]
        run_loop(settings, store, worker, gateway, clock=lambda: now, max_iterations=1)
        assert store.rows('SELECT state FROM events') == [{'state': 'done'}]
        assert [row[0] for row in gateway.calls] == ['create']
        assert store.rows("SELECT * FROM intents WHERE state!='done'") == []
        assert len(store.rows('SELECT * FROM links')) == 1


@pytest.mark.parametrize('crash_stage', ['before_write', 'after_remote_commit', 'before_readback', 'after_complete_before_record'])
def test_restart_at_durable_write_stages_never_creates_a_duplicate(settings, store, event, now, crash_stage):
    class CrashingGateway(SimulatedGateway):
        fail = True
        def create(self, desired):
            if self.fail and crash_stage == 'before_write':
                raise SystemExit(99)
            target = super().create(desired)
            if self.fail and crash_stage == 'after_remote_commit':
                raise SystemExit(99)
            return target
        def detail(self, target):
            if self.fail and crash_stage == 'before_readback':
                raise SystemExit(99)
            return super().detail(target)
    gateway = CrashingGateway()
    worker = Worker(settings, store, gateway)
    if crash_stage == 'after_complete_before_record':
        original = worker.record
        def crash(*args):
            raise SystemExit(99)
        worker.record = crash
    store.ingest(event, now)
    with pytest.raises(SystemExit):
        run_loop(settings, store, worker, gateway, clock=lambda: now, max_iterations=1)
    assert store.rows('SELECT state FROM events') == [{'state': 'working'}]
    gateway.fail = False
    restarted = Store(store.path)
    run_loop(settings, restarted, Worker(settings, restarted, gateway), gateway,
             clock=lambda: now+10, max_iterations=1)
    assert len(gateway.items) <= 1
    if crash_stage in ('before_write', 'after_remote_commit'):
        assert restarted.rows('SELECT state FROM events') == [{'state': 'review'}]
        assert restarted.rows("SELECT COUNT(*) AS n FROM intents WHERE state!='done'")[0]['n'] == 1
    else:
        assert restarted.rows('SELECT state FROM events') == [{'state': 'done'}]
        assert restarted.rows("SELECT * FROM intents WHERE state!='done'") == []


def test_wrapper_rejects_simulation_template_without_state_or_gateway(tmp_path, monkeypatch, capsys):
    from booking_bridge.model import Settings
    state = tmp_path/'uncreated'
    monkeypatch.setattr(Settings, 'load', lambda *args, **kwargs: Settings(state=state))
    monkeypatch.setenv('BRIDGE_PRODUCTION_READINESS_FILE', 'unused')
    assert main(['--config', str(tmp_path/'config.json'), '--readiness', str(tmp_path/'readiness.json')]) == 2
    assert not state.exists()
    assert 'server_worker_review_required' in capsys.readouterr().out


def test_wrapper_rejects_unreviewed_production_before_client_or_store(tmp_path, monkeypatch):
    from booking_bridge.model import Settings
    state = tmp_path/'uncreated'
    monkeypatch.setattr(Settings, 'load', lambda *args, **kwargs: Settings(state=state, mode='production'))
    monkeypatch.setenv('BRIDGE_PRODUCTION_READINESS_FILE', 'unused')
    def forbidden(*args, **kwargs):
        raise AssertionError('Never construct state or network client before gate')
    monkeypatch.setattr(Store, '__init__', forbidden)
    assert main(['--config', str(tmp_path/'config.json'), '--readiness', str(tmp_path/'readiness.json')]) == 2
    assert not state.exists()


def test_restored_database_hold_blocks_legacy_worker_before_claim(settings, store, gateway, event, now):
    store.ingest(event, now)
    store.put('recovery-hold', {'remote_reconciliation_required': True})
    with pytest.raises(Review, match='restored_state_requires_reconciliation'):
        Worker(settings, store, gateway).once(now)
    assert store.rows('SELECT state,attempts FROM events') == [{'state': 'queued', 'attempts': 0}]
    assert not gateway.calls


def test_hold_added_after_initial_worker_check_is_not_cached_away(settings, store, gateway, event, now):
    worker = Worker(settings, store, gateway)
    assert worker.once(now) is False
    store.put('recovery-hold', {'remote_reconciliation_required': True})
    store.ingest(event, now)
    with pytest.raises(Review, match='restored_state_requires_reconciliation'):
        worker.once(now)
    assert store.rows('SELECT state,attempts FROM events') == [{'state': 'queued', 'attempts': 0}]
    assert not gateway.calls


def test_held_database_cannot_requeue_work_through_legacy_loop(settings, store, gateway, event, now):
    store.ingest(event, now)
    store.execute("UPDATE events SET state='working'")
    store.put('recovery-hold', {'remote_reconciliation_required': True})
    with pytest.raises(Review, match='restored_state_requires_reconciliation'):
        run_loop(settings, store, Worker(settings, store, gateway), gateway,
                 clock=lambda: now, max_iterations=1)
    assert store.rows('SELECT state FROM events') == [{'state': 'working'}]
    assert not gateway.calls
