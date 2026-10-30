import json
from datetime import date

import pytest

from provider_assignment.core import Failure
from booking_bridge.model import HOME, Review, Temporary, Uncertain
from booking_bridge.simplybook import Gateway


class Transport:
    company = 'studioandjelija'
    base = 'https://user-api-v2.simplybook.me'

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        value = self.responses.pop(0)
        if isinstance(value, Exception): raise value
        return value


def approved(settings, monkeypatch):
    settings.mode = 'production'; settings.reads_enabled = True
    for key in ('live_writes', 'business_rules', 'notification_behavior', 'account_booking_trial',
                'calendar_blocks_trial', 'empty_feed_trial', 'hosting', 'privacy'):
        settings.approvals[key] = True
    # These transport contract tests use synthetic, profile-bound review evidence.
    # No production/private profile or provider network is available to them.
    import time
    from booking_bridge.tests.test_production_readiness import evidence_for
    path, _ = evidence_for(settings, settings.state/'contract-evidence', time.time())
    monkeypatch.setenv('BRIDGE_PRODUCTION_READINESS_FILE', str(path))


def test_rest_booking_contract_matches_fresh_official_schema(settings, monkeypatch):
    approved(settings, monkeypatch)
    transport = Transport([{'bookings': [{'id': 123}]}])
    gateway = Gateway(settings, transport)
    body = {'service_id': 91, 'provider_id': 81, 'client_id': 71, 'count': 1,
            'start_datetime': '2026-10-23 10:00:00', 'end_datetime': '2026-10-23 11:00:00'}
    assert gateway.create(body) == 123
    assert transport.calls == [('POST', '/admin/bookings', body)]
    schema = json.loads((HOME / 'evidence/admin-openapi.json').read_text(encoding='utf-8'))
    props = schema['components']['schemas']['AdminBookingBuildEntity']['properties']
    assert set(body).issubset(props)
    assert 'jsonrpc' not in body and 'unitId' not in body


def test_mutation_failure_is_never_replayed_by_booking_adapter(settings, monkeypatch):
    approved(settings, monkeypatch)
    transport = Transport([Failure('opaque')])
    gateway = Gateway(settings, transport)
    with pytest.raises(Uncertain): gateway.create({})
    assert len(transport.calls) == 1


def test_simulation_cannot_use_real_write_transport(settings):
    transport = Transport([])
    with pytest.raises(Review, match='writes_disabled'): Gateway(settings, transport).create({})
    assert not transport.calls


def test_account_and_region_are_bound_to_checkpoint(settings):
    transport = Transport([]); transport.base = 'https://user-api-v2.simplybook.it'
    with pytest.raises(Review, match='region_identity'): Gateway(settings, transport)


def test_separate_test_account_requires_explicit_identity(settings):
    transport = Transport([]); transport.company = 'isolated-test-company'
    settings.salon = transport.company; settings.expected_rest_base = transport.base
    with pytest.raises(Review, match='isolated_account_identity'): Gateway(settings, transport)
    settings.approvals['account_identity_verified'] = True
    assert Gateway(settings, transport).transport.company == 'isolated-test-company'


def test_rest_cancel_edit_and_approve_use_documented_verbs(settings, monkeypatch):
    approved(settings, monkeypatch)
    transport = Transport([{}, {}, {}]); gateway = Gateway(settings, transport)
    gateway.edit(123, {'provider_id': 81}); gateway.cancel(123); gateway.approve(123)
    assert [(m, p) for m, p, b in transport.calls] == [
        ('PUT', '/admin/bookings/123'), ('DELETE', '/admin/bookings/123'), ('PUT', '/admin/bookings/123/approve')]


def test_pilot_target_cannot_cancel_real_client_booking(settings, monkeypatch):
    approved(settings, monkeypatch); settings.mode = 'pilot'; settings.approvals['pilot_isolation'] = True
    settings.pilot_client_ids = [71]; settings.pilot_service_ids = [91]
    transport = Transport([{'id': 123, 'client_id': 999, 'provider_id': 81, 'service_id': 91}])
    with pytest.raises(Review, match='pilot_target_outside'): Gateway(settings, transport).cancel(123)
    assert transport.calls[0][0] == 'GET' and len(transport.calls) == 1


