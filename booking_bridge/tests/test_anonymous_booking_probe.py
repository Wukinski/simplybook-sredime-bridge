import copy
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from booking_bridge import anonymous_booking_probe as probe_module
from booking_bridge.model import Review

NOW = 1793358000
DAY = '2026-11-02'
START = DAY + ' 10:00:00'
END = DAY + ' 10:30:00'
PRIVATE = 'SYNTHETIC_CONTACT_NEVER_PERSIST'


class FakeTransport:
    company = probe_module.COMPANY
    base = probe_module.BASE

    def __init__(self):
        self.calls = []
        self.provider = {'id': 9, 'name': 'TEST integracija A', 'is_active': True,
            'is_visible': False, 'qty': 1, 'services': [496, 17], 'email': '', 'phone': ''}
        self.service = {'id': 496, 'name': 'TEST integracija 30 min', 'is_active': True,
            'is_visible': False, 'duration': 30, 'providers': [9], 'buffer_time_after': 0, 'price': '0.00'}
        self.clients = 1
        self.bookings = {47: {'id': 47, 'provider_id': 9, 'service_id': 496, 'duration': 30,
            'start_datetime': DAY + ' 09:00:00', 'end_datetime': DAY + ' 09:30:00',
            'status': 'canceled', 'client_id': 1,
            'client': {'id': 1, 'name': PRIVATE, 'email': PRIVATE, 'phone': PRIVATE}}}
        self.next_id = 1101
        self.available = [{'date': DAY, 'time': '10:00:00'}]
        self.create_timeout = False
        self.create_happens = True
        self.cancel_timeout = False
        self.cancel_happens = True
        self.return_old_id = False
        self.flat_client = None
        self.nested_client = None
        self.create_clients = 0
        self.fail_client_reads_after_create = False
        self.modify_before_cleanup = False
        self.read_count = {}

    def request(self, method, path, body=None):
        self.calls.append((method, path, copy.deepcopy(body)))
        parsed = urlsplit(path)
        if method == 'GET':
            if path == '/admin/providers/9': return copy.deepcopy(self.provider)
            if path == '/admin/services/496': return copy.deepcopy(self.service)
            if path == '/admin/clients?page=1&on_page=1':
                if self.fail_client_reads_after_create and 1101 in self.bookings:
                    raise RuntimeError(PRIVATE)
                rows = [{'id': 1, 'name': PRIVATE, 'email': PRIVATE, 'phone': PRIVATE}] if self.clients else []
                return {'data': rows, 'metadata': {'page': 1, 'pages_count': self.clients, 'items_count': self.clients}}
            if parsed.path == '/admin/schedule/available-slots':
                assert parse_qs(parsed.query)['provider_id'] == ['9']
                assert parse_qs(parsed.query)['service_id'] == ['496']
                return copy.deepcopy(self.available)
            if parsed.path == '/admin/bookings':
                query = parse_qs(parsed.query)
                assert query['filter[date]'] == [DAY]
                rows = list(self.bookings.values())
                return {'data': copy.deepcopy(rows), 'metadata': {'page': int(query['page'][0]),
                    'pages_count': 1 if rows else 0, 'items_count': len(rows)}}
            if parsed.path.startswith('/admin/bookings/'):
                identifier = int(parsed.path.rsplit('/', 1)[1])
                self.read_count[identifier] = self.read_count.get(identifier, 0) + 1
                value = copy.deepcopy(self.bookings[identifier])
                if self.modify_before_cleanup and self.read_count[identifier] > 1:
                    value['provider_id'] = 8
                return value
            raise AssertionError('Read outside fixed probe scope')
        if method == 'POST':
            assert path == '/admin/bookings' and set(body) == probe_module.PAYLOAD_KEYS
            assert body['provider_id'] == 9 and body['service_id'] == 496 and body['count'] == 1
            if self.create_happens:
                value = {'id': self.next_id, **body, 'duration': 30, 'status': 'confirmed',
                    'client_id': self.flat_client, 'client': self.nested_client}
                self.bookings[self.next_id] = value
                self.clients += self.create_clients
            if self.create_timeout: raise RuntimeError(PRIVATE)
            return {'bookings': [{'id': 47 if self.return_old_id else self.next_id,
                                  'client_id': self.flat_client}]}
        if method == 'DELETE':
            assert path == '/admin/bookings/1101' and body is None
            if self.cancel_happens: self.bookings[1101]['status'] = 'canceled'
            if self.cancel_timeout: raise RuntimeError(PRIVATE)
            return copy.deepcopy(self.bookings[1101])
        raise AssertionError('No PUT or client mutation is allowed')


@pytest.fixture
def prepared(tmp_path):
    transport = FakeTransport()
    directory = tmp_path / 'new-anonymous-experiment'
    probe = probe_module.Probe(transport)
    result = probe_module.prepare(probe, directory, [DAY], now=NOW)
    authorization = probe_module.authorization_for_review(result['plan_sha256'])
    authorization.update(allow_one_exact_booking_post_and_cancel=True,
                         acknowledge_server_may_create_client_object=True)
    return transport, probe, directory, authorization


