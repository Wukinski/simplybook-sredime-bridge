import copy
import csv
import hashlib
import json

import pytest

from booking_bridge import catalog_alignment as catalog
from booking_bridge.model import Review


def source(identifier, name, **fields):
    return {'id': str(identifier), 'name': name, 'duration_minutes': 30, 'price': '1000', **fields}


def target(identifier, name, **fields):
    return {'id': identifier, 'name': name, 'duration_minutes': 30, 'price': '1000',
            'active': True, 'visible': True, 'provider_ids': [5], 'after_buffer_minutes': 0, **fields}


def review(left, right, details=(), **kwargs):
    return catalog.build_review(catalog.normalize_services(left, True, details=details), [],
                                catalog.normalize_services(right, False), [], **kwargs)


def test_strict_punctuation_ambiguous_and_unmatched_are_separate():
    report = review([source(1, 'Isti tretman'), source(2, 'Lice + vrat'), source(3, 'Duplikat'),
                     source(4, 'Duplikat'), source(5, 'Sličan tretman A')],
                    [target(11, 'ISTI TRETMAN'), target(12, 'LICE VRAT'), target(13, 'DUPLIKAT'),
                     target(14, 'Sličan tretman B')])
    assert report['summary']['strict_unique_service_pairs'] == 1
    assert report['summary']['punctuation_candidate_pairs'] == 1
    assert report['summary']['ambiguous_service_groups'] == 1
    assert report['source_no_candidate_ids'] == ['5']
    assert report['target_no_candidate_ids'] == [14]
    assert {row['row_id'] for row in report['service_pairs']} == {'S-1-T-11', 'S-2-T-12'}
    assert all(row['identity'] == 'pending' and not row['runtime_mapping_approved'] for row in report['service_pairs'])


def test_word_candidate_is_not_a_verified_duration_or_identity_conflict():
    report = review([source(1, 'Lice + vrat', duration_minutes=90)], [target(11, 'LICE VRAT')])
    rows = report['decisions']
    assert rows[0]['field'] == 'treatment_identity'
    assert next(row for row in rows if row['field'] == 'duration_minutes')['comparison_basis'] == 'conditional_on_treatment_identity'
    assert report['runtime_mappings_written'] is False


def test_unknown_active_is_not_fabricated_from_css_or_visibility():
    report = review([source(1, 'Jedan', inactive_style_marker=True)], [target(11, 'Jedan', visible=False)])
    assert report['source_services'][0]['active'] is None
    assert report['summary']['source_active_unknown'] == 1
    assert not any(row['field'] in ('active', 'visible') for row in report['decisions'])
    report = review([source(1, 'Jedan')], [target(11, 'Jedan', visible=False)],
                    details=[source(1, 'Jedan', active=False)])
    assert [row['field'] for row in report['decisions']] == ['active']


def test_detail_coverage_does_not_fill_other_service_resources_or_timing():
    report = review([source(1, 'Jedan'), source(2, 'Drugi')], [target(11, 'Jedan'), target(12, 'Drugi')],
                    details=[source(1, 'Jedan', active=True, employee_ids=[], asset_ids=[], cleanup_minutes=0)])
    assert report['source_services'][0]['asset_ids'] == []
    assert report['source_services'][1]['asset_ids'] is None
    assert report['source_services'][1]['cleanup_minutes'] is None
    assert report['summary']['source_resource_details_unknown'] == 1
    assert all(row['physical_resources_verified'] is False for row in report['service_pairs'])


def test_prices_are_numeric_and_ambiguous_display_is_left_unknown():
    assert catalog.displayed_price("Ime\n2,400.00\n45'") == '2400'
    assert catalog.displayed_price("Ime\n2,400.00\n3,000.00\n45'") is None
    assert catalog.money('NaN') is None
    report = review([source(1, 'Jedan', price='2400.00')], [target(11, 'Jedan', price='2400.0')])
    assert not any(row['field'] == 'price' for row in report['decisions'])


def test_duplicate_word_group_cannot_reuse_a_strict_target():
    report = review([source(1, 'Lice vrat'), source(2, 'Lice + vrat')], [target(11, 'Lice vrat')])
    assert report['summary']['strict_unique_service_pairs'] == 1
    assert report['summary']['punctuation_candidate_pairs'] == 0
    assert report['ambiguous_service_groups'][0]['source_ids'] == ['1', '2']


