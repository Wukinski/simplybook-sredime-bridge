"""One process owns mutations. Every remote write has a committed local intent."""
import json
import time
from datetime import datetime, timedelta

from .model import BELGRADE, UTC, Review, Temporary, Uncertain, affected_sources, company_time, digest, positive, stamp

FIELDS = ('service_id', 'provider_id', 'client_id', 'start_datetime', 'end_datetime')


def matches(actual, desired):
    return all(actual.get(k) == desired.get(k) for k in FIELDS)


class Worker:
    def __init__(self, settings, store, gateway):
        self.settings, self.store, self.gateway = settings, store, gateway
        self._recovery_checked = False

    def once(self, now=None):
        from .production_readiness import require_production_evidence
        from .recovery import recovery_start_allowed
        if not recovery_start_allowed(self.store.path, deep=not self._recovery_checked):
            raise Review('restored_state_requires_reconciliation')
        self._recovery_checked = True
        require_production_evidence(self.settings)
        now = time.time() if now is None else now
        row = self.store.claim(now)
        if not row:
            return False
        try:
            self.process(row, now)
        except Temporary as exc:
            dead = row['attempts'] >= self.settings.max_attempts
            self.store.finish(row['id'], 'dead' if dead else 'queued', str(exc),
                              now + min(3600, 15 * 2 ** row['attempts']))
            self.store.issue('event:' + row['id'], str(exc), now)
        except (Review, Uncertain) as exc:
            self.store.finish(row['id'], 'review', str(exc))
            self.store.issue('event:' + row['id'], str(exc), now)
        except Exception:
            # Persist the failure, omit exception text (it can include URLs/PII).
            self.store.finish(row['id'], 'review', 'unexpected_worker_error')
            self.store.issue('event:' + row['id'], 'unexpected_worker_error', now)
        return True

    def process(self, row, now):
        event = json.loads(row['payload'])
        data = event['data']
        booking = data['id']
        if event.get('test') is True:
            self.store.finish(row['id'], 'test', 'buker_test_never_written')
            return
        # All signed non-test snapshots participate, including ignored employees.
        if not self.current(row):
            return
        source_employee = (data.get('employee') or {}).get('id')
        if not isinstance(source_employee, str) or not source_employee:
            raise Review('missing_employee_id')
        if source_employee not in self.settings.allowed_employees:
            self.store.finish(row['id'], 'ignored', 'employee_outside_allowlist')
            # A known source moving outside the allowlist needs immediate review.
            previous = self.store.rows('SELECT snapshot FROM links WHERE booking=? AND target IS NOT NULL', (booking,))
            if previous:
                snapshot = json.loads(previous[0]['snapshot']) if previous[0]['snapshot'] else {}
                self.store.issue('scope:' + booking, 'known_booking_moved_outside_allowlist', now,
                                 scope=affected_sources(self.settings, snapshot, data))
            return
        links = self.store.rows('SELECT * FROM links WHERE booking=?', (booking,))
        link = links[0] if links else None
        # Compare against all non-test accepted snapshots, including blocked events.
        newer = self.store.rows("SELECT id FROM events WHERE booking=? AND created>? AND json_extract(payload,'$.test')=0 AND id!=?",
                                (booking, row['created'], row['id']))
        if newer or (link and row['created'] < link['version']):
            self.store.finish(row['id'], 'stale', 'newer_snapshot_exists')
            return
        ties = self.store.rows("SELECT payload FROM events WHERE booking=? AND created=? AND id!=? AND json_extract(payload,'$.test')=0",
                               (booking, row['created'], row['id']))
        if any(json.loads(tie['payload'])['data'] != data for tie in ties):
            raise Review('equal_timestamp_conflicting_snapshots')
        if link and link['snapshot']:
            old = json.loads(link['snapshot'])
            if (old.get('employee') or {}).get('id') not in self.settings.allowed_employees:
                raise Review('cross_scope_employee_move')
        action = self.settings.action(data['status'], event['type'])
        if action == 'review':
            raise Review('status_requires_business_review')
        if action == 'wait':
            self.record(row, data, link['target'] if link else None, 'waiting')
            return
        if action == 'retain':
            self.record(row, data, link['target'] if link else None, 'no_show')
            return
        intents = self.store.rows('SELECT * FROM intents WHERE booking=?', (booking,))
        if intents and intents[0]['state'] != 'done':
            self.reconcile_intent(intents[0], now)
            intents = self.store.rows('SELECT * FROM intents WHERE booking=?', (booking,))
            if intents[0]['state'] != 'done':
                raise Review('unresolved_remote_intent')
            # Reload the mapping after recovery of a prior write.
            links = self.store.rows('SELECT * FROM links WHERE booking=?', (booking,))
            link = links[0] if links else link
        target = link['target'] if link else None
        if action == 'cancel':
            if target:
                current = self.gateway.detail(target)
                if current.get('status') != 'canceled':
                    if not self.current(row): return
                    self.intent(row, 'cancel', target, {}, [])
                    self.gateway.cancel(target)
                    if self.gateway.detail(target).get('status') != 'canceled':
                        raise Uncertain('cancel_readback_mismatch')
                    self.complete_intent(booking, target)
            self.record(row, data, target, 'canceled')
            return
        if target and link['state'] == 'canceled':
            raise Review('reactivation_requires_manual_review')
        employee = self.settings.target('employees', data.get('employee') or {})
        service = self.settings.target('services', data.get('service') or {})
        source_client = (data.get('customer') or {}).get('id')
        client = self.settings.clients.get(source_client)
        saved = self.store.rows('SELECT target FROM clients WHERE source=?', (source_client,))
        if saved:
            if client and client != saved[0]['target']:
                raise Review('client_mapping_changed')
            client = saved[0]['target']
        if not client or not self.settings.approvals.get('client_mapping'):
            raise Review('client_mapping_or_consent_missing')
        client = positive(client)
        if self.settings.mode == 'pilot' and (client not in self.settings.pilot_client_ids or service['id'] not in self.settings.pilot_service_ids):
            raise Review('pilot_client_or_service_outside_isolation')
        reverse = [k for k, value in self.settings.clients.items() if value == client and k != source_client]
        if reverse:
            raise Review('different_customers_share_target_client')
        reverse_saved = self.store.rows('SELECT source FROM clients WHERE target=? AND source!=?', (client, source_client))
        if reverse_saved:
            raise Review('different_customers_share_target_client')
        self.store.execute('INSERT OR IGNORE INTO clients VALUES(?,?)', (source_client, client))
        start, end = stamp(data.get('start_at')), stamp(data.get('end_at'))
        if end <= start or (end-start).total_seconds() != positive(data.get('duration')) * 60:
            raise Review('invalid_duration_or_bounds')
        horizon = datetime.fromtimestamp(now, UTC).astimezone(BELGRADE).date() + timedelta(days=self.settings.horizon_days)
        if start.astimezone(BELGRADE).date() >= horizon:
            raise Review('outside_supported_horizon')
        desired = {'service_id': service['id'], 'provider_id': employee['id'], 'client_id': client,
                   'start_datetime': company_time(data['start_at']), 'end_datetime': company_time(data['end_at']),
                   'count': 1}
        self.gateway.validate_booking(desired, data, service)
        if not target:
            baseline = self.gateway.bookings(desired['start_datetime'][:10], desired['end_datetime'][:10])
            if any(matches(b, desired) and b.get('status') != 'canceled' for b in baseline):
                raise Review('preexisting_exact_booking_requires_link_review')
            self.gateway.ensure_available(desired)
            if not self.current(row): return
            self.intent(row, 'create', None, desired, [b['id'] for b in baseline])
            target = self.gateway.create(desired)
            # Save the result before another network request; a crash can recover it.
            self.store.execute('UPDATE intents SET result=? WHERE booking=?', (target, booking))
            # Keep the source link before generating any ICS feed.
            self.store.execute('INSERT INTO links(booking,target) VALUES(?,?) ON CONFLICT(booking) DO UPDATE SET target=excluded.target', (booking, target))
            actual = self.gateway.detail(target)
            if not matches(actual, desired) or actual.get('status') != 'confirmed':
                self.observe_intent_scope(booking, actual)
                raise Uncertain('create_readback_mismatch_or_unconfirmed')
            self.complete_intent(booking, target)
        else:
            actual = self.gateway.detail(target)
            previous = self.store.get('applied:' + booking)[0]
            if previous and not matches(actual, previous) and not matches(actual, desired):
                raise Review('source_booking_edited_in_simplybook')
            if actual.get('status') == 'canceled':
                raise Review('source_booking_canceled_in_simplybook')
            if not matches(actual, desired):
                self.gateway.ensure_available(desired, target)
                if not self.current(row): return
                self.intent(row, 'edit', target, desired, [])
                self.gateway.edit(target, desired)
                readback = self.gateway.detail(target)
                if not matches(readback, desired):
                    self.observe_intent_scope(booking, readback)
                    raise Uncertain('edit_readback_mismatch')
                self.complete_intent(booking, target)
            if data['status'] == 1 and self.gateway.detail(target).get('status') == 'pending':
                if not self.current(row): return
                self.intent(row, 'approve', target, desired, [])
                self.gateway.approve(target)
                if self.gateway.detail(target).get('status') != 'confirmed':
                    raise Uncertain('approval_readback_mismatch')
                self.complete_intent(booking, target)
        self.store.put('applied:' + booking, desired, now)
        self.record(row, data, target, 'active')

    def current(self, row):
        head = self.store.rows('SELECT * FROM booking_heads WHERE booking=?', (row['booking'],))
        if head and row['created'] < head[0]['created']:
            self.store.finish(row['id'], 'stale', 'newer_snapshot_exists')
            return False
        if head and row['created'] == head[0]['created'] and head[0]['conflicted']:
            raise Review('equal_timestamp_conflicting_snapshots')
        return True

    def intent(self, row, kind, target, desired, baseline):
        previous = self.store.rows('SELECT snapshot FROM links WHERE booking=?', (row['booking'],))
        old = json.loads(previous[0]['snapshot']) if previous and previous[0]['snapshot'] else {}
        current = json.loads(row['payload'])['data']
        applied = self.store.get('applied:' + row['booking'])[0] or {}
        scope = affected_sources(self.settings, old, current,
                                 provider_ids=(desired.get('provider_id'), applied.get('provider_id')))
        now = time.time()
        with self.store.connect() as conn:
            conn.execute('INSERT OR REPLACE INTO intents VALUES(?,?,?,?,?,?,?,?,?)',
                         (row['booking'], row['id'], kind, target, json.dumps(desired), json.dumps(baseline),
                          'started', None, now))
            conn.execute('INSERT OR REPLACE INTO cache VALUES(?,?,?)',
                         ('feed-scope:intent:' + row['booking'], json.dumps(scope), now))

    def complete_intent(self, booking, target):
        self.store.execute("UPDATE intents SET state='done',result=? WHERE booking=?", (target, booking))
        self.store.execute('UPDATE issues SET resolved=1 WHERE key=?', ('intent:' + booking,))

    def observe_intent_scope(self, booking, actual):
        key = 'feed-scope:intent:' + booking
        old = self.store.get(key)[0]
        # Never narrow an unknown legacy scope; missing provider data is unknown.
        if not isinstance(old, list) or type(actual.get('provider_id')) is not int:
            self.store.put(key, None)
            return
        additional = affected_sources(self.settings, provider_ids=(actual['provider_id'],)) or []
        self.store.put(key, sorted(set(old + additional)))

    def record(self, row, data, target, state):
        old = self.store.rows('SELECT snapshot FROM links WHERE booking=?', (row['booking'],))
        self.store.execute('INSERT INTO links VALUES(?,?,?,?,?) ON CONFLICT(booking) DO UPDATE SET target=excluded.target,version=excluded.version,snapshot=excluded.snapshot,state=excluded.state',
                           (row['booking'], target, row['created'], json.dumps(data), state))
        self.store.finish(row['id'], 'done')
        self.store.execute('UPDATE issues SET resolved=1 WHERE key=?', ('event:' + row['id'],))
        self.store.execute('UPDATE issues SET resolved=1 WHERE key=?', ('scope:' + row['booking'],))
        # A successfully applied later snapshot supersedes older business reviews.
        # Ambiguous remote writes remain protected by their separate intent records.
        older = self.store.rows("SELECT id FROM events WHERE booking=? AND created<? AND state IN ('review','dead')",
                                (row['booking'], row['created']))
        for previous in older:
            self.store.finish(previous['id'], 'stale', 'superseded_by_applied_snapshot')
            self.store.execute('UPDATE issues SET resolved=1 WHERE key=?', ('event:' + previous['id'],))
        employees = {(data.get('employee') or {}).get('id')}
        if old and old[0]['snapshot']:
            employees.add((json.loads(old[0]['snapshot']).get('employee') or {}).get('id'))
        for employee in employees:
            if employee:
                # The owned copy is excluded from outbound occupancy. Recompute
                # first; unchanged feeds must not consume SrediMe's refresh quota.
                self.store.put('feed-recheck:' + employee, True)

    def reconcile_intent(self, intent, now):
        desired = json.loads(intent['desired'])
        target = intent['result'] or intent['target']
        if intent['kind'] == 'create':
            if not target:
                candidates = self.gateway.bookings(desired['start_datetime'][:10], desired['end_datetime'][:10])
                baseline = json.loads(intent['baseline'])
                ids = [b['id'] for b in candidates if b['id'] not in baseline and matches(b, desired) and b.get('status') != 'canceled']
                self.store.put('candidates:' + intent['booking'], ids, now)
                # No documented idempotency key or external source marker on REST.
                # Even one exact match could belong to another writer. Operator verifies ownership.
                raise Review('create_outcome_unknown_manual_link_required')
            actual = self.gateway.detail(target)
            if not matches(actual, desired) or actual.get('status') != 'confirmed':
                raise Review('create_result_requires_review')
            self.store.execute('INSERT INTO links(booking,target) VALUES(?,?) ON CONFLICT(booking) DO UPDATE SET target=excluded.target',
                               (intent['booking'], target))
        elif intent['kind'] == 'cancel':
            if self.gateway.detail(target).get('status') != 'canceled':
                raise Review('cancel_outcome_requires_review')
        elif intent['kind'] == 'approve':
            if self.gateway.detail(target).get('status') != 'confirmed':
                raise Review('approve_outcome_requires_review')
        elif not matches(self.gateway.detail(target), desired):
            raise Review('edit_outcome_requires_review')
        self.complete_intent(intent['booking'], target)

    def reconcile_all(self, now=None):
        now = time.time() if now is None else now
        for intent in self.store.rows("SELECT * FROM intents WHERE state!='done'"):
            try:
                self.reconcile_intent(intent, now)
                self.store.execute("UPDATE events SET state='queued',due=0 WHERE id=? AND state='review'", (intent['event'],))
            except (Review, Temporary) as exc:
                self.store.issue('intent:' + intent['booking'], str(exc), now)
