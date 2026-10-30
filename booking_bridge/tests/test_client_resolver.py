"""Synthetic-only client resolution tests; conftest also blocks real HTTP."""
import copy
from dataclasses import replace
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from booking_bridge.client_resolver import (
    ClientResolver, ClientResolverPolicy, normalize_email, normalize_phone,
)
from booking_bridge.model import Review, Temporary, Uncertain


CONTACTS = {'name': 'Synthetic Person', 'email': 'person@unit.test', 'phone': '+12025550101'}


def client(identifier=701, **changes):
    return {'id': identifier, **CONTACTS, **changes}


def page(rows=(), *, number=1, pages=None, total=None):
    rows = list(rows)
    return {'data': rows, 'metadata': {'page': number, 'pages_count': int(bool(rows)) if pages is None else pages,
                                      'items_count': len(rows) if total is None else total}}


class FakeGateway:
    def __init__(self):
        self.calls = []
        self.search_pages = {}
        self.default_page = page()
        self.details = {}
        self.default_detail = client()
        self.post_results = [{'id': 701}]
        self.before_write = None
        self.before_read = None

    def read(self, path):
        self.calls.append(('GET', path, None))
        if self.before_read:
            self.before_read(path)
        if path.startswith('/admin/clients?'):
            query = parse_qs(urlsplit(path).query)
            key = (query['filter[search]'][0], int(query['page'][0]))
            result = self.search_pages.get(key, self.default_page)
        else:
            result = self.details.get(int(path.rsplit('/', 1)[1]), self.default_detail)
            if isinstance(result, list):
                result = result.pop(0)
        if isinstance(result, BaseException):
            raise result
        return copy.deepcopy(result)

    def write(self, method, path, body):
        self.calls.append((method, path, copy.deepcopy(body)))
        assert method == 'POST' and path == '/admin/clients'
        if self.before_write:
            self.before_write(method, path, body)
        result = self.post_results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return copy.deepcopy(result)


@pytest.fixture
def policy():
    return ClientResolverPolicy(storage_approved=True, linking_approved=True,
                                create_approved=True, required_fields_verified=True)


@pytest.fixture
def transport():
    return FakeGateway()


def resolver(store, transport, policy, **kwargs):
    return ClientResolver(store, transport, policy=policy, **kwargs)


def resolve(instance, source='opaque-source', contacts=None):
    return instance.resolve(source, dict(CONTACTS) if contacts is None else contacts,
                            contacts_verified=True)


def intent(store, source='opaque-source'):
    return store.get('client-intent:' + source)[0]


def posts(transport):
    return [row for row in transport.calls if row[0] == 'POST']


def test_constructor_never_calls_store_gateway_or_contact_source(policy):
    class Bomb:
        def __getattr__(self, key):
            raise AssertionError('Constructor accessed an injected capability')
    ClientResolver(Bomb(), Bomb(), policy=policy)


@pytest.mark.parametrize('change,reason', [
    ({'storage_approved': False}, 'client_resolver_consent_required'),
    ({'linking_approved': False}, 'client_resolver_consent_required'),
    ({'required_fields_verified': False}, 'client_field_policy_unverified'),
    ({'required_fields': ('name', 'birthdate')}, 'client_required_fields_not_supported'),
    ({'required_fields': ('name', ['email'])}, 'client_required_fields_not_supported'),
    ({'max_pages': 11}, 'client_resolver_policy_invalid'),
    ({'page_size': 101}, 'client_resolver_policy_invalid'),
])
def test_unapproved_or_invalid_policy_performs_no_network(store, transport, policy, change, reason):
    with pytest.raises(Review, match=reason):
        resolver(store, transport, replace(policy, **change))
    assert transport.calls == []


def test_verified_contact_source_is_separate_from_global_consent(store, transport, policy):
    with pytest.raises(Review, match='client_contact_source_unverified'):
        resolver(store, transport, policy).resolve('opaque-source', CONTACTS)
    assert transport.calls == []


