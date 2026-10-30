"""REST Admin operations only. Reuses the existing paced, budgeted client."""
from datetime import date, timedelta
from urllib.parse import urlencode

from provider_assignment.client import Client
from provider_assignment.core import Failure

from .model import Review, Temporary, Uncertain, positive


def minimal_booking(value):
    keys = ('id', 'service_id', 'provider_id', 'client_id', 'start_datetime', 'end_datetime',
            'status', 'is_confirmed', 'duration', 'additional_fields')
    if not isinstance(value, dict) or not value.get('id'):
        raise Review('invalid_booking_response')
    result = {k: value[k] for k in keys if k in value}
    # Intake answers may contain personal data. They are not retained or overwritten.
    result.pop('additional_fields', None)
    return result


class Gateway:
    def __init__(self, settings, transport=None):
        self.settings = settings
        self.transport = transport or Client()
        if self.transport.company != settings.salon:
            raise Review('company_identity_mismatch')
        # Existing importer is the authoritative region/account identity.
        import json
        from .model import ROOT
        checkpoint = ROOT / 'service_importer/progress_log.json'
        identity = (json.loads(checkpoint.read_text(encoding='utf-8'))['identity'] if checkpoint.exists()
                    else json.loads((ROOT / 'booking_bridge/evidence/account-identity.json').read_text(encoding='utf-8')))
        if settings.expected_rest_base:
            if (settings.expected_rest_base != self.transport.base
                    or not settings.approvals.get('account_identity_verified')):
                raise Review('isolated_account_identity_not_verified')
        elif self.transport.base != identity['base'] or settings.salon != identity['company']:
            raise Review('region_identity_mismatch')

    def read(self, path):
        try:
            return self.transport.request('GET', path)
        except Failure:
            raise Temporary('simplybook_read_failed') from None

    def write(self, method, path, body=None):
        if self.settings.mode not in ('pilot', 'production'):
            raise Review('writes_disabled')
        self.settings.validate()
        from .production_readiness import require_production_evidence
        from .recovery import recovery_start_allowed
        if not recovery_start_allowed(self.settings.state / 'bridge.sqlite',
                                      deep=not getattr(self, '_recovery_checked', False)):
            raise Review('restored_state_requires_reconciliation')
        self._recovery_checked = True
        require_production_evidence(self.settings)
        try:
            return self.transport.request(method, path, body)
        except Failure:
            # No mutation retries at this layer, even on an explicit rejection.
            raise Uncertain('simplybook_mutation_requires_readback') from None

    def bookings(self, start, end):
        result, seen, expected = [], set(), None
        for page in range(1, 1001):
            query = urlencode({'filter[date_from]': start, 'filter[date_to]': end,
                               'page': page, 'on_page': 100})
            value = self.read('/admin/bookings?' + query)
            if not isinstance(value, dict) or not isinstance(value.get('data'), list):
                raise Temporary('invalid_booking_inventory')
            meta = value.get('metadata', {})
            if any(type(meta.get(key)) is not int for key in ('page', 'pages_count', 'items_count')):
                raise Temporary('invalid_booking_pagination')
            total, pages = meta['items_count'], meta['pages_count']
            if total < 0 or pages < 0 or meta['page'] != page:
                raise Temporary('invalid_booking_pagination')
            if expected is not None and expected != (total, pages):
                raise Temporary('booking_inventory_changed_during_read')
            expected = total, pages
            data = [minimal_booking(b) for b in value['data']]
            ids = [positive(b['id']) for b in data]
            if len(ids) != len(set(ids)) or seen.intersection(ids):
                raise Temporary('duplicate_booking_page')
            # Read-verified account behavior: no appointments => pages_count=0.
            if total == 0:
                if page != 1 or data or pages not in (0, 1):
                    raise Temporary('invalid_empty_booking_inventory')
                return []
            if pages < 1:
                raise Temporary('invalid_booking_pagination')
            # Existing account sometimes returns an entire inventory on page one.
            if page == 1 and len(data) == total:
                return data
            if not data or len(result) + len(data) > total:
                raise Temporary('incomplete_booking_inventory')
            seen.update(ids); result.extend(data)
            if page == pages:
                if len(result) != total:
                    raise Temporary('incomplete_booking_inventory')
                return result
        raise Temporary('booking_pagination_bound_exceeded')

    def detail(self, booking):
        value = minimal_booking(self.read('/admin/bookings/' + str(positive(booking))))
        if value['id'] != booking:
            raise Review('booking_identity_mismatch')
        return value

    def validate_booking(self, desired, source, mapping):
        service = self.read('/admin/services/' + str(desired['service_id']))
        provider = self.read('/admin/providers/' + str(desired['provider_id']))
        if service.get('id') != desired['service_id'] or provider.get('id') != desired['provider_id']:
            raise Review('service_or_provider_identity_mismatch')
        if not service.get('is_active') or not provider.get('is_active'):
            raise Review('inactive_target')
        assigned = service.get('providers')
        if not isinstance(assigned, list):
            raise Review('unknown_service_provider_relationship')
        # Existing project/account contract: [] means ANY eligible provider.
        # Keep SrediMe's specific provider even when the service is unrestricted.
        if assigned and desired['provider_id'] not in assigned:
            raise Review('provider_not_assigned_to_service')
        if not mapping.get('timing_verified') or not mapping.get('resources_verified'):
            raise Review('service_timing_resources_not_verified')
        if source['duration'] != service.get('duration') or source['duration'] != mapping['duration']:
            raise Review('service_duration_mismatch')
        parts = source['service']
        if any(parts.get(key, 0) != 0 for key in ('start_duration', 'end_duration')):
            raise Review('unsupported_split_treatment')
        if parts.get('cleanup_duration', 0) != service.get('buffer_time_after', 0):
            raise Review('cleanup_buffer_mismatch')
        # Resource allocation is performed by SimplyBook, never inferred here.
        # Resources/intake/payment behavior must be verified in the isolated trial.
        # "hold" is an occupancy mirror: SrediMe remains the confirmation authority.
        # Its pending state is preserved locally, not forced into an unrelated SB custom status.

    def create(self, desired):
        value = self.write('POST', '/admin/bookings', desired)
        try:
            bookings = value['bookings']
            if len(bookings) != 1:
                raise ValueError()
            return positive(bookings[0]['id'])
        except (KeyError, TypeError, ValueError, Review):
            raise Uncertain('unexpected_create_response') from None

    def ensure_available(self, desired, target=None):
        query = urlencode({'service_id': desired['service_id'], 'provider_id': desired['provider_id'],
                           'date': desired['start_datetime'][:10], 'count': 1})
        slots = self.read('/admin/schedule/available-slots?' + query)
        if not isinstance(slots, list):
            raise Review('invalid_availability_response')
        wanted = desired['start_datetime']
        if not any(isinstance(slot, dict) and str(slot.get('date', '')) + ' ' + str(slot.get('time', '')) == wanted for slot in slots):
            # REST has no documented exclude-booking parameter. An edit overlapping
            # its own old interval may need staff review; never cancel/recreate to bypass it.
            raise Review('edit_slot_requires_review' if target else 'slot_conflict_or_unavailable')

    def edit(self, booking, desired):
        self.guard_pilot_target(booking)
        self.write('PUT', '/admin/bookings/' + str(positive(booking)), desired)

    def cancel(self, booking):
        self.guard_pilot_target(booking)
        self.write('DELETE', '/admin/bookings/' + str(positive(booking)))

    def approve(self, booking):
        self.guard_pilot_target(booking)
        self.write('PUT', f'/admin/bookings/{positive(booking)}/approve')

    def guard_pilot_target(self, booking):
        if self.settings.mode != 'pilot':
            return
        actual = self.detail(booking)
        providers = {row['id'] for source, row in self.settings.employees.items() if source in self.settings.allowed_employees}
        if (actual.get('provider_id') not in providers or actual.get('client_id') not in self.settings.pilot_client_ids
                or actual.get('service_id') not in self.settings.pilot_service_ids):
            raise Review('pilot_target_outside_isolation')

    def services(self):
        try:
            return self.transport.inventory('services')
        except Failure:
            raise Temporary('service_inventory_failed') from None

    def provider_schedule(self, provider, service, start, end):
        query = urlencode({'provider_id': positive(provider), 'service_id': positive(service),
                           'date_from': str(start), 'date_to': str(end)})
        rows = self.read('/admin/schedule?' + query)
        if not isinstance(rows, list):
            raise Review('invalid_provider_schedule')
        values = {row['date']: row for row in rows}
        if len(values) != len(rows):
            raise Review('duplicate_schedule_day')
        return values

    def calendar_week(self, provider, start, schedule):
        query = urlencode({'mode': 'week', 'filter[date_from]': str(start),
                           'filter[date_to]': str(start + timedelta(days=6)),
                           'filter[providers][]': provider})
        data = self.read('/admin/calendar?' + query)
        if not isinstance(data, dict) or not isinstance(data.get('columns'), list):
            raise Review('invalid_calendar_response')
        result = {column['date'][:10]: column for column in data['columns']}
        # Account checks: both day/week calendar omit Sunday entirely, while
        # /admin/schedule explicitly returns is_day_off:true. Require that evidence.
        for offset in range(7):
            day = start + timedelta(days=offset)
            if str(day) not in result:
                evidence = schedule.get(str(day))
                if not evidence or evidence.get('is_day_off') is not True:
                    raise Review('calendar_day_coverage_unverified')
                result[str(day)] = {'date': str(day), 'is_day_off': True, 'from': '00:00:00',
                                    'to': '00:00:00', 'breaktimes': [], 'blocked': [], 'notes': []}
        expected = {str(start + timedelta(days=n)) for n in range(7)}
        if set(result) != expected:
            raise Review('calendar_range_mismatch')
        return result


