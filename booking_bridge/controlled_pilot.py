"""Small, journaled setup on the explicitly authorized SimplyBook test account.

Does not create clients/bookings or modify SrediMe. Existing assignments to
existing providers must remain intact; inherited links to the new provider are
recorded rather than misrepresented as isolation.
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from provider_assignment.client import Client
from service_importer.import_services import atomic_json
from .model import HOME, Review, digest
from .provision_pilot import baseline, verify_record


def now():
    return datetime.now(timezone.utc).isoformat()


def provision(client, report, journal_path):
    journal_path = Path(journal_path)
    original = report['preserved_baseline']
    if (client.company != 'studioandjelija' or report.get('company') != client.company
            or report.get('identity_verified') is not True or report.get('read_only') is not True
            or report.get('preserved_baseline_sha256') != digest(original)):
        raise Review('verified_pilot_baseline_required')
    if client.request('GET', '/admin/company/info').get('login') != client.company:
        raise Review('pilot_live_identity_mismatch')
    journal = (json.loads(journal_path.read_text(encoding='utf-8')) if journal_path.exists()
               else {'company': client.company, 'baseline_sha256': digest(original), 'steps': []})
    if journal.get('company') != client.company or journal.get('baseline_sha256') != digest(original):
        raise Review('pilot_journal_baseline_mismatch')
    originals = {kind: {r['id'] for r in original[kind]} for kind in original}

    def inventory():
        return {kind: client.inventory(kind) for kind in original}

    current = inventory()
    # Reconcile only explicitly recorded rollback outcomes, and prove the
    # complete baseline is restored before retiring the previous attempt.
    if journal['steps'] and all(s['state'] == 'rolled_back' for s in journal['steps']):
        if (baseline(current['providers'], current['services']) != original or
                any(not s.get('rollback', {}).get('success') or
                    not s.get('rollback', {}).get('baseline_restored') or
                    any(r['id'] == s.get('id') for r in current[s['kind']])
                    for s in journal['steps'])):
            raise Review('pilot_rollback_not_reconciled')
        journal.setdefault('history', []).append({'steps': journal['steps'], 'reconciled_at': now(),
                                                  'baseline_restored_by_live_read': True})
        journal['steps'] = []
        atomic_json(journal_path, journal)
    if any(s['state'] != 'verified' for s in journal['steps']):
        raise Review('pilot_unfinished_intent_requires_reconciliation')
    if journal['steps'] and journal.get('policy') != 'sb_test_account_2026_10_23':
        raise Review('pilot_previous_policy_requires_review')
    journal['policy'] = 'sb_test_account_2026_10_23'
    journal['authorization'] = 'User approved SimplyBook integration testing; complete provider isolation waived'
    journal['production_enabled'] = False

    def check(current):
        new = {kind: {s['id'] for s in journal['steps'] if s['kind'] == kind and s['state'] == 'verified'}
               for kind in original}
        if any({r['id'] for r in current[kind]} != originals[kind] | new[kind] for kind in original):
            raise Review('unexpected_records_require_review')
        preserved = baseline(*[[r for r in current[kind] if r['id'] in originals[kind]]
                               for kind in ('providers', 'services')])
        changes = []
        for row in preserved['services']:
            old = next(r for r in original['services'] if r['id'] == row['id'])
            added = sorted(set(row['providers']) - set(old['providers']))
            if added:
                changes.append({'service_id': row['id'], 'before': old['providers'],
                                'after': row['providers'], 'added_test_providers': added})
            row['providers'] = [p for p in row['providers'] if p not in new['providers']]
        journal['observed_existing_service_assignment_changes'] = changes
        atomic_json(journal_path, journal)
        if preserved != original:
            raise Review('existing_catalog_or_assignments_changed_stop_pilot')

    check(current)
    names = {'TEST integracija A', 'TEST integracija 30 min'}
    known = {(s['kind'], s['id']) for s in journal['steps']}
    if any(r['name'] in names and (kind, r['id']) not in known for kind in current for r in current[kind]):
        raise Review('existing_test_records_require_explicit_id_review')
    if not any(s['kind'] == 'providers' for s in journal['steps']):
        tariff = client.request('GET', '/admin/tariff/current')
        limit = next((x for x in tariff.get('limits', []) if x['key'] == 'provider_limit'), {})
        if tariff.get('is_expired') is not False or limit.get('rest', 0) < 1:
            raise Review('pilot_provider_capacity_not_verified')

    def create(kind, payload):
        previous = next((s for s in journal['steps'] if s['kind'] == kind), None)
        if previous:
            if previous['payload'] != payload:
                raise Review('pilot_payload_changed')
            record = client.request('GET', f"/admin/{kind}/{previous['id']}")
        else:
            step = {'kind': kind, 'payload': payload, 'state': 'intent', 'started_at': now()}
            journal['steps'].append(step)
            atomic_json(journal_path, journal)
            result = client.request('POST', f'/admin/{kind}', payload)
            if not isinstance(result, dict) or type(result.get('id')) is not int or result['id'] <= 0:
                raise Review('pilot_create_outcome_uncertain')
            step['id'] = result['id']
            atomic_json(journal_path, journal)
            record = client.request('GET', f"/admin/{kind}/{step['id']}")
            previous = step
        if record.get('id') != previous['id']:
            raise Review('pilot_created_id_mismatch')
        if kind == 'providers':
            if not isinstance(record.get('services'), list):
                raise Review('pilot_provider_assignments_unknown')
            # Verify real identity/visibility/capacity while retaining the actual
            # observed assignments; no assertion of zero connections or isolation.
            if (record.get('name') != payload['name'] or record.get('is_visible') is not False
                    or record.get('qty') != 1 or record.get('is_active') is not True):
                raise Review('pilot_provider_identity_visibility_or_capacity_mismatch')
            previous['observed_service_ids'] = sorted(record['services'])
        else:
            verify_record(kind, record, payload)
        previous['state'] = 'verified'
        previous['verified_at'] = now()
        atomic_json(journal_path, journal)
        check(inventory())
        return previous['id']

    provider = create('providers', {'name': 'TEST integracija A', 'qty': 1, 'is_visible': False})
    service = create('services', {'name': 'TEST integracija 30 min', 'duration': 30,
                                'price': 0, 'is_visible': False, 'providers': [provider]})
    final_provider = client.request('GET', f'/admin/providers/{provider}')
    final_services = sorted(final_provider['services'])
    if service not in final_services:
        raise Review('pilot_service_not_attached')
    journal['steps'][0]['observed_service_ids'] = final_services
    journal['execution'] = 'minimal_test_records_verified'
    journal['completed_at'] = now()
    journal['cleanup'] = {'provider_ids': [provider], 'service_ids': [service],
                          'procedure': 'Check for bookings, delete only listed test service then provider; compare original baseline'}
    atomic_json(journal_path, journal)
    return {'provider_ids': [provider], 'service_ids': [service], 'provider_service_ids': final_services,
            'existing_catalog_preserved': True, 'existing_to_existing_assignments_preserved': True,
            'existing_service_assignment_changes': journal['observed_existing_service_assignment_changes'],
            'client_writes': 0, 'booking_writes': 0, 'production_enabled': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', required=True)
    parser.parse_args()
    report = json.loads((HOME / 'state/diagnostics.json').read_text(encoding='utf-8'))
    print(json.dumps(provision(Client(), report, HOME / 'state/pilot-provisioning.json')))


if __name__ == '__main__':
    main()
