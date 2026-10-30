import json

import pytest

from booking_bridge.diagnostics import ReadOnlyGateway, inspect_account
from booking_bridge.model import HOME, Review, Settings


class AccountClient:
    company = 'studioandjelija'
    base = 'https://user-api-v2.simplybook.me'

    def __init__(self): self.calls = 0; self.verbs = []

    def request(self, method, path, body=None):
        self.calls += 1; self.verbs.append(method)
        if path.startswith('/admin/providers?'):
            return {'data': [{'id': 81, 'name': 'TEST integracija A', 'is_active': True, 'is_visible': False}],
                    'metadata': {'page': 1, 'pages_count': 1, 'items_count': 1}}
        if path.startswith('/admin/services?'):
            return {'data': [{'id': 91, 'name': 'TEST integracija 30 min', 'duration': 30, 'providers': [81]}],
                    'metadata': {'page': 1, 'pages_count': 1, 'items_count': 1}}
        if path == '/admin/company/info':
            return {'login': self.company, 'timezone': 'Europe/Belgrade', 'email': 'DO NOT EXPORT'}
        if path.startswith('/admin/bookings?'):
            return {'data': [], 'metadata': {'page': 1, 'pages_count': 0, 'items_count': 0}}
        raise AssertionError('Unexpected path')


def test_read_only_facade_blocks_all_writes_even_with_production_configuration(settings):
    settings.mode = 'production'
    client = AccountClient(); gateway = ReadOnlyGateway(settings, client)
    for method in ('POST', 'PUT', 'DELETE', 'PATCH'):
        with pytest.raises(Review, match='writes_forbidden'):
            gateway.transport.request(method, '/admin/bookings')
    with pytest.raises(Review, match='writes_forbidden'): gateway.create({})
    with pytest.raises(Review, match='writes_forbidden'): gateway.edit(123, {})
    with pytest.raises(Review, match='writes_forbidden'): gateway.cancel(123)
    assert not client.verbs


def test_diagnostics_uses_get_only_and_does_not_export_contact_fields(settings):
    client = AccountClient(); report = inspect_account(settings, ReadOnlyGateway(settings, client))
    assert client.verbs == ['GET'] * 4
    assert report['business_writes'] == 0 and report['identity_verified']
    assert len(report['test_provider_candidates']) == 1
    assert 'DO NOT EXPORT' not in json.dumps(report)
    assert report['quota_for_two_extra_providers'].startswith('not_established')


def test_diagnostic_settings_do_not_require_business_approval(tmp_path, monkeypatch):
    path = tmp_path / 'profile.json'
    path.write_text(json.dumps({'mode': 'pilot', 'approvals': {'business_rules': False}}))
    monkeypatch.setenv('BRIDGE_FEED_TOKENS', '{}')
    config = Settings.load(path, read_only=True)
    assert config.mode == 'pilot' and config.approvals['business_rules'] is False
    with pytest.raises(Review, match='live_approval_missing'): Settings.load(path)


def test_json_mapping_cannot_be_silently_erased_by_empty_local_csv(tmp_path, monkeypatch):
    import booking_bridge.model as model
    (tmp_path / 'mappings').mkdir()
    (tmp_path / 'mappings/employees.local.csv').write_text('sredime_id,simplybook_id\n')
    path = tmp_path / 'profile.json'
    path.write_text(json.dumps({'employees': {'source': {'id': 123}}}))
    monkeypatch.setattr(model, 'HOME', tmp_path)
    monkeypatch.setenv('BRIDGE_FEED_TOKENS', '{}')
    with pytest.raises(Review, match='conflicting_employees_mapping_sources'): Settings.load(path, read_only=True)


def test_prepare_pilot_is_offline_binds_baseline_and_keeps_production_unapproved(settings):
    from booking_bridge.pilot_setup import prepare
    client = AccountClient()
    report = inspect_account(settings, ReadOnlyGateway(settings, client))
    report['test_provider_candidates'] = []; report['test_service_candidates'] = []
    calls = client.calls
    proposal = prepare(report)
    assert client.calls == calls and proposal['execution'] == 'not_dispatched'
    assert proposal['production_business_rules_confirmed'] is False
    assert len(proposal['creates']['providers']) == 1
    assert proposal['simplybook_complete_provider_isolation_required'] is False
    assert 'controlled_test_contact_supplied_locally' in proposal['booking_blocked_until']
    assert all(p['is_visible'] is False for p in proposal['creates']['providers'])
    assert proposal['baseline_sha256'] == report['preserved_baseline_sha256']
    report['preserved_baseline']['services'][0]['duration'] = 999
    with pytest.raises(Review, match='baseline_hash_mismatch'): prepare(report)


def test_prepare_pilot_refuses_duplicate_names_and_wrong_account(settings):
    from booking_bridge.pilot_setup import prepare
    report = inspect_account(settings, ReadOnlyGateway(settings, AccountClient()))
    with pytest.raises(Review, match='existing_test_records'): prepare(report)
    report['company'] = 'another-company'
    with pytest.raises(Review, match='company_identity'): prepare(report)