def test_default_source_webhook_customer_id_cannot_manufacture_contacts(store, transport, policy):
    with pytest.raises(Review, match='client_required_contact_missing'):
        resolve(resolver(store, transport, policy), contacts={'id': 'opaque-customer-only'})
    assert transport.calls == [] and intent(store) is None


@pytest.mark.parametrize('field', ['name', 'email', 'phone'])
@pytest.mark.parametrize('value', [None, '', '  '])
def test_missing_current_mandatory_fields_never_create_placeholders(store, transport, policy, field, value):
    supplied = {**CONTACTS, field: value}
    with pytest.raises(Review, match='client_required_contact_missing'):
        resolve(resolver(store, transport, policy), contacts=supplied)
    assert transport.calls == [] and intent(store) is None


@pytest.mark.parametrize('phone', ['02079460000', '0641234567', '12025550101', '+44 (0)20 7946 0018',
                                   '+12025550101x8', '+0123456789', '0000000000'])
def test_phone_countries_and_extensions_are_not_guessed(phone):
    with pytest.raises(Review, match='client_phone_international_required'):
        normalize_phone(phone)


def test_contact_normalization_preserves_mailbox_aliases_and_explicit_country():
    assert normalize_email(' A.B+Tag@UNIT.TEST ') == 'a.b+tag@unit.test'
    assert normalize_phone('00 44 (20) 7946-0018') == '+442079460018'
    assert normalize_phone('+1 (202) 555.0101') == '+12025550101'


@pytest.mark.parametrize('email', ['bad', 'Name <a@unit.test>', 'a..b@unit.test', 'a@localhost', 'a@missing.invalid'])
def test_invalid_or_placeholder_email_is_rejected(email):
    with pytest.raises(Review):
        normalize_email(email)


def test_control_characters_cannot_enter_contact_payloads(store, transport, policy):
    with pytest.raises(Review, match='client_contact_value_invalid'):
        resolve(resolver(store, transport, policy), contacts={**CONTACTS, 'name': 'Private\nName'})
    assert transport.calls == []


def test_create_journal_precedes_post_and_success_is_saved_before_readback(store, transport, policy):
    observed = []
    def before_write(method, path, body):
        current = intent(store)
        assert current['state'] == 'started' and current['target'] is None
        assert store.rows('SELECT * FROM clients') == []
        assert body == CONTACTS
        observed.append('journal_before_post')
    def before_read(path):
        if path == '/admin/clients/701':
            current = intent(store)
            assert current['state'] == 'result_saved' and current['target'] == 701
            assert store.rows('SELECT * FROM clients') == []
            observed.append('result_before_readback')
    transport.before_write, transport.before_read = before_write, before_read
    result = resolve(resolver(store, transport, policy))
    assert result.client_id == 701 and result.outcome == 'created'
    assert observed == ['journal_before_post', 'result_before_readback']
    assert store.rows('SELECT * FROM clients') == [{'source': 'opaque-source', 'target': 701}]
    assert intent(store)['state'] == 'done'


def test_does_not_copy_extra_contacts_mutate_payloads_or_touch_ingress_hash(store, transport, policy, event):
    store.ingest(event)
    old_events = store.rows('SELECT * FROM events')
    supplied = {**CONTACTS, 'notes': 'never copy', 'address1': 'never copy', 'event': event}
    before = copy.deepcopy(supplied)
    resolve(resolver(store, transport, policy), contacts=supplied)
    assert supplied == before
    assert posts(transport)[0][2] == CONTACTS
    assert store.rows('SELECT * FROM events') == old_events
    private_state = json.dumps(store.rows('SELECT key,value FROM cache'))
    assert CONTACTS['email'] not in private_state and CONTACTS['phone'] not in private_state
    assert CONTACTS['name'] not in private_state and 'never copy' not in private_state


def test_exact_match_links_existing_id_after_authoritative_detail_read(store, transport, policy):
    transport.default_page = page([client(71, name='  SYNTHETIC   PERSON ', email='PERSON@UNIT.TEST',
                                                   phone='001 (202) 555-0101')])
    transport.details[71] = client(71)
    result = resolve(resolver(store, transport, policy))
    assert result.client_id == 71 and result.outcome == 'matched'
    assert not posts(transport)
    assert transport.calls[-1] == ('GET', '/admin/clients/71', None)
    assert intent(store)['kind'] == 'link' and intent(store)['state'] == 'done'


