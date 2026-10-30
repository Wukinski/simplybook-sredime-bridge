import ipaddress
import json
import socket
import time
from datetime import datetime, timedelta
from urllib.parse import urlsplit

import requests

from .calendar import bounds, feed_version, make_feed, reconcile_feed
from .model import BELGRADE, UTC, Review, Temporary, affected_sources
from .worker import matches


def private_request(url, method='GET'):
    """Configured secret URLs only; reject redirects and internal network targets."""
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.port not in (None, 443) or parsed.username or parsed.password or parsed.fragment:
        raise Review('invalid_private_endpoint')
    try:
        addresses = socket.getaddrinfo(parsed.hostname, 443)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise Review('private_endpoint_resolves_to_internal_address')
        with requests.request(method, url, timeout=(3, 5), allow_redirects=False, stream=True) as response:
            if not 200 <= response.status_code < 300:
                raise Temporary('private_endpoint_failed')
            body = bytearray()
            for chunk in response.iter_content(65536):
                body.extend(chunk)
                if len(body) > 5_000_000:
                    raise Review('private_response_too_large')
            if method == 'GET' and 'text/calendar' not in response.headers.get('Content-Type', '').lower():
                raise Review('private_endpoint_not_calendar')
            if method == 'POST':
                value = json.loads(body)
                if value.get('success') is not True or value.get('refresh_scheduled') is not True:
                    raise Temporary('refresh_not_scheduled')
            return bytes(body)
    except (requests.RequestException, OSError, ValueError):
        raise Temporary('private_endpoint_unavailable') from None


