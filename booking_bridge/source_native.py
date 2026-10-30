"""Observed SrediMe native-UI reads and NON-EXECUTABLE mutation plans.

This is not a public booking API. Constructors do no network I/O. This release
only dispatches GET requests; production booking mutation execution is absent.
Private HTML/forms/contacts/tokens never belong in diagnostics or public logs.
"""
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path
import re
import stat
import time
from urllib.parse import urljoin, urlsplit

import requests

from .model import BELGRADE, Review, Temporary, digest, local_stamp

ORIGIN = 'https://www.sredime.rs'
MAX_SECRET_BYTES = 16 * 1024
MAX_HTML_BYTES = 1024 * 1024
CONTACT_FIELDS = ('first_name', 'last_name', 'phone', 'phone_alt', 'email')
COMMON_FIELDS = {'hid', 'vendor_id', 'customer_id', 'user_id', 'first_name', 'last_name', 'phone', 'email',
                 'form_date', 'internal_note', 'note', 'original_start_at', 'apply_start_to_same_date_bookings', '_token', 'status'}
EDIT_FIELDS = COMMON_FIELDS | {'service_id', 'employee_id', 'employee_name', 'total_value',
                              'form_time_start', 'form_time_end', 'cleanup_duration'}
CREATE_FIELDS = COMMON_FIELDS | {'service_id[]', 'employee_id[]', 'employee_id2[]', 'total_value[]',
                                'form_time_start[]', 'form_time_end[]', 'max_cleanup_duration'}
REQUIRED_WRITE_REVIEWS = ('explicit_source_write_scope_bound_to_production_profile', 'complete_production_evidence',
                          'recovery_and_external_budget_reconciliation', 'durable_single_attempt_origin_and_intent',
                          'fresh_native_availability_and_exact_client_binding', 'native_notification_resource_and_price_contract',
                          'authoritative_post_write_readback_without_blind_retry')


def native_id(value):
    if type(value) is int:
        value = str(value)
    if not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]{0,19}', value):
        raise Review('source_native_id_invalid')
    return value


def booking_uid(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value):
        raise Review('source_booking_uid_invalid')
    return value


@dataclass(frozen=True)
class SourceScope:
    salon_slug: str
    vendor_id: str
    employee_ids: frozenset
    service_ids: frozenset
    contacts_authorized: bool = False

    def __post_init__(self):
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,100}', self.salon_slug or ''):
            raise Review('source_salon_scope_invalid')
        object.__setattr__(self, 'vendor_id', native_id(self.vendor_id))
        object.__setattr__(self, 'employee_ids', frozenset(native_id(value) for value in self.employee_ids))
        object.__setattr__(self, 'service_ids', frozenset(native_id(value) for value in self.service_ids))
        if not self.employee_ids or not self.service_ids or type(self.contacts_authorized) is not bool:
            raise Review('source_explicit_read_scope_required')


@dataclass(frozen=True, repr=False)
class SourceAccess:
    protoken: str = field(repr=False)
    expires: float

    def __repr__(self):
        return 'SourceAccess(<redacted>)'


def read_access_file(path, scope, *, now=None):
    """Read only the reviewed minimal worker secret format, without HTTP."""
    path = Path(path)
    now = time.time() if now is None else now
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_SECRET_BYTES:
            raise ValueError()
        info = path.stat()
        if os.name != 'nt' and (stat.S_IMODE(info.st_mode) & 0o077 or info.st_uid != os.geteuid()):
            raise ValueError()
        def unique(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError()
                result[key] = value
            return result
        data = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique)
        if (set(data) != {'schema_version', 'origin', 'salon_slug', 'vendor_id', 'cookies'} or
                type(data['schema_version']) is not int or data['schema_version'] != 1 or data['origin'] != ORIGIN or
                data['salon_slug'] != scope.salon_slug or native_id(data['vendor_id']) != scope.vendor_id or
                not isinstance(data['cookies'], list) or len(data['cookies']) != 1):
            raise ValueError()
        cookie = data['cookies'][0]
        if (set(cookie) != {'name', 'value', 'domain', 'path', 'secure', 'httpOnly', 'expires'} or
                cookie['name'] != 'protoken' or cookie['domain'] != 'www.sredime.rs' or cookie['path'] != '/' or
                cookie['secure'] is not True or cookie['httpOnly'] is not True or
                type(cookie['expires']) not in (int, float) or not math.isfinite(cookie['expires']) or cookie['expires'] <= now or
                not isinstance(cookie['value'], str) or not 1 <= len(cookie['value']) <= 4096 or
                any(ord(char) <= 32 or char in ';,' or ord(char) == 127 for char in cookie['value'])):
            raise ValueError()
        return SourceAccess(cookie['value'], cookie['expires'])
    except (OSError, ValueError, TypeError, KeyError, Review):
        raise Review('source_access_file_unavailable_or_invalid') from None