@pytest.mark.parametrize('candidate', [
    client(71, phone='+12025550202'),
    client(71, email='other@unit.test'),
    client(71, name='Another Person'),
    client(71, phone=None),
])
def test_partial_contacts_or_different_name_never_autolink(store, transport, policy, candidate):
    transport.default_page = page([candidate])
    with pytest.raises(Review, match='client_contact_conflict'):
        resolve(resolver(store, transport, policy))
    assert not posts(transport) and store.rows('SELECT * FROM clients') == []


@pytest.mark.parametrize('candidates', [
    [client(71), client(72)],
    [client(71, phone='+12025550202'), client(72, email='other@unit.test')],
    [client(71), client(72, name='Family Member', email='family@unit.test')],
])
def test_shared_or_split_contact_candidates_are_always_reviewed(store, transport, policy, candidates):
    transport.default_page = page(candidates)
    with pytest.raises(Review, match='client_shared_or_ambiguous_contact'):
        resolve(resolver(store, transport, policy))
    assert not posts(transport) and intent(store) is None


def test_name_only_match_neither_merges_nor_creates_duplicate_silently(store, transport, policy):
    transport.default_page = page([client(71, email='other@unit.test', phone='+12025550202')])
    with pytest.raises(Review, match='client_name_only_match_requires_review'):
        resolve(resolver(store, transport, policy))
    assert not posts(transport)


def test_unrelated_fuzzy_candidates_are_not_selected_as_the_best_match(store, transport, policy):
    transport.default_page = page([client(71, name='Unrelated', email='other@unit.test', phone='+12025550202')])
    result = resolve(resolver(store, transport, policy))
    assert result.client_id == 701 and len(posts(transport)) == 1


def test_paginated_search_exhausts_pages_and_checks_both_contacts(store, transport, policy):
    other = client(72, name='Unrelated', email='other@unit.test', phone='+12025550202')
    for query in (CONTACTS['email'], CONTACTS['phone']):
        transport.search_pages[(query, 1)] = page([other], number=1, pages=2, total=2)
        transport.search_pages[(query, 2)] = page([client(71)], number=2, pages=2, total=2)
    transport.details[71] = client(71)
    result = resolve(resolver(store, transport, policy))
    assert result.client_id == 71 and len(transport.calls) == 5 and not posts(transport)


@pytest.mark.parametrize('second,reason', [
    (page([client(72)], number=2, pages=2, total=3), 'client_search_changed_during_read'),
    (page([client(71)], number=2, pages=2, total=2), 'client_search_duplicate_identifiers'),
    (page([], number=2, pages=2, total=2), 'client_search_pagination_invalid'),
    (page([client(72)], number=1, pages=2, total=2), 'client_search_pagination_invalid'),
])
def test_ambiguous_or_changing_pages_cannot_establish_absence(store, transport, policy, second, reason):
    transport.search_pages[(CONTACTS['email'], 1)] = page([client(71)], pages=2, total=2)
    transport.search_pages[(CONTACTS['email'], 2)] = second
    with pytest.raises(Review, match=reason):
        resolve(resolver(store, transport, policy))
    assert not posts(transport)


@pytest.mark.parametrize('bad', [
    [], {'data': [], 'metadata': {}},
    page([], pages=6, total=0), page([], pages=1, total=501),
    {'data': [], 'metadata': {'page': True, 'pages_count': 0, 'items_count': 0}},
    page([client(True)]), page([{'id': 71, 'email': CONTACTS['email']}]),
])
def test_malformed_or_unbounded_search_metadata_stops_without_post(store, transport, policy, bad):
    transport.default_page = bad
    with pytest.raises(Review):
        resolve(resolver(store, transport, policy))
    assert not posts(transport)


