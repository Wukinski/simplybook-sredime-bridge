"""Offline catalog comparison. Every proposed link remains a review candidate.

Only catalog labels, IDs, typed metadata, counts and evidence hashes are emitted.
No Settings/Store/client is constructed and no runtime mapping is written.
"""
import argparse
from collections import Counter, defaultdict
import csv
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import unicodedata

from .model import Review, digest
from .source_review import displayed_duration, csv_cell, name_key


def word_key(value):
    # Preserve Unicode letters, accents, numbers, word order and boundaries.
    # This is a punctuation-only candidate rule, never a fuzzy identity match.
    return tuple(re.findall(r'[^\W_]+', name_key(value)))


def number(value):
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, str) and re.fullmatch(r'[0-9]+', value):
        return int(value)
    return None


def money(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return format(amount.normalize(), 'f') if amount.is_finite() and amount >= 0 else None


def displayed_price(summary):
    if not isinstance(summary, str):
        return None
    values = [line.strip().replace(',', '') for line in summary.splitlines()
              if re.fullmatch(r'(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)\.[0-9]{2}', line.strip())]
    return money(values[0]) if len(values) == 1 else None


def _bool(value):
    return value if type(value) is bool else None


def _ids(value, native):
    if value is None:
        return None
    if not isinstance(value, list):
        raise Review('catalog_relation_invalid')
    result = []
    for item in value:
        identifier = str(item) if native else item
        if (not re.fullmatch(r'[1-9][0-9]*', identifier) if native else
                type(identifier) is not int or identifier <= 0):
            raise Review('catalog_relation_invalid')
        if identifier in result:
            raise Review('catalog_relation_duplicate')
        result.append(identifier)
    return sorted(result, key=lambda v: int(v))


def _field(row, *names):
    return next((row[key] for key in names if key in row), None)


def normalize_staff(rows, native, observed_at=None):
    result = []
    for row in rows:
        identifier = _ids([row['id']], native)[0]
        name_key(row['name'])
        result.append({'id': identifier, 'name': row['name'],
                       'active': _bool(_field(row, 'active', 'is_active')),
                       'bookable': _bool(row.get('bookable')) if native else None,
                       'visible': _bool(_field(row, 'visible', 'is_visible')),
                       'service_ids': _ids(_field(row, 'service_ids', 'services'), native),
                       'role_code': _field(row, 'role_code', 'role') if native and isinstance(_field(row, 'role_code', 'role'), (str, int)) else None,
                       'role_code_semantics_verified': False,
                       'observed_at': _field(row, 'fetched_at_utc', 'observed_at_utc') or observed_at})
    if len({row['id'] for row in result}) != len(result):
        raise Review('catalog_duplicate_staff_id')
    return result


def normalize_services(rows, native, observed_at=None, details=()):
    detail_index = {str(row['id']): row for row in details}
    if len(detail_index) != len(details):
        raise Review('catalog_duplicate_detail_id')
    result = []
    for row in rows:
        identifier = _ids([row['id']], native)[0]
        name_key(row['name'])
        embedded = row.get('details') if isinstance(row.get('details'), dict) else {}
        detail = detail_index.get(str(identifier), embedded)
        if detail and detail.get('name') and name_key(detail['name']) != name_key(row['name']):
            raise Review('catalog_detail_name_changed')
        duration = number(_field(detail, 'duration_minutes', 'duration'))
        if duration is None:
            duration = number(_field(row, 'duration_minutes', 'duration'))
        if duration is None and native:
            duration = displayed_duration(row.get('summary'))
        price = money(_field(detail, 'price')) or money(row.get('price'))
        if price is None and native:
            price = displayed_price(row.get('summary'))
        fields = {'id': identifier, 'name': row['name'], 'duration_minutes': duration, 'price': price,
                  'active': _bool(_field(detail, 'active', 'is_active')) if detail else _bool(_field(row, 'active', 'is_active')),
                  'visible': _bool(_field(row, 'visible', 'is_visible')),
                  'observed_at': row.get('observed_at_utc', observed_at),
                  'detail_observed_at': _field(detail, 'fetched_at_utc', 'observed_at_utc') or observed_at if detail else None}
        if native:
            fields.update({'cleanup_minutes': number(_field(detail, 'cleanup_minutes', 'cleanup_duration')),
                           'start_extension_minutes': number(_field(detail, 'start_extension_minutes', 'start_duration')),
                           'end_extension_minutes': number(_field(detail, 'end_extension_minutes', 'end_duration')),
                           'required_employees': number(detail.get('required_employees')),
                           'service_form_employee_ids': _ids(_field(detail, 'employee_ids', 'employees'), True),
                           'asset_ids': _ids(_field(detail, 'asset_ids', 'assets'), True),
                           'sale_price': money(detail.get('sale_price')), 'full_price': money(detail.get('full_price')),
                           'duration_type': detail.get('duration_type') if isinstance(detail.get('duration_type'), (str, int)) else None,
                           'price_type': detail.get('price_type') if isinstance(detail.get('price_type'), (str, int)) else None,
                           'variant_controls_observed_count': len(detail['timing_price_variant_controls'])
                           if isinstance(detail.get('timing_price_variant_controls'), list) else None,
                           'variant_control_semantics_verified': False,
                           'price_comparison_basis': 'source_index_displayed_numeric_price_not_assumed_sale_or_full_price'})
        else:
            fields.update({'provider_ids': _ids(_field(row, 'provider_ids', 'providers'), False),
                           'after_buffer_minutes': number(_field(row, 'after_buffer_minutes', 'buffer_time_after')),
                           'resource_ids': _ids(row.get('resource_ids'), False)})
        result.append(fields)
    if len({row['id'] for row in result}) != len(result):
        raise Review('catalog_duplicate_service_id')
    if set(detail_index) - {str(row['id']) for row in result}:
        raise Review('catalog_detail_without_service')
    return result


def classify(left, right):
    strict, words = [], []
    indexes = []
    for rows in (left, right):
        exact, tokens = defaultdict(list), defaultdict(list)
        for row in rows:
            exact[name_key(row['name'])].append(row)
            tokens[word_key(row['name'])].append(row)
        indexes.append((exact, tokens))
    for key in sorted(indexes[0][0]):
        a, b = indexes[0][0][key], indexes[1][0].get(key, [])
        if len(a) == len(b) == 1:
            strict.append((a[0], b[0]))
    used_left, used_right = {a['id'] for a, _ in strict}, {b['id'] for _, b in strict}
    for key in sorted(indexes[0][1]):
        a, b = indexes[0][1][key], indexes[1][1].get(key, [])
        if len(a) == len(b) == 1 and a[0]['id'] not in used_left and b[0]['id'] not in used_right:
            words.append((a[0], b[0]))
            used_left.add(a[0]['id']); used_right.add(b[0]['id'])
    ambiguous, duplicate_groups = [], []
    for side, (exact, _) in zip(('source', 'target'), indexes):
        for key, rows in sorted(exact.items()):
            if len(rows) > 1:
                duplicate_groups.append({'side': side, 'normalized_label': key, 'ids': [row['id'] for row in rows]})
    for key, a in sorted(indexes[0][1].items()):
        b = indexes[1][1].get(key, [])
        if b and (len(a) > 1 or len(b) > 1):
            ambiguous.append({'word_sequence': list(key), 'source_ids': [row['id'] for row in a],
                              'target_ids': [row['id'] for row in b], 'identity': 'pending'})
    a_ambiguous = {value for row in ambiguous for value in row['source_ids']}
    b_ambiguous = {value for row in ambiguous for value in row['target_ids']}
    return {'strict': strict, 'punctuation': words, 'ambiguous_groups': ambiguous, 'duplicate_name_groups': duplicate_groups,
            'source_unpaired': [row for row in left if row['id'] not in used_left],
            'target_unpaired': [row for row in right if row['id'] not in used_right],
            'source_no_candidate': [row for row in left if row['id'] not in used_left | a_ambiguous],
            'target_no_candidate': [row for row in right if row['id'] not in used_right | b_ambiguous]}


def build_review(source_services, source_staff, target_services, target_staff, *, metadata=None, provenance=None,
                 source_test_service_ids=(), target_test_service_ids=(), target_test_provider_ids=()):
    source_services, source_staff, target_services, target_staff = (
        [dict(row) for row in rows] for rows in (source_services, source_staff, target_services, target_staff))
    matched = classify(source_services, target_services)
    staff = classify(source_staff, target_staff)
    inferred_staff = {left['id']: right['id'] for left, right in staff['strict']}
    source_staff_names = {row['id']: row['name'] for row in source_staff}
    target_staff_names = {row['id']: row['name'] for row in target_staff}
    source_test_service_ids, target_test_service_ids = set(source_test_service_ids), set(target_test_service_ids)
    target_test_provider_ids = set(target_test_provider_ids)
    staff_with_services = {row['id'] for row in source_staff if row['service_ids'] is not None}
    relation_differences = []
    for row in source_services:
        row['scope_role'] = 'historical_controlled_test' if row['id'] in source_test_service_ids else 'business_catalog_not_approved'
        member_ids = sorted([staff_row['id'] for staff_row in source_staff if staff_row['service_ids'] is not None and
                             row['id'] in staff_row['service_ids']], key=int)
        row['employee_form_memberships'] = member_ids
        selected = row['service_form_employee_ids']
        if selected is None or not staff_with_services:
            row['source_staff_relation_views'] = 'unverified'
        elif set(selected) & staff_with_services == set(member_ids):
            row['source_staff_relation_views'] = 'consistent_for_observed_employee_forms'
        else:
            row['source_staff_relation_views'] = 'different_for_observed_employee_forms_semantics_unverified'
            if row['scope_role'] != 'historical_controlled_test':
                relation_differences.append({'row_id': 'SRC-S-'+str(row['id'])+':staff_relation_projection',
                                             'source_service_id': row['id'], 'source_name': row['name'],
                                             'service_form_employee_ids': selected, 'employee_form_memberships': member_ids,
                                             'decision': 'technical_semantics_review_required_not_overwritten_by_source_authority'})
    for row in target_services:
        row['scope_role'] = 'historical_controlled_test' if row['id'] in target_test_service_ids else 'business_catalog_not_approved'
        if provenance and row['id'] in provenance:
            row['recorded_import_assignment_provenance'] = provenance[row['id']]
    for row in target_staff:
        row['scope_role'] = 'historical_controlled_test' if row['id'] in target_test_provider_ids else 'business_staff_not_approved'
    pairs, decisions = [], []

    def decision(identifier, field, left, right, basis):
        decisions.append({'decision_id': identifier+':'+field, 'row_id': identifier, 'field': field,
                          'source_value': left, 'target_value': right, 'comparison_basis': basis,
                          'decision': 'pending', 'chosen_value': None})

    for kind, matches in (('strict_unique_name', matched['strict']), ('punctuation_word_sequence_candidate', matched['punctuation'])):
        for source, target in matches:
            identifier = 'S-'+str(source['id'])+'-T-'+str(target['id'])
            member_ids = sorted([row['id'] for row in source_staff if row['service_ids'] is not None and
                                 source['id'] in row['service_ids']], key=int)
            selected_ids = source['service_form_employee_ids']
            compared_ids = selected_ids if selected_ids is not None else member_ids
            expected = sorted({inferred_staff[value] for value in compared_ids if value in inferred_staff})
            unresolved = [value for value in compared_ids if value not in inferred_staff]
            actual = target['provider_ids']
            business_actual = [value for value in actual if value not in target_test_provider_ids] if actual is not None else None
            if actual is None:
                relation = 'target_assignment_unverified'
            elif not actual:
                relation = 'target_unrestricted_any_eligible_provider'
            elif selected_ids == []:
                relation = 'source_empty_selection_semantics_unverified'
            elif selected_ids is None and not member_ids:
                relation = 'source_assignment_unverified'
            elif unresolved:
                relation = 'source_staff_identity_unresolved'
            else:
                relation = 'same_given_unique_staff_name_inference' if expected == sorted(business_actual) else 'different_given_unique_staff_name_inference'
            values = {'row_id': identifier, 'candidate_kind': kind, 'source': source, 'target': target,
                      'source_staff_memberships_from_employee_forms': member_ids,
                      'source_membership_coverage': 'observed_employee_forms_only_not_all_possible_employees',
                      'source_assignment_comparison_basis': 'explicit_service_form_selection' if selected_ids is not None else 'observed_employee_form_memberships_only',
                      'source_staff_labels': [source_staff_names[value] for value in member_ids],
                      'target_provider_labels': [target_staff_names.get(value, 'unobserved-provider-'+str(value)) for value in (actual or [])],
                      'target_business_provider_ids_for_owner_question': business_actual,
                      'historical_test_provider_present_in_target': any(value in target_test_provider_ids for value in (actual or [])),
                      'inferred_target_provider_ids': expected, 'unresolved_source_staff_ids': unresolved,
                      'assignment_comparison': relation, 'identity': 'pending', 'runtime_mapping_approved': False,
                      'physical_resources_verified': False, 'provider_specific_timing_verified': False}
            if provenance and target['id'] in provenance:
                values['target_import_assignment_provenance'] = provenance[target['id']]
            pairs.append(values)
            if source['id'] in source_test_service_ids or target['id'] in target_test_service_ids:
                continue
            if kind != 'strict_unique_name':
                decision(identifier, 'treatment_identity', source['name'], target['name'], 'punctuation_candidate_only')
            basis = 'unique_name_observed_difference' if kind == 'strict_unique_name' else 'conditional_on_treatment_identity'
            for field in ('duration_minutes', 'price', 'active', 'visible'):
                if source[field] is not None and target[field] is not None and source[field] != target[field]:
                    decision(identifier, field, source[field], target[field], basis)
            if source['cleanup_minutes'] is not None and target['after_buffer_minutes'] is not None and source['cleanup_minutes'] != target['after_buffer_minutes']:
                decision(identifier, 'cleanup_after_buffer_minutes', source['cleanup_minutes'], target['after_buffer_minutes'], basis)
            if relation == 'different_given_unique_staff_name_inference':
                decision(identifier, 'staff_eligibility', compared_ids, business_actual, basis+'_and_staff_identity_inference')
    staff_rows = []
    for source, target in staff['strict']:
        identifier = 'E-'+str(source['id'])+'-P-'+str(target['id'])
        staff_rows.append({'row_id': identifier, 'kind': 'strict_unique_name', 'source': source, 'target': target,
                           'runtime_mapping_approved': False})
        for field in ('active', 'visible'):
            if source[field] is not None and target[field] is not None and source[field] != target[field]:
                decision(identifier, field, source[field], target[field], 'unique_staff_name_observed_difference')
    source_ids, target_ids = {row['id'] for row in source_services}, {row['id'] for row in target_services}
    paired_source, paired_target = {row['source']['id'] for row in pairs}, {row['target']['id'] for row in pairs}
    report = {'schema_version': 1, 'scope': metadata or {}, 'read_only': True, 'network_calls': 0,
              'runtime_mappings_written': False, 'all_proposals_pending': True, 'whole_live_catalog_certified': False,
              'summary': {'source_services': len(source_services), 'target_services': len(target_services),
                          'source_staff_observed': len(source_staff), 'target_staff_observed': len(target_staff),
                          'strict_unique_service_pairs': len(matched['strict']), 'punctuation_candidate_pairs': len(matched['punctuation']),
                          'strict_unique_business_service_pairs': sum(row['candidate_kind'] == 'strict_unique_name' and
                              row['source']['id'] not in source_test_service_ids and row['target']['id'] not in target_test_service_ids for row in pairs),
                          'punctuation_business_candidate_pairs': sum(row['candidate_kind'] == 'punctuation_word_sequence_candidate' and
                              row['source']['id'] not in source_test_service_ids and row['target']['id'] not in target_test_service_ids for row in pairs),
                          'ambiguous_service_groups': len(matched['ambiguous_groups']),
                          'source_duplicate_name_groups': sum(row['side'] == 'source' for row in matched['duplicate_name_groups']),
                          'target_duplicate_name_groups': sum(row['side'] == 'target' for row in matched['duplicate_name_groups']),
                          'source_services_without_unique_pair': len(source_ids - paired_source),
                          'target_services_without_unique_pair': len(target_ids - paired_target),
                          'source_services_without_exact_or_word_candidate': len(matched['source_no_candidate']),
                          'target_services_without_exact_or_word_candidate': len(matched['target_no_candidate']),
                          'source_active_unknown': sum(row['active'] is None for row in source_services),
                          'source_active_count': sum(row['active'] is True for row in source_services),
                          'source_inactive_count': sum(row['active'] is False for row in source_services),
                          'target_active_count': sum(row['active'] is True for row in target_services),
                          'target_inactive_count': sum(row['active'] is False for row in target_services),
                          'target_active_unknown': sum(row['active'] is None for row in target_services),
                          'source_resource_details_unknown': sum(row['asset_ids'] is None for row in source_services),
                          'source_services_with_selected_assets': sum(bool(row['asset_ids']) for row in source_services),
                          'source_active_services_with_selected_assets': sum(bool(row['asset_ids']) and row['active'] is True for row in source_services),
                          'source_internal_staff_relation_view_differences': len(relation_differences),
                          'target_resource_details_unknown': sum(row['resource_ids'] is None for row in target_services),
                          'pending_decisions': len(decisions),
                          'known_controlled_source_service_rows': sum(row['id'] in source_test_service_ids for row in source_services),
                          'known_controlled_target_service_rows': sum(row['id'] in target_test_service_ids for row in target_services),
                          'known_controlled_target_provider_rows': sum(row['id'] in target_test_provider_ids for row in target_staff),
                          'decision_counts': dict(sorted(Counter(row['field'] for row in decisions).items()))},
              'service_pairs': pairs, 'source_services': source_services, 'target_services': target_services,
              'source_no_candidate_ids': [row['id'] for row in matched['source_no_candidate']],
              'target_no_candidate_ids': [row['id'] for row in matched['target_no_candidate']],
              'ambiguous_service_groups': matched['ambiguous_groups'], 'duplicate_name_groups': matched['duplicate_name_groups'],
              'staff_unique_name_pairs': staff_rows, 'source_staff_unpaired': staff['source_unpaired'],
              'source_internal_staff_relation_view_differences': relation_differences,
              'target_staff_unpaired': staff['target_unpaired'], 'decisions': decisions,
              'limitations': ['name_candidates_are_not_protocol_or_treatment_identity_authority',
                              'unmatched_names_do_not_prove_treatments_absent', 'active_is_not_visibility_or_bookability',
                              'missing_metadata_remains_unknown', 'no_fuzzy_pairs_are_generated',
                              'staff_assignment_comparison_depends_on_recorded_staff_identity_basis',
                              'no_customer_records_contacts_urls_or_credentials_are_included']}
    if len(paired_source) != len(pairs) or len(paired_target) != len(pairs):
        raise Review('catalog_candidate_reused_identifier')
    return report


def write_review(output, report, plan=None):
    output = Path(output)
    output.mkdir(mode=0o700)
    (output/'manifest.json').write_text(json.dumps({'schema_version': 1, 'complete': False}), encoding='utf-8')
    (output/'review.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    rows = []
    for pair in report['service_pairs']:
        rows.append({'row_id': pair['row_id'], 'candidate_kind': pair['candidate_kind'],
                     'source_id': pair['source']['id'], 'source_name': pair['source']['name'],
                     'target_id': pair['target']['id'], 'target_name': pair['target']['name'],
                     'source_duration_minutes': pair['source']['duration_minutes'], 'target_duration_minutes': pair['target']['duration_minutes'],
                     'source_price': pair['source']['price'], 'target_price': pair['target']['price'],
                     'source_active': pair['source']['active'], 'target_active': pair['target']['active'],
                     'source_visible': pair['source']['visible'], 'target_visible': pair['target']['visible'],
                     'source_staff_ids': pair['source_staff_memberships_from_employee_forms'],
                     'target_provider_ids': pair['target']['provider_ids'], 'assignment_comparison': pair['assignment_comparison'],
                     'identity': 'pending', 'timing_verified': 'no', 'resources_verified': 'no', 'approved': 'no'})
    staff_rows = [{'row_id': row['row_id'], 'kind': row['kind'],
                   'source_id': row['source']['id'], 'source_name': row['source']['name'],
                   'source_active': row['source']['active'], 'source_bookable': row['source']['bookable'],
                   'target_id': row['target']['id'], 'target_name': row['target']['name'],
                   'target_active': row['target']['active'], 'target_visible': row['target']['visible'],
                   'identity': 'pending', 'approved': 'no'} for row in report['staff_unique_name_pairs']]
    for side, records in (('source', report['source_staff_unpaired']), ('target', report['target_staff_unpaired'])):
        for row in records:
            staff_rows.append({'row_id': ('E-' if side == 'source' else 'P-')+str(row['id'])+'-unpaired',
                               'kind': side+'_unpaired_not_an_identity_assertion',
                               'source_id': row['id'] if side == 'source' else None,
                               'source_name': row['name'] if side == 'source' else None,
                               'source_active': row['active'] if side == 'source' else None,
                               'source_bookable': row['bookable'] if side == 'source' else None,
                               'target_id': row['id'] if side == 'target' else None,
                               'target_name': row['name'] if side == 'target' else None,
                               'target_active': row['active'] if side == 'target' else None,
                               'target_visible': row['visible'] if side == 'target' else None,
                               'identity': 'pending', 'approved': 'no'})
    paired_source = {row['source']['id'] for row in report['service_pairs']}
    paired_target = {row['target']['id'] for row in report['service_pairs']}
    unmatched = []
    for side, inventory, paired in (('source', report['source_services'], paired_source),
                                     ('target', report['target_services'], paired_target)):
        for row in inventory:
            if row['id'] in paired:
                continue
            unmatched.append({'row_id': 'U-'+('S-' if side == 'source' else 'T-')+str(row['id']),
                              'side': side, 'id': row['id'], 'name': row['name'], 'scope_role': row['scope_role'],
                              'classification': 'no_unique_pair_not_proof_of_treatment_absence',
                              'equivalence_or_scope_decision': 'pending', 'chosen_other_id': None,
                              'approved': 'no'})
    datasets = {'service-candidates.csv': rows, 'decisions.csv': report['decisions'],
                'source-inventory.csv': report['source_services'], 'target-inventory.csv': report['target_services'],
                'staff-review.csv': staff_rows, 'unpaired-review.csv': unmatched,
                'duplicate-name-groups.csv': report['duplicate_name_groups'],
                'ambiguous-service-groups.csv': report['ambiguous_service_groups']}
    for name, items in datasets.items():
        headers = list(dict.fromkeys(key for row in items for key in row)) if items else ['row_id', 'decision']
        with (output/name).open('w', encoding='utf-8-sig', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writeheader()
            for row in items:
                writer.writerow({key: csv_cell(json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else
                                               ('unknown' if value is None else value)) for key, value in row.items()})
    (output/'summary.json').write_text(json.dumps({'schema_version': 1, 'scope': report['scope'], **report['summary'],
                                                  'runtime_mappings_written': False}, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    if plan is not None:
        (output/'source-authoritative-plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    artifacts = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in output.iterdir()
                 if path.is_file() and path.name != 'manifest.json'}
    (output/'manifest.json').write_text(json.dumps({'schema_version': 1, 'complete': True,
                                                   'artifacts_sha256': artifacts}, indent=2)+'\n', encoding='utf-8')


def source_authoritative_plan(report, policy):
    """Propose target alignment, while keeping identity and capability gaps open."""
    if policy.get('catalog_authority') != 'sredime' or policy.get('owner_authority_recorded') is not True:
        raise Review('catalog_source_authority_record_required')
    inferred_staff = {row['source']['id']: row['target']['id'] for row in report['staff_unique_name_pairs']}
    protected_targets = set(_ids(policy.get('protected_target_service_ids', []), False))
    candidates, unresolved = [], []
    for pair in report['service_pairs']:
        source, target = pair['source'], pair['target']
        if source['scope_role'] == 'historical_controlled_test' or target['scope_role'] == 'historical_controlled_test':
            continue
        proposed, blockers = {}, []
        for field in ('duration_minutes', 'active'):
            if source[field] is not None and source[field] != target[field]:
                proposed[field] = source[field]
        if source['price'] is not None and source['price'] != target['price']:
            if source['sale_price'] is not None and source['sale_price'] != source['price']:
                blockers.append('source_displayed_price_and_form_sale_price_differ')
            else:
                proposed['price'] = source['price']
        if source['cleanup_minutes'] is not None and source['cleanup_minutes'] != target['after_buffer_minutes']:
            proposed['after_buffer_minutes'] = source['cleanup_minutes']
        members = source['service_form_employee_ids']
        if source['source_staff_relation_views'] == 'different_for_observed_employee_forms_semantics_unverified':
            blockers.append('source_internal_staff_relation_views_differ_semantics_review')
        elif members is None:
            blockers.append('source_service_form_assignments_unobserved')
        elif not members:
            blockers.append('source_empty_staff_selection_semantics_unverified')
        elif any(value not in inferred_staff for value in members):
            blockers.append('source_employee_identity_unresolved')
        else:
            desired = sorted({inferred_staff[value] for value in members})
            actual = pair['target_business_provider_ids_for_owner_question']
            if desired != actual:
                proposed['business_provider_ids'] = desired
        if source['active'] is None:
            blockers.append('source_active_state_unobserved')
        if source['asset_ids']:
            blockers.append('source_asset_to_target_resource_configuration_requires_review')
        if source['asset_ids'] is None or target['resource_ids'] is None:
            blockers.append('physical_resource_semantics_unverified')
        if source['start_extension_minutes'] or source['end_extension_minutes']:
            blockers.append('split_treatment_timing_capability_unverified')
        if source['required_employees'] not in (None, 1):
            blockers.append('multiple_simultaneous_staff_capability_unverified')
        if source['required_employees'] is None:
            blockers.append('required_staff_count_unobserved')
        if any(source[field] is None for field in ('cleanup_minutes', 'start_extension_minutes', 'end_extension_minutes')):
            blockers.append('source_timing_extension_fields_unobserved')
        if source['variant_controls_observed_count']:
            blockers.append('source_price_or_duration_variant_semantics_unverified')
        if 'active' in proposed:
            blockers.append('target_active_state_write_contract_and_history_preservation_require_review')
        row = {'row_id': pair['row_id'], 'source_id': source['id'], 'target_id': target['id'],
               'source_name': source['name'], 'target_name': target['name'],
               'correspondence_basis': pair['candidate_kind'], 'source_active': source['active'],
               'desired_target_metadata': proposed, 'required_reviews': sorted(set(blockers)),
               'runtime_write_approved': False, 'deletion_proposed': False}
        row['fresh_active_future_booking_check_required'] = True
        if target['id'] in protected_targets:
            row['conditional_desired_metadata_after_origin_review'] = row['desired_target_metadata']
            row['desired_target_metadata'] = {}
            row['required_reviews'].append('protected_existing_native_origin_future_bookings')
        if pair['candidate_kind'] != 'strict_unique_name':
            row['required_reviews'].append('treatment_identity_equivalence_pending')
            unresolved.append(row)
        else:
            row['required_reviews'].append('native_to_target_correspondence_and_webhook_identity_verification')
            candidates.append(row)
    sources = {row['id']: row for row in report['source_services']}
    targets = {row['id']: row for row in report['target_services']}
    possible_creates = [{'row_id': 'U-S-'+str(value), 'source': sources[value],
                         'action': 'potential_create_after_equivalence_scope_and_capability_review',
                         'treatment_absence_proven': False, 'create_active': sources[value]['active'],
                         'runtime_write_approved': False} for value in report['source_no_candidate_ids']
                        if sources[value]['scope_role'] != 'historical_controlled_test']
    preserved = [{'row_id': 'U-T-'+str(value), 'target': targets[value],
                  'action': 'preserve_protected_native_origin_future_bookings_service' if value in protected_targets else
                            'preserve_pending_owner_equivalence_and_active_scope_policy',
                  'delete_or_disable_approved': False} for value in report['target_no_candidate_ids']
                 if targets[value]['scope_role'] != 'historical_controlled_test']
    resource_review = [{'row_id': 'R-S-'+str(row['id']), 'source_service_id': row['id'], 'source_name': row['name'],
                        'source_asset_ids': row['asset_ids'], 'target_resource_correspondence': 'unverified',
                        'numeric_id_namespaces_are_not_shared': True, 'decision': 'pending'}
                       for row in report['source_services'] if row['asset_ids'] and row['scope_role'] != 'historical_controlled_test']
    return {'schema_version': 1, 'dry_run': True, 'catalog_authority': 'sredime', 'live_writes': 0,
            'runtime_mappings_changed': False, 'inactive_source_records_never_activated_by_plan': True,
            'protected_target_service_ids': sorted(protected_targets),
            'future_booking_safety_check_required_for_every_target_change': True,
            'existing_native_origin_reservations_must_be_preserved': True,
            'unique_inventory_correspondence_candidates': candidates,
            'punctuation_identity_candidates_pending': unresolved,
            'ambiguous_treatment_groups_pending': report['ambiguous_service_groups'],
            'source_only_potential_creations': possible_creates, 'target_only_preserved_pending_policy': preserved,
            'source_staff_identity_pending': report['source_staff_unpaired'],
            'target_staff_identity_pending': [row for row in report['target_staff_unpaired'] if row['scope_role'] != 'historical_controlled_test'],
            'resource_correspondence_reviews': resource_review,
            'source_internal_staff_relation_reviews': report['source_internal_staff_relation_view_differences'],
            'field_authority_resolutions': [
                {'decision_id': row['decision_id'], 'field': row['field'],
                 'chosen_value': None if row['field'] == 'treatment_identity' else row['source_value'],
                 'status': 'entity_identity_still_pending' if row['field'] == 'treatment_identity' else
                           'source_value_selected_by_owner_global_catalog_authority',
                 'requires_owner_input_for_field_value': row['field'] == 'treatment_identity',
                 'entity_equivalence_may_still_be_pending': row['comparison_basis'].startswith('conditional_'),
                 'runtime_change_applied': False} for row in report['decisions']],
            'deletions_proposed': 0, 'provenance_report_sha256': digest(report),
            'limits': ['source_authority_does_not_resolve_entity_identity', 'unmatched_names_do_not_prove_absence',
                       'resource_ids_are_separate_system_namespaces', 'target_write_contracts_not_certified_by_this_plan',
                       'calendar_backfill_and_bidirectional_booking_execution_not_performed']}


def load_current(directory, source_details_directory=None, **scope_flags):
    directory = Path(directory)
    manifest = json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('complete') is not True:
        raise Review('catalog_metadata_collection_incomplete')
    data, hashes = {}, {}
    for name in ('source-services', 'source-employees', 'source-service-details', 'target-services', 'target-providers'):
        body = (directory/(name+'.json')).read_bytes()
        value = json.loads(body)
        if value.get('schema_version') != 1 or not isinstance(value.get('rows'), list):
            raise Review('catalog_metadata_wrapper_invalid')
        data[name] = value
        hashes[name+'.json'] = hashlib.sha256(body).hexdigest()
        if manifest.get('files', {}).get(name+'.json', {}).get('sha256') != hashes[name+'.json']:
            raise Review('catalog_metadata_hash_changed')
        if manifest.get('rows', {}).get(name.replace('-', '_')) != len(value['rows']):
            raise Review('catalog_metadata_row_count_changed')
    source_at = data['source-services'].get('observed_at_utc')
    target_at = data['target-services'].get('observed_at_utc')
    details = data['source-service-details']['rows']
    employees = list(data['source-employees']['rows'])
    detail_scope = 'only_collected_detail_forms_unknown_elsewhere'
    full_manifest_hash = None
    full_started, full_completed = None, None
    if source_details_directory is not None:
        full = Path(source_details_directory)
        final_manifest = full/'complete-manifest.json'
        manifest_file = final_manifest if final_manifest.exists() else full/'manifest.json'
        details_file = full/('source-service-details-complete.json' if final_manifest.exists() else 'source-service-details.json')
        full_manifest_body = manifest_file.read_bytes()
        full_manifest = json.loads(full_manifest_body)
        full_started, full_completed = full_manifest.get('started_at_utc'), full_manifest.get('completed_at_utc')
        wrapper_body = details_file.read_bytes()
        wrapper = json.loads(wrapper_body)
        if full_manifest.get('complete') is not True or wrapper.get('complete') is not True:
            raise Review('catalog_full_detail_collection_incomplete')
        if final_manifest.exists():
            if full_manifest['combined_file']['path'] != details_file.name or full_manifest['combined_file']['sha256'] != hashlib.sha256(wrapper_body).hexdigest():
                raise Review('catalog_completed_detail_wrapper_changed')
            merged_files = {}
            for role in ('initial_manifest', 'continuation_manifest'):
                item = full_manifest[role]
                relative = Path(item['path'])
                if relative.is_absolute() or '..' in relative.parts:
                    raise Review('catalog_detail_artifact_path_invalid')
                path = full/relative
                body = path.read_bytes()
                if path.is_symlink() or not path.resolve().is_relative_to(full.resolve()) or hashlib.sha256(body).hexdigest() != item['sha256']:
                    raise Review('catalog_detail_component_manifest_changed')
                for key, record in json.loads(body)['row_files'].items():
                    if key in merged_files:
                        raise Review('catalog_detail_duplicate_completed_id')
                    merged_files[key] = {'filename': str(relative.parent/record['filename']), 'sha256': record['sha256']}
            full_manifest['row_files'] = merged_files
            if full_manifest.get('index_reference', {}).get('sha256') != hashes['source-services.json']:
                raise Review('catalog_completed_detail_index_changed')
        details = wrapper['rows']
        required = {str(row['id']) for row in data['source-services']['rows']}
        if ((full_manifest.get('expected_rows') is not None and full_manifest['expected_rows'] != len(required)) or
                {str(row['id']) for row in details} != required or len(details) != len(required)):
            raise Review('catalog_full_detail_coverage_mismatch')
        # Compare each aggregate row to the persisted, hashed per-service result.
        for row in details:
            record = full_manifest['row_files'][str(row['id'])]
            filename = record.get('filename', record.get('path', record.get('file')))
            relative = Path(filename) if isinstance(filename, str) else None
            if relative is None or relative.is_absolute() or '..' in relative.parts:
                raise Review('catalog_detail_artifact_path_invalid')
            artifact = full/relative
            if artifact.is_symlink() or not artifact.resolve().is_relative_to(full.resolve()):
                raise Review('catalog_detail_artifact_path_invalid')
            body = artifact.read_bytes()
            if hashlib.sha256(body).hexdigest() != record['sha256'] or json.loads(body) != row:
                raise Review('catalog_detail_artifact_changed')
        full_manifest_hash = hashlib.sha256(full_manifest_body).hexdigest()
        hashes['full-source-service-details.json'] = hashlib.sha256(wrapper_body).hexdigest()
        detail_scope = 'all_service_forms_from_observed_index_with_individual_fetch_timestamps'
        supplemental_manifest = full/'supplemental-employees-manifest.json'
        if supplemental_manifest.exists():
            supplemental_body = supplemental_manifest.read_bytes()
            supplemental = json.loads(supplemental_body)
            extra_body = (full/'source-employees-supplemental.json').read_bytes()
            extra = json.loads(extra_body)
            if supplemental.get('complete') is not True or extra.get('complete') is not True or supplemental.get('output_sha256') != hashlib.sha256(extra_body).hexdigest():
                raise Review('catalog_supplemental_employee_collection_incomplete_or_changed')
            employees.extend({**row, 'observed_at_utc': _field(row, 'fetched_at_utc', 'observed_at_utc') or extra.get('observed_at_utc')}
                             for row in extra['rows'])
            hashes['supplemental-employees-manifest.json'] = hashlib.sha256(supplemental_body).hexdigest()
            hashes['source-employees-supplemental.json'] = hashlib.sha256(extra_body).hexdigest()
    return build_review(normalize_services(data['source-services']['rows'], True, source_at, details),
                        normalize_staff(employees, True, data['source-employees'].get('observed_at_utc')),
                        normalize_services(data['target-services']['rows'], False, target_at),
                        normalize_staff(data['target-providers']['rows'], False, data['target-providers'].get('observed_at_utc')),
                        metadata={'basis': 'fresh_filtered_metadata_collection',
                                  'collection_started_at_utc': manifest.get('started_at_utc'),
                                  'collection_completed_at_utc': manifest.get('completed_at_utc'),
                                  'source_service_observed_at': source_at, 'target_service_observed_at': target_at,
                                  'collection_manifest_sha256': hashlib.sha256((directory/'manifest.json').read_bytes()).hexdigest(),
                                  'source_employee_forms_observed': len(employees),
                                  'source_service_detail_forms_observed': len(details),
                                  'source_service_detail_coverage': detail_scope,
                                  'full_detail_manifest_sha256': full_manifest_hash,
                                  'full_detail_started_at_utc': full_started,
                                  'full_detail_completed_at_utc': full_completed,
                                  'input_sha256': hashes,
                                  'coverage_limit': 'all_means_all_rows_in_saved_inventories_not_unobserved_account_fields'}, **scope_flags)


def load_import_provenance(checkpoint_path, workbook_path, assignment_journal_path, assignment_directory):
    """Project saved import/assignment evidence; never output login or raw files."""
    checkpoint_bytes = Path(checkpoint_path).read_bytes()
    checkpoint = json.loads(checkpoint_bytes)
    workbook_hash = hashlib.sha256(Path(workbook_path).read_bytes()).hexdigest()
    if checkpoint.get('identity', {}).get('workbook_sha256') != workbook_hash:
        raise Review('catalog_original_workbook_changed')
    journal_bytes = Path(assignment_journal_path).read_bytes()
    journal = json.loads(journal_bytes)
    result = {}
    for entry in checkpoint['rows'].values():
        identifier = entry.get('remote_id')
        if identifier is None:
            continue
        _ids([identifier], False)
        if identifier in result:
            raise Review('catalog_import_target_duplicate')
        normalized = entry['normalized']
        calculated = hashlib.sha256(json.dumps(normalized, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        if calculated != entry.get('row_hash'):
            raise Review('catalog_import_row_hash_changed')
        result[identifier] = {'original_workbook_hash_matches_checkpoint': True,
                              'original_import_status': entry.get('status'), 'original_excel_row': normalized['excel_row'],
                              'recorded_target_name': normalized['name'], 'recorded_duration_minutes': normalized['duration_minutes'],
                              'recorded_price': money(normalized['price']), 'normalized_row_sha256': calculated,
                              'native_id_creation_crosswalk_present': False}
    directory = Path(assignment_directory)
    assignment_count = 0
    no_direct_reference = []
    for key, item in journal['rows'].items():
        identifier = int(key)
        if item.get('status') != 'verified' or identifier not in result:
            continue
        filename = item.get('observed_snapshot')
        if filename is None:
            result[identifier].update({'assignment_status': 'verified_journal_without_direct_observed_reference',
                                       'assignment_readback_available_from_this_journal': False})
            no_direct_reference.append(identifier)
            continue
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise Review('catalog_assignment_path_invalid')
        path = directory/filename
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024*1024:
            raise Review('catalog_assignment_artifact_invalid')
        body = path.read_bytes()
        observation = json.loads(body)
        service = observation['service']
        if observation.get('plan_id') != journal['plan_id'] or service.get('id') != identifier:
            raise Review('catalog_assignment_identity_changed')
        result[identifier].update({'assignment_status': 'verified', 'assignment_readback_sha256': hashlib.sha256(body).hexdigest(),
                                   'assignment_readback_observed_at': observation.get('observed_at'),
                                   'assignment_observed_provider_ids': _ids(service.get('providers'), False),
                                   'assignment_observed_active': _bool(service.get('is_active'))})
        assignment_count += 1
    return result, {'original_workbook_sha256': workbook_hash,
                    'import_checkpoint_sha256': hashlib.sha256(checkpoint_bytes).hexdigest(),
                    'assignment_journal_sha256': hashlib.sha256(journal_bytes).hexdigest(),
                    'recorded_import_targets': len(result), 'verified_assignment_readbacks': assignment_count,
                    'verified_journal_rows': sum(item.get('status') == 'verified' for item in journal['rows'].values()),
                    'journal_rows_without_direct_readback_reference': sorted(no_direct_reference),
                    'native_id_crosswalk_reconstructed': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--current-metadata-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-details-dir', type=Path)
    parser.add_argument('--import-checkpoint', type=Path)
    parser.add_argument('--original-workbook', type=Path)
    parser.add_argument('--assignment-journal', type=Path)
    parser.add_argument('--assignment-directory', type=Path)
    parser.add_argument('--authority-record', type=Path)
    parser.add_argument('--source-test-service', action='append', default=[])
    parser.add_argument('--target-test-service', action='append', default=[], type=int)
    parser.add_argument('--target-test-provider', action='append', default=[], type=int)
    args = parser.parse_args(argv)
    try:
        proof_args = (args.import_checkpoint, args.original_workbook, args.assignment_journal, args.assignment_directory)
        if any(proof_args) and not all(proof_args):
            raise Review('catalog_complete_import_provenance_arguments_required')
        provenance, proof_summary = load_import_provenance(*proof_args) if all(proof_args) else (None, None)
        report = load_current(args.current_metadata_dir, source_details_directory=args.source_details_dir,
                              source_test_service_ids=args.source_test_service,
                              target_test_service_ids=args.target_test_service,
                              target_test_provider_ids=args.target_test_provider, provenance=provenance)
        if proof_summary:
            report['scope']['recorded_import_assignment_evidence'] = proof_summary
        policy = json.loads(args.authority_record.read_text(encoding='utf-8')) if args.authority_record else None
        plan = source_authoritative_plan(report, policy) if policy is not None else None
        write_review(args.output, report, plan)
    except (OSError, ValueError, KeyError, TypeError, Review):
        print(json.dumps({'prepared': False, 'reason': 'catalog_review_requires_inspection', 'runtime_mappings_written': False}))
        return 2
    print(json.dumps({'prepared': True, 'summary': report['summary'], 'runtime_mappings_written': False}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
