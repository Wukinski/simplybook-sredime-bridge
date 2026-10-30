import argparse
import json
import secrets
import time
from pathlib import Path

from provider_assignment.core import Failure, lock

from .model import HOME, Review, Settings, Uncertain, positive
from .simplybook import Gateway, SimulatedGateway
from .store import Store
from .worker import Worker, matches


def init():
    """Create local files only if absent. Never display generated secrets."""
    from shutil import copyfile
    local = HOME / 'config.local.json'
    if not local.exists():
        copyfile(HOME / 'config.example.json', local)
    env = HOME / '.env'
    if not env.exists():
        env.write_text('SREDIME_WEBHOOK_SECRET=\nSIMPLYBOOK_WEBHOOK_SECRET=\n'
                       'BRIDGE_ADMIN_KEY=' + secrets.token_urlsafe(48) + '\n'
                       'BRIDGE_FEED_TOKENS={}\nSREDIME_EXPORT_URLS={}\nBRIDGE_ALERTS_URL=\n', encoding='utf-8')
    for kind in ('employees', 'services'):
        path = HOME / 'mappings' / (kind + '.local.csv')
        if not path.exists():
            copyfile(HOME / 'mappings' / (kind + '.csv'), path)
    print('Local private configuration prepared; edit booking_bridge/.env locally. No API calls.')


