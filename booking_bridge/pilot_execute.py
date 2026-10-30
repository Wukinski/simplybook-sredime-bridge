"""Execute one reviewed, durably queued local pilot event, with no automatic retry.

Use a separate execution JSON profile in pilot mode. The simulation capture and
hosted receiver profiles remain unchanged. Credentials are loaded locally through
the existing .env sources; this module never transfers them to another machine.
"""
import argparse
import json
import os
import re
import time
from dataclasses import replace
from pathlib import Path

from dotenv import load_dotenv
from fastapi import HTTPException

from provider_assignment.core import Failure, lock

from .event_envelope import envelope
from .model import ROOT, Review, Settings, digest, stamp
from .preflight import inspect as inspect_preflight
from .simplybook import Gateway
from .store import Store
from .worker import Worker


class Blocked(Review):
    """Only fixed operator-facing codes, optionally with preflight check names."""
    def __init__(self, code, failed_checks=()):
        super().__init__(code)
        self.failed_checks = tuple(failed_checks)


def _id(value):
    return type(value) is int and value > 0


def _scope(settings):
    if settings.mode != 'pilot' or settings.reads_enabled is not True:
        raise Blocked('explicit_live_pilot_profile_required')
    if (not isinstance(settings.approvals, dict) or
            settings.approvals.get('pilot_scope_reviewed') is not True):
        raise Blocked('pilot_scope_review_required')
    employees = settings.allowed_employees
    if (not isinstance(employees, list) or len(employees) != 1 or
            not isinstance(employees[0], str) or not employees[0] or
            not isinstance(settings.employees, dict) or
            set(settings.employees) != set(employees) or
            not isinstance(settings.employees[employees[0]], dict) or
            not _id(settings.employees[employees[0]].get('id'))):
        raise Blocked('single_employee_pilot_scope_required')
    services = settings.services
    allowed_services = settings.pilot_service_ids
    if (not isinstance(services, dict) or not services or
            not isinstance(allowed_services, list) or not allowed_services or
            any(not _id(value) for value in allowed_services) or
            len(set(allowed_services)) != len(allowed_services) or
            any(not isinstance(source, str) or not source or not isinstance(row, dict) or
                not _id(row.get('id')) or row['id'] not in allowed_services
                for source, row in services.items()) or
            {row['id'] for row in services.values()} != set(allowed_services)):
        raise Blocked('explicit_test_services_pilot_scope_required')
    clients = settings.clients
    allowed_clients = settings.pilot_client_ids
    if (not isinstance(clients, dict) or not clients or
            not isinstance(allowed_clients, list) or not allowed_clients or
            any(not _id(value) for value in allowed_clients) or
            len(set(allowed_clients)) != len(allowed_clients) or
            any(not isinstance(source, str) or not source or not _id(target) or
                target not in allowed_clients for source, target in clients.items()) or
            len(set(clients.values())) != len(clients)):
        raise Blocked('explicit_verified_pilot_clients_required')
    if (not isinstance(settings.policies, dict) or
            settings.policies.get('notifications') != 'controlled_test_contacts_only'):
        raise Blocked('controlled_test_contact_policy_required')


def _verified_event(settings, store, row):
    try:
        raw = json.loads(row['payload'])
        event = envelope(row['payload'].encode(), settings.approvals.get('customer_contacts') is True)
        if (digest(raw) != row['hash'] or event['id'] != row['id'] or
                event['data']['id'] != row['booking'] or
                stamp(event['created_at']).timestamp() != row['created']):
            raise ValueError()
    except (HTTPException, KeyError, TypeError, ValueError, Review):
        raise Blocked('stored_pilot_event_integrity_failed') from None
    data = event['data']
    if event['test'] is not False:
        raise Blocked('real_source_pilot_event_required')
    if (data.get('employee') or {}).get('id') != settings.allowed_employees[0]:
        raise Blocked('pilot_event_employee_outside_scope')
    action = settings.action(data['status'], event['type'])
    if action not in ('upsert', 'cancel'):
        raise Blocked('pilot_event_action_requires_review')
    reference = data
    if action == 'cancel' and ('service' not in data or 'customer' not in data):
        links = store.rows('SELECT snapshot FROM links WHERE booking=?', (row['booking'],))
        try:
            reference = json.loads(links[0]['snapshot'])
        except (IndexError, KeyError, TypeError, ValueError):
            raise Blocked('pilot_cancel_scope_unverified') from None
        if (not isinstance(reference, dict) or
                (reference.get('employee') or {}).get('id') != settings.allowed_employees[0]):
            raise Blocked('pilot_cancel_scope_unverified')
    service = (reference.get('service') or {}).get('id')
    customer = (reference.get('customer') or {}).get('id')
    if not isinstance(service, str) or service not in settings.services:
        raise Blocked('pilot_event_service_outside_scope')
    if not isinstance(customer, str) or customer not in settings.clients:
        raise Blocked('pilot_event_customer_not_verified')