def test_owner_decision_ids_are_stable_and_test_records_are_not_business_questions():
    left, right = [source(1, 'Jedan', duration_minutes=90)], [target(11, 'Jedan')]
    assert review(left, right)['decisions'][0]['decision_id'] == 'S-1-T-11:duration_minutes'
    report = review(left, right, source_test_service_ids=['1'])
    assert report['decisions'] == []
    assert report['source_services'][0]['scope_role'] == 'historical_controlled_test'


def test_private_fields_are_ignored_and_inputs_are_not_modified():
    left = catalog.normalize_services([source(1, 'Jedan', export_url='PRIVATE_SECRET_URL',
                                             customer={'email': 'PRIVATE_CONTACT'})], True)
    right = catalog.normalize_services([target(11, 'Jedan', note='PRIVATE_NOTE')], False)
    before = copy.deepcopy((left, right))
    report = catalog.build_review(left, [], right, [])
    assert (left, right) == before
    assert 'PRIVATE_' not in json.dumps(report)


def test_csv_cells_are_safe_and_existing_outputs_are_not_overwritten(tmp_path):
    report = review([source(1, '=FORMULA')], [target(11, '=FORMULA')])
    output = tmp_path/'review'
    catalog.write_review(output, report)
    with (output/'source-inventory.csv').open(encoding='utf-8-sig', newline='') as handle:
        assert next(csv.DictReader(handle))['name'] == "'=FORMULA"
    with pytest.raises(FileExistsError):
        catalog.write_review(output, report)


