import copy
import json
import sqlite3
import sys

import pytest

from booking_bridge.model import Settings
from booking_bridge.preflight import inspect, local_state, run
from booking_bridge.store import Store


def configured(settings):
    settings.reads_enabled = True
    settings.approvals.update({name: True for name in (
        'live_writes', 'business_rules', 'hosting', 'privacy', 'account_identity_verified',
        'schedule_reference_verified', 'client_mapping', 'pilot_scope_reviewed',
        'notification_behavior', 'account_booking_trial', 'calendar_blocks_trial', 'empty_feed_trial')})
    settings.pilot_client_ids = [71]
    settings.pilot_service_ids = [91, 92]
    settings.schedule_service_ids = {e: 91 for e in settings.allowed_employees}
    settings.feed_tokens = {e: 'synthetic-private-token-' + 'x' * 40 for e in settings.allowed_employees}
    settings.export_urls = {e: 'https://example.invalid/DO_NOT_EXPORT_PRIVATE_URL' for e in settings.allowed_employees}
    return {'SIMPLYBOOK_REST_BASE_URL': 'https://user-api-v2.simplybook.me',
            'SIMPLYBOOK_COMPANY_LOGIN': settings.salon,
            'SIMPLYBOOK_ADMIN_LOGIN': 'DO_NOT_EXPORT_LOGIN',
            'SIMPLYBOOK_ADMIN_SECRET': 'DO_NOT_EXPORT_PASSWORD'}


def blocked(report):
    return {c['code'] for c in report['checks'] if not c['ok']}


def test_configured_preflight_does_not_change_mode_or_create_state(settings):
    env = configured(settings)
    before = copy.deepcopy(settings)
    report = inspect(settings, environ=env)
    assert report['configuration_ready'] is True
    assert report['external_validation_performed'] is False
    assert settings == before and not (settings.state / 'bridge.sqlite').exists()
    text = json.dumps(report)
    for value in [env['SIMPLYBOOK_ADMIN_SECRET'], env['SIMPLYBOOK_ADMIN_LOGIN'],
                  *settings.feed_tokens.values(), *settings.export_urls.values()]:
        assert value not in text


def test_default_profile_reports_missing_prerequisites_without_creating_directory(tmp_path):
    state = tmp_path / 'absent'
    report = inspect(Settings(state=state), environ={})
    assert report['configuration_ready'] is False
    assert {'employee_allowlist', 'employee_mappings', 'service_mappings', 'client_mappings',
            'sredime_signing_secret', 'rest_credentials', 'pilot_client_ids',
            'schedule_references', 'private_feed_tokens', 'source_export_endpoints'} <= blocked(report)
    assert not state.exists()


@pytest.mark.parametrize('field,value,reason', [
    ('employees', {}, 'employee_mappings'),
    ('services', {}, 'service_mappings'),
    ('schedule_service_ids', {}, 'schedule_references'),
    ('feed_tokens', {}, 'private_feed_tokens'),
    ('export_urls', {}, 'source_export_endpoints'),
    ('pilot_client_ids', [99], 'pilot_client_scope'),
    ('pilot_service_ids', [99], 'pilot_service_scope'),
    ('simplybook_webhook_secret', '', 'simplybook_signing_secret'),
])
def test_incomplete_mapping_or_credentials_block_configuration(settings, field, value, reason):
    env = configured(settings)
    setattr(settings, field, value)
    report = inspect(settings, environ=env)
    assert report['configuration_ready'] is False
    assert reason in blocked(report)


def test_production_requires_completed_trials_not_only_pilot_isolation(settings):
    env = configured(settings)
    settings.approvals['empty_feed_trial'] = False
    assert inspect(settings, 'pilot', env)['configuration_ready'] is True
    assert 'approval_empty_feed_trial' in blocked(inspect(settings, 'production', env))


def test_pending_intent_blocks_and_existing_db_is_not_modified(settings):
    env = configured(settings)
    path = settings.state / 'bridge.sqlite'
    store = Store(path)
    store.execute("INSERT INTO intents VALUES('synthetic','e','create',NULL,'{}','[]','started',NULL,0)")
    before = path.read_bytes()
    report = inspect(settings, environ=env)
    assert 'remote_intents_resolved' in blocked(report)
    assert path.read_bytes() == before
    assert store.rows('SELECT state FROM intents') == [{'state': 'started'}]
    store.execute("UPDATE intents SET state='done'")
    assert inspect(settings, environ=env)['configuration_ready'] is True


def test_persisted_client_mapping_is_accepted_read_only(settings):
    env = configured(settings)
    settings.clients = {}
    store = Store(settings.state / 'bridge.sqlite')
    store.execute("INSERT INTO clients VALUES('synthetic-customer',71)")
    assert inspect(settings, environ=env)['configuration_ready'] is True


def test_unknown_db_schema_is_rejected_without_migration(tmp_path):
    path = tmp_path / 'bridge.sqlite'
    with sqlite3.connect(path) as conn:
        conn.execute('PRAGMA user_version=99')
    before = path.read_bytes()
    assert local_state(path) == (False, False, set())
    assert path.read_bytes() == before


def test_invalid_configuration_is_redacted(monkeypatch, capsys):
    def invalid(**kwargs):
        raise ValueError('DO_NOT_EXPORT_PASSWORD')
    monkeypatch.setattr(Settings, 'load', invalid)
    assert run('pilot') == 2
    output = capsys.readouterr().out
    assert 'DO_NOT_EXPORT_PASSWORD' not in output
    assert blocked(json.loads(output)) == {'local_configuration_unreadable'}


@pytest.mark.parametrize('target', [None, 'production'])
def test_cli_preflight_has_json_output_and_blocked_exit_code(tmp_path, monkeypatch, capsys, target):
    import booking_bridge.__main__ as cli
    import dotenv
    monkeypatch.setattr(Settings, 'load', lambda **kwargs: Settings(state=tmp_path / 'absent'))
    monkeypatch.setattr(dotenv, 'load_dotenv', lambda *args, **kwargs: None)
    monkeypatch.setattr(sys, 'argv', ['booking_bridge', 'preflight'] + (['--target', target] if target else []))
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
    report = json.loads(capsys.readouterr().out)
    assert report['target'] == (target or 'pilot')
    assert report['configuration_ready'] is False and not (tmp_path / 'absent').exists()
