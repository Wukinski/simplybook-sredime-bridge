"""Offline preparation only. Creating providers/services is not an implicit side effect."""
from .model import Review, digest


def prepare(report, expected_company='studioandjelija'):
    if report.get('read_only') is not True or not report.get('identity_verified'):
        raise Review('verified_read_only_diagnostics_required')
    if report.get('company') != expected_company:
        raise Review('pilot_company_identity_mismatch')
    if report.get('preserved_baseline_sha256') != digest(report.get('preserved_baseline')):
        raise Review('diagnostic_baseline_hash_mismatch')
    if report.get('test_provider_candidates') or report.get('test_service_candidates'):
        raise Review('existing_test_records_require_explicit_id_review')
    proposal = {
        'schema_version': 2, 'company': report['company'], 'purpose': 'controlled_pilot_setup',
        'baseline_sha256': report['preserved_baseline_sha256'],
        'source_checked_at': report['checked_at'],
        'owner_confirmed_original_account': True,
        'production_business_rules_confirmed': False,
        'creates': {
            'providers': [{'name': name, 'qty': 1, 'is_visible': False}
                          for name in ('TEST integracija A',)],
            'services': [{'name': 'TEST integracija ' + str(minutes) + ' min', 'duration': minutes,
                          'price': '0', 'is_visible': False, 'buffer_time_after': 0,
                          'providers': 'only_verified_new_test_provider_ids'} for minutes in (30,)],
            'client': {'create_only_if_needed': True, 'contacts': 'owner_enters_genuine_test_contact_locally'},
        },
        'blocked_until': ['capacity_for_one_provider_verified_without_unapproved_cost',
                          'actual_write_tool_schema_and_permissions_reviewed'],
        'booking_blocked_until': ['controlled_test_contact_supplied_locally',
                                 'sredime_test_scope_reviewed', 'public_https_callbacks_verified'],
        'simplybook_complete_provider_isolation_required': False,
        'availability_under_60_seconds': 'optimization_target_not_pilot_gate',
        'forbidden': ['production_bookings', 'existing_provider_or_service_updates', 'service_reimport',
                      'bulk_mapping_by_name', 'public_test_visibility', 'unapproved_cost'],
        'execution': 'not_dispatched',
        'cleanup': 'review_created_ids_after_pilot; no automatic deletion',
    }
    proposal['review_hash'] = digest(proposal)
    return proposal
