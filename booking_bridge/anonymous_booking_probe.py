"""Dormant one-shot capability probe for the existing hidden test records only.

No default transport is constructed. Preparation performs GETs only. Execution
requires a plan-bound explicit experiment authorization and a separate durable
journal. This is not a worker/gateway mode and never enables synchronization.
"""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time
from urllib.parse import urlencode
import uuid

from provider_assignment.core import lock
from .model import BELGRADE, Review, local_stamp

COMPANY = 'studioandjelija'
BASE = 'https://user-api-v2.simplybook.me'
PROVIDER = 9
PROVIDER_NAME = 'TEST integracija A'
SERVICE = 496
SERVICE_NAME = 'TEST integracija 30 min'
DURATION = 30
MAX_PAGES = 10
PLAN_TTL = 600
PAYLOAD_KEYS = {'provider_id', 'service_id', 'start_datetime', 'end_datetime', 'count'}


def require(condition, code):
    if not condition:
        raise Review(code)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def moment(value):
    require(type(value) in (int, float) and 0 < value < 253402300799,
            'anonymous_probe_clock_invalid')
    return value


def positive(value):
    require(type(value) is int and value > 0, 'anonymous_probe_identifier_invalid')
    return value


def write(path, data, *, exclusive=False):
    path = Path(path)
    require(not path.is_symlink() and path.parent.is_dir(), 'anonymous_probe_private_path_invalid')
    body = (json.dumps(data, sort_keys=True, allow_nan=False, indent=2) + '\n').encode()
    if exclusive:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(body); handle.flush(); os.fsync(handle.fileno())
        return
    descriptor, temporary = tempfile.mkstemp(prefix='.anonymous-probe-', dir=path.parent)
    try:
        if hasattr(os, 'fchmod'):
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(body); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read(path):
    path = Path(path)
    require(not path.is_symlink() and path.is_file() and path.stat().st_size <= 1024 * 1024,
            'anonymous_probe_private_input_invalid')
    if os.name != 'nt':
        require(stat.S_IMODE(path.stat().st_mode) & 0o077 == 0,
                'anonymous_probe_private_permissions_required')
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, 'anonymous_probe_duplicate_configuration')
            value[key] = item
        return value
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(Review('anonymous_probe_input_invalid')))


def client_shape(value):
    """Presence categories only; never retain a client's ID/name/contact values."""
    require(isinstance(value, dict), 'anonymous_probe_booking_shape_invalid')
    flat = 'absent' if 'client_id' not in value else 'null' if value['client_id'] is None else 'nonnull'
    nested = 'absent' if 'client' not in value else 'null' if value['client'] is None else 'nonnull'
    contact = any(value.get(key) not in (None, '') for key in ('name', 'email', 'phone', 'client_name', 'client_email', 'client_phone'))
    return {'client_id_state': flat, 'client_object_state': nested,
            'contact_values_present': contact}


def booking_projection(value):
    require(isinstance(value, dict), 'anonymous_probe_booking_shape_invalid')
    keys = ('id', 'provider_id', 'service_id', 'start_datetime', 'end_datetime', 'status')
    require(all(key in value for key in keys), 'anonymous_probe_booking_shape_invalid')
    result = {key: value[key] for key in keys}
    for key in ('id', 'provider_id', 'service_id'):
        positive(result[key])
    for key in ('start_datetime', 'end_datetime'):
        require(isinstance(result[key], str) and
                re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', result[key]),
                'anonymous_probe_booking_time_invalid')
        local_stamp(result[key])
    require(result['status'] in ('confirmed', 'confirmed_pending', 'pending', 'process', 'canceled'),
            'anonymous_probe_booking_status_invalid')
    if 'duration' in value:
        require(type(value['duration']) is int and value['duration'] > 0,
                'anonymous_probe_booking_duration_invalid')
        result['duration'] = value['duration']
    result['client_shape'] = client_shape(value)
    return result