@dataclass(repr=False)
class NativeForm:
    action: str
    method: str
    identifier: str
    values: dict
    controls: dict
    options: dict
    labels: dict

    def __repr__(self):
        return 'NativeForm(<private fields redacted>)'


class NativeHTML(HTMLParser):
    """Successful controls for observed simple forms; unsupported shapes stop."""
    def __init__(self, url):
        super().__init__(convert_charrefs=True)
        self.url, self.forms, self.links = url, [], []
        self.current, self.select, self.textarea, self.option = None, None, None, None
        self.label = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'option' and self.select is not None:
            if self.option is not None:
                self.handle_endtag('option')
            self.option = {'value': a.get('value'), 'selected': 'selected' in a,
                           'disabled': 'disabled' in a, 'text': []}
            return
        if tag == 'optgroup' and 'disabled' in a:
            raise Review('source_native_disabled_optgroup_unverified')
        if tag == 'a' and a.get('href'):
            self.links.append(urljoin(self.url, a['href']))
        if tag == 'form':
            if self.current is not None:
                raise Review('source_native_nested_form_unverified')
            self.current = NativeForm(urljoin(self.url, a.get('action', '')), a.get('method', 'get').lower(),
                                      a.get('id', ''), {}, {}, {}, {})
        if self.current is None:
            return
        if tag == 'fieldset' and 'disabled' in a:
            raise Review('source_native_disabled_fieldset_unverified')
        if tag == 'label':
            self.label = {'for': a.get('for'), 'ids': [], 'text': []}
        if tag not in ('input', 'select', 'textarea') or not a.get('name'):
            return
        name, kind = a['name'], a.get('type', 'text').lower() if tag == 'input' else tag
        control = {'tag': tag, 'type': kind, 'disabled': 'disabled' in a, 'id': a.get('id'),
                   'value': a.get('value', ''), 'checked': 'checked' in a}
        self.current.controls.setdefault(name, []).append(control)
        if self.label is not None and a.get('id'):
            self.label['ids'].append(a['id'])
        if tag == 'select':
            if self.select is not None:
                raise Review('source_native_nested_select_unverified')
            self.select = {'name': name, 'disabled': control['disabled'], 'multiple': 'multiple' in a, 'options': []}
        elif tag == 'textarea':
            self.textarea = {'name': name, 'disabled': control['disabled'], 'text': []}
        elif not control['disabled'] and kind not in ('button', 'submit', 'image', 'reset', 'file'):
            if kind not in ('checkbox', 'radio') or control['checked']:
                self.current.values.setdefault(name, []).append(a.get('value', 'on' if kind in ('checkbox', 'radio') else ''))

    def handle_data(self, value):
        if self.label is not None:
            self.label['text'].append(value)
        if self.textarea is not None:
            self.textarea['text'].append(value)
        if self.option is not None:
            self.option['text'].append(value)

    def handle_endtag(self, tag):
        if self.current is None:
            return
        if tag == 'label' and self.label is not None:
            for identifier in ([self.label['for']] if self.label['for'] else self.label['ids']):
                self.current.labels[identifier] = ' '.join(''.join(self.label['text']).split())
            self.label = None
        if tag == 'option' and self.option is not None:
            if self.option['value'] is None:
                self.option['value'] = ''.join(self.option['text'])
            self.select['options'].append(self.option)
            self.option = None
        if tag == 'select' and self.select is not None:
            item = self.select
            enabled = [option for option in item['options'] if not option['disabled']]
            selected = [option['value'] for option in enabled if option['selected']]
            if not selected and not item['multiple'] and enabled:
                selected = [enabled[0]['value']]
            self.current.options[item['name']] = tuple(option['value'] for option in enabled)
            if not item['disabled'] and selected:
                self.current.values.setdefault(item['name'], []).extend(selected)
            self.select = None
        if tag == 'textarea' and self.textarea is not None:
            item = self.textarea
            if not item['disabled']:
                self.current.values.setdefault(item['name'], []).append(''.join(item['text']))
            self.textarea = None
        if tag == 'form':
            if self.select is not None or self.textarea is not None:
                raise Review('source_native_unclosed_control')
            self.forms.append(self.current)
            self.current = None

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def feed(self, data):
        super().feed(data)
        if self.current is not None:
            raise Review('source_native_unclosed_form')