def test_same_id_with_changed_contacts_between_queries_requires_review(store, transport, policy):
    transport.search_pages[(CONTACTS['email'], 1)] = page([client(71)])
    transport.search_pages[(CONTACTS['phone'], 1)] = page([client(71, email='changed@unit.test')])
    with pytest.raises(Review, match='client_search_changed_during_read'):
        resolve(resolver(store, transport, policy))
    assert not posts(transport)


def test_response_byte_budget_and_errors_never_echo_vendor_contact_values(store, transport, policy):
    transport.default_page = {**page(), 'extra': 'PRIVATE_VALUE_' * 100}
    with pytest.raises(Review) as error:
        resolve(resolver(store, transport, replace(policy, max_response_bytes=256)))
    assert str(error.value) == 'client_api_response_too_large'
    assert 'PRIVATE_VALUE' not in str(error.value) and not posts(transport)


def test_existing_persisted_mapping_uses_one_get_without_search_or_post(store, transport, policy):
    store.execute('INSERT INTO clients VALUES(?,?)', ('opaque-source', 71))
    transport.details[71] = client(71)
    result = resolve(resolver(store, transport, replace(policy, create_approved=False)))
    assert result.client_id == 71 and result.outcome == 'persisted'
    assert transport.calls == [('GET', '/admin/clients/71', None)]


def test_configured_mapping_is_verified_and_persisted_without_search(store, transport, policy):
    transport.details[71] = client(71)
    result = resolve(resolver(store, transport, policy, configured_clients={'opaque-source': 71}))
    assert result.client_id == 71 and transport.calls == [('GET', '/admin/clients/71', None)]
    assert store.rows('SELECT * FROM clients') == [{'source': 'opaque-source', 'target': 71}]


def test_configured_and_persisted_mapping_disagreement_stops_before_http(store, transport, policy):
    store.execute('INSERT INTO clients VALUES(?,?)', ('opaque-source', 72))
    with pytest.raises(Review, match='client_mapping_changed'):
        resolve(resolver(store, transport, policy, configured_clients={'opaque-source': 71}))
    assert transport.calls == []


def test_configured_targets_and_persisted_targets_are_one_to_one(store, transport, policy):
    with pytest.raises(Review, match='client_configured_target_shared'):
        resolver(store, transport, policy, configured_clients={'one': 71, 'two': 71})
    store.execute('INSERT INTO clients VALUES(?,?)', ('another-source', 71))
    transport.default_page = page([client(71)])
    with pytest.raises(Review, match='client_target_already_linked'):
        resolve(resolver(store, transport, policy))
    assert not posts(transport)


def test_create_needs_its_own_permission_even_when_linking_is_approved(store, transport, policy):
    with pytest.raises(Review, match='client_creation_not_approved'):
        resolve(resolver(store, transport, replace(policy, create_approved=False)))
    assert not posts(transport) and intent(store) is None


def test_unavailable_existing_client_is_not_recreated_or_edited(store, transport, policy):
    transport.default_page = page([client(71, is_deleted=True)])
    with pytest.raises(Review, match='client_target_unavailable'):
        resolve(resolver(store, transport, policy))
    assert not posts(transport)


def test_lost_post_response_is_never_replayed_or_owned_from_search(store, transport, policy):
    transport.post_results = [TimeoutError('PRIVATE_VENDOR_BODY')]
    first = resolver(store, transport, policy)
    with pytest.raises(Uncertain) as error:
        resolve(first)
    assert str(error.value) == 'client_creation_requires_manual_review'
    assert intent(store)['state'] == 'uncertain' and intent(store)['target'] is None
    calls = len(transport.calls)
    transport.default_page = page([client(701)])  # Could be the uncertain write, or an older real client.
    with pytest.raises(Review, match='client_create_outcome_requires_review'):
        resolve(resolver(store, transport, policy))
    assert len(transport.calls) == calls and len(posts(transport)) == 1
    assert store.rows('SELECT * FROM clients') == []


@pytest.mark.parametrize('bad', [{}, {'id': True}, {'id': 0}, [], {'id': 701, 'large': 'x' * (1024 * 1024)}])
def test_unknown_create_response_cannot_trigger_another_post(store, transport, policy, bad):
    transport.post_results = [bad]
    with pytest.raises(Uncertain):
        resolve(resolver(store, transport, policy))
    with pytest.raises(Review, match='client_create_outcome_requires_review'):
        resolve(resolver(store, transport, policy))
    assert len(posts(transport)) == 1