def main():
    parser = argparse.ArgumentParser(description='Andjelija connector: defaults to local simulation')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('init')
    sub.add_parser('status')
    sub.add_parser('worker')
    preflight = sub.add_parser('preflight')
    preflight.add_argument('--target', choices=('pilot', 'production'), default='pilot')
    preflight.add_argument('--readiness', type=Path)
    diagnose = sub.add_parser('diagnose')
    diagnose.add_argument('--read-only', action='store_true', required=True)
    sub.add_parser('prepare-pilot')
    source_review = sub.add_parser('prepare-source-review')
    source_review.add_argument('--source', required=True, type=Path)
    source_review.add_argument('--expected-salon', required=True)
    source_review.add_argument('--expected-vendor', required=True)
    source_review.add_argument('--output', required=True, type=Path)
    binding = sub.add_parser('bind-source-uid')
    binding.add_argument('--employee', required=True)
    binding.add_argument('--uid', required=True)
    binding.add_argument('--booking', required=True)
    binding.add_argument('--verified-reference', action='store_true', required=True)
    sub.add_parser('rotate-feed').add_argument('--employee', required=True)
    backup = sub.add_parser('backup')
    backup.add_argument('--destination', required=True)
    link = sub.add_parser('resolve-create')
    link.add_argument('--booking', required=True)
    link.add_argument('--target', required=True, type=int)
    link.add_argument('--verified-ownership', action='store_true', required=True)
    client = sub.add_parser('map-client')
    client.add_argument('--source', required=True)
    client.add_argument('--target', required=True, type=int)
    client.add_argument('--verified-person', action='store_true', required=True)
    create_client = sub.add_parser('create-client')
    create_client.add_argument('--event', required=True)
    create_client.add_argument('--verified-new-person', action='store_true', required=True)
    args = parser.parse_args()
    if args.command == 'preflight':
        from .preflight import run
        raise SystemExit(run(args.target, args.readiness))
    if args.command == 'init':
        init()
        return
    settings = Settings.load(read_only=args.command in ('diagnose', 'prepare-pilot', 'prepare-source-review'))
    if args.command == 'prepare-source-review':
        from .source_review import run
        run(settings, args.source, args.expected_salon, args.expected_vendor, args.output)
        return
    if args.command == 'diagnose':
        from .diagnostics import ReadOnlyGateway, inspect_account
        from service_importer.import_services import atomic_json
        report = inspect_account(settings, ReadOnlyGateway(settings))
        settings.state.mkdir(parents=True, exist_ok=True)
        atomic_json(settings.state / 'diagnostics.json', report)
        print(json.dumps({'read_only': True, 'business_writes': 0, 'identity_verified': report['identity_verified'],
                          'provider_count': report['provider_count'], 'service_count': report['service_count'],
                          'test_provider_count': len(report['test_provider_candidates']),
                          'test_service_count': len(report['test_service_candidates']),
                          'direct_transport_calls': report['direct_transport_calls']}))
        return
    if args.command == 'prepare-pilot':
        from .pilot_setup import prepare
        from service_importer.import_services import atomic_json
        path = settings.state / 'diagnostics.json'
        if not path.exists():
            raise Review('run_read_only_diagnostics_first')
        report = json.loads(path.read_text(encoding='utf-8'))
        proposal = prepare(report, settings.salon)
        atomic_json(settings.state / 'pilot-setup.json', proposal)
        print(json.dumps({'prepared': True, 'execution': 'not_dispatched', 'review_hash': proposal['review_hash'],
                          'new_providers': len(proposal['creates']['providers']),
                          'new_services': len(proposal['creates']['services']), 'business_writes': 0}))
        return
    store = Store(settings.state / 'bridge.sqlite')
    if args.command == 'status':
        print(json.dumps({'mode': settings.mode, 'states': store.rows('SELECT state,COUNT(*) AS count FROM events GROUP BY state'),
                          'open_issues': store.rows('SELECT COUNT(*) AS count FROM issues WHERE resolved=0')[0]['count'],
                          'heartbeat_age_seconds': round(time.time() - store.get('heartbeat')[1])}))
        return
    if args.command == 'backup':
        store.backup(args.destination)
        print('SQLite online backup completed. Protect the backup as private data.')
        return
    if args.command == 'rotate-feed':
        if args.employee not in settings.allowed_employees:
            raise Review('employee_not_enabled')
        from dotenv import set_key
        values = dict(settings.feed_tokens)
        values[args.employee] = secrets.token_urlsafe(48)
        set_key(str(HOME / '.env'), 'BRIDGE_FEED_TOKENS', json.dumps(values))
        print('Token saved privately to booking_bridge/.env. Restart API, update the private Buker import URL locally.')
        return
    # Operations that change local linkage cannot race with the singleton worker.
    with lock(settings.state / 'worker.lock'):
        if args.command == 'bind-source-uid':
            if args.employee not in settings.allowed_employees:
                raise Review('employee_not_enabled')
            if not store.rows('SELECT 1 FROM links WHERE booking=?', (args.booking,)):
                raise Review('unknown_source_booking')
            existing = store.rows('SELECT booking FROM source_bindings WHERE employee=? AND uid=?', (args.employee, args.uid))
            if existing and existing[0]['booking'] != args.booking:
                raise Review('refusing_source_uid_reassignment')
            store.execute('INSERT OR IGNORE INTO source_bindings VALUES(?,?,?)', (args.employee, args.uid, args.booking))
            # Re-evaluate the next authoritative source poll, even if unchanged.
            store.execute('DELETE FROM cache WHERE key=?', ('source-feed:' + args.employee,))
            store.execute('INSERT INTO audit VALUES(?,?,?)', (time.time(), 'verified_source_uid', args.booking))
            print('Verified ICS UID binding saved. No remote writes. Restart worker.')
            return
        gateway = SimulatedGateway() if settings.mode == 'simulation' else Gateway(settings)
        worker = Worker(settings, store, gateway)
        if args.command == 'resolve-create':
            if settings.mode == 'simulation':
                raise Review('manual_live_resolution_requires_live_configuration')
            rows = store.rows("SELECT * FROM intents WHERE booking=? AND kind='create' AND state!='done'", (args.booking,))
            if len(rows) != 1:
                raise Review('no_uncertain_create')
            desired = json.loads(rows[0]['desired'])
            actual = gateway.detail(positive(args.target))
            if not matches(actual, desired) or actual.get('status') != 'confirmed':
                raise Review('verified_target_does_not_match_intent')
            with store.connect() as conn:
                conn.execute('INSERT INTO links(booking,target) VALUES(?,?) ON CONFLICT(booking) DO UPDATE SET target=excluded.target', (args.booking, args.target))
                conn.execute("UPDATE intents SET result=?,state='done' WHERE booking=?", (args.target, args.booking))
                conn.execute("UPDATE events SET state='queued',due=0 WHERE id=?", (rows[0]['event'],))
                conn.execute('INSERT INTO audit VALUES(?,?,?)', (time.time(), 'verified_create_link', args.booking))
                conn.execute('UPDATE issues SET resolved=1 WHERE key=?', ('intent:' + args.booking,))
            print('Verified source booking linked; event queued. Restart the worker.')
            return
        if args.command == 'map-client':
            if settings.mode == 'simulation':
                raise Review('client_operations_require_live_configuration')
            if not settings.approvals.get('client_mapping'):
                raise Review('client_mapping_consent_required')
            actual = gateway.read('/admin/clients/' + str(positive(args.target)))
            if actual.get('id') != args.target:
                raise Review('client_identity_mismatch')
            existing = store.rows('SELECT target FROM clients WHERE source=?', (args.source,))
            if existing and existing[0]['target'] != args.target:
                raise Review('refusing_customer_reassignment')
            store.execute('INSERT OR IGNORE INTO clients VALUES(?,?)', (args.source, args.target))
            store.execute('INSERT INTO audit VALUES(?,?,?)', (time.time(), 'verified_client_link', args.source))
            print('Verified client mapping saved. Retry the reviewed event after restarting the worker.')
            return
        if args.command == 'create-client':
            if settings.mode == 'simulation':
                raise Review('client_operations_require_live_configuration')
            if not settings.approvals.get('customer_contacts') or not settings.approvals.get('client_mapping'):
                raise Review('authorized_customer_contacts_required')
            rows = store.rows('SELECT payload FROM events WHERE id=?', (args.event,))
            if len(rows) != 1:
                raise Review('event_not_found')
            event = json.loads(rows[0]['payload'])
            if event['test'] or event['data'].get('employee', {}).get('id') not in settings.allowed_employees:
                raise Review('client_create_outside_pilot_scope')
            customer = event['data'].get('customer', {})
            source = customer.get('id')
            if not source or not all(isinstance(customer.get(k), str) and customer[k].strip() for k in ('name', 'email', 'phone')):
                raise Review('approved_customer_fields_incomplete')
            if store.rows('SELECT 1 FROM clients WHERE source=?', (source,)) or source in settings.clients:
                raise Review('client_already_mapped')
            if store.get('client-intent:' + source)[0]:
                raise Review('client_create_already_attempted_manual_resolution_required')
            # A person must review existing records first. Matching contact strings
            # does not prove two people are the same (family/shared contacts).
            store.put('client-intent:' + source, {'state': 'started', 'event': args.event})
            value = gateway.write('POST', '/admin/clients', {k: customer[k] for k in ('name', 'email', 'phone')})
            target = positive(value.get('id'))
            store.execute('INSERT INTO clients VALUES(?,?)', (source, target))
            store.put('client-intent:' + source, {'state': 'done', 'target': target})
            print('Reviewed new client created once and mapped. No contact data logged.')
            return
        if args.command == 'worker':
            from .server_worker import run_loop
            print('Singleton worker started in ' + settings.mode + ' mode. Ctrl+C stops safely.')
            run_loop(settings, store, worker, gateway)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('Worker stopped; committed events and intents are retained.')
    except (Review, Failure, Uncertain) as exc:
        print('Stopped safely: ' + str(exc))
        raise SystemExit(2)
