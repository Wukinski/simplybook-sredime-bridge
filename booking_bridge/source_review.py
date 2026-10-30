"""Offline SrediMe inventory review. Suggestions never become runtime mappings."""
import csv
import json
import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

from .model import Review, digest


def name_key(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 1024:
        raise Review('invalid_source_inventory_name')
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())


def source_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]{0,19}', value):
        raise Review('invalid_source_inventory_id')
    return value


def displayed_duration(summary):
    if not isinstance(summary, str):
        return None
    values = [int(m.group(1)) for line in summary.splitlines()
              if (m := re.fullmatch(r"([1-9][0-9]{0,3})'", line.strip()))]
    return values[0] if len(values) == 1 else None


def index(rows, source=False):
    result = defaultdict(list)
    ids = set()
    for row in rows:
        identifier = source_id(row['id']) if source else row['id']
        if not source and (type(identifier) is not int or identifier <= 0):
            raise Review('invalid_target_inventory_id')
        if identifier in ids:
            raise Review('duplicate_inventory_id')
        ids.add(identifier)
        result[name_key(row['name'])].append(row)
    return result


def candidates(source_rows, target_rows, services=False):
    source_index = index(source_rows, source=True)
    target_index = index(target_rows)
    rows = []
    for source in source_rows:
        key = name_key(source['name'])
        exact = target_index.get(key, [])
        unambiguous = len(source_index[key]) == 1 and len(exact) == 1
        choices = exact if exact else sorted(target_rows, key=lambda target: (
            -SequenceMatcher(None, key, name_key(target['name'])).ratio(), target['id']))[:3]
        for rank, target in enumerate(choices or [None], 1):
            row = {'sredime_id': source['id'], 'sredime_name': source['name'],
                   'simplybook_id': target['id'] if target else '',
                   'simplybook_name': target['name'] if target else '',
                   'rank': rank, 'match': 'unique_name' if unambiguous else
                   ('ambiguous_name' if exact else 'suggestion_only'),
                   'approved': 'no', 'timing_verified': 'no', 'resources_verified': 'no'}
            if services:
                duration = displayed_duration(source.get('summary'))
                target_duration = target.get('duration') if target else None
                row.update({'sredime_duration_minutes': duration if duration else '',
                            'simplybook_duration_minutes': target_duration if type(target_duration) is int else '',
                            'duration_comparison': 'unverified' if duration is None or
                            type(target_duration) is not int else
                            ('equal' if duration == target_duration else 'mismatch')})
            rows.append(row)
    return rows


def prepare(source, target, expected_slug, expected_vendor, expected_company):
    """Return a whitelisted report: no session, contact, URL or secret fields."""
    if (source.get('authenticated') is not True or source.get('read_only') is not True or
            source.get('business_writes') != 0 or source.get('salon_slug') != expected_slug or
            source.get('vendor_id') != source_id(expected_vendor)):
        raise Review('source_account_identity_unverified')
    if (target.get('read_only') is not True or target.get('identity_verified') is not True or
            target.get('company') != expected_company or target.get('preserved_baseline_sha256') !=
            digest(target.get('preserved_baseline'))):
        raise Review('target_account_identity_unverified')
    employees, services = source['employees'], source['services']
    for employee in employees:
        if employee.get('vendor_id') != expected_vendor or type(employee.get('active')) is not bool or \
                type(employee.get('bookable')) is not bool:
            raise Review('source_employee_scope_unverified')
    # Validate all inventory, including inactive/nonbookable people.
    index(employees, source=True)
    index(services, source=True)
    bookable = [e for e in employees if e['active'] and e['bookable']]
    staff = candidates(bookable, target['preserved_baseline']['providers'])
    treatments = candidates(services, target['preserved_baseline']['services'], services=True)
    unique = [r for r in treatments if r['match'] == 'unique_name']
    report = {
        'read_only': True, 'business_writes': 0, 'mappings_applied': False,
        'salon_slug': expected_slug, 'vendor_id': expected_vendor,
        'source_checked_at': source.get('checked_at'), 'target_checked_at': target.get('checked_at'),
        'source_active_employee_count': sum(e['active'] for e in employees),
        'source_bookable_employee_count': len(bookable), 'source_service_count': len(services),
        'target_employee_count': len(target['preserved_baseline']['providers']),
        'target_service_count': len(target['preserved_baseline']['services']),
        'unique_employee_name_candidates': sum(r['match'] == 'unique_name' for r in staff),
        'employees_without_unique_name_match': [e['id'] for e in bookable if not any(
            r['sredime_id'] == e['id'] and r['match'] == 'unique_name' for r in staff)],
        'bookable_employees_without_assigned_services': [e['id'] for e in bookable if not e.get('services')],
        'unique_service_name_candidates': len(unique),
        'unique_service_duration_mismatches': sum(r['duration_comparison'] == 'mismatch' for r in unique),
        'source_imports_configured': sum(bool(e.get('import_url')) for e in employees),
        'source_exports_available': sum(bool(e.get('export_url')) for e in employees),
        'instant_booking_enabled': source.get('instant_booking_enabled'),
        'source_webhook_count': source.get('webhook_count'),
        'resource_count': len(source.get('resources', [])),
        'production_enabled': False, 'subminute_verified': False,
    }
    return report, staff, treatments


def csv_cell(value):
    text = str(value)
    # These files are intended for spreadsheet review; never execute cell formulas.
    return "'" + text if text.lstrip().startswith(('=', '+', '-', '@')) or text.startswith(('\t', '\r', '\n')) else text


def write_review(output, report, staff, treatments):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'account-review.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    for name, rows in [('employee-candidates.csv', staff), ('service-candidates.csv', treatments)]:
        with (output / name).open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else ['sredime_id', 'approved'])
            writer.writeheader()
            writer.writerows({k: csv_cell(v) for k, v in row.items()} for row in rows)


def run(settings, source_path, expected_slug, expected_vendor, output):
    try:
        source = json.loads(Path(source_path).read_text(encoding='utf-8'))
        target = json.loads((settings.state / 'diagnostics.json').read_text(encoding='utf-8'))
        report, staff, treatments = prepare(source, target, expected_slug, expected_vendor, settings.salon)
        write_review(output, report, staff, treatments)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise Review('source_review_input_invalid') from None
    print(json.dumps(report))