def test_calendar_omitted_sunday_requires_explicit_offday_evidence(settings):
    columns = [{'date': '2026-10-' + str(n), 'from': '09:00:00', 'to': '18:00:00', 'is_day_off': False}
               for n in range(26, 32)]
    transport = Transport([{'columns': columns}]); gateway = Gateway(settings, transport)
    result = gateway.calendar_week(81, date(2026, 10, 26), {'2026-11-01': {'is_day_off': True}})
    assert result['2026-11-01']['is_day_off'] is True and len(result) == 7
    transport.responses = [{'columns': columns}]
    with pytest.raises(Review, match='day_coverage'): gateway.calendar_week(81, date(2026, 10, 26), {})


def test_duration_cleanup_and_split_treatment_require_explicit_equivalence(settings, event):
    service = {'id': 91, 'is_active': True, 'providers': [81], 'duration': 60, 'buffer_time_after': 10}
    provider = {'id': 81, 'is_active': True}
    desired = {'service_id': 91, 'provider_id': 81}
    mapping = settings.services['synthetic-service-A']
    gateway = Gateway(settings, Transport([service, provider]))
    with pytest.raises(Review, match='cleanup_buffer'): gateway.validate_booking(desired, event['data'], mapping)
    event['data']['service']['cleanup_duration'] = 10
    gateway.transport.responses = [service, provider]
    gateway.validate_booking(desired, event['data'], mapping)
    event['data']['service']['start_duration'] = 5
    gateway.transport.responses = [service, provider]
    with pytest.raises(Review, match='unsupported_split'): gateway.validate_booking(desired, event['data'], mapping)


def test_no_matching_slot_fails_closed(settings):
    gateway = Gateway(settings, Transport([[]]))
    desired = {'service_id': 91, 'provider_id': 81, 'start_datetime': '2026-10-23 10:00:00'}
    with pytest.raises(Review, match='slot_conflict'): gateway.ensure_available(desired)


def test_mapping_catalog_contains_exact_imported_ids_no_fuzzy_matching():
    import csv
    with (HOME / 'mappings/services.csv').open(encoding='utf-8-sig') as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 490
    assert len({row['simplybook_id'] for row in rows}) == 490
    assert not any(row['sredime_id'] for row in rows)
    assert not any(row['timing_verified'] == 'yes' for row in rows)


def test_real_empty_booking_list_has_zero_pages(settings):
    transport = Transport([{'data': [], 'metadata': {'page': 1, 'pages_count': 0, 'items_count': 0}}])
    assert Gateway(settings, transport).bookings('2026-10-20', '2026-12-20') == []


def test_booking_pagination_full_inventory_and_unique_ids(settings):
    row = {'id': 123, 'status': 'confirmed'}
    transport = Transport([{'data': [row], 'metadata': {'page': 1, 'pages_count': 2, 'items_count': 2}},
                           {'data': [{'id': 124}], 'metadata': {'page': 2, 'pages_count': 2, 'items_count': 2}}])
    assert [r['id'] for r in Gateway(settings, transport).bookings('2026-10-20', '2026-12-20')] == [123, 124]


@pytest.mark.parametrize('response', [
    {'data': [], 'metadata': {'page': 1, 'pages_count': 0, 'items_count': 2}},
    {'data': [{'id': 123}, {'id': 123}], 'metadata': {'page': 1, 'pages_count': 1, 'items_count': 2}},
    {'data': [], 'metadata': {'page': 1, 'pages_count': 1, 'items_count': 1}}
])
def test_incomplete_booking_response_never_publishes_empty_snapshot(settings, response):
    with pytest.raises(Temporary): Gateway(settings, Transport([response])).bookings('2026-10-20', '2026-12-20')


def test_unrestricted_service_keeps_sredime_specific_provider(settings, event):
    service = {'id': 91, 'is_active': True, 'providers': [], 'duration': 60, 'buffer_time_after': 0}
    provider = {'id': 81, 'is_active': True}
    gateway = Gateway(settings, Transport([service, provider]))
    gateway.validate_booking({'service_id': 91, 'provider_id': 81}, event['data'], settings.services['synthetic-service-A'])