class Scheduler:
    def __init__(self, settings, store, gateway, worker, request=private_request, clock=None):
        self.settings, self.store, self.gateway, self.worker = settings, store, gateway, worker
        self.request = request
        self.clock = clock

    def moment(self, supplied):
        return self.clock() if self.clock else supplied

    def due(self, key, seconds, now):
        return now - self.store.get('task:' + key)[1] >= seconds

    def run_task(self, key, seconds, now, function, *, accelerated=False):
        failed = key != 'schedule-step' and bool(self.store.rows(
            'SELECT 1 FROM issues WHERE key=? AND resolved=0', ('task:' + key,)))
        interval = min(seconds, 10) if failed or accelerated else seconds
        if not self.due(key, interval, now):
            return
        fallback = self.due(key, seconds, now)
        if failed and not fallback and self.store.rate_available_at('task-recovery:' + key, 12, now=now) > now:
            return
        if key == 'bookings' and not fallback and not self.store.rate('sb-accelerated-snapshots', 60, now=now):
            return
        if failed and not fallback and not self.store.rate('task-recovery:' + key, 12, now=now):
            return
        # Persist attempt time too, to bound retry traffic across restarts.
        self.store.put('task:' + key, 'attempted', now)
        try:
            if function() is not False:
                self.store.execute('UPDATE issues SET resolved=1 WHERE key=?', ('task:' + key,))
        except (Review, Temporary) as exc:
            if key == 'schedule-step':
                self.store.put('schedule-backoff', True, now)
            self.store.issue('task:' + key, str(exc), now)
        except Exception:
            if key == 'schedule-step':
                self.store.put('schedule-backoff', True, now)
            self.store.issue('task:' + key, 'unexpected_scheduler_error', now)

    def tick(self, now=None):
        now = time.time() if now is None else now
        self.store.put('heartbeat', True, now)
        if self.settings.reads_enabled:
            self.recheck_feeds(now)
            hint_at = self.store.get('sb-change-hint')[1]
            hinted = hint_at > self.store.get('bookings-hint-applied')[1]
            # Cap accelerated full snapshots as well as the shared transport quota.
            # Keep the hint pending if this allowance is exhausted.
            self.run_task('bookings', 300, now, lambda: self.snapshot_bookings(now), accelerated=hinted)
            # Notify promptly before lower-priority inventory/schedule work.
            self.refresh_source(self.moment(now))
            self.run_task('buffers', 3600, self.moment(now), lambda: self.snapshot_buffers(self.moment(now)))
            self.run_task('schedule-step', 1, self.moment(now), lambda: self.schedule_step(self.moment(now)))
            self.run_task('intents', 300, now, lambda: self.worker.reconcile_all(now))
            self.poll_source(self.moment(now))
        self.monitor(self.moment(now))

    def snapshot_bookings(self, now):
        hint_at = self.store.get('sb-change-hint')[1]
        # Read callbacks may process source events between inventory pages.
        owned = [(link, self.store.get('applied:' + link['booking'])[0])
                 for link in self.store.rows('SELECT * FROM links WHERE target IS NOT NULL')]
        first, last = bounds(now, self.settings.horizon_days)
        data = self.gateway.bookings(str(first.astimezone(BELGRADE).date()), str(last.astimezone(BELGRADE).date()))
        self.store.put('bookings', data, now)
        by_id = {b['id']: b for b in data}
        for link, applied in owned:
            actual = by_id.get(link['target'])
            # An absent booking may be outside the range. Only detail can confirm state.
            if actual is None and applied:
                actual = self.gateway.detail(link['target'])
            if applied and actual:
                canceled = actual.get('status') == 'canceled'
                expected_canceled = link['state'] == 'canceled'
                drifted = canceled != expected_canceled or (not canceled and not matches(actual, applied))
                snapshot = json.loads(link['snapshot']) if link['snapshot'] else {}
                self.store.check_drift(link, applied, drifted,
                    affected_sources(self.settings, snapshot,
                        provider_ids=(applied.get('provider_id'), actual.get('provider_id'))), self.moment(now))
        # Notify old AND new employees only after a complete new ICS is available.
        for employee in self.settings.allowed_employees:
            self.queue_if_feed_changed(employee, self.moment(now))
        self.store.put('bookings-hint-applied', True, hint_at)

    def recheck_feeds(self, now):
        for employee in self.settings.allowed_employees:
            requested = self.store.get('feed-recheck:' + employee)[1]
            if requested > self.store.get('task:feed-recheck:' + employee)[1]:
                if self.queue_if_feed_changed(employee, self.moment(now)):
                    self.store.put('task:feed-recheck:' + employee, True, requested)

    def snapshot_buffers(self, now):
        services = self.gateway.services()
        values = {}
        for service in services:
            buffer = service.get('buffer_time_after')
            if type(buffer) is not int or buffer < 0:
                raise Review('service_buffer_contract_unverified')
            values[str(service['id'])] = buffer
        self.store.put('buffers', values, now)

    def schedule_step(self, now):
        """One provider-reference or calendar-week read per tick, durable on restart.

        Only complete snapshots replace published data. Near-week merges retain
        the full snapshot's original age, so stale distant dates never look fresh.
        """
        if now - self.store.get('schedule-backoff')[1] < 60:
            return False
        first, last = bounds(now, self.settings.horizon_days)
        start, end = first.astimezone(BELGRADE).date(), last.astimezone(BELGRADE).date()
        week = start - timedelta(days=start.weekday())
        employees = list(self.settings.allowed_employees)
        employees.sort(key=lambda e: (
            not (self.store.get('schedule-request:' + e)[1] > self.store.get('schedule:' + e)[1]),
            self.store.get('schedule:' + e)[1]))
        for employee in employees:
            mapping = self.settings.employees.get(employee)
            if not mapping:
                raise Review('unmapped_schedule_employee')
            service = self.settings.schedule_service_ids.get(employee)
            if not service or not self.settings.approvals.get('schedule_reference_verified'):
                raise Review('neutral_schedule_reference_service_required')
            old, old_at = self.store.get('schedule:' + employee)
            request_at = self.store.get('schedule-request:' + employee)[1]
            key = 'schedule-job:' + employee
            job = self.store.get(key)[0]
            # Midnight changes the coverage horizon. Never publish yesterday's job.
            if job and (job['end'] != str(end) or job.get('provider') != mapping['id'] or
                        job.get('service') != service or now - job['started'] > self.settings.schedule_max_age):
                self.store.execute('DELETE FROM cache WHERE key=?', (key,))
                job = None
            full = old is None or now - old_at >= 3600 or request_at > old_at
            if not job:
                if not full and now - self.store.get('schedule-near:' + employee)[1] < 900:
                    continue
                scan_end = end if full else min(end, week + timedelta(days=14))
                last_week_end = scan_end + timedelta(days=(6-scan_end.weekday()) % 7)
                reference = self.gateway.provider_schedule(mapping['id'], service, week, last_week_end)
                job = {'end': str(end), 'scan_end': str(scan_end), 'cursor': str(week),
                       'reference': reference, 'columns': {}, 'started': now, 'full': full,
                       'provider': mapping['id'], 'service': service}
                self.store.put(key, job, now)
                return
            cursor = datetime.fromisoformat(job['cursor']).date()
            try:
                job['columns'].update(self.gateway.calendar_week(mapping['id'], cursor, job['reference']))
            except (Review, Temporary):
                # Re-read reference evidence after a rejected/failed calendar page.
                self.store.execute('DELETE FROM cache WHERE key=?', (key,))
                raise
            job['cursor'] = str(cursor + timedelta(days=7))
            if job['cursor'] < job['scan_end']:
                self.store.put(key, job, now)
                return
            columns = job['columns'] if job['full'] else {**(old or {}), **job['columns']}
            from .calendar import schedule_blocks
            try:
                schedule_blocks(columns, first, last, mapping['id'])
            except Review:
                self.store.execute('DELETE FROM cache WHERE key=?', (key,))
                raise
            self.store.put('schedule:' + employee, columns, job['started'] if job['full'] else old_at)
            self.store.put('schedule-near:' + employee, True, job['started'])
            self.store.execute('DELETE FROM cache WHERE key=?', (key,))
            self.queue_if_feed_changed(employee, now)
            return
        return False

    def queue_if_feed_changed(self, employee, now):
        try:
            body, count = make_feed(self.settings, self.store, employee, now)
            # DTSTAMP changes do not represent a change of occupancy.
            digest = feed_version(body)
            self.store.publish_feed(employee, digest, count, self.moment(now))
            if count == 0:
                self.store.issue('empty-out:' + employee, 'empty_outbound_feed_support_check_required', now)
            else:
                self.store.execute('UPDATE issues SET resolved=1 WHERE key=?', ('empty-out:' + employee,))
            return True
        except Review:
            return False

    def poll_source(self, now):
        for employee, url in self.settings.export_urls.items():
            if employee not in self.settings.allowed_employees:
                continue
            rows = self.store.rows('SELECT * FROM feed_health WHERE employee=?', (employee,))
            row = rows[0] if rows else {'failures': 0, 'due': 0, 'last_ok': None, 'state': 'new'}
            if row['state'] == 'stopped' or row['due'] > now:
                continue
            if not self.store.rate('sredime-get:' + employee, 12, now=now):
                continue
            try:
                self.worker.once()
                now = self.moment(now)
                self.recheck_feeds(now)
                self.refresh_source(now)
                now = self.moment(now)
                body = self.request(url)
                count = reconcile_feed(self.store, employee, body, now)
                if count == 0:
                    raise Temporary('empty_source_feed')
                self.store.execute('INSERT OR REPLACE INTO feed_health VALUES(?,0,?,?,?)', (employee, now+900, now, 'ok'))
                self.store.execute('UPDATE issues SET resolved=1 WHERE key=?', ('source:' + employee,))
            except (Review, Temporary) as exc:
                failures = row['failures'] + 1
                delay = min(43200, 900 * 2 ** min(6, failures))
                state = 'stopped' if failures >= 100 else 'backoff'
                self.store.execute('INSERT OR REPLACE INTO feed_health VALUES(?,?,?,?,?)',
                                   (employee, failures, now + delay, row['last_ok'], state))
                self.store.issue('source:' + employee, str(exc), now)

    def refresh_source(self, now):
        if self.settings.mode == 'simulation' or not self.settings.approvals.get('sredime_refresh'):
            return
        for row in self.store.rows('SELECT * FROM refresh WHERE due<=?', (now,)):
            now = self.moment(now)
            employee = row['employee']
            url = self.settings.export_urls.get(employee)
            if not url or employee not in self.settings.allowed_employees:
                continue
            try:
                self.worker.once()
                now = self.moment(now)
                self.recheck_feeds(now)
                # Verify that SrediMe can now fetch a complete, fresh feed.
                body, count = make_feed(self.settings, self.store, employee, now)
                version = feed_version(body)
                now = self.moment(now)
                self.store.publish_feed(employee, version, count, now)
                observation = self.store.latest_feed_observation(employee, version)
                last_attempt = self.store.get('refresh-attempt:' + employee)[1]
                interval = self.settings.refresh_coalesce_seconds
                if last_attempt and now - last_attempt < interval:
                    self.store.execute('UPDATE refresh SET due=? WHERE employee=?', (last_attempt + interval, employee))
                    continue
                if not self.store.rate('sredime-post:' + employee, 60, now=now):
                    due = self.store.rate_available_at('sredime-post:' + employee, 60, now=now)
                    self.store.execute('UPDATE refresh SET due=? WHERE employee=?', (due, employee))
                    self.store.issue('refresh-quota:' + employee, 'refresh_hourly_quota_exhausted', now)
                    continue
                generation = self.store.get('refresh-generation:' + employee)[0]
                self.store.put('refresh-attempt:' + employee, True, now)
                self.request(url, 'POST')
                completed = self.moment(now)
                self.store.complete_refresh(employee, generation, completed, interval)
                if observation:
                    self.store.execute('UPDATE availability_observations SET scheduled=COALESCE(scheduled,?) WHERE id=?',
                                       (completed, observation))
                self.store.put('refresh-scheduled:' + employee, True, completed)
                self.store.put('refresh-failures:' + employee, 0, completed)
                self.store.execute('UPDATE issues SET resolved=1 WHERE key=?', ('refresh:' + employee,))
                self.store.execute('UPDATE issues SET resolved=1 WHERE key=?', ('refresh-quota:' + employee,))
            except (Review, Temporary) as exc:
                delay = self.settings.refresh_coalesce_seconds
                if isinstance(exc, Temporary):
                    failures = self.store.get('refresh-failures:' + employee)[0]
                    failures = (failures if type(failures) is int else 0) + 1
                    self.store.put('refresh-failures:' + employee, failures, self.moment(now))
                    delay = min(120, delay * 2 ** min(failures-1, 5))
                self.store.execute('UPDATE refresh SET due=? WHERE employee=?', (self.moment(now) + delay, employee))
                self.store.issue('refresh:' + employee, str(exc), now)

    def monitor(self, now):
        aged = self.store.rows("SELECT COUNT(*) AS n FROM events WHERE state IN ('queued','working') AND received<?", (now - 10,))[0]['n']
        if aged:
            self.store.issue('queue-age', 'webhook_processing_delayed', now)
        else:
            self.store.execute("UPDATE issues SET resolved=1 WHERE key='queue-age'")
        if self.settings.reads_enabled:
            for employee in self.settings.allowed_employees:
                try:
                    make_feed(self.settings, self.store, employee, now)
                    self.store.execute('UPDATE issues SET resolved=1 WHERE key=?', ('feed:' + employee,))
                except Review as exc:
                    self.store.issue('feed:' + employee, str(exc), now)
                latest = self.store.rows('SELECT ready,fetched FROM availability_observations WHERE employee=? ORDER BY id DESC LIMIT 1', (employee,))
                if latest and latest[0]['fetched'] is None and now - latest[0]['ready'] >= 60:
                    self.store.issue('availability-fetch:' + employee, 'latest_feed_fetch_not_observed_within_60s', now)
                else:
                    self.store.execute('UPDATE issues SET resolved=1 WHERE key=?', ('availability-fetch:' + employee,))
        issues = self.store.rows('SELECT key,reason FROM issues WHERE resolved=0 ORDER BY key')
        self.store.put('health', {'open_issues': len(issues), 'old_queued': aged}, now)
        if issues and self.settings.alerts_url and self.due('alert', 900, now):
            self.store.put('task:alert', True, now)
            # Generic alert, never raw payloads, client data, URLs, or credentials.
            try:
                parsed = urlsplit(self.settings.alerts_url)
                if parsed.scheme != 'https' or not parsed.hostname:
                    raise ValueError()
                response = requests.post(self.settings.alerts_url,
                    json={'service': 'andjelija-booking-bridge', 'open_issues': len(issues),
                          'action': 'Check the authenticated operations endpoint'},
                    timeout=(3, 5), allow_redirects=False)
                if not 200 <= response.status_code < 300:
                    raise ValueError()
                self.store.execute("UPDATE issues SET resolved=1 WHERE key='alerts'")
            except (requests.RequestException, ValueError):
                self.store.issue('alerts', 'alert_delivery_failed', now)
