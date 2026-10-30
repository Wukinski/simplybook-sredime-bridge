import copy
import json

import pytest

from booking_bridge.model import Review, digest
from booking_bridge.provision_pilot import baseline, provision


class Account:
    company = 'studioandjelija'

    def __init__(self):
        self.rows = {
            'providers': [{'id': 2, 'name': 'Existing', 'is_active': True,
                           'is_visible': True, 'services': [3]}],
            'services': [{'id': 3, 'name': 'Existing service', 'price': '100',
                          'duration': 60, 'buffer_time_after': 0, 'providers': [2], 'is_visible': True}],
        }
        self.posts = []
        self.uncertain = False
        self.expose = False
        self.capacity = 9

    def inventory(self, kind):
        return copy.deepcopy(self.rows[kind])

    def request(self, method, path, payload=None):
        if path == '/admin/company/info':
            return {'login': self.company}
        if path == '/admin/tariff/current':
            return {'is_expired': False, 'limits': [{'key': 'provider_limit', 'rest': self.capacity}]}
        kind = path.split('/')[2]
        if method == 'POST':
            self.posts.append((kind, copy.deepcopy(payload)))
            row = {'id': 100 + len(self.posts), 'is_active': True, **copy.deepcopy(payload)}
            if kind == 'services':
                row['buffer_time_after'] = 0
                for provider in self.rows['providers']:
                    if provider['id'] in row['providers']:
                        provider['services'].append(row['id'])
            if self.expose:
                row['is_visible'] = True
            self.rows[kind].append(row)
            if self.uncertain:
                raise TimeoutError('lost create response')
            return copy.deepcopy(row)
        return copy.deepcopy(next(row for row in self.rows[kind] if row['id'] == int(path.split('/')[-1])))


def report(account):
    saved = baseline(account.rows['providers'], account.rows['services'])
    return {'company': account.company, 'read_only': True, 'identity_verified': True,
            'pilot_provider_isolation_verified': True,
            'preserved_baseline': saved, 'preserved_baseline_sha256': digest(saved)}


def test_isolated_creation_and_repeat_without_duplicate_writes(tmp_path):
    account = Account()
    saved = report(account)
    path = tmp_path / 'journal.json'
    result = provision(account, saved, path)
    assert len(account.posts) == 4
    assert account.posts[0][1]['services'] == []
    assert all(payload['is_visible'] is False for _, payload in account.posts)
    assert account.posts[2][1]['providers'] == result['provider_ids']
    assert provision(account, saved, path) == result
    assert len(account.posts) == 4


def test_lost_response_persists_intent_and_blocks_retry(tmp_path):
    account = Account()
    saved = report(account)
    account.uncertain = True
    path = tmp_path / 'journal.json'
    with pytest.raises(TimeoutError):
        provision(account, saved, path)
    assert json.loads(path.read_text())['steps'][0]['state'] == 'intent'
    with pytest.raises(Review, match='unfinished_intent'):
        provision(account, saved, path)
    assert len(account.posts) == 1


@pytest.mark.parametrize('failure', ['capacity', 'baseline', 'unrestricted', 'company'])
def test_preflight_blocks_writes(tmp_path, failure):
    account = Account()
    saved = report(account)
    if failure == 'capacity':
        account.capacity = 1
    elif failure == 'baseline':
        account.rows['services'][0]['duration'] = 90
    elif failure == 'unrestricted':
        account.rows['services'][0]['providers'] = []
        saved = report(account)
    else:
        account.company = 'another-company'
    with pytest.raises(Review):
        provision(account, saved, tmp_path / 'journal.json')
    assert account.posts == []


def test_wrong_visibility_stops_before_next_create(tmp_path):
    account = Account()
    account.expose = True
    with pytest.raises(Review, match='visibility_mismatch'):
        provision(account, report(account), tmp_path / 'journal.json')
    assert len(account.posts) == 1


def test_unproven_provider_isolation_blocks_every_create(tmp_path):
    account = Account()
    saved = report(account)
    saved.pop('pilot_provider_isolation_verified')
    with pytest.raises(Review, match='assignments_not_proven_safe'):
        provision(account, saved, tmp_path / 'journal.json')
    assert account.posts == []


def test_server_ignoring_empty_service_assignments_stops_after_one_create(tmp_path):
    account = Account()
    saved = report(account)
    original_request = account.request

    def ignores_services(method, path, payload=None):
        result = original_request(method, path, payload)
        if method == 'POST' and path == '/admin/providers':
            account.rows['providers'][-1]['services'] = [3]
        return result

    account.request = ignores_services
    with pytest.raises(Review, match='isolation_mismatch'):
        provision(account, saved, tmp_path / 'journal.json')
    assert len(account.posts) == 1
