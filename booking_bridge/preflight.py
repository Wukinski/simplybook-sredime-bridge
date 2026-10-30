"""Offline configuration checks. Never construct a gateway or initialize a DB."""
import json
import os
import re
import sqlite3
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit

from .model import HOME, ROOT, Review, Settings


def positive_id(value):
    return type(value) is int and value > 0


def https_endpoint(value):
    try:
        parsed = urlsplit(value)
        return bool(parsed.scheme == 'https' and parsed.hostname and
                    parsed.port in (None, 443) and not parsed.username and
                    not parsed.password and not parsed.fragment)
    except (TypeError, ValueError, AttributeError):
        return False


def local_state(path):
    if not path.exists():
        return True, True, set()
    try:
        conn = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=1)
        try:
            if conn.execute('PRAGMA user_version').fetchone()[0] != 1:
                return False, False, set()
            conn.execute('BEGIN')
            unresolved = conn.execute("SELECT COUNT(*) FROM intents WHERE state!='done'").fetchone()[0]
            clients = {row[0] for row in conn.execute('SELECT target FROM clients')}
            return True, unresolved == 0, clients
        finally:
            conn.close()
    except sqlite3.Error:
        return False, False, set()


def inspect(settings, target='pilot', environ=None, *, readiness_path=None, now=None):
    if target not in ('pilot', 'production'):
        raise ValueError('unsupported_preflight_target')
    environ = os.environ if environ is None else environ
    checks = []

    def check(code, ok):
        checks.append({'code': code, 'ok': bool(ok)})

    try:
        replace(settings, mode=target).validate()
        valid = True
    except (Review, TypeError, ValueError):
        valid = False
    check('runtime_configuration', valid)
    if target == 'production' and settings.require_subminute_availability:
        check('subminute_availability_transport', False)
    required = ['live_writes', 'business_rules', 'hosting', 'privacy',
                'account_identity_verified', 'schedule_reference_verified', 'client_mapping']
    required += (['pilot_scope_reviewed'] if target == 'pilot' else
                 ['notification_behavior', 'account_booking_trial', 'calendar_blocks_trial', 'empty_feed_trial'])
    for name in required:
        check('approval_' + name, settings.approvals.get(name) is True)
    check('live_reads', settings.reads_enabled is True)
    check('sredime_signing_secret', bool(re.fullmatch('[a-fA-F0-9]{64}', settings.webhook_secret)))
    check('simplybook_signing_secret', bool(settings.simplybook_webhook_secret))
    check('admin_key', len(settings.admin_key) >= 32)
    base = environ.get('SIMPLYBOOK_REST_BASE_URL', '').rstrip('/')
    check('rest_credentials', bool(environ.get('SIMPLYBOOK_ADMIN_LOGIN') and
                                   environ.get('SIMPLYBOOK_ADMIN_SECRET')))
    check('rest_company', environ.get('SIMPLYBOOK_COMPANY_LOGIN') == settings.salon)
    if settings.expected_rest_base:
        identity_ok = base == settings.expected_rest_base and https_endpoint(base)
    else:
        identity = json.loads((HOME / 'evidence/account-identity.json').read_text(encoding='utf-8'))
        identity_ok = base == identity['base'] and settings.salon == identity['company']
    check('rest_region', identity_ok)
    employees = settings.allowed_employees
    check('employee_allowlist', bool(employees) and all(isinstance(e, str) and e for e in employees)
          and len(set(employees)) == len(employees))
    check('employee_mappings', bool(employees) and all(
        positive_id(settings.employees.get(e, {}).get('id')) for e in employees))
    check('unique_employee_targets', len({settings.employees.get(e, {}).get('id') for e in employees})
          == len(employees))
    services = list(settings.services.values())
    service_ids = {s.get('id') for s in services}
    check('service_mappings', bool(services) and all(positive_id(s.get('id')) for s in services))
    check('service_timing_and_resources', bool(services) and all(
        s.get('timing_verified') is True and s.get('resources_verified') is True and
        type(s.get('duration')) is int and s['duration'] > 0 for s in services))
    check('schedule_references', bool(employees) and all(
        positive_id(settings.schedule_service_ids.get(e)) and
        settings.schedule_service_ids[e] in service_ids for e in employees))
    check('private_feed_tokens', bool(employees) and all(
        isinstance(settings.feed_tokens.get(e), str) and len(settings.feed_tokens[e]) >= 32 for e in employees))
    check('source_export_endpoints', bool(employees) and all(
        https_endpoint(settings.export_urls.get(e)) for e in employees))
    state_ok, intents_ok, persisted_clients = local_state(settings.state / 'bridge.sqlite')
    check('local_state_readable', state_ok)
    from .recovery import recovery_start_allowed
    check('restore_reconciliation_complete', recovery_start_allowed(settings.state / 'bridge.sqlite'))
    check('remote_intents_resolved', intents_ok)
    clients = set(settings.clients.values()) | persisted_clients
    check('client_mappings', bool(clients) and all(positive_id(v) for v in clients))
    if target == 'pilot':
        for name, values in [('pilot_client_ids', settings.pilot_client_ids),
                             ('pilot_service_ids', settings.pilot_service_ids)]:
            check(name, bool(values) and all(positive_id(v) for v in values) and len(set(values)) == len(values))
        check('pilot_service_scope', bool(service_ids) and service_ids <= set(settings.pilot_service_ids))
        check('pilot_client_scope', bool(clients) and clients <= set(settings.pilot_client_ids))
    else:
        from .production_readiness import inspect_evidence
        evidence = inspect_evidence(settings, readiness_path or
            environ.get('BRIDGE_PRODUCTION_READINESS_FILE'), now=now)
        checks.extend(evidence['checks'])
        check('production_state_present', (settings.state / 'bridge.sqlite').is_file())
    return {'target': target, 'current_mode': settings.mode,
            'configuration_ready': all(row['ok'] for row in checks), 'checks': checks,
            'external_validation_performed': False}


def run(target, readiness_path=None):
    from dotenv import load_dotenv
    # Match the REST client's local credential sources without creating a client.
    try:
        settings = Settings.load(read_only=True)
        load_dotenv(ROOT / 'service_importer/.env')
        load_dotenv(ROOT / 'provider_assignment/.env')
        report = inspect(settings, target, readiness_path=readiness_path)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, Review):
        # Parser errors may include private configuration values; never echo them.
        report = {'target': target, 'current_mode': None, 'configuration_ready': False,
                  'checks': [{'code': 'local_configuration_unreadable', 'ok': False}],
                  'external_validation_performed': False}
    print(json.dumps(report))
    return 0 if report['configuration_ready'] else 2
