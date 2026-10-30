import copy
import json
import os
import subprocess
import sys
from dataclasses import replace

import pytest

from booking_bridge import pilot_execute
from booking_bridge.model import ROOT, Review, Settings
from booking_bridge.simplybook import SimulatedGateway
from booking_bridge.store import Store
from conftest import changed


@pytest.fixture
def pilot(settings):
    employee = settings.allowed_employees[0]
    settings.mode = 'pilot'
    settings.reads_enabled = True
    settings.allowed_employees = [employee]
    settings.employees = {employee: settings.employees[employee]}
    settings.pilot_service_ids = [91, 92]
    settings.pilot_client_ids = [71]
    settings.schedule_service_ids = {employee: 91}
    settings.export_urls = {employee: 'https://example.invalid/synthetic-calendar'}
    settings.policies['notifications'] = 'controlled_test_contacts_only'
    settings.approvals.update({key: True for key in (
        'live_writes', 'business_rules', 'hosting', 'privacy', 'account_identity_verified',
        'schedule_reference_verified', 'client_mapping', 'pilot_scope_reviewed')})
    store = Store(settings.state / 'bridge.sqlite')
    env = {'SIMPLYBOOK_REST_BASE_URL': 'https://user-api-v2.simplybook.me',
           'SIMPLYBOOK_COMPANY_LOGIN': settings.salon,
           'SIMPLYBOOK_ADMIN_LOGIN': 'synthetic-private-login',
           'SIMPLYBOOK_ADMIN_SECRET': 'synthetic-private-secret'}
    return settings, store, env


def run(pilot, event, now, gateway_factory):
    settings, store, env = pilot
    return pilot_execute.execute_one(settings, execute=True, event_id=event['id'],
                                     environ=env, gateway_factory=gateway_factory, now=now)


def forbidden_gateway(settings):
    pytest.fail('Gateway must not be initialized before all guards pass')