def one(fields, key):
    value = fields.get(key)
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], str):
        raise Review('source_native_scalar_field_changed')
    return value[0]


def read_form(html, url, expected_action):
    document = NativeHTML(url)
    document.feed(html)
    forms = [form for form in document.forms if form.identifier == 'booking-form' and form.action == expected_action]
    if len(forms) != 1 or forms[0].method != 'post':
        raise Review('source_native_exact_form_changed')
    form = forms[0]
    if not one(form.values, '_token') or len(form.controls.get('_token', [])) != 1 or form.controls['_token'][0]['type'] != 'hidden':
        raise Review('source_native_csrf_contract_changed')
    return form, document


@dataclass(frozen=True, repr=False)
class NativeBooking:
    uid: str
    employee_id: str
    service_id: str
    customer_id: str
    status: int
    start_at: str
    end_at: str
    cleanup_minutes: int
    private_form: NativeForm | None = field(default=None, repr=False)

    def __repr__(self):
        return 'NativeBooking(<private snapshot redacted>)'

    def public_summary(self):
        return {'booking_ref': digest(self.uid), 'contacts_exposed': False, 'native_record_observed': True}


@dataclass(frozen=True, repr=False)
class NativeContact:
    native_customer_id: str
    first_name: str
    last_name: str
    email: str
    phone: str
    phone_alt: str

    def __repr__(self):
        return 'NativeContact(<redacted>)'


@dataclass(frozen=True, repr=False)
class NativeMutationPlan:
    kind: str
    action: str
    private_fields: dict = field(repr=False)
    changed_fields: tuple
    required_reviews: tuple = REQUIRED_WRITE_REVIEWS
    executable: bool = False

    def __repr__(self):
        return 'NativeMutationPlan(kind='+repr(self.kind)+', executable=False)'

    def public_summary(self):
        return {'kind': self.kind, 'changed_field_names': list(self.changed_fields),
                'executable': False, 'required_reviews': list(self.required_reviews)}