def test_saved_success_with_failed_readback_resumes_with_get_only(store, transport, policy):
    transport.details[701] = [TimeoutError('private'), client(701)]
    with pytest.raises(Temporary, match='client_readback_unavailable'):
        resolve(resolver(store, transport, policy))
    assert intent(store)['state'] == 'result_saved' and intent(store)['target'] == 701
    assert store.rows('SELECT * FROM clients') == []
    calls = len(transport.calls)
    result = resolve(resolver(store, transport, policy))
    assert result.client_id == 701 and result.outcome == 'resumed_create'
    assert transport.calls[calls:] == [('GET', '/admin/clients/701', None)]
    assert len(posts(transport)) == 1


def test_failed_link_readback_resumes_pinned_candidate_without_research_or_create(store, transport, policy):
    transport.default_page = page([client(71)])
    transport.details[71] = [TimeoutError('private'), client(71)]
    with pytest.raises(Temporary):
        resolve(resolver(store, transport, policy))
    calls = len(transport.calls)
    result = resolve(resolver(store, transport, policy))
    assert result.client_id == 71 and result.outcome == 'resumed_link'
    assert transport.calls[calls:] == [('GET', '/admin/clients/71', None)] and not posts(transport)


@pytest.mark.parametrize('changed', [client(702), client(701, email='other@unit.test'),
                                     client(701, phone='+12025550202'), client(701, name='Other')])
def test_readback_must_match_exact_result_and_contacts(store, transport, policy, changed):
    transport.default_detail = changed
    with pytest.raises(Review):
        resolve(resolver(store, transport, policy))
    assert intent(store)['state'] == 'result_saved'
    assert store.rows('SELECT * FROM clients') == []
    assert len(posts(transport)) == 1


def test_changed_input_after_saved_create_does_not_research_or_overwrite_contacts(store, transport, policy):
    transport.details[701] = [TimeoutError('private')]
    with pytest.raises(Temporary):
        resolve(resolver(store, transport, policy))
    count = len(transport.calls)
    with pytest.raises(Review, match='client_contacts_changed_after_intent'):
        resolve(resolver(store, transport, policy), contacts={**CONTACTS, 'phone': '+12025550202'})
    assert len(transport.calls) == count and len(posts(transport)) == 1


def test_crash_after_remote_response_before_result_save_leaves_nonreplayable_intent(store, transport, policy, monkeypatch):
    class Crash(BaseException):
        pass
    instance = resolver(store, transport, policy)
    monkeypatch.setattr(instance, '_save_result', lambda *args: (_ for _ in ()).throw(Crash()))
    with pytest.raises(Crash):
        resolve(instance)
    assert intent(store)['state'] == 'started'
    with pytest.raises(Review, match='client_create_outcome_requires_review'):
        resolve(resolver(store, transport, policy))
    assert len(posts(transport)) == 1


def test_failure_after_successful_local_result_commit_keeps_get_recovery(store, transport, policy, monkeypatch):
    instance = resolver(store, transport, policy)
    original = instance._save_result
    def saved_then_failure(*args):
        original(*args)
        raise RuntimeError('PRIVATE_COMMIT_CONTEXT')
    monkeypatch.setattr(instance, '_save_result', saved_then_failure)
    with pytest.raises(Uncertain):
        resolve(instance)
    assert intent(store)['state'] == 'result_saved'
    count = len(transport.calls)
    result = resolve(resolver(store, transport, policy))
    assert result.client_id == 701
    assert transport.calls[count:] == [('GET', '/admin/clients/701', None)]
    assert len(posts(transport)) == 1


