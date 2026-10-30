import copy
import csv
import json

import pytest

from booking_bridge.model import Review, digest
from booking_bridge.source_review import candidates, csv_cell, displayed_duration, prepare, run, write_review


def inventories():
    source = {'authenticated': True, 'read_only': True, 'business_writes': 0,
              'salon_slug': 'test-salon', 'vendor_id': '1404',
              'employees': [{'id': '10', 'name': 'Alice', 'vendor_id': '1404',
                             'active': True, 'bookable': True, 'services': ['100'],
                             'import_url': '', 'export_url': 'https://private.invalid/SECRET_TOKEN',
                             'password': 'DO_NOT_EXPORT_PASSWORD', 'email': 'DO_NOT_EXPORT_CONTACT'}],
              'services': [{'id': '100', 'name': 'Wash', 'summary': "Wash\n60'"}],
              'resources': [], 'instant_booking_enabled': False, 'webhook_count': 0,
              'cookie': 'DO_NOT_EXPORT_COOKIE', 'app_token': 'DO_NOT_EXPORT_CSRF'}
    baseline = {'providers': [{'id': 81, 'name': 'ALICE'}],
                'services': [{'id': 91, 'name': 'WASH', 'duration': 45}]}
    target = {'read_only': True, 'identity_verified': True, 'company': 'studioandjelija',
              'preserved_baseline': baseline, 'preserved_baseline_sha256': digest(baseline)}
    return source, target


def review(source, target):
    return prepare(source, target, 'test-salon', '1404', 'studioandjelija')


def test_inventory_review_proposes_but_never_approves_name_or_timing(settings):
    source, target = inventories()
    before = copy.deepcopy((source, target, settings))
    report, staff, services = review(source, target)
    assert report['unique_employee_name_candidates'] == 1
    assert report['unique_service_duration_mismatches'] == 1
    assert services[0]['duration_comparison'] == 'mismatch'
    assert staff[0]['simplybook_id'] == 81
    assert services[0]['simplybook_id'] == 91
    for row in staff + services:
        assert row['approved'] == row['timing_verified'] == row['resources_verified'] == 'no'
    assert report['mappings_applied'] is False and report['subminute_verified'] is False
    assert (source, target, settings) == before


def test_ambiguous_names_are_not_unique_candidates():
    source, target = inventories()
    source['services'].append({'id': '101', 'name': 'WASH', 'summary': "60'"})
    report, _, rows = review(source, target)
    assert report['unique_service_name_candidates'] == 0
    assert all(r['match'] == 'ambiguous_name' for r in rows)
    source, target = inventories()
    target['preserved_baseline']['services'].append({'id': 92, 'name': 'Wash', 'duration': 60})
    target['preserved_baseline_sha256'] = digest(target['preserved_baseline'])
    assert review(source, target)[0]['unique_service_name_candidates'] == 0


def test_approximate_names_are_suggestions_with_no_identity_claim():
    rows = candidates([{'id': '10', 'name': 'Sanja'}], [{'id': 3, 'name': 'Sara'}])
    assert rows[0]['match'] == 'suggestion_only' and rows[0]['approved'] == 'no'


@pytest.mark.parametrize('side,field,value,reason', [
    ('source', 'vendor_id', 'OTHER_SECRET', 'source_account_identity_unverified'),
    ('source', 'salon_slug', 'wrong-salon', 'source_account_identity_unverified'),
    ('source', 'authenticated', False, 'source_account_identity_unverified'),
    ('source', 'business_writes', 1, 'source_account_identity_unverified'),
    ('target', 'company', 'OTHER_SECRET', 'target_account_identity_unverified'),
    ('target', 'preserved_baseline_sha256', 'OTHER_SECRET', 'target_account_identity_unverified'),
])
def test_wrong_identity_or_baseline_blocks_review(side, field, value, reason):
    source, target = inventories()
    (source if side == 'source' else target)[field] = value
    with pytest.raises(Review, match=reason) as error:
        review(source, target)
    assert 'OTHER_SECRET' not in str(error.value)


def test_employee_scope_and_duplicate_ids_block_review():
    source, target = inventories()
    source['employees'][0]['vendor_id'] = '1405'
    with pytest.raises(Review, match='source_employee_scope_unverified'):
        review(source, target)
    source, target = inventories()
    source['services'].append(copy.deepcopy(source['services'][0]))
    with pytest.raises(Review, match='duplicate_inventory_id'):
        review(source, target)


def test_missing_duration_is_never_inferred_or_verified():
    for text in (None, 'Wash 60 minutes', "60'\n90'", "0'", "1h 30m"):
        assert displayed_duration(text) is None
    assert displayed_duration("Wash\n2,000.00\n60'") == 60
    rows = candidates([{'id': '100', 'name': 'Wash'}], [{'id': 91, 'name': 'Wash', 'duration': 60}], True)
    assert rows[0]['duration_comparison'] == 'unverified'


def test_nonbookable_employees_are_not_proposed_for_runtime_scope():
    source, target = inventories()
    source['employees'][0]['bookable'] = False
    report, staff, _ = review(source, target)
    assert not staff and report['source_bookable_employee_count'] == 0


def test_report_and_candidates_whitelist_fields_and_clear_stale_output(tmp_path):
    source, target = inventories()
    report, staff, services = review(source, target)
    write_review(tmp_path, report, staff, services)
    exported = '\n'.join(p.read_text(encoding='utf-8-sig') for p in tmp_path.iterdir())
    for secret in ('SECRET_TOKEN', 'DO_NOT_EXPORT_PASSWORD', 'DO_NOT_EXPORT_COOKIE',
                   'DO_NOT_EXPORT_CONTACT', 'DO_NOT_EXPORT_CSRF', 'private.invalid'):
        assert secret not in exported
    write_review(tmp_path, report, [], [])
    assert list(csv.DictReader((tmp_path/'employee-candidates.csv').open(encoding='utf-8-sig'))) == []


@pytest.mark.parametrize('value', ['=WEBSERVICE("bad")', ' +formula', '-1+2', '@SUM(A1)', '\tformula'])
def test_csv_review_cannot_execute_spreadsheet_formulas(value):
    assert csv_cell(value).startswith("'")
    assert csv_cell('Normal service') == 'Normal service'


def test_offline_run_writes_review_without_initializing_runtime_db(settings, tmp_path, capsys):
    source, target = inventories()
    source_path = tmp_path/'source.json'
    source_path.write_text(json.dumps(source), encoding='utf-8')
    (settings.state/'diagnostics.json').write_text(json.dumps(target), encoding='utf-8')
    run(settings, source_path, 'test-salon', '1404', tmp_path/'review')
    assert not (settings.state/'bridge.sqlite').exists()
    assert json.loads(capsys.readouterr().out)['mappings_applied'] is False