def matches_booking(row, payload, *, active=True):
    return (all(row.get(key) == payload[key] for key in
                ('provider_id', 'service_id', 'start_datetime', 'end_datetime')) and
            row.get('duration', DURATION) == DURATION and
            (not active or row.get('status') != 'canceled'))


class Probe:
    """Fixed account/IDs; no arbitrary write method, client write, or source API."""
    def __init__(self, transport):
        require(getattr(transport, 'company', None) == COMPANY and
                getattr(transport, 'base', None) == BASE, 'anonymous_probe_account_mismatch')
        self._transport = transport

    def _account(self):
        require(getattr(self._transport, 'company', None) == COMPANY and
                getattr(self._transport, 'base', None) == BASE,
                'anonymous_probe_account_mismatch')

    def _get(self, path):
        self._account()
        require(path in (f'/admin/providers/{PROVIDER}', f'/admin/services/{SERVICE}',
                         '/admin/clients?page=1&on_page=1') or
                path.startswith('/admin/schedule/available-slots?') or
                path.startswith('/admin/bookings?') or
                re.fullmatch(r'/admin/bookings/[1-9][0-9]*', path),
                'anonymous_probe_read_outside_scope')
        try:
            return self._transport.request('GET', path)
        except Exception:
            raise Review('anonymous_probe_read_unavailable') from None

    def identities(self):
        provider = self._get(f'/admin/providers/{PROVIDER}')
        service = self._get(f'/admin/services/{SERVICE}')
        require(isinstance(provider, dict) and isinstance(service, dict), 'anonymous_probe_identity_invalid')
        require(provider.get('id') == PROVIDER and provider.get('name') == PROVIDER_NAME and
                provider.get('is_active') is True and provider.get('is_visible') is False and
                type(provider.get('qty')) is int and provider['qty'] == 1 and
                isinstance(provider.get('services'), list) and SERVICE in provider['services'],
                'anonymous_probe_test_provider_changed')
        require(not provider.get('email') and not provider.get('phone'),
                'anonymous_probe_provider_contact_requires_review')
        require(service.get('id') == SERVICE and service.get('name') == SERVICE_NAME and
                service.get('is_active') is True and service.get('is_visible') is False and
                type(service.get('duration')) is int and service['duration'] == DURATION and
                service.get('providers') == [PROVIDER] and service.get('buffer_time_after', 0) == 0 and
                str(service.get('price')) in ('0', '0.0', '0.00'),
                'anonymous_probe_test_service_changed')
        return {'provider': {key: provider[key] for key in ('id', 'name', 'is_active', 'is_visible', 'qty')},
                'provider_has_service': True,
                'service': {key: service[key] for key in ('id', 'name', 'is_active', 'is_visible', 'duration', 'providers')},
                'service_zero_price_and_buffer': True}

    def client_count(self):
        value = self._get('/admin/clients?page=1&on_page=1')
        require(isinstance(value, dict) and isinstance(value.get('data'), list) and
                isinstance(value.get('metadata'), dict), 'anonymous_probe_client_metadata_invalid')
        metadata, rows = value['metadata'], value['data']
        require(all(type(metadata.get(key)) is int for key in ('page', 'pages_count', 'items_count')) and
                metadata['page'] == 1 and metadata['items_count'] >= 0 and
                metadata['pages_count'] >= 0 and len(rows) <= metadata['items_count'],
                'anonymous_probe_client_metadata_invalid')
        require((metadata['items_count'] == 0 and len(rows) == 0 and metadata['pages_count'] in (0, 1)) or
                (metadata['items_count'] > 0 and len(rows) > 0 and metadata['pages_count'] >= 1),
                'anonymous_probe_client_metadata_invalid')
        # The documented endpoint has no metadata-only/field-projection option.
        # It can return a row with contacts on the wire; none are retained here.
        return {'items_count': metadata['items_count'], 'page': 1,
                'pages_count': metadata['pages_count'], 'rows_returned': len(rows),
                'contact_fields_retained': False, 'requested_on_page': 1}

    def bookings(self, day):
        require(date.fromisoformat(day).isoformat() == day, 'anonymous_probe_date_invalid')
        result, seen, expected = [], set(), None
        for page in range(1, MAX_PAGES + 1):
            query = urlencode({'filter[date]': day, 'filter[upcoming_only]': 0, 'page': page, 'on_page': 100})
            value = self._get('/admin/bookings?' + query)
            require(isinstance(value, dict) and isinstance(value.get('data'), list) and
                    isinstance(value.get('metadata'), dict), 'anonymous_probe_booking_inventory_invalid')
            meta = value['metadata']
            require(all(type(meta.get(key)) is int for key in ('page', 'pages_count', 'items_count')) and
                    meta['page'] == page and 0 <= meta['items_count'] <= 1000 and
                    0 <= meta['pages_count'] <= MAX_PAGES,
                    'anonymous_probe_booking_pagination_invalid')
            marker = (meta['items_count'], meta['pages_count'])
            require((meta['items_count'] == 0 and meta['pages_count'] in (0, 1)) or
                    (meta['items_count'] > 0 and meta['pages_count'] >= 1),
                    'anonymous_probe_booking_pagination_invalid')
            require(expected is None or marker == expected, 'anonymous_probe_booking_inventory_changed')
            expected = marker
            rows = [booking_projection(item) for item in value['data']]
            ids = {row['id'] for row in rows}
            require(len(ids) == len(rows) and not ids.intersection(seen), 'anonymous_probe_duplicate_booking_page')
            require(all(row['start_datetime'][:10] == day for row in rows), 'anonymous_probe_booking_date_filter_unverified')
            seen.update(ids); result.extend(rows)
            if len(result) == meta['items_count']:
                require(meta['items_count'] > 0 or page == 1, 'anonymous_probe_booking_pagination_invalid')
                return sorted(result, key=lambda row: row['id'])
            require(rows and len(result) < meta['items_count'] and page < meta['pages_count'],
                    'anonymous_probe_booking_inventory_incomplete')
        raise Review('anonymous_probe_booking_pagination_bound')

    def slots(self, day):
        query = urlencode({'service_id': SERVICE, 'provider_id': PROVIDER, 'date': day, 'count': 1})
        value = self._get('/admin/schedule/available-slots?' + query)
        require(isinstance(value, list) and len(value) <= 500, 'anonymous_probe_slots_invalid')
        result = set()
        for slot in value:
            require(isinstance(slot, dict) and slot.get('date') == day and isinstance(slot.get('time'), str),
                    'anonymous_probe_slots_invalid')
            clock = slot['time']
            if re.fullmatch(r'\d{2}:\d{2}', clock):
                clock += ':00'
            require(re.fullmatch(r'\d{2}:\d{2}:\d{2}', clock), 'anonymous_probe_slots_invalid')
            start = day + ' ' + clock
            local_stamp(start)
            result.add(start)
        return sorted(result)

    def detail(self, identifier):
        value = booking_projection(self._get('/admin/bookings/' + str(positive(identifier))))
        require(value['id'] == identifier, 'anonymous_probe_booking_identity_mismatch')
        return value