def test_executor_import_has_no_default_config_database_or_api_side_effect(tmp_path):
    unexpected_state = tmp_path / 'must-not-be-created'
    script = '''
import sys
from pathlib import Path
from booking_bridge.model import Settings
from booking_bridge.store import Store
def forbidden(*args, **kwargs):
    raise AssertionError('Unexpected default configuration or database access')
Settings.load = classmethod(forbidden)
Store.__init__ = forbidden
import booking_bridge.pilot_execute
assert 'booking_bridge.api' not in sys.modules
assert not Path(sys.argv[1]).exists()
'''
    env = dict(os.environ, BRIDGE_STATE=str(unexpected_state))
    result = subprocess.run([sys.executable, '-c', script, str(unexpected_state)],
                            cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout == '' and not unexpected_state.exists()


def test_api_reexports_the_single_canonical_envelope_parser():
    from booking_bridge.api import envelope as api_envelope
    from booking_bridge.event_envelope import envelope as canonical_envelope
    assert api_envelope is canonical_envelope is pilot_execute.envelope


def test_one_event_creates_once_and_repeat_is_noop(pilot, event, now):
    settings, store, env = pilot
    store.ingest(event, now=now)
    gateway = SimulatedGateway()
    constructed = []

    def factory(value):
        constructed.append(value)
        return gateway

    first = run(pilot, event, now, factory)
    second = run(pilot, event, now + 1, factory)
    assert first['status'] == 'done' and first['events_processed'] == 1
    assert second['status'] == 'already_processed' and second['events_processed'] == 0
    assert first['target_booking_id'] == second['target_booking_id'] == 1001
    assert len(constructed) == 1
    assert [call[0] for call in gateway.calls] == ['create']
    assert store.rows('SELECT state,attempts FROM events') == [{'state': 'done', 'attempts': 1}]
    output = json.dumps(first) + json.dumps(second)
    for value in (*env.values(), *settings.feed_tokens.values(), *settings.export_urls.values(),
                  settings.webhook_secret, settings.simplybook_webhook_secret, settings.admin_key):
        assert value not in output


def test_optional_event_id_processes_only_one_oldest_event(pilot, event, now):
    settings, store, env = pilot
    store.ingest(event, now=now)
    later = changed(event, 2)
    later['data']['id'] = 'synthetic-booking-B'
    store.ingest(later, now=now + 1)
    gateway = SimulatedGateway()
    result = pilot_execute.execute_one(settings, execute=True, environ=env,
                                       gateway_factory=lambda _: gateway, now=now + 200)
    assert result['event_id'] == event['id'] and result['events_processed'] == 1
    assert len(gateway.calls) == 1
    assert store.rows('SELECT state FROM events WHERE id=?', (later['id'],)) == [{'state': 'queued'}]


def test_create_move_cancel_reuses_target_with_one_event_per_call(pilot, event, now):
    settings, store, env = pilot
    gateway = SimulatedGateway()
    factory = lambda _: gateway
    store.ingest(event, now=now)
    assert run(pilot, event, now, factory)['target_booking_id'] == 1001
    moved = changed(event, 2, start_at='2026-10-24T13:00:00+02:00', end_at='2026-10-24T14:00:00+02:00')
    store.ingest(moved, now=now + 120)
    assert run(pilot, moved, now + 180, factory)['target_booking_id'] == 1001
    canceled = changed(moved, 3, status=-2)
    store.ingest(canceled, now=now + 240)
    assert run(pilot, canceled, now + 300, factory)['target_booking_id'] == 1001
    assert [call[0] for call in gateway.calls] == ['create', 'edit', 'cancel']
    assert gateway.items[1001]['status'] == 'canceled'


def test_minimal_delete_uses_previously_verified_link_scope(pilot, event, now):
    settings, store, env = pilot
    gateway = SimulatedGateway()
    store.ingest(event, now=now)
    run(pilot, event, now, lambda _: gateway)
    deleted = changed(event, 2)
    deleted['type'] = 'booking.deleted'
    deleted['data'] = {key: deleted['data'][key] for key in ('id', 'status', 'employee')}
    store.ingest(deleted, now=now + 120)
    assert run(pilot, deleted, now + 180, lambda _: gateway)['status'] == 'done'
    assert gateway.items[1001]['status'] == 'canceled'


@pytest.mark.parametrize('failure', [
    'execute', 'mode', 'reads', 'review', 'second_employee', 'extra_employee_mapping',
    'service_scope', 'empty_clients', 'client_scope', 'duplicate_target_client',
    'notification_policy', 'signing_secret', 'service_timing', 'service_resources',
    'rest_credentials', 'business_approval',
])
def test_false_gates_reject_before_gateway_and_leave_event_queued(pilot, event, now, failure):
    settings, store, env = pilot
    store.ingest(event, now=now)
    execute = True
    if failure == 'execute': execute = False
    elif failure == 'mode': settings.mode = 'simulation'
    elif failure == 'reads': settings.reads_enabled = False
    elif failure == 'review': settings.approvals['pilot_scope_reviewed'] = False
    elif failure == 'second_employee': settings.allowed_employees.append('other-employee')
    elif failure == 'extra_employee_mapping': settings.employees['other-employee'] = {'id': 82}
    elif failure == 'service_scope': settings.services['synthetic-service-A']['id'] = 999
    elif failure == 'empty_clients': settings.clients = {}
    elif failure == 'client_scope': settings.clients['synthetic-customer-A'] = 999
    elif failure == 'duplicate_target_client': settings.clients['another-customer'] = 71
    elif failure == 'notification_policy': settings.policies['notifications'] = 'all_clients'
    elif failure == 'signing_secret': settings.simplybook_webhook_secret = ''
    elif failure == 'service_timing': settings.services['synthetic-service-A']['timing_verified'] = False
    elif failure == 'service_resources': settings.services['synthetic-service-A']['resources_verified'] = False
    elif failure == 'rest_credentials': env['SIMPLYBOOK_ADMIN_SECRET'] = ''
    elif failure == 'business_approval': settings.approvals['business_rules'] = False
    before = store.rows('SELECT * FROM events')
    with pytest.raises(Review):
        pilot_execute.execute_one(settings, execute=execute, event_id=event['id'],
                                  environ=env, gateway_factory=forbidden_gateway, now=now)
    assert store.rows('SELECT * FROM events') == before
    assert store.rows('SELECT * FROM intents') == []
    assert store.rows('SELECT * FROM links') == []


def test_preflight_failure_returns_actual_check_codes(pilot, event, now):
    settings, store, env = pilot
    store.ingest(event, now=now)
    settings.simplybook_webhook_secret = ''
    settings.services['synthetic-service-A']['resources_verified'] = False
    with pytest.raises(pilot_execute.Blocked) as exc:
        run(pilot, event, now, forbidden_gateway)
    assert str(exc.value) == 'pilot_preflight_failed'
    assert {'simplybook_signing_secret', 'service_timing_and_resources'} <= set(exc.value.failed_checks)


def test_unresolved_intent_stops_before_gateway_even_if_preflight_raced(pilot, event, now, monkeypatch):
    settings, store, env = pilot
    store.ingest(event, now=now)
    store.execute('INSERT INTO intents VALUES(?,?,?,?,?,?,?,?,?)',
                  (event['data']['id'], event['id'], 'create', None, '{}', '[]', 'started', None, now))
    monkeypatch.setattr(pilot_execute, 'inspect_preflight', lambda *args, **kwargs:
                        {'configuration_ready': True, 'checks': []})
    with pytest.raises(pilot_execute.Blocked, match='unresolved_remote_intents_require_review'):
        run(pilot, event, now, forbidden_gateway)
    assert store.rows('SELECT state,attempts FROM events') == [{'state': 'queued', 'attempts': 0}]


def test_expected_event_mismatch_leaves_both_events_unchanged(pilot, event, now):
    settings, store, env = pilot
    store.ingest(event, now=now)
    later = changed(event, 2)
    store.ingest(later, now=now + 1)
    before = store.rows('SELECT * FROM events ORDER BY id')
    with pytest.raises(pilot_execute.Blocked, match='pilot_event_id_mismatch'):
        run(pilot, later, now + 180, forbidden_gateway)
    assert store.rows('SELECT * FROM events ORDER BY id') == before


def test_new_older_event_cannot_be_claimed_in_selection_race(pilot, event, now):
    settings, store, env = pilot
    store.ingest(event, now=now)
    gateway = SimulatedGateway()
    earlier = copy.deepcopy(event)
    earlier['id'] = '0' * 32
    earlier['created_at'] = '2026-10-21T09:59:00+02:00'

    def factory(_):
        store.ingest(earlier, now=now + 1)
        return gateway

    with pytest.raises(pilot_execute.Blocked, match='pilot_event_id_mismatch'):
        run(pilot, event, now + 2, factory)
    assert store.rows('SELECT DISTINCT state,attempts FROM events') == [{'state': 'queued', 'attempts': 0}]
    assert gateway.calls == []


@pytest.mark.parametrize('change', ['employee', 'service', 'customer', 'test', 'hash'])
def test_unverified_or_out_of_scope_event_rejected_before_gateway(pilot, event, now, change):
    settings, store, env = pilot
    value = copy.deepcopy(event)
    if change == 'employee': value['data']['employee']['id'] = 'other-employee'
    elif change == 'service': value['data']['service']['id'] = 'other-service'
    elif change == 'customer': value['data']['customer']['id'] = 'other-customer'
    elif change == 'test': value['test'] = True
    store.ingest(value, now=now)
    if change == 'hash': store.execute("UPDATE events SET hash='changed'")
    before = store.rows('SELECT * FROM events')
    with pytest.raises(pilot_execute.Blocked):
        run(pilot, value, now, forbidden_gateway)
    assert store.rows('SELECT * FROM events') == before


def test_failed_attempt_is_not_automatically_retried(pilot, event, now):
    settings, store, env = pilot
    store.ingest(event, now=now)
    gateway = SimulatedGateway()
    gateway.fail_read = True
    result = run(pilot, event, now, lambda _: gateway)
    assert result['status'] == 'queued' and result['events_processed'] == 1
    assert result['automatic_retry'] is False
    with pytest.raises(pilot_execute.Blocked, match='pilot_event_retry_requires_review'):
        run(pilot, event, now + 1000, forbidden_gateway)
    assert gateway.calls == []


@pytest.mark.parametrize('state', ['working', 'review', 'dead'])
def test_nonqueued_states_are_not_recovered_or_retried(pilot, event, now, state):
    settings, store, env = pilot
    store.ingest(event, now=now)
    store.execute('UPDATE events SET state=?', (state,))
    with pytest.raises(pilot_execute.Blocked, match='pilot_event_state_requires_review'):
        run(pilot, event, now, forbidden_gateway)
    assert store.rows('SELECT state FROM events') == [{'state': state}]


def test_empty_queue_does_not_construct_gateway(pilot, now):
    settings, store, env = pilot
    result = pilot_execute.execute_one(settings, execute=True, environ=env,
                                       gateway_factory=forbidden_gateway, now=now)
    assert result['status'] == 'no_queued_events' and result['events_processed'] == 0


def test_missing_durable_state_is_not_created(pilot, now):
    settings, store, env = pilot
    settings = replace(settings, state=settings.state / 'absent')
    with pytest.raises(pilot_execute.Blocked, match='existing_durable_pilot_state_required'):
        pilot_execute.execute_one(settings, execute=True, environ=env,
                                  gateway_factory=forbidden_gateway, now=now)
    assert not settings.state.exists()


@pytest.mark.parametrize('argv', [[], ['--config', 'config.json', '--state', 'state'],
                                 ['--execute', '--state', 'state'], ['--execute', '--config', 'config.json']])
def test_cli_requires_execute_and_explicit_config_state_before_loading(argv, monkeypatch):
    monkeypatch.setattr(pilot_execute, 'load_dotenv', lambda *args, **kwargs: pytest.fail('No secrets read expected'))
    with pytest.raises(SystemExit) as exc:
        pilot_execute.main(argv)
    assert exc.value.code == 2


def test_cli_uses_isolated_read_only_loader_then_explicit_state(pilot, tmp_path, monkeypatch, capsys):
    settings, store, env = pilot
    loads = []
    executed = []
    config = tmp_path / 'separate-execution.json'
    monkeypatch.setattr(pilot_execute, 'load_dotenv', lambda *args, **kwargs: None)
    monkeypatch.setattr(Settings, 'load', classmethod(lambda cls, path, **kwargs:
                        loads.append((path, kwargs)) or settings))

    def execute(value, **kwargs):
        executed.append((value, kwargs))
        return {'status': 'no_queued_events', 'events_processed': 0}

    monkeypatch.setattr(pilot_execute, 'execute_one', execute)
    state = tmp_path / 'explicit-state'
    assert pilot_execute.main(['--execute', '--config', str(config), '--state', str(state)]) == 0
    assert loads == [(config, {'read_only': True, 'isolated_profile': True})]
    assert executed[0][0].state == state.resolve()
    assert executed[0][1] == {'execute': True, 'event_id': None}
    assert json.loads(capsys.readouterr().out)['events_processed'] == 0