class SimulatedGateway:
    """In-memory remote. Never authenticates and never sends HTTP."""
    def __init__(self):
        self.items = {}
        self.calls = []
        self.next_id = 1000
        self.fail_read = False
        self.timeout_after_create = False

    def bookings(self, start, end):
        if self.fail_read:
            raise Temporary('simulated_outage')
        return list(self.items.values())

    def detail(self, booking):
        if self.fail_read:
            raise Temporary('simulated_outage')
        if booking not in self.items:
            raise Review('simulated_booking_missing')
        return dict(self.items[booking])

    def validate_booking(self, desired, source, mapping):
        if not mapping.get('timing_verified') or not mapping.get('resources_verified'):
            raise Review('service_timing_resources_not_verified')
        if source['duration'] != mapping['duration']:
            raise Review('service_duration_mismatch')

    def create(self, desired):
        self.next_id += 1
        self.calls.append(('create', self.next_id, dict(desired)))
        self.items[self.next_id] = dict(desired, id=self.next_id, status='confirmed', is_confirmed=True)
        if self.timeout_after_create:
            raise Uncertain('simulated_timeout_after_commit')
        return self.next_id

    def ensure_available(self, desired, target=None):
        for booking in self.items.values():
            if booking['id'] == target or booking.get('status') == 'canceled' or booking['provider_id'] != desired['provider_id']:
                continue
            if desired['start_datetime'] < booking['end_datetime'] and booking['start_datetime'] < desired['end_datetime']:
                raise Review('slot_conflict_or_unavailable')

    def edit(self, booking, desired):
        self.calls.append(('edit', booking, dict(desired)))
        self.items[booking].update(desired)

    def cancel(self, booking):
        self.calls.append(('cancel', booking))
        self.items[booking].update(status='canceled', is_confirmed=False)

    def approve(self, booking):
        self.calls.append(('approve', booking))
        self.items[booking].update(status='confirmed', is_confirmed=True)