def prepare(probe, directory, candidate_dates, *, now=None):
    """GET-only preparation. Root must explicitly invoke it after code review."""
    now = moment(time.time() if now is None else now)
    require(isinstance(candidate_dates, list) and 1 <= len(candidate_dates) <= 7 and
            len(set(candidate_dates)) == len(candidate_dates), 'anonymous_probe_date_scope_invalid')
    local_today = datetime.fromtimestamp(now, BELGRADE).date()
    for day in candidate_dates:
        require(isinstance(day, str) and local_today < date.fromisoformat(day) <= local_today + timedelta(days=7),
                'anonymous_probe_future_date_required')
    directory = Path(directory)
    require(not directory.exists() and not directory.is_symlink(), 'anonymous_probe_fresh_directory_required')
    identity = probe.identities()
    clients = probe.client_count()
    selected = None
    for day in candidate_dates:
        before = probe.bookings(day)
        for start in probe.slots(day):
            instant = local_stamp(start)
            if instant.timestamp() < now + 7200:
                continue
            end = (datetime.strptime(start, '%Y-%m-%d %H:%M:%S') + timedelta(minutes=DURATION)).strftime('%Y-%m-%d %H:%M:%S')
            if end[:10] != day:
                continue
            local_stamp(end)
            overlapping = [row for row in before if row['provider_id'] == PROVIDER and
                row['status'] != 'canceled' and local_stamp(row['start_datetime']) < local_stamp(end) and
                instant < local_stamp(row['end_datetime'])]
            if overlapping:
                continue
            selected = (day, start, end, before)
            break
        if selected:
            break
    require(selected is not None, 'anonymous_probe_no_verified_free_slot')
    day, start, end, before = selected
    payload = {'service_id': SERVICE, 'provider_id': PROVIDER, 'count': 1,
               'start_datetime': start, 'end_datetime': end}
    plan = {'schema_version': 1, 'experiment': 'anonymous_booking_capability_only',
            'experiment_id': uuid.uuid4().hex, 'company': COMPANY, 'base': BASE,
            'created_at': now, 'expires_at': now + PLAN_TTL, 'identity': identity,
            'date': day, 'payload': payload, 'before_bookings': before,
            'before_booking_ids': [row['id'] for row in before], 'before_clients': clients,
            'slot_observed_available': True, 'production_enabled': False,
            'source_requests': 0, 'client_mutations_allowed': False}
    directory.mkdir(mode=0o700, parents=True)
    write(directory / 'plan.json', plan, exclusive=True)
    journal = {'schema_version': 1, 'plan_sha256': digest(plan), 'state': 'prepared',
               'create_attempts': 0, 'delete_attempts': 0, 'owned_booking_id': None,
               'candidate_booking_ids': [], 'events': [], 'cleanup_verified': False,
               'client_requirement_failed': None, 'capability_verified': False}
    write(directory / 'journal.json', journal, exclusive=True)
    return {'prepared': True, 'plan_sha256': digest(plan), 'expires_at': plan['expires_at'],
            'live_business_writes': 0, 'client_count_before': clients['items_count'],
            'requires_explicit_experiment_authorization': True}