def mutations(transport, method=None):
    return [call for call in transport.calls if call[0] != 'GET' and (method is None or call[0] == method)]


def test_preparation_is_get_only_and_persists_no_contact_values(prepared):
    transport, _, directory, _ = prepared
    assert mutations(transport) == []
    plan = probe_module.read(directory / 'plan.json')
    assert plan['payload'] == {'service_id': 496, 'provider_id': 9, 'count': 1,
                              'start_datetime': START, 'end_datetime': END}
    assert plan['before_booking_ids'] == [47]
    assert PRIVATE not in ''.join(path.read_text() for path in directory.iterdir())
    assert plan['before_clients']['requested_on_page'] == 1
    assert plan['before_clients']['contact_fields_retained'] is False


@pytest.mark.parametrize('target,change', [
    ('provider', {'name': 'Real provider'}), ('provider', {'is_visible': True}),
    ('provider', {'is_active': False}), ('provider', {'qty': 2}),
    ('provider', {'services': []}), ('provider', {'email': PRIVATE}),
    ('service', {'name': 'Real treatment'}), ('service', {'is_visible': True}),
    ('service', {'is_active': False}), ('service', {'duration': 60}),
    ('service', {'providers': [9, 8]}), ('service', {'buffer_time_after': 10}),
    ('service', {'price': '1.00'}),
])
def test_fresh_identity_changes_block_preparation_before_any_write(tmp_path, target, change):
    transport = FakeTransport(); getattr(transport, target).update(change)
    with pytest.raises(Review):
        probe_module.prepare(probe_module.Probe(transport), tmp_path / 'probe', [DAY], now=NOW)
    assert mutations(transport) == [] and not (tmp_path / 'probe').exists()


def test_wrong_account_is_rejected_without_requests():
    transport = FakeTransport(); transport.company = 'wrong'
    with pytest.raises(Review, match='account_mismatch'):
        probe_module.Probe(transport)
    assert transport.calls == []


def test_success_performs_one_post_and_cancels_only_proven_new_booking(prepared):
    transport, probe, directory, authorization = prepared
    before = copy.deepcopy(transport.bookings[47])
    result = probe_module.execute(probe, directory, authorization, now=NOW + 60)
    assert result['capability_verified'] and result['cleanup_verified']
    assert result['create_attempts'] == result['cancel_attempts'] == 1
    assert transport.bookings[47] == before and transport.bookings[1101]['status'] == 'canceled'
    assert [call[:2] for call in mutations(transport)] == [('POST', '/admin/bookings'), ('DELETE', '/admin/bookings/1101')]
    assert not result['zero_client_objects_proven'] and not result['production_enabled']
    assert PRIVATE not in json.dumps(result) + (directory / 'journal.json').read_text()
    probe_module.execute(probe, directory, authorization, now=NOW + 100)
    assert len(mutations(transport)) == 2


@pytest.mark.parametrize('field', ['allow_one_exact_booking_post_and_cancel', 'acknowledge_server_may_create_client_object'])
def test_pending_owner_experiment_decision_blocks_execution(prepared, field):
    transport, probe, directory, authorization = prepared
    authorization[field] = False
    with pytest.raises(Review, match='explicit_experiment_authorization_required'):
        probe_module.execute(probe, directory, authorization, now=NOW + 60)
    assert mutations(transport) == []


@pytest.mark.parametrize('change', ['expired', 'slot_taken', 'baseline_changed', 'identity_changed'])
def test_changed_conditions_block_post_after_preparation(prepared, change):
    transport, probe, directory, authorization = prepared
    when = NOW + 60
    if change == 'expired': when += probe_module.PLAN_TTL
    elif change == 'slot_taken': transport.available = []
    elif change == 'baseline_changed': transport.bookings[47]['status'] = 'confirmed'
    else: transport.service['duration'] = 60
    with pytest.raises(Review):
        probe_module.execute(probe, directory, authorization, now=when)
    assert mutations(transport) == []


@pytest.mark.parametrize('client', [0, 1, '1'])
def test_any_nonnull_client_id_fails_requirement_without_client_deletion(prepared, client):
    transport, probe, directory, authorization = prepared
    transport.flat_client = client
    result = probe_module.execute(probe, directory, authorization, now=NOW + 60)
    assert result['client_requirement_failed'] and not result['capability_verified']
    assert result['cleanup_verified']
    assert [path for method, path, _ in mutations(transport) if method == 'DELETE'] == ['/admin/bookings/1101']
    assert transport.clients == 1


def test_nested_anonymous_client_object_is_not_silently_accepted(prepared):
    transport, probe, directory, authorization = prepared
    transport.nested_client = {'id': 444, 'name': PRIVATE, 'email': PRIVATE}
    result = probe_module.execute(probe, directory, authorization, now=NOW + 60)
    assert result['client_requirement_failed'] and not result['capability_verified']
    assert PRIVATE not in (directory / 'journal.json').read_text()