def test_local_link_transaction_failure_does_not_erase_saved_remote_success(store, transport, policy):
    def fail_after_remote_success(path):
        if path == '/admin/clients/701':
            # Install the fault after the initial schema/recovery validation.
            store.execute("CREATE TRIGGER refuse_client BEFORE INSERT ON clients BEGIN SELECT RAISE(ABORT,'synthetic'); END")
    transport.before_read = fail_after_remote_success
    with pytest.raises(Review, match='client_resolver_state_unavailable'):
        resolve(resolver(store, transport, policy))
    assert intent(store)['state'] == 'result_saved'
    assert store.rows('SELECT * FROM clients') == []
    store.execute('DROP TRIGGER refuse_client')
    transport.before_read = None
    count = len(transport.calls)
    resolve(resolver(store, transport, policy))
    assert transport.calls[count:] == [('GET', '/admin/clients/701', None)] and len(posts(transport)) == 1


def test_contact_claim_still_blocks_recreation_if_only_intent_is_deleted(store, transport, policy):
    transport.post_results = [TimeoutError('private')]
    with pytest.raises(Uncertain):
        resolve(resolver(store, transport, policy))
    store.execute('DELETE FROM cache WHERE key=?', ('client-intent:opaque-source',))
    with pytest.raises(Review, match='client_contact_claim_requires_review'):
        resolve(resolver(store, transport, policy))
    assert len(posts(transport)) == 1


def test_concurrent_different_source_cannot_create_a_shared_phone_client(store, transport, policy):
    second = FakeGateway()
    second.default_detail = client(702, email='second@unit.test')
    second.post_results = [{'id': 702}]
    observed = []
    def before_write(*args):
        # Reentrant state access demonstrates no SQLite transaction spans HTTP.
        with pytest.raises(Review, match='client_shared_contact_requires_review'):
            resolve(resolver(store, second, policy), source='other-source',
                    contacts={**CONTACTS, 'email': 'second@unit.test'})
        observed.append('blocked_before_second_post')
    transport.before_write = before_write
    resolve(resolver(store, transport, policy))
    assert observed == ['blocked_before_second_post'] and not posts(second)
    assert len(posts(transport)) == 1


def test_concurrent_verified_readback_of_same_claim_is_idempotent(store, transport, policy):
    transport.default_page = page([client(71)])
    transport.details[71] = client(71)
    second = FakeGateway()
    second.details[71] = client(71)
    observed = []
    def finish_pinned_claim(path):
        if path == '/admin/clients/71':
            observed.append(resolve(resolver(store, second, policy)).outcome)
    transport.before_read = finish_pinned_claim
    result = resolve(resolver(store, transport, policy))
    assert result.client_id == 71 and observed == ['resumed_link']
    assert store.rows('SELECT * FROM clients') == [{'source': 'opaque-source', 'target': 71}]
    assert not posts(transport) and not posts(second)


@pytest.mark.parametrize('old', [{'state': 'started', 'event': 'synthetic'},
                                 {'state': 'done', 'target': 71}])
def test_legacy_operator_intent_is_not_silently_reset(store, transport, policy, old):
    store.put('client-intent:opaque-source', old)
    with pytest.raises(Review, match='client_legacy_intent_requires_review'):
        resolve(resolver(store, transport, policy))
    assert transport.calls == [] and intent(store) == old


def test_recovery_hold_blocks_reads_and_client_journal_changes(store, transport, policy):
    store.put('recovery-hold', True)
    with pytest.raises(Review, match='client_resolver_recovery_hold'):
        resolve(resolver(store, transport, policy))
    assert transport.calls == [] and intent(store) is None


def test_verified_optional_field_policy_omits_missing_values_without_placeholder(store, transport, policy):
    optional_phone = replace(policy, required_fields=('name', 'email'))
    supplied = {**CONTACTS, 'phone': None}
    result = resolve(resolver(store, transport, optional_phone), contacts=supplied)
    assert result.client_id == 701
    assert posts(transport)[0][2] == {'name': CONTACTS['name'], 'email': CONTACTS['email']}


def test_module_produces_no_contact_logs_and_redacts_result_repr(store, transport, policy, capsys):
    result = resolve(resolver(store, transport, policy))
    assert capsys.readouterr() == ('', '')
    assert '701' not in repr(result) and CONTACTS['name'] not in repr(result)
    assert all(row[0] in ('GET', 'POST') for row in transport.calls)