def validate_plan(plan, journal):
    require(isinstance(plan, dict) and plan.get('schema_version') == 1 and
            plan.get('experiment') == 'anonymous_booking_capability_only' and
            plan.get('company') == COMPANY and plan.get('base') == BASE and
            plan.get('production_enabled') is False and plan.get('client_mutations_allowed') is False,
            'anonymous_probe_plan_invalid')
    require(journal.get('plan_sha256') == digest(plan), 'anonymous_probe_plan_changed')
    payload = plan.get('payload')
    require(isinstance(payload, dict) and set(payload) == PAYLOAD_KEYS and
            payload['provider_id'] == PROVIDER and payload['service_id'] == SERVICE and
            type(payload['count']) is int and payload['count'] == 1,
            'anonymous_probe_payload_outside_scope')
    require((local_stamp(payload['end_datetime']) - local_stamp(payload['start_datetime'])).total_seconds() == DURATION * 60,
            'anonymous_probe_payload_duration_changed')
    require(payload['start_datetime'][:10] == payload['end_datetime'][:10] == plan['date'] and
            moment(plan['created_at']) + PLAN_TTL == moment(plan['expires_at']) and
            local_stamp(payload['start_datetime']).timestamp() >= plan['created_at'] + 7200,
            'anonymous_probe_payload_time_scope_invalid')
    require(set(plan['before_booking_ids']) == {row['id'] for row in plan['before_bookings']},
            'anonymous_probe_baseline_invalid')
    require(type(journal.get('create_attempts')) is int and type(journal.get('delete_attempts')) is int and
            journal['create_attempts'] in (0, 1) and journal['delete_attempts'] in (0, 1),
            'anonymous_probe_journal_invalid')