class _ExpectedEventStore:
    """Delegate storage, but atomically refuse a different or retried claim."""
    def __init__(self, store, event_id):
        self.store, self.event_id = store, event_id

    def __getattr__(self, name):
        return getattr(self.store, name)

    def claim(self, now):
        with self.store.connect() as conn:
            row = conn.execute("SELECT * FROM events WHERE state='queued' ORDER BY created,received LIMIT 1").fetchone()
            if not row:
                return None
            if row['id'] != self.event_id:
                raise Blocked('pilot_event_id_mismatch')
            if row['attempts'] != 0:
                raise Blocked('pilot_event_retry_requires_review')
            if row['due'] > now:
                raise Blocked('pilot_event_not_due')
            conn.execute("UPDATE events SET state='working',attempts=attempts+1 WHERE id=?", (self.event_id,))
            result = dict(row)
            result['attempts'] += 1
            return result


def _result(store, row=None, *, processed=0, status=None):
    target = None
    reason = None
    if row:
        current = store.rows('SELECT state,reason FROM events WHERE id=?', (row['id'],))[0]
        state = current['state']
        reason = current['reason']
        targets = store.rows('SELECT target FROM links WHERE booking=?', (row['booking'],))
        if targets:
            target = targets[0]['target']
    else:
        state = None
    # Worker reasons are fixed codes. Never echo an unexpected stored value.
    if reason and not re.fullmatch('[a-z][a-z0-9_]{0,120}', reason):
        reason = 'operator_review_required'
    return {'status': status or state, 'event_id': row['id'] if row else None,
            'event_state': state, 'reason': reason, 'target_booking_id': target,
            'events_processed': processed,
            'queued_events': store.rows("SELECT COUNT(*) AS n FROM events WHERE state='queued'")[0]['n'],
            'unresolved_intents': store.rows("SELECT COUNT(*) AS n FROM intents WHERE state!='done'")[0]['n'],
            'automatic_retry': False}


def execute_one(settings, *, execute=False, event_id=None, environ=None, gateway_factory=None, now=None):
    """Process at most one eligible event under worker.lock, or refuse safely.

    The existing durable receiver is responsible for signature verification at
    ingestion. Stored envelope/hash and exact reviewed source scope are checked
    again here before any gateway is constructed.
    """
    if execute is not True:
        raise Blocked('explicit_execute_required')
    _scope(settings)
    if event_id is not None and (not isinstance(event_id, str) or not re.fullmatch('[a-f0-9]{32}', event_id)):
        raise Blocked('invalid_expected_event_id')
    database = settings.state / 'bridge.sqlite'
    if not database.is_file():
        raise Blocked('existing_durable_pilot_state_required')
    with lock(settings.state / 'worker.lock'):
        report = inspect_preflight(settings, target='pilot', environ=os.environ if environ is None else environ)
        if not report['configuration_ready']:
            raise Blocked('pilot_preflight_failed', [c['code'] for c in report['checks'] if not c['ok']])
        store = Store(database)
        if store.rows("SELECT 1 FROM intents WHERE state!='done' LIMIT 1"):
            raise Blocked('unresolved_remote_intents_require_review')
        requested = store.rows('SELECT * FROM events WHERE id=?', (event_id,)) if event_id else []
        if event_id and not requested:
            raise Blocked('expected_pilot_event_not_found')
        if requested and requested[0]['state'] == 'done':
            _verified_event(settings, store, requested[0])
            return _result(store, requested[0], status='already_processed')
        if requested and requested[0]['state'] != 'queued':
            raise Blocked('pilot_event_state_requires_review')
        queued = store.rows("SELECT * FROM events WHERE state='queued' ORDER BY created,received LIMIT 1")
        if not queued:
            return _result(store, status='no_queued_events')
        row = queued[0]
        if event_id is not None and row['id'] != event_id:
            raise Blocked('pilot_event_id_mismatch')
        if row['attempts'] != 0:
            raise Blocked('pilot_event_retry_requires_review')
        now = time.time() if now is None else now
        if row['due'] > now:
            raise Blocked('pilot_event_not_due')
        _verified_event(settings, store, row)
        # Account initialization starts only after all actual pilot gates pass.
        gateway = (gateway_factory or Gateway)(settings)
        worker = Worker(settings, _ExpectedEventStore(store, row['id']), gateway)
        handled = worker.once(now)
        return _result(store, row, processed=int(handled), status=None if handled else 'event_no_longer_queued')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', required=True)
    parser.add_argument('--config', required=True, type=Path, help='Explicit separate pilot execution JSON')
    parser.add_argument('--state', required=True, type=Path, help='Existing local durable pilot state directory')
    parser.add_argument('--event-id', help='Expected oldest queued source event ID')
    args = parser.parse_args(argv)
    try:
        load_dotenv(ROOT / 'service_importer/.env')
        load_dotenv(ROOT / 'provider_assignment/.env')
        settings = Settings.load(args.config, read_only=True, isolated_profile=True)
        settings = replace(settings, state=args.state.resolve())
        result = execute_one(settings, execute=args.execute, event_id=args.event_id)
    except Blocked as error:
        result = {'status': 'blocked', 'error': str(error), 'failed_checks': list(error.failed_checks)}
        print(json.dumps(result))
        return 2
    except (Review, Failure):
        print(json.dumps({'status': 'blocked', 'error': 'pilot_configuration_or_gateway_rejected'}))
        return 2
    except (OSError, ValueError, TypeError, KeyError):
        print(json.dumps({'status': 'blocked', 'error': 'pilot_configuration_or_state_unreadable'}))
        return 2
    print(json.dumps(result))
    return 0 if result['status'] in ('done', 'already_processed', 'no_queued_events') else 2


if __name__ == '__main__':
    raise SystemExit(main())
