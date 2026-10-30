import copy
import json

import pytest

from booking_bridge.controlled_pilot import provision
from booking_bridge.model import Review
from booking_bridge.tests.test_provision_pilot import Account, report
from booking_bridge.tests.test_preflight import configured, blocked
from booking_bridge.preflight import inspect


class TestAccount(Account):
    __test__ = False

    def __init__(self):
        super().__init__()
        self.inherit = True

    def request(self, method, path, payload=None):
        result = super().request(method, path, payload)
        if method == 'POST' and path == '/admin/providers':
            row = self.rows['providers'][-1]
            row['services'] = [3] if self.inherit else []
            if self.inherit:
                self.rows['services'][0]['providers'].append(row['id'])
        return result


def test_inherited_assignments_are_logged_and_repeat_has_no_creates(tmp_path):
    account = TestAccount()
    saved = report(account)
    saved.pop('pilot_provider_isolation_verified')
    path = tmp_path / 'journal.json'
    result = provision(account, saved, path)
    assert len(account.posts) == 2
    assert 'services' not in account.posts[0][1]
    assert result['provider_service_ids'] == [3, 102]
    assert result['existing_service_assignment_changes'] == [
        {'service_id': 3, 'before': [2], 'after': [2, 101], 'added_test_providers': [101]}]
    assert account.rows['services'][0]['duration'] == 60
    assert provision(account, saved, path) == result
    assert len(account.posts) == 2


def test_rolled_back_intent_is_live_reconciled_and_preserved(tmp_path):
    account = TestAccount()
    saved = report(account)
    old = {'id': 8, 'kind': 'providers', 'state': 'rolled_back',
           'rollback': {'success': True, 'baseline_restored': True}}
    path = tmp_path / 'journal.json'
    path.write_text(json.dumps({'company': account.company, 'baseline_sha256': saved['preserved_baseline_sha256'],
                                'steps': [old]}))
    provision(account, saved, path)
    journal = json.loads(path.read_text())
    assert journal['history'][0]['steps'] == [old]
    assert journal['history'][0]['baseline_restored_by_live_read'] is True
    assert len(journal['steps']) == 2


@pytest.mark.parametrize('state', ['intent', 'rolled_back'])
def test_unreconciled_attempt_never_creates(tmp_path, state):
    account = TestAccount()
    saved = report(account)
    path = tmp_path / 'journal.json'
    path.write_text(json.dumps({'company': account.company, 'baseline_sha256': saved['preserved_baseline_sha256'],
                                'steps': [{'id': 8, 'kind': 'providers', 'state': state}]}))
    with pytest.raises(Review):
        provision(account, saved, path)
    assert not account.posts


def test_lost_create_response_never_replays(tmp_path):
    account = TestAccount()
    saved = report(account)
    account.uncertain = True
    path = tmp_path / 'journal.json'
    with pytest.raises(TimeoutError):
        provision(account, saved, path)
    with pytest.raises(Review, match='unfinished_intent'):
        provision(account, saved, path)
    assert len(account.posts) == 1


def test_existing_catalog_change_stops_after_first_create(tmp_path):
    account = TestAccount()
    saved = report(account)
    original = account.request

    def alters(method, path, payload=None):
        result = original(method, path, payload)
        if method == 'POST':
            account.rows['services'][0]['duration'] = 99
        return result

    account.request = alters
    with pytest.raises(Review, match='existing_catalog_or_assignments_changed'):
        provision(account, saved, tmp_path / 'journal.json')
    assert len(account.posts) == 1


def test_pilot_needs_source_scope_but_not_sb_isolation_or_subminute(settings):
    env = configured(settings)
    settings.require_subminute_availability = True
    settings.approvals.pop('pilot_isolation', None)
    assert inspect(settings, 'pilot', env)['configuration_ready'] is True
    assert 'subminute_availability_transport' in blocked(inspect(settings, 'production', env))
    settings.approvals['pilot_scope_reviewed'] = False
    assert 'approval_pilot_scope_reviewed' in blocked(inspect(settings, 'pilot', env))


def test_pilot_preserves_signature_and_contact_scope_checks(settings):
    env = configured(settings)
    settings.webhook_secret = ''
    settings.pilot_client_ids = [999]
    failures = blocked(inspect(settings, 'pilot', env))
    assert {'sredime_signing_secret', 'pilot_client_scope'} <= failures
