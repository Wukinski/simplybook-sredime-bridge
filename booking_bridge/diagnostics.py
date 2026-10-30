"""Account inspection with an independent, unconditional business-write fence."""
from datetime import datetime

from provider_assignment.client import Client

from .model import BELGRADE, HOME, Review, digest
from .simplybook import Gateway


class ReadOnlyTransport:
    def __init__(self, client, before_read=None):
        self._client = client
        self.before_read = before_read
        self.company, self.base = client.company, client.base

    def request(self, method, path, body=None, **kwargs):
        if method != 'GET' or body is not None or kwargs:
            raise Review('diagnostics_writes_forbidden')
        if self.before_read:
            # Outside the client's locks: the singleton mutation worker may run.
            self.before_read()
        # Internal token acquisition/refresh remains the existing client's job.
        # No account mutation is dispatched through this facade.
        return self._client.request('GET', path)

    def inventory(self, kind, filters=None):
        return Client.inventory(self, kind, filters)

    @property
    def calls(self):
        return self._client.calls


class ReadOnlyGateway(Gateway):
    def __init__(self, settings, client=None, before_read=None):
        super().__init__(settings, ReadOnlyTransport(client or Client(), before_read))

    def write(self, *args, **kwargs):
        raise Review('diagnostics_writes_forbidden')


def inspect_account(settings, gateway):
    today = datetime.now(BELGRADE).date().isoformat()
    providers = gateway.transport.inventory('providers')
    services = gateway.services()
    company = gateway.read('/admin/company/info')
    bookings = gateway.bookings(today, today)
    names = ('TEST integracija A', 'TEST integracija B')
    test_services = ('TEST integracija 30 min', 'TEST integracija 45 min')
    def baseline_rows(rows, fields):
        values = []
        for row in rows:
            value = {key: row.get(key) for key in fields}
            for key in ('providers', 'services'):
                if isinstance(value.get(key), list):
                    value[key] = sorted(value[key])
            values.append(value)
        return sorted(values, key=lambda row: row['id'])
    report = {
        'checked_at': datetime.now(BELGRADE).isoformat(), 'read_only': True, 'business_writes': 0,
        'configured_mode': settings.mode, 'company': settings.salon,
        'identity_verified': company.get('login') == settings.salon,
        'timezone': company.get('timezone') if isinstance(company.get('timezone'), str) else 'timezone_schema_unverified',
        'provider_count': len(providers), 'service_count': len(services), 'bookings_today_count': len(bookings),
        'providers': [{k: p.get(k) for k in ('id', 'name', 'is_active', 'is_visible')} for p in providers],
        'test_provider_candidates': [{k: p.get(k) for k in ('id', 'name', 'is_active', 'is_visible')}
                                     for p in providers if p.get('name') in names],
        'test_service_candidates': [{k: s.get(k) for k in ('id', 'name', 'duration', 'is_visible', 'providers')}
                                    for s in services if s.get('name') in test_services],
        'mappings': {kind: {'count': len(getattr(settings, kind)),
                            'source': 'local_csv' if (HOME / 'mappings' / (kind + '.local.csv')).exists() else 'config_json'}
                     for kind in ('employees', 'services')},
        'quota_for_two_extra_providers': 'not_established_by_this_read_only_check',
        'mcp_connection': 'not_checked_by_rest_diagnostics',
        'mcp_budget_visibility': 'not_included_in_local_transport_counter',
        'production_business_rules_confirmed': settings.approvals.get('business_rules') is True,
        'preserved_baseline': {
            'providers': baseline_rows(providers, ('id', 'name', 'is_active', 'is_visible', 'services')),
            'services': baseline_rows(services, ('id', 'name', 'price', 'duration', 'buffer_time_after', 'providers', 'is_visible')),
        },
    }
    if not report['identity_verified']:
        raise Review('diagnostic_company_identity_mismatch')
    report['direct_transport_calls'] = gateway.transport.calls
    report['preserved_baseline_sha256'] = digest(report['preserved_baseline'])
    return report
