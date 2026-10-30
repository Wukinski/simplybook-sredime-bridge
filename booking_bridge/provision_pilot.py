"""Provision the approved small SimplyBook test scope.

Run diagnostics first. An unfinished create intent always stops subsequent runs;
an operator must reconcile its outcome rather than retrying a create.
The original strict-isolation helper below remains for historical validation;
the CLI uses the revised, explicitly authorized controlled-account policy.
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from provider_assignment.client import Client
from service_importer.import_services import atomic_json
from .model import HOME, Review, digest


def baseline(providers, services):
    def rows(items, fields):
        result = []
        for item in items:
            row = {key: item.get(key) for key in fields}
            for key in ('providers', 'services'):
                if isinstance(row.get(key), list):
                    row[key] = sorted(row[key])
            result.append(row)
        return sorted(result, key=lambda row: row['id'])
    return {
        'providers': rows(providers, ('id', 'name', 'is_active', 'is_visible', 'services')),
        'services': rows(services, ('id', 'name', 'price', 'duration', 'buffer_time_after', 'providers', 'is_visible')),
    }


def verify_record(kind, record, payload):
    if not isinstance(record, dict) or type(record.get('id')) is not int or record['id'] <= 0:
        raise Review('pilot_readback_id_missing')
    if record.get('name') != payload['name'] or record.get('is_visible') is not False:
        raise Review('pilot_readback_identity_or_visibility_mismatch')
    if kind == 'providers':
        if record.get('qty') != 1 or not record.get('is_active') or record.get('services') != []:
            raise Review('pilot_provider_isolation_mismatch')
    else:
        if (record.get('duration') != payload['duration'] or
                str(record.get('price')) not in ('0', '0.0', '0.00') or
                record.get('buffer_time_after') != 0 or
                sorted(record.get('providers', [])) != sorted(payload['providers'])):
            raise Review('pilot_service_readback_mismatch')


def provision(client, report, journal_path):
    journal_path = Path(journal_path)
    if (client.company != 'studioandjelija' or report.get('company') != client.company or
            report.get('read_only') is not True or report.get('identity_verified') is not True):
        raise Review('verified_pilot_account_required')
    original = report['preserved_baseline']
    if digest(original) != report.get('preserved_baseline_sha256'):
        raise Review('pilot_baseline_hash_mismatch')
    if client.request('GET', '/admin/company/info').get('login') != client.company:
        raise Review('pilot_live_identity_mismatch')
    if journal_path.exists():
        journal = json.loads(journal_path.read_text(encoding='utf-8'))
        if journal.get('baseline_sha256') != digest(original) or journal.get('company') != client.company:
            raise Review('pilot_journal_baseline_mismatch')
        if any(step['state'] != 'verified' for step in journal['steps']):
            raise Review('pilot_unfinished_intent_requires_reconciliation')
    else:
        journal = {'company': client.company, 'baseline_sha256': digest(original), 'steps': []}
    originals = {kind: {row['id'] for row in original[kind]} for kind in original}

    def check_baseline():
        current = {kind: client.inventory(kind) for kind in original}
        preserved = baseline(*[[row for row in current[kind] if row['id'] in originals[kind]]
                               for kind in ('providers', 'services')])
        if preserved != original:
            raise Review('existing_records_changed_stop_pilot')
        allowed = {kind: originals[kind] | {step['id'] for step in journal['steps']
                   if step['kind'] == kind and step['state'] == 'verified'} for kind in original}
        if any({row['id'] for row in current[kind]} != allowed[kind] for kind in original):
            raise Review('unexpected_records_require_review')
        return current

    current = check_baseline()
    names = {'TEST integracija A', 'TEST integracija B',
             'TEST integracija 30 min', 'TEST integracija 45 min'}
    known_ids = {(step['kind'], step['id']) for step in journal['steps']}
    if any(row['name'] in names and (kind, row['id']) not in known_ids
           for kind in current for row in current[kind]):
        raise Review('existing_test_records_require_explicit_id_review')
    if any(not row.get('providers') for row in current['services']):
        raise Review('unrestricted_existing_service_prevents_pilot_isolation')
    tariff = client.request('GET', '/admin/tariff/current')
    limit = next((item for item in tariff.get('limits', []) if item['key'] == 'provider_limit'), {})
    remaining_creates = 2 - sum(step['kind'] == 'providers' for step in journal['steps'])
    if tariff.get('is_expired') is not False or limit.get('rest', 0) < remaining_creates:
        raise Review('pilot_provider_capacity_not_verified')
    # 2026-10-22: this account ignored services=[] on both POST and PUT
    # /admin/providers and connected the new employee to existing services.
    # Hidden visibility alone does not prove exclusion from Any Employee.
    # A separate verified provisioning mechanism is required before another create.
    if report.get('pilot_provider_isolation_verified') is not True:
        raise Review('provider_create_assignments_not_proven_safe')

    def create(kind, payload):
        previous = next((step for step in journal['steps'] if step['payload']['name'] == payload['name']), None)
        if previous:
            if previous['payload'] != payload:
                raise Review('pilot_payload_changed')
            record = client.request('GET', f"/admin/{kind}/{previous['id']}")
            if kind == 'services':
                verify_record(kind, record, payload)
            else:
                # Services created later legitimately attach to the new employees.
                expected = [s['id'] for s in journal['steps'] if s['kind'] == 'services']
                if sorted(record.get('services', [])) != sorted(expected):
                    raise Review('pilot_provider_unexpected_service')
                verify_record(kind, {**record, 'services': []}, payload)
            return previous['id']
        step = {'kind': kind, 'payload': payload, 'state': 'intent',
                'started_at': datetime.now(timezone.utc).isoformat()}
        journal['steps'].append(step)
        atomic_json(journal_path, journal)
        created = client.request('POST', f'/admin/{kind}', payload)
        if not isinstance(created, dict) or type(created.get('id')) is not int:
            raise Review('pilot_create_outcome_uncertain')
        step['id'] = created['id']
        atomic_json(journal_path, journal)
        record = client.request('GET', f"/admin/{kind}/{step['id']}")
        if record.get('id') != step['id']:
            raise Review('pilot_created_id_mismatch')
        verify_record(kind, record, payload)
        step['state'] = 'verified'
        step['verified_at'] = datetime.now(timezone.utc).isoformat()
        atomic_json(journal_path, journal)
        check_baseline()
        return step['id']

    provider_ids = [create('providers', {'name': f'TEST integracija {letter}',
                    'qty': 1, 'is_visible': False, 'services': []}) for letter in ('A', 'B')]
    service_ids = [create('services', {'name': f'TEST integracija {minutes} min',
                   'duration': minutes, 'price': 0, 'is_visible': False,
                   'providers': provider_ids}) for minutes in (30, 45)]
    current = check_baseline()
    for provider_id in provider_ids:
        row = next(row for row in current['providers'] if row['id'] == provider_id)
        if sorted(row.get('services', [])) != sorted(service_ids):
            raise Review('pilot_provider_final_assignment_mismatch')
    journal['existing_records_preserved'] = True
    journal['completed_at'] = datetime.now(timezone.utc).isoformat()
    atomic_json(journal_path, journal)
    return {'provider_ids': provider_ids, 'service_ids': service_ids,
            'existing_records_preserved': True, 'booking_writes': 0, 'client_writes': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', required=True)
    parser.parse_args()
    report = json.loads((HOME / 'state/diagnostics.json').read_text(encoding='utf-8'))
    from .controlled_pilot import provision as controlled_provision
    print(json.dumps(controlled_provision(Client(), report, HOME / 'state/pilot-provisioning.json')))


if __name__ == '__main__':
    main()
