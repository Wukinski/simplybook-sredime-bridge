import copy
import json

import pytest
import requests

from booking_bridge.model import HOME, Settings, stamp
from booking_bridge.simplybook import SimulatedGateway
from booking_bridge.store import Store
from booking_bridge.worker import Worker


@pytest.fixture(autouse=True)
def no_external_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError('Real HTTP is forbidden in connector tests')
    monkeypatch.setattr(requests.sessions.Session, 'request', blocked)


@pytest.fixture
def event():
    return json.loads((HOME / 'fixtures/booking.created.json').read_text(encoding='utf-8'))


@pytest.fixture
def now(event):
    return stamp(event['created_at']).timestamp()


@pytest.fixture
def settings(tmp_path):
    return Settings(state=tmp_path, require_subminute_availability=False,
                    webhook_secret='a' * 64, simplybook_webhook_secret='b' * 64,
                    admin_key='admin-' + 'x' * 40,
                    employees={'synthetic-employee-A': {'id': 81, 'external_id': 'test-provider-81'},
                               'synthetic-employee-B': {'id': 82, 'external_id': 'test-provider-82'}},
                    services={'synthetic-service-A': {'id': 91, 'external_id': 'test-service-91', 'duration': 60,
                                                      'timing_verified': True, 'resources_verified': True},
                              'synthetic-service-B': {'id': 92, 'external_id': 'test-service-92', 'duration': 60,
                                                      'timing_verified': True, 'resources_verified': True}},
                    clients={'synthetic-customer-A': 71},
                    policies={'pending': 'hold', 'no_show': 'retain'},
                    approvals={'client_mapping': True},
                    allowed_employees=['synthetic-employee-A', 'synthetic-employee-B'],
                    feed_tokens={'synthetic-employee-A': 't' * 48})


@pytest.fixture
def store(settings):
    return Store(settings.state / 'test.sqlite')


@pytest.fixture
def gateway():
    return SimulatedGateway()


@pytest.fixture
def worker(settings, store, gateway):
    return Worker(settings, store, gateway)


def changed(event, number, **fields):
    value = copy.deepcopy(event)
    value['id'] = f'{number:032x}'
    value['type'] = 'booking.updated'
    dt = stamp(event['created_at'])
    from datetime import timedelta
    value['created_at'] = (dt + timedelta(minutes=number)).isoformat()
    value['data'].update(fields)
    return value


def state(store, event):
    return store.rows('SELECT * FROM events WHERE id=?', (event['id'],))[0]