def authorization_for_review(plan_sha256):
    """Public template, deliberately non-executable until the owner decides."""
    return {'experiment': 'anonymous_booking_capability_only', 'plan_sha256': plan_sha256,
            'allow_one_exact_booking_post_and_cancel': False,
            'acknowledge_server_may_create_client_object': False,
            'no_client_endpoint_mutations': True}


def execute(probe, directory, authorization, *, now=None):
    """One POST and, only for proven ownership, one exact cancellation at most."""
    clock = time.time if now is None else lambda: now
    now = moment(clock())
    directory = Path(directory)
    with lock(directory / 'probe.lock'):
        plan, journal = read(directory / 'plan.json'), read(directory / 'journal.json')
        validate_plan(plan, journal)
        require(isinstance(authorization, dict) and set(authorization) == set(authorization_for_review(digest(plan))) and
                authorization.get('experiment') == 'anonymous_booking_capability_only' and
                authorization.get('plan_sha256') == digest(plan) and
                authorization.get('allow_one_exact_booking_post_and_cancel') is True and
                authorization.get('acknowledge_server_may_create_client_object') is True and
                authorization.get('no_client_endpoint_mutations') is True,
                'anonymous_probe_explicit_experiment_authorization_required')
        payload = plan['payload']
        def save(code, **fields):
            journal.update(fields)
            journal['events'].append({'code': code, 'at': moment(clock())})
            write(directory / 'journal.json', journal)
        if journal['cleanup_verified']:
            return public_result(plan, journal)
        if journal['create_attempts'] == 0:
            require(plan['created_at'] <= now <= plan['expires_at'], 'anonymous_probe_preparation_expired')
            require(probe.identities() == plan['identity'], 'anonymous_probe_identity_changed_since_prepare')
            require(probe.bookings(plan['date']) == plan['before_bookings'], 'anonymous_probe_baseline_changed_since_prepare')
            require(probe.client_count() == plan['before_clients'], 'anonymous_probe_client_baseline_changed')
            require(payload['start_datetime'] in probe.slots(plan['date']), 'anonymous_probe_slot_no_longer_available')
            require(plan['created_at'] <= moment(clock()) <= plan['expires_at'],
                    'anonymous_probe_preparation_expired_during_reads')
            save('create_attempt_reserved', create_attempts=1, state='create_attempted')
            try:
                probe._account()
                response = probe._transport.request('POST', '/admin/bookings', dict(payload))
            except Exception:
                response = None
                save('create_outcome_uncertain', state='create_uncertain')
            if response is not None:
                bookings = response.get('bookings') if isinstance(response, dict) else None
                if (isinstance(bookings, list) and len(bookings) == 1 and isinstance(bookings[0], dict)
                        and type(bookings[0].get('id')) is int and bookings[0]['id'] > 0
                        and bookings[0]['id'] not in plan['before_booking_ids']):
                    save('create_response_identity_retained', owned_booking_id=bookings[0]['id'],
                         response_client_shape=client_shape(bookings[0]), state='created_response_known')
                else:
                    save('create_response_requires_review', state='create_uncertain')
        # A repeated call after an ambiguous POST only reads. It never POSTs again.
        rows = probe.bookings(plan['date'])
        candidates = [row for row in rows if row['id'] not in plan['before_booking_ids'] and matches_booking(row, payload)]
        save('create_readback_observed', candidate_booking_ids=[row['id'] for row in candidates])
        owned = journal['owned_booking_id']
        if owned is None:
            try:
                unowned_clients = probe.client_count()
            except Review:
                unowned_clients = None
            failed = journal.get('client_requirement_failed') is True or unowned_clients is None or any(
                row['client_shape']['client_id_state'] == 'nonnull' or
                row['client_shape']['client_object_state'] == 'nonnull' or
                row['client_shape']['contact_values_present'] for row in candidates)
            if unowned_clients is not None:
                failed = failed or unowned_clients['items_count'] != plan['before_clients']['items_count']
            else:
                failed = True
            save('candidate_ownership_unproven', state='manual_ownership_review',
                 client_requirement_failed=failed,
                 client_count_final=unowned_clients['items_count'] if unowned_clients else None)
            return public_result(plan, journal)
        actual = probe.detail(owned)
        require(owned not in plan['before_booking_ids'] and matches_booking(actual, payload, active=False),
                'anonymous_probe_owned_booking_changed_requires_review')
        try:
            clients_after = probe.client_count()
        except Review:
            clients_after = None
        shapes = [actual['client_shape'], journal.get('response_client_shape', {})]
        failed = journal.get('client_requirement_failed') is True or any(shape.get('client_id_state') == 'nonnull' or
                     shape.get('client_object_state') == 'nonnull' or
                     shape.get('contact_values_present') is True for shape in shapes)
        failed = failed or clients_after is None or clients_after['items_count'] != plan['before_clients']['items_count']
        save('client_requirement_observed', client_requirement_failed=failed,
             client_count_after_create=clients_after['items_count'] if clients_after else None)
        if journal['delete_attempts'] == 0:
            # Require the exact known-new booking immediately before its one cancel.
            actual = probe.detail(owned)
            require(matches_booking(actual, payload, active=False),
                    'anonymous_probe_cleanup_identity_changed')
            if actual['status'] != 'canceled':
                save('delete_attempt_reserved', delete_attempts=1, state='cleanup_attempted')
                try:
                    probe._account()
                    probe._transport.request('DELETE', '/admin/bookings/' + str(positive(owned)))
                except Exception:
                    save('delete_outcome_uncertain', state='cleanup_uncertain')
            else:
                save('owned_booking_already_canceled', state='cleanup_observation')
        # DELETE uncertainty is reconciled, never retried, on this or later calls.
        final = probe.bookings(plan['date'])
        own_rows = [row for row in final if row['id'] == owned]
        cleanup = not own_rows or len(own_rows) == 1 and matches_booking(own_rows[0], payload, active=False) and own_rows[0]['status'] == 'canceled'
        old = {row['id']: row for row in final if row['id'] in plan['before_booking_ids']}
        baseline_unchanged = old == {row['id']: row for row in plan['before_bookings']}
        try:
            final_clients = probe.client_count()
        except Review:
            final_clients = None
        failed = failed or final_clients is None or final_clients['items_count'] != plan['before_clients']['items_count']
        failed = failed or any(row['client_shape']['client_id_state'] == 'nonnull' or
                             row['client_shape']['client_object_state'] == 'nonnull' or
                             row['client_shape']['contact_values_present'] for row in own_rows)
        save('cleanup_readback_observed', cleanup_verified=cleanup, baseline_bookings_unchanged=baseline_unchanged,
             client_count_final=final_clients['items_count'] if final_clients else None, client_requirement_failed=failed,
             capability_verified=cleanup and baseline_unchanged and not failed,
             state='closed' if cleanup else 'manual_cleanup_review')
        return public_result(plan, journal)


def public_result(plan, journal):
    return {'schema_version': 1, 'experiment': 'anonymous_booking_capability_only',
            'plan_sha256': journal['plan_sha256'], 'state': journal['state'],
            'create_attempts': journal['create_attempts'], 'cancel_attempts': journal['delete_attempts'],
            'owned_booking_id': journal['owned_booking_id'],
            'candidate_count': len(journal['candidate_booking_ids']),
            'cleanup_verified': journal['cleanup_verified'],
            'client_requirement_failed': journal['client_requirement_failed'],
            'capability_verified': journal['capability_verified'],
            'client_count_before': plan['before_clients']['items_count'],
            'client_count_final': journal.get('client_count_final'),
            'zero_client_objects_proven': False,
            'count_comparison_proves_only_net_change': True,
            'client_mutations': 0, 'source_requests': 0, 'production_enabled': False,
            'no_real_contacts_submitted': True,
            'unknown_post_candidate_is_ownership_proof': False}