def test_fresh_metadata_hash_and_collection_complete_are_required(tmp_path):
    directory = tmp_path/'input';directory.mkdir()
    manifest = {'complete': False, 'files': {}, 'rows': {}}
    (directory/'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(Review, match='incomplete'):
        catalog.load_current(directory)
    datasets = {'source-services': [source(1, 'Jedan')], 'source-employees': [], 'source-service-details': [],
                'target-services': [target(11, 'Jedan')], 'target-providers': []}
    for key, rows in datasets.items():
        body = json.dumps({'schema_version': 1, 'observed_at_utc': '2026-10-30T12:00:00Z', 'rows': rows}).encode()
        (directory/(key+'.json')).write_bytes(body)
        manifest['files'][key+'.json'] = {'sha256': hashlib.sha256(body).hexdigest()}
        manifest['rows'][key.replace('-', '_')] = len(rows)
    manifest['complete'] = True
    (directory/'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    assert catalog.load_current(directory)['summary']['source_services'] == 1
    (directory/'source-services.json').write_text('{}', encoding='utf-8')
    with pytest.raises(Review):
        catalog.load_current(directory)


def test_unobserved_source_assignment_and_test_provider_are_not_owner_mismatches():
    report = review([source(1, 'Jedan')], [target(11, 'Jedan', provider_ids=[9])],
                    target_test_provider_ids=[9])
    assert report['service_pairs'][0]['assignment_comparison'] == 'source_assignment_unverified'
    assert not any(row['field'] == 'staff_eligibility' for row in report['decisions'])
    staff = catalog.normalize_staff([{'id': '10', 'name': 'Osoba', 'service_ids': ['1']}], True)
    providers = catalog.normalize_staff([{'id': 5, 'name': 'Osoba'}, {'id': 9, 'name': 'TEST'}], False)
    report = catalog.build_review(catalog.normalize_services([source(1, 'Jedan')], True), staff,
                                  catalog.normalize_services([target(11, 'Jedan', provider_ids=[5, 9])], False), providers,
                                  target_test_provider_ids=[9])
    assert not any(row['field'] == 'staff_eligibility' for row in report['decisions'])
    assert report['service_pairs'][0]['historical_test_provider_present_in_target'] is True


def test_import_provenance_is_hash_checked_and_only_whitelisted_values_leave(tmp_path):
    workbook = tmp_path/'original.xlsx';workbook.write_bytes(b'synthetic-workbook-hash-input')
    normalized = {'excel_row': 2, 'name': 'Jedan', 'source_name': 'Jedan', 'price': '1000', 'duration_minutes': 30}
    row_hash = hashlib.sha256(json.dumps(normalized, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    checkpoint = {'identity': {'workbook_sha256': hashlib.sha256(workbook.read_bytes()).hexdigest(), 'admin_login': 'PRIVATE_ADMIN'},
                  'rows': {'2': {'remote_id': 11, 'normalized': normalized, 'row_hash': row_hash, 'status': 'confirmed'}}}
    cp = tmp_path/'checkpoint.json';cp.write_text(json.dumps(checkpoint), encoding='utf-8')
    observed = {'plan_id': 'synthetic-plan', 'observed_at': '2026-10-21T00:00:00Z',
                'service': {'id': 11, 'is_active': True, 'providers': [5], 'description': 'PRIVATE_CONTACT'}}
    (tmp_path/'observed.json').write_text(json.dumps(observed), encoding='utf-8')
    journal = tmp_path/'journal.json'
    journal.write_text(json.dumps({'plan_id': 'synthetic-plan', 'rows': {'11': {'status': 'verified', 'observed_snapshot': 'observed.json'}}}), encoding='utf-8')
    rows, summary = catalog.load_import_provenance(cp, workbook, journal, tmp_path)
    assert rows[11]['assignment_observed_provider_ids'] == [5]
    assert rows[11]['native_id_creation_crosswalk_present'] is False
    assert 'PRIVATE_' not in json.dumps((rows, summary))
    checkpoint['rows']['2']['normalized']['duration_minutes'] = 99
    cp.write_text(json.dumps(checkpoint), encoding='utf-8')
    with pytest.raises(Review, match='row_hash_changed'):
        catalog.load_import_provenance(cp, workbook, journal, tmp_path)


def test_source_authority_plan_respects_inactive_and_identity_boundaries():
    report = review([source(1, 'Jedan', duration_minutes=70), source(2, 'Lice + vrat'), source(3, 'Nepovezano')],
                    [target(11, 'Jedan'), target(12, 'LICE VRAT'), target(13, 'Stari drugačiji naziv')],
                    details=[source(1, 'Jedan', duration_minutes=70, active=False, employee_ids=['99'], asset_ids=['51']),
                             source(3, 'Nepovezano', active=False, employee_ids=[], asset_ids=[])])
    plan = catalog.source_authoritative_plan(report, {'catalog_authority': 'sredime', 'owner_authority_recorded': True})
    selected = plan['unique_inventory_correspondence_candidates'][0]
    assert selected['desired_target_metadata']['duration_minutes'] == 70
    assert selected['desired_target_metadata']['active'] is False
    assert 'business_provider_ids' not in selected['desired_target_metadata']
    assert 'source_employee_identity_unresolved' in selected['required_reviews']
    assert plan['punctuation_identity_candidates_pending'][0]['runtime_write_approved'] is False
    assert plan['source_only_potential_creations'][0]['create_active'] is False
    assert plan['target_only_preserved_pending_policy'][0]['delete_or_disable_approved'] is False
    assert plan['resource_correspondence_reviews'][0]['numeric_id_namespaces_are_not_shared'] is True
    assert plan['live_writes'] == plan['deletions_proposed'] == 0


def test_partial_provenance_columns_and_plan_are_exported_with_complete_manifest(tmp_path):
    report = review([source(1, 'Jedan'), source(2, 'Drugi')], [target(11, 'Jedan'), target(12, 'Drugi')],
                    provenance={12: {'original_excel_row': 8}})
    plan = catalog.source_authoritative_plan(report, {'catalog_authority': 'sredime', 'owner_authority_recorded': True})
    output = tmp_path/'output'
    catalog.write_review(output, report, plan)
    manifest = json.loads((output/'manifest.json').read_text(encoding='utf-8'))
    assert manifest['complete'] is True
    assert 'source-authoritative-plan.json' in manifest['artifacts_sha256']
    with (output/'target-inventory.csv').open(encoding='utf-8-sig', newline='') as handle:
        rows = list(csv.DictReader(handle))
        assert rows[0]['recorded_import_assignment_provenance'] == ''
        assert 'original_excel_row' in rows[1]['recorded_import_assignment_provenance']


def test_completed_detail_merge_preserves_stopped_history_and_checks_both_components(tmp_path):
    current = tmp_path/'current';current.mkdir()
    files = {'source-services': [source(1, 'Jedan'), source(2, 'Drugi')], 'source-employees': [],
             'source-service-details': [], 'target-services': [target(11, 'Jedan'), target(12, 'Drugi')],
             'target-providers': []}
    manifest = {'complete': True, 'files': {}, 'rows': {}}
    for name, rows in files.items():
        body = json.dumps({'schema_version': 1, 'observed_at_utc': '2026-10-30T12:00:00Z', 'rows': rows}).encode()
        (current/(name+'.json')).write_bytes(body)
        manifest['files'][name+'.json'] = {'sha256': hashlib.sha256(body).hexdigest()}
        manifest['rows'][name.replace('-', '_')] = len(rows)
    (current/'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    full = tmp_path/'full';full.mkdir();continuation=full/'continuation';continuation.mkdir()
    rows = [source(1, 'Jedan', active=True), source(2, 'Drugi', active=False)]
    components = []
    for directory, row, complete in ((full, rows[0], False), (continuation, rows[1], True)):
        body = json.dumps(row).encode();filename='service-'+row['id']+'.json'
        (directory/filename).write_bytes(body)
        state = {'complete': complete, 'row_files': {row['id']: {'filename': filename, 'sha256': hashlib.sha256(body).hexdigest()}}}
        body = json.dumps(state).encode();(directory/'manifest.json').write_bytes(body)
        components.append({'path': str((directory/'manifest.json').relative_to(full)), 'sha256': hashlib.sha256(body).hexdigest()})
    original = (full/'manifest.json').read_bytes()
    body = json.dumps({'schema_version': 1, 'complete': True, 'rows': rows}).encode()
    (full/'source-service-details-complete.json').write_bytes(body)
    final = {'complete': True, 'expected_rows': 2, 'initial_manifest': components[0], 'continuation_manifest': components[1],
             'combined_file': {'path': 'source-service-details-complete.json', 'sha256': hashlib.sha256(body).hexdigest()},
             'index_reference': {'sha256': manifest['files']['source-services.json']['sha256']}}
    (full/'complete-manifest.json').write_text(json.dumps(final), encoding='utf-8')
    report = catalog.load_current(current, source_details_directory=full)
    assert report['summary']['source_active_unknown'] == 0
    assert report['summary']['source_active_count'] == report['summary']['source_inactive_count'] == 1
    assert (full/'manifest.json').read_bytes() == original
    (continuation/'manifest.json').write_text('{}', encoding='utf-8')
    with pytest.raises(Review, match='component_manifest_changed'):
        catalog.load_current(current, source_details_directory=full)


def test_source_priority_does_not_silently_choose_between_different_source_staff_views():
    employees = catalog.normalize_staff([{'id': '10', 'name': 'Osoba', 'service_ids': ['1'], 'bookable': False}], True)
    providers = catalog.normalize_staff([{'id': 5, 'name': 'Osoba'}], False)
    services = catalog.normalize_services([source(1, 'Jedan')], True,
                                          details=[source(1, 'Jedan', employee_ids=[], active=True)])
    report = catalog.build_review(services, employees, catalog.normalize_services([target(11, 'Jedan')], False), providers)
    issue = report['source_internal_staff_relation_view_differences'][0]
    assert issue['service_form_employee_ids'] == [] and issue['employee_form_memberships'] == ['10']
    plan = catalog.source_authoritative_plan(report, {'catalog_authority': 'sredime', 'owner_authority_recorded': True})
    row = plan['unique_inventory_correspondence_candidates'][0]
    assert 'business_provider_ids' not in row['desired_target_metadata']
    assert 'source_internal_staff_relation_views_differ_semantics_review' in row['required_reviews']


def test_known_native_origin_future_booking_services_remain_protected():
    report = review([source(1, 'Jedan', duration_minutes=90)],
                    [target(11, 'Jedan'), target(377, 'Native-origin future booking service')])
    plan = catalog.source_authoritative_plan(report, {'catalog_authority': 'sredime', 'owner_authority_recorded': True,
                                                      'protected_target_service_ids': [11, 377]})
    assert plan['unique_inventory_correspondence_candidates'][0]['desired_target_metadata'] == {}
    assert plan['unique_inventory_correspondence_candidates'][0]['conditional_desired_metadata_after_origin_review']['duration_minutes'] == 90
    assert plan['target_only_preserved_pending_policy'][0]['action'] == 'preserve_protected_native_origin_future_bookings_service'
    assert plan['future_booking_safety_check_required_for_every_target_change'] is True
    assert plan['live_writes'] == plan['deletions_proposed'] == 0
