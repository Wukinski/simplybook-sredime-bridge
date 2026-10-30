"""Dormant, explicitly authorized client linking/creation through a guarded gateway.

No transport, credentials, database or network operation is constructed here.
Callers supply an existing Store, a gateway with read/write methods, verified
field requirements, and contacts obtained from an independently authorized
source. This module is intentionally not wired into ingress or the worker.
"""
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import json
import math
import re
import secrets
import time
import unicodedata
from urllib.parse import urlencode

from .model import Review, Temporary, Uncertain

FIELDS = frozenset(('name', 'email', 'phone'))
STATES = frozenset(('started', 'result_saved', 'done', 'uncertain'))
MAX_RESPONSE_BYTES = 1_048_576
MAX_JOURNAL_BYTES = 16_384


def require(condition, code):
    if not condition:
        raise Review(code)


def _plain(value, limit, *, optional=False):
    if optional and value in (None, ''):
        return None
    require(isinstance(value, str) and len(value) <= limit,
            'client_contact_value_invalid')
    require(not any(unicodedata.category(char).startswith('C') for char in value),
            'client_contact_value_invalid')
    result = unicodedata.normalize('NFKC', value).strip()
    if optional and not result:
        return None
    require(bool(result), 'client_contact_value_invalid')
    return result


def normalize_email(value):
    """Trim/case-fold only; never remove plus tags or mailbox dots."""
    result = _plain(value, 254, optional=True)
    if result is None:
        return None
    require(result.count('@') == 1, 'client_email_invalid')
    local, domain = result.rsplit('@', 1)
    require(bool(re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}", local)) and
            not local.startswith('.') and not local.endswith('.') and '..' not in local,
            'client_email_invalid')
    try:
        domain = domain.encode('idna').decode('ascii').lower()
    except UnicodeError:
        raise Review('client_email_invalid') from None
    labels = domain.split('.')
    require(len(labels) >= 2 and all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', part)
                                   for part in labels), 'client_email_invalid')
    require(labels[-1] not in ('invalid', 'localhost', 'example'), 'client_placeholder_contact_rejected')
    return local.casefold() + '@' + domain


def normalize_phone(value):
    """Accept explicit international numbers; never infer a local country/trunk."""
    result = _plain(value, 80, optional=True)
    if result is None:
        return None
    require('(0)' not in result and bool(re.fullmatch(r'[+0-9 ().-]+', result)),
            'client_phone_international_required')
    compact = re.sub(r'[ ().-]', '', result)
    if compact.startswith('00'):
        compact = '+' + compact[2:]
    require(bool(re.fullmatch(r'\+[1-9][0-9]{7,14}', compact)),
            'client_phone_international_required')
    return compact


def _name(value):
    return ' '.join(_plain(value, 200).split())


def _source(value):
    require(isinstance(value, str) and 1 <= len(value) <= 512 and value == value.strip() and
            not any(unicodedata.category(char).startswith('C') for char in value),
            'client_source_identifier_invalid')
    return value


def _identifier(value):
    require(type(value) is int and 0 < value < 2**63, 'client_target_identifier_invalid')
    return value


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=True, allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class ClientResolverPolicy:
    storage_approved: bool = False
    linking_approved: bool = False
    create_approved: bool = False
    required_fields_verified: bool = False
    required_fields: tuple = ('name', 'email', 'phone')
    max_pages: int = 5
    page_size: int = 100
    max_candidates: int = 500
    max_response_bytes: int = MAX_RESPONSE_BYTES

    def validate(self):
        require(self.storage_approved is True and self.linking_approved is True,
                'client_resolver_consent_required')
        require(type(self.create_approved) is bool, 'client_resolver_policy_invalid')
        require(self.required_fields_verified is True, 'client_field_policy_unverified')
        require(type(self.required_fields) is tuple and all(isinstance(item, str) for item in self.required_fields)
                and len(set(self.required_fields)) == len(self.required_fields) and
                set(self.required_fields) <= FIELDS, 'client_required_fields_not_supported')
        for value, low, high in ((self.max_pages, 1, 10), (self.page_size, 1, 100),
                                 (self.max_candidates, 1, 1000),
                                 (self.max_response_bytes, 128, MAX_RESPONSE_BYTES)):
            require(type(value) is int and low <= value <= high, 'client_resolver_policy_invalid')