def test_client_count_increase_is_failure_and_no_client_is_deleted(prepared):
    transport, probe, directory, authorization = prepared
    transport.create_clients = 1
    result = probe_module.execute(probe, directory, authorization, now=NOW + 60)
    assert result['client_requirement_failed'] and transport.clients == 2
    assert result['client_count_final'] == 2 and result['cleanup_verified']
    assert result['count_comparison_proves_only_net_change']
    assert all(not path.startswith('/admin/clients') for _, path, _ in mutations(transport))


@pytest.mark.parametrize('created', [True, False])
def test_uncertain_post_is_never_retried_and_exact_candidate_is_not_ownership(prepared, created):
    transport, probe, directory, authorization = prepared
    transport.create_timeout = True; transport.create_happens = created
    result = probe_module.execute(probe, directory, authorization, now=NOW + 60)
    assert result['state'] == 'manual_ownership_review' and result['owned_booking_id'] is None
    assert result['candidate_count'] == int(created)
    assert result['unknown_post_candidate_is_ownership_proof'] is False
    probe_module.execute(probe, directory, authorization, now=NOW + 120)
    assert len(mutations(transport, 'POST')) == 1 and mutations(transport, 'DELETE') == []


def test_client_increase_is_still_diagnosed_after_uncertain_unowned_post(prepared):
    transport, probe, directory, authorization = prepared
    transport.create_timeout = True; transport.create_clients = 1
    result = probe_module.execute(probe, directory, authorization, now=NOW + 60)
    assert result['client_requirement_failed'] and result['client_count_final'] == 2
    assert result['owned_booking_id'] is None and mutations(transport, 'DELETE') == []


def test_preparation_skips_overlap_even_if_slots_endpoint_lists_it(tmp_path):
    transport = FakeTransport()
    transport.bookings[47].update(status='confirmed', start_datetime=START, end_datetime=END)
    transport.available += [{'date': DAY, 'time': '11:00:00'}]
    directory = tmp_path / 'free-slot'
    probe_module.prepare(probe_module.Probe(transport), directory, [DAY], now=NOW)
    plan = probe_module.read(directory / 'plan.json')
    assert plan['payload']['start_datetime'] == DAY + ' 11:00:00'
    assert mutations(transport) == []


@pytest.mark.parametrize('canceled', [True, False])
def test_uncertain_cancel_is_read_back_and_never_repeated(prepared, canceled):
    transport, probe, directory, authorization = prepared
    transport.cancel_timeout = True; transport.cancel_happens = canceled
    result = probe_module.execute(probe, directory, authorization, now=NOW + 60)
    assert result['cleanup_verified'] is canceled
    probe_module.execute(probe, directory, authorization, now=NOW + 120)
    assert len(mutations(transport, 'POST')) == len(mutations(transport, 'DELETE')) == 1


def test_preexisting_id_returned_by_create_is_never_canceled(prepared):
    transport, probe, directory, authorization = prepared
    transport.return_old_id = True
    result = probe_module.execute(probe, directory, authorization, now=NOW + 60)
    assert result['owned_booking_id'] is None and result['state'] == 'manual_ownership_review'
    assert mutations(transport, 'DELETE') == []


def test_changed_owned_record_blocks_cleanup_instead_of_canceling_another_scope(prepared):
    transport, probe, directory, authorization = prepared
    transport.modify_before_cleanup = True
    with pytest.raises(Review, match='cleanup_identity_changed'):
        probe_module.execute(probe, directory, authorization, now=NOW + 60)
    assert len(mutations(transport, 'POST')) == 1 and mutations(transport, 'DELETE') == []


def test_unavailable_client_count_does_not_prevent_safe_owned_booking_cleanup(prepared):
    transport, probe, directory, authorization = prepared
    transport.fail_client_reads_after_create = True
    result = probe_module.execute(probe, directory, authorization, now=NOW + 60)
    assert result['cleanup_verified'] and result['client_requirement_failed']
    assert result['client_count_final'] is None and not result['capability_verified']


def test_payload_with_client_field_cannot_be_smuggled_through_plan(prepared):
    transport, probe, directory, authorization = prepared
    plan = probe_module.read(directory / 'plan.json')
    plan['payload']['client_id'] = 1
    journal = probe_module.read(directory / 'journal.json')
    journal['plan_sha256'] = probe_module.digest(plan)
    authorization['plan_sha256'] = journal['plan_sha256']
    probe_module.write(directory / 'plan.json', plan)
    probe_module.write(directory / 'journal.json', journal)
    with pytest.raises(Review, match='payload_outside_scope'):
        probe_module.execute(probe, directory, authorization, now=NOW + 60)
    assert mutations(transport) == []


def test_prepared_payload_uses_only_documented_admin_booking_fields(prepared):
    _, _, directory, _ = prepared
    from booking_bridge.model import HOME
    schema = json.loads((HOME / 'evidence/admin-openapi.json').read_text(encoding='utf-8'))
    entity = schema['components']['schemas']['AdminBookingBuildEntity']
    payload = probe_module.read(directory / 'plan.json')['payload']
    assert set(payload) <= set(entity['properties'])
    assert set(entity['required']) <= set(payload)
    assert 'client_id' not in entity['required'] and 'client_id' not in payload