class SourceNativeTransport:
    """Only observed native GET routes. Mutation dispatch always rejects."""
    def __init__(self, scope, access, session=None):
        if not isinstance(scope, SourceScope) or not isinstance(access, SourceAccess):
            raise Review('source_native_explicit_access_and_scope_required')
        self.scope, self.base = scope, ORIGIN+'/buker/'+scope.salon_slug
        self._session = session or requests.Session()
        self._session.trust_env = False
        self._session.cookies.set('protoken', access.protoken, domain='www.sredime.rs', path='/', secure=True,
                                  rest={'HttpOnly': True})
        self._access_expires, self.read_calls = access.expires, 0

    @classmethod
    def from_secret_file(cls, path, scope, session=None):
        return cls(scope, read_access_file(path, scope), session=session)

    def close(self):
        self._session.close()

    def _get(self, path, params=None):
        if self._access_expires <= time.time():
            raise Review('source_native_access_expired')
        if not re.fullmatch(r'/(?:booking/(?:[A-Za-z0-9_-]{1,128}/)?update|customer/[1-9][0-9]{0,19}(?:/update)?|calendar/json)', path):
            raise Review('source_native_read_route_unobserved')
        if path.startswith('/customer/') and self.scope.contacts_authorized is not True:
            raise Review('source_customer_contacts_not_authorized')
        url, response = self.base+path, None
        try:
            self.read_calls += 1
            response = self._session.get(url, params=params, timeout=(3, 8), allow_redirects=False, stream=True)
            if response.status_code != 200:
                raise Temporary('source_native_authenticated_get_unavailable')
            parsed = urlsplit(response.url)
            if parsed.scheme != 'https' or parsed.netloc != 'www.sredime.rs' or parsed.path != urlsplit(url).path or parsed.fragment:
                raise Review('source_native_response_route_changed')
            body = bytearray()
            for chunk in response.iter_content(65536):
                body.extend(chunk)
                if len(body) > MAX_HTML_BYTES:
                    raise Review('source_native_response_too_large')
            return bytes(body).decode('utf-8', 'strict')
        except (requests.RequestException, UnicodeDecodeError):
            raise Temporary('source_native_read_unavailable') from None
        finally:
            if response is not None:
                response.close()

    def read_booking(self, uid):
        uid = booking_uid(uid)
        path = '/booking/'+uid+'/update'
        form, _ = read_form(self._get(path), self.base+path, self.base+path)
        if set(form.controls) - EDIT_FIELDS or any(key.endswith('[]') for key in form.values):
            raise Review('source_native_booking_edit_schema_changed')
        values = form.values
        if one(values, 'hid') != uid or native_id(one(values, 'vendor_id')) != self.scope.vendor_id:
            raise Review('source_native_booking_identity_changed')
        employee, service, customer = (native_id(one(values, key)) for key in ('employee_id', 'service_id', 'customer_id'))
        if employee not in self.scope.employee_ids or service not in self.scope.service_ids:
            raise Review('source_native_booking_outside_read_scope')
        try:
            date = datetime.strptime(one(values, 'form_date'), '%d.%m.%Y.').date().isoformat()
            first = local_stamp(date+' '+one(values, 'form_time_start')+':00')
            last = local_stamp(date+' '+one(values, 'form_time_end')+':00')
            status, cleanup = int(one(values, 'status')), int(one(values, 'cleanup_duration'))
            if last <= first or cleanup < 0:
                raise ValueError()
        except (ValueError, TypeError):
            raise Review('source_native_booking_interval_changed') from None
        return NativeBooking(uid, employee, service, customer, status, first.isoformat(), last.isoformat(), cleanup,
                             form if self.scope.contacts_authorized else None)

    def contact_for_booking(self, booking):
        if self.scope.contacts_authorized is not True or not isinstance(booking, NativeBooking):
            raise Review('source_customer_contacts_not_authorized')
        if booking.employee_id not in self.scope.employee_ids or booking.service_id not in self.scope.service_ids:
            raise Review('source_native_booking_outside_read_scope')
        identifier = native_id(booking.customer_id)
        values = booking.private_form.values if booking.private_form is not None else {}
        if not all(key in values for key in ('first_name', 'last_name', 'phone', 'email')) or not one(values, 'first_name'):
            path = '/customer/'+identifier
            text = self._get(path)
            document = NativeHTML(self.base+path);document.feed(text)
            edit = self.base+path+'/update'
            links = [link for link in document.links if link == edit]
            if not links:
                raise Review('source_customer_exact_observed_profile_link_missing')
            form, _ = read_form(self._get(path+'/update'), edit, edit)
            values = form.values
        return NativeContact(identifier, *(one(values, key) if key in values else '' for key in
                                           ('first_name', 'last_name', 'email', 'phone', 'phone_alt')))

    def read_create_form(self, employee_id, start_at, end_at):
        if self.scope.contacts_authorized is not True:
            raise Review('source_customer_contacts_not_authorized')
        employee_id = native_id(employee_id)
        if employee_id not in self.scope.employee_ids:
            raise Review('source_native_booking_outside_read_scope')
        first, last = local_stamp(start_at).astimezone(BELGRADE), local_stamp(end_at).astimezone(BELGRADE)
        if last <= first or first.date() != last.date() or first.second or last.second or first.microsecond or last.microsecond:
            raise Review('source_native_create_interval_unverified')
        path = '/booking/update'
        params = {'active': '1', 'start_at': first.isoformat(), 'end_at': last.isoformat(),
                  'employee_id': employee_id, 'vendor_id': self.scope.vendor_id}
        form, _ = read_form(self._get(path, params), self.base+path, self.base+path)
        if set(form.controls) - CREATE_FIELDS or one(form.values, 'vendor_id') != self.scope.vendor_id:
            raise Review('source_native_booking_create_schema_changed')
        if one(form.values, 'hid') not in ('', '0') or one(form.values, 'status') != '1':
            raise Review('source_native_create_template_is_existing_or_unverified')
        return form

    def prepare_create(self, form, contact, employee_id, service_id, start_at, end_at, *,
                       total_value, required_employees=1, asset_ids=(), cleanup_minutes=0):
        if not self.scope.contacts_authorized or not isinstance(form, NativeForm) or not isinstance(contact, NativeContact):
            raise Review('source_native_verified_existing_customer_required')
        customer_id = native_id(contact.native_customer_id)
        employee_id, service_id = native_id(employee_id), native_id(service_id)
        if employee_id not in self.scope.employee_ids or service_id not in self.scope.service_ids:
            raise Review('source_native_booking_outside_read_scope')
        if form.action != self.base+'/booking/update' or form.method != 'post' or set(form.controls) - CREATE_FIELDS:
            raise Review('source_native_booking_create_schema_changed')
        if one(form.values, 'vendor_id') != self.scope.vendor_id or one(form.values, 'hid') not in ('', '0'):
            raise Review('source_native_create_template_is_existing_or_unverified')
        if required_employees != 1 or asset_ids or cleanup_minutes != 0:
            raise Review('source_native_resource_or_multistaff_create_unverified')
        if not contact.first_name or not isinstance(total_value, str) or not re.fullmatch(r'[0-9]+(?:[.,][0-9]{1,2})?', total_value):
            raise Review('source_native_actual_contact_and_price_required')
        first, last = local_stamp(start_at).astimezone(BELGRADE), local_stamp(end_at).astimezone(BELGRADE)
        if last <= first or first.date() != last.date() or first.second or last.second or first.microsecond or last.microsecond:
            raise Review('source_native_create_interval_unverified')
        fields = {key: list(value) for key, value in form.values.items()}
        replacements = {'customer_id': customer_id, 'employee_id[]': employee_id, 'service_id[]': service_id,
                        'form_time_start[]': first.strftime('%H:%M'), 'form_time_end[]': last.strftime('%H:%M'),
                        'form_date': first.strftime('%d.%m.%Y.'), 'total_value[]': total_value,
                        'max_cleanup_duration': '0', 'status': '1'}
        for key, value in replacements.items():
            if key in form.options and value not in form.options[key]:
                raise Review('source_native_create_option_unavailable')
            fields[key] = [value]
        for key in ('first_name', 'last_name', 'phone', 'email'):
            if key in fields:
                fields[key] = [getattr(contact, key)]
        # Only the reviewed single-employee case can omit this hidden UI default.
        fields.pop('employee_id2[]', None)
        changed = tuple(sorted(key for key in set(fields) | set(form.values) if fields.get(key) != form.values.get(key)))
        return NativeMutationPlan('create', form.action, fields, changed,
                                  REQUIRED_WRITE_REVIEWS+('generic_create_pricing_and_selection_side_effects_unverified',))

    def prepare_move(self, booking, start_at, end_at):
        form = self._planning_form(booking)
        first, last = local_stamp(start_at).astimezone(BELGRADE), local_stamp(end_at).astimezone(BELGRADE)
        if last <= first or first.date() != last.date() or first.second or last.second or first.microsecond or last.microsecond:
            raise Review('source_native_move_interval_unverified')
        fields = {key: list(value) for key, value in form.values.items()}
        fields['form_date'] = [first.strftime('%d.%m.%Y.')]
        for key, value in (('form_time_start', first.strftime('%H:%M')), ('form_time_end', last.strftime('%H:%M'))):
            if value not in form.options.get(key, ()):
                raise Review('source_native_time_option_unavailable')
            fields[key] = [value]
        changed = tuple(sorted(key for key in fields if fields[key] != form.values.get(key)))
        reviews = REQUIRED_WRITE_REVIEWS + ('cross_date_move_contract_unverified',) if first.date() != local_stamp(booking.start_at).astimezone(BELGRADE).date() else REQUIRED_WRITE_REVIEWS
        return NativeMutationPlan('move', form.action, fields, changed, reviews)

    def prepare_cancel(self, booking):
        form = self._planning_form(booking)
        radio = [control for control in form.controls.get('status', []) if control['type'] == 'radio' and
                 control['value'] == '-101' and control['id'] == 'status-101']
        if len(radio) != 1 or form.labels.get('status-101') != 'Salon otkazao':
            raise Review('source_native_salon_cancel_semantics_unverified')
        fields = {key: list(value) for key, value in form.values.items()}
        fields['status'] = ['-101']
        return NativeMutationPlan('salon_cancel', form.action, fields, ('status',),
                                  REQUIRED_WRITE_REVIEWS+('source_cancel_actor_policy_review',))

    def _planning_form(self, booking):
        if not self.scope.contacts_authorized or not isinstance(booking, NativeBooking) or booking.private_form is None:
            raise Review('source_native_complete_private_baseline_required')
        if booking.employee_id not in self.scope.employee_ids or booking.service_id not in self.scope.service_ids:
            raise Review('source_native_booking_outside_read_scope')
        if booking.status not in (0, 1):
            raise Review('source_native_existing_booking_state_requires_review')
        return booking.private_form

    def execute_plan(self, plan, *args, **kwargs):
        # Even a caller supplying approval flags cannot turn the native UI
        # groundwork into a production writer without reviewed implementation.
        raise Review('source_native_mutation_dispatch_unverified')