@dataclass(frozen=True, repr=False)
class _Contacts:
    name: str
    email: str | None
    phone: str | None

    def payload(self):
        return {key: value for key, value in (('name', self.name), ('email', self.email),
                                             ('phone', self.phone)) if value is not None}

    @property
    def fingerprint(self):
        return _digest({'name': self.name.casefold(), 'email': self.email, 'phone': self.phone})


@dataclass(frozen=True)
class ClientResolution:
    client_id: int = field(repr=False)
    outcome: str


class ClientResolver:
    """All network calls occur inside resolve; POST uses the injected write guard.

    The injected gateway must retain normal account, quota, recovery and
    production checks. Its writes must not replay POSTs. It is normally the
    existing booking_bridge.simplybook.Gateway, not a naked HTTP session.
    """

    def __init__(self, store, gateway, *, policy, configured_clients=None, clock=time.time):
        require(isinstance(policy, ClientResolverPolicy), 'client_resolver_policy_required')
        policy.validate()
        require(configured_clients is None or type(configured_clients) is dict,
                'client_configuration_invalid')
        configured = dict(configured_clients or {})
        require(len(configured) <= 10000, 'client_configuration_too_large')
        targets = set()
        for source, target in configured.items():
            _source(source)
            _identifier(target)
            require(target not in targets, 'client_configured_target_shared')
            targets.add(target)
        self.store, self.gateway, self.policy = store, gateway, policy
        self.configured, self.clock = configured, clock

    def _contacts(self, supplied, verified):
        require(verified is True, 'client_contact_source_unverified')
        require(type(supplied) is dict, 'client_contact_data_invalid')
        for key in self.policy.required_fields:
            require(isinstance(supplied.get(key), str) and bool(supplied[key].strip()),
                    'client_required_contact_missing')
        require(isinstance(supplied.get('name'), str) and bool(supplied['name'].strip()),
                'client_required_contact_missing')
        result = _Contacts(_name(supplied['name']), normalize_email(supplied.get('email')),
                           normalize_phone(supplied.get('phone')))
        require(result.email is not None or result.phone is not None,
                'client_contact_data_incomplete')
        return result

    def _now(self):
        value = self.clock()
        require(type(value) in (int, float) and math.isfinite(value) and value > 0,
                'client_resolver_clock_invalid')
        return value

    @contextmanager
    def _state(self):
        try:
            with self.store.connect() as conn:
                yield conn
        except Review:
            raise
        except Exception:
            raise Review('client_resolver_state_unavailable') from None

    @staticmethod
    def _journal_key(source):
        # Share the namespace with the existing operator CLI, which is reviewed
        # rather than silently reset when its older intent shape is encountered.
        return 'client-intent:' + source

    @staticmethod
    def _read_cache(conn, key):
        row = conn.execute('SELECT value FROM cache WHERE key=?', (key,)).fetchone()
        if row is None:
            return None
        require(len(row['value'].encode()) <= MAX_JOURNAL_BYTES, 'client_journal_invalid')
        try:
            return json.loads(row['value'])
        except (ValueError, TypeError):
            raise Review('client_journal_invalid') from None

    def _write_cache(self, conn, key, value):
        conn.execute('INSERT INTO cache(key,value,updated) VALUES(?,?,?) '
                     'ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated=excluded.updated',
                     (key, json.dumps(value, sort_keys=True, allow_nan=False), self._now()))

    def _journal(self, conn, source):
        value = self._read_cache(conn, self._journal_key(source))
        if value is None:
            return None
        require(type(value) is dict and type(value.get('schema_version')) is int and value.get('schema_version') == 1 and
                value.get('resolver') == 'exact_contacts_v1', 'client_legacy_intent_requires_review')
        require(set(value) == {'schema_version', 'resolver', 'state', 'kind', 'claim',
                               'contacts_digest', 'target'} and value['state'] in STATES and
                value['kind'] in ('create', 'link') and
                isinstance(value['claim'], str) and bool(re.fullmatch('[a-f0-9]{32}', value['claim'])) and
                isinstance(value['contacts_digest'], str) and bool(re.fullmatch('[a-f0-9]{64}', value['contacts_digest'])),
                'client_journal_invalid')
        if value['state'] in ('result_saved', 'done'):
            _identifier(value['target'])
        else:
            require(value['target'] is None and value['kind'] == 'create', 'client_journal_invalid')
        return value

    def _reverse_guard(self, conn, source, target):
        require(not any(other != source and value == target for other, value in self.configured.items()),
                'client_target_already_linked')
        row = conn.execute('SELECT source FROM clients WHERE target=? AND source!=?', (target, source)).fetchone()
        require(row is None, 'client_target_already_linked')

    def _mapping(self, conn, source):
        row = conn.execute('SELECT target FROM clients WHERE source=?', (source,)).fetchone()
        stored = _identifier(row['target']) if row else None
        configured = self.configured.get(source)
        require(not (stored and configured and stored != configured), 'client_mapping_changed')
        target = stored or configured
        if target:
            self._reverse_guard(conn, source, target)
        return stored, configured

    @staticmethod
    def _reservation_keys(contacts):
        return ['client-contact-reservation:' + key + ':' + hashlib.sha256(value.encode()).hexdigest()
                for key, value in (('email', contacts.email), ('phone', contacts.phone)) if value is not None]

    def _inspect(self, source):
        with self._state() as conn:
            stored, configured = self._mapping(conn, source)
            intent = self._journal(conn, source)
            if intent:
                if intent['state'] == 'done':
                    require(stored == intent['target'], 'client_mapping_journal_inconsistent')
                elif intent['state'] in ('started', 'uncertain'):
                    raise Review('client_create_outcome_requires_review')
                else:
                    require(not stored or stored == intent['target'], 'client_mapping_changed')
                    require(not configured or configured == intent['target'], 'client_mapping_changed')
            return stored, configured, intent

    def _claim(self, source, contacts, target):
        if target is not None:
            _identifier(target)
        with self._state() as conn:
            stored, configured = self._mapping(conn, source)
            require(stored is None and self._journal(conn, source) is None,
                    'client_resolution_changed_during_read')
            require(not configured or target == configured, 'client_mapping_changed')
            if target is not None:
                self._reverse_guard(conn, source, target)
            for key in self._reservation_keys(contacts):
                old = self._read_cache(conn, key)
                if old is not None:
                    require(type(old) is dict and old.get('source') == source,
                            'client_shared_contact_requires_review')
                    # A leftover claim is evidence of an earlier operation;
                    # deleting its journal never authorizes another POST.
                    raise Review('client_contact_claim_requires_review')
            intent = {'schema_version': 1, 'resolver': 'exact_contacts_v1',
                      'state': 'result_saved' if target else 'started',
                      'kind': 'link' if target else 'create', 'claim': secrets.token_hex(16),
                      'contacts_digest': contacts.fingerprint, 'target': target}
            self._write_cache(conn, self._journal_key(source), intent)
            for key in self._reservation_keys(contacts):
                self._write_cache(conn, key, {'source': source, 'claim': intent['claim'], 'state': 'reserved'})
        return intent

    def _mark_uncertain(self, source, intent):
        try:
            with self._state() as conn:
                current = self._journal(conn, source)
                if current == intent:
                    current['state'] = 'uncertain'
                    self._write_cache(conn, self._journal_key(source), current)
        except Review:
            # The already committed started intent still prohibits replay.
            pass

    def _save_result(self, source, intent, target):
        with self._state() as conn:
            current = self._journal(conn, source)
            require(current == intent, 'client_intent_changed_during_create')
            current.update(state='result_saved', target=_identifier(target))
            self._write_cache(conn, self._journal_key(source), current)
        return current

    def _finalize(self, source, contacts, intent):
        target = intent['target']
        with self._state() as conn:
            current = self._journal(conn, source)
            stored, configured = self._mapping(conn, source)
            if current == {**intent, 'state': 'done'} and stored == target:
                # A concurrent verified GET completed this exact pinned claim.
                return
            require(current == intent and current['state'] == 'result_saved', 'client_intent_changed_before_link')
            require(not stored or stored == target, 'client_mapping_changed')
            require(not configured or configured == target, 'client_mapping_changed')
            self._reverse_guard(conn, source, target)
            for key in self._reservation_keys(contacts):
                owner = self._read_cache(conn, key)
                require(type(owner) is dict and owner.get('source') == source and owner.get('claim') == intent['claim'],
                        'client_contact_claim_changed')
            if stored is None:
                conn.execute('INSERT INTO clients(source,target) VALUES(?,?)', (source, target))
            current['state'] = 'done'
            self._write_cache(conn, self._journal_key(source), current)
            for key in self._reservation_keys(contacts):
                self._write_cache(conn, key, {'source': source, 'claim': intent['claim'],
                                             'state': 'linked', 'target': target})

    def _bounded(self, value):
        try:
            require(len(json.dumps(value, allow_nan=False, ensure_ascii=True).encode()) <= self.policy.max_response_bytes,
                    'client_api_response_too_large')
        except (ValueError, TypeError, OverflowError):
            raise Review('client_api_response_invalid') from None
        return value

    @staticmethod
    def _candidate(value):
        require(type(value) is dict, 'client_api_response_invalid')
        identifier = _identifier(value.get('id'))
        require(isinstance(value.get('name'), str), 'client_api_response_invalid')
        for flag in ('is_deleted', 'is_blocked'):
            require(flag not in value or type(value[flag]) is bool, 'client_api_response_invalid')
        return {'id': identifier, 'name': _name(value['name']).casefold(),
                'email': normalize_email(value.get('email')), 'phone': normalize_phone(value.get('phone')),
                'unavailable': value.get('is_deleted') is True or value.get('is_blocked') is True}

    def _read(self, path, *, detail=False):
        try:
            value = self.gateway.read(path)
        except Exception:
            raise Temporary('client_readback_unavailable' if detail else 'client_search_unavailable') from None
        return self._bounded(value)

    def _search_one(self, query):
        result, seen, expected = [], set(), None
        for page in range(1, self.policy.max_pages + 1):
            path = '/admin/clients?' + urlencode({'filter[search]': query, 'page': page,
                                                 'on_page': self.policy.page_size})
            value = self._read(path)
            require(type(value) is dict and type(value.get('data')) is list and type(value.get('metadata')) is dict,
                    'client_search_response_invalid')
            metadata, data = value['metadata'], value['data']
            require(all(type(metadata.get(key)) is int for key in ('page', 'pages_count', 'items_count')),
                    'client_search_pagination_invalid')
            total, pages = metadata['items_count'], metadata['pages_count']
            require(metadata['page'] == page and 0 <= total <= self.policy.max_candidates and
                    0 <= pages <= self.policy.max_pages, 'client_search_pagination_invalid')
            require(expected is None or expected == (total, pages), 'client_search_changed_during_read')
            expected = total, pages
            if total == 0:
                require(page == 1 and not data and pages in (0, 1), 'client_search_pagination_invalid')
                return []
            require(pages >= 1 and bool(data), 'client_search_pagination_invalid')
            rows = [self._candidate(item) for item in data]
            identifiers = [row['id'] for row in rows]
            require(len(identifiers) == len(set(identifiers)) and not seen.intersection(identifiers),
                    'client_search_duplicate_identifiers')
            require(len(result) + len(rows) <= total, 'client_search_pagination_invalid')
            seen.update(identifiers)
            result.extend(rows)
            # Some existing account endpoints return the entire first page;
            # exact total cardinality and unique IDs still prove full coverage.
            if page == 1 and len(result) == total:
                return result
            if page == pages:
                require(len(result) == total, 'client_search_pagination_invalid')
                return result
        raise Review('client_search_page_limit_reached')

    def _search(self, contacts):
        candidates = {}
        for query in (contacts.email, contacts.phone):
            if query is None:
                continue
            for row in self._search_one(query):
                old = candidates.get(row['id'])
                require(old is None or old == row, 'client_search_changed_during_read')
                candidates[row['id']] = row
                require(len(candidates) <= self.policy.max_candidates, 'client_search_candidate_limit_reached')
        shared, names_only = [], False
        for row in candidates.values():
            same = [row[key] == value for key, value in (('email', contacts.email), ('phone', contacts.phone))
                    if value is not None]
            if any(same):
                shared.append((row, all(same)))
            elif row['name'] == contacts.name.casefold():
                names_only = True
        require(len(shared) <= 1, 'client_shared_or_ambiguous_contact')
        if shared:
            row, every_contact = shared[0]
            require(every_contact and row['name'] == contacts.name.casefold(), 'client_contact_conflict')
            require(not row['unavailable'], 'client_target_unavailable')
            return row['id']
        require(not names_only, 'client_name_only_match_requires_review')
        return None

    def _verify(self, target, contacts):
        row = self._candidate(self._read('/admin/clients/' + str(_identifier(target)), detail=True))
        require(row['id'] == target, 'client_readback_identifier_mismatch')
        require(not row['unavailable'], 'client_target_unavailable')
        require(row['name'] == contacts.name.casefold() and
                all(row[key] == value for key, value in (('email', contacts.email), ('phone', contacts.phone))
                    if value is not None), 'client_readback_contact_mismatch')

    def resolve(self, source, contacts, *, contacts_verified=False):
        """Return a verified client ID, or a fixed review/temporary/uncertain code.

        contacts_verified means an external authorized source established these
        fields. A default webhook containing only a customer ID cannot set it.
        """
        self.policy.validate()
        source = _source(source)
        prepared = self._contacts(contacts, contacts_verified)
        from .recovery import recovery_start_allowed
        require(recovery_start_allowed(self.store.path), 'client_resolver_recovery_hold')
        stored, configured, intent = self._inspect(source)
        if stored and (intent is None or intent['state'] == 'done'):
            self._verify(stored, prepared)
            return ClientResolution(stored, 'persisted')
        if intent:
            require(intent['contacts_digest'] == prepared.fingerprint, 'client_contacts_changed_after_intent')
            self._verify(intent['target'], prepared)
            self._finalize(source, prepared, intent)
            return ClientResolution(intent['target'], 'resumed_create' if intent['kind'] == 'create' else 'resumed_link')
        target = configured or self._search(prepared)
        require(target is not None or self.policy.create_approved is True, 'client_creation_not_approved')
        intent = self._claim(source, prepared, target)
        if target is None:
            try:
                response = self._bounded(self.gateway.write('POST', '/admin/clients', prepared.payload()))
                require(type(response) is dict, 'client_create_response_invalid')
                target = _identifier(response.get('id'))
                intent = self._save_result(source, intent, target)
            except Exception:
                self._mark_uncertain(source, intent)
                raise Uncertain('client_creation_requires_manual_review') from None
        self._verify(target, prepared)
        self._finalize(source, prepared, intent)
        return ClientResolution(target, 'created' if intent['kind'] == 'create' else 'matched')
