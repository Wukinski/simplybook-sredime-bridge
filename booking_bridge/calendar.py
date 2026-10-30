"""Private, PII-free ICS generated ONLY from SimplyBook source snapshots."""
import hashlib
import json
import time
from datetime import datetime, timedelta

from icalendar import Calendar, Event

from .model import BELGRADE, UTC, Review, local_stamp, stamp


def bounds(now, days=60):
    today = datetime.fromtimestamp(now, UTC).astimezone(BELGRADE).date()
    start = datetime.combine(today - timedelta(days=1), datetime.min.time(), BELGRADE).astimezone(UTC)
    end = datetime.combine(today + timedelta(days=days), datetime.min.time(), BELGRADE).astimezone(UTC)
    return start, end


def event_uid(kind, identifier):
    return hashlib.sha256(f'{kind}:{identifier}'.encode()).hexdigest() + '@andjelija-connector'


def feed_version(body):
    """Occupancy version independent of changing DTSTAMP or component order."""
    events = Calendar.from_ical(body).walk('VEVENT')
    state = sorted((str(e['UID']), str(e['DTSTART']), str(e['DTEND'])) for e in events)
    return hashlib.sha256(json.dumps(state).encode()).hexdigest()


def period(day, value):
    if not isinstance(value, str):
        raise Review('invalid_calendar_period')
    if len(value) <= 8:
        if value.startswith('24:00'):
            return local_stamp(str(datetime.fromisoformat(day).date() + timedelta(days=1)) + ' 00:00:00')
        return local_stamp(day + ' ' + value)
    return local_stamp(value)


def schedule_blocks(columns, start, end, provider):
    result = []
    covered = set()
    for day, column in columns.items():
        lo = local_stamp(day + ' 00:00:00')
        hi = local_stamp(str(datetime.fromisoformat(day).date() + timedelta(days=1)) + ' 00:00:00')
        if hi <= start or lo >= end:
            continue
        covered.add(day)
        if type(column.get('is_day_off')) is not bool:
            raise Review('calendar_day_off_missing')
        if column['is_day_off']:
            result.append((event_uid('off', f'{provider}:{day}'), lo, hi))
            continue
        opening, closing = period(day, column.get('from')), period(day, column.get('to'))
        if closing <= opening or opening < lo or closing > hi:
            raise Review('unsupported_work_schedule')
        if opening > lo:
            result.append((event_uid('before', f'{provider}:{day}'), lo, opening))
        if closing < hi:
            result.append((event_uid('after', f'{provider}:{day}'), closing, hi))
        for kind in ('breaktimes', 'blocked', 'notes'):
            values = column.get(kind)
            if not isinstance(values, list):
                raise Review('missing_calendar_block_collection')
            for item in values:
                if kind == 'notes':
                    if item.get('time_blocked') is not True:
                        continue
                    if item.get('service_id') and not item.get('provider_id'):
                        raise Review('service_only_block_requires_resource_review')
                    if item.get('provider_id') not in (None, 0, provider):
                        continue
                first, last = period(day, item.get('from')), period(day, item.get('to'))
                if last <= first:
                    raise Review('invalid_calendar_block_bounds')
                uid = event_uid(kind, f'{provider}:{day}:{item.get("id", "")}:{first.isoformat()}:{last.isoformat()}')
                result.append((uid, first, last))
    expected = set()
    day = start.astimezone(BELGRADE).date()
    while day < end.astimezone(BELGRADE).date():
        expected.add(str(day))
        day += timedelta(days=1)
    if not expected.issubset(covered):
        raise Review('incomplete_schedule_coverage')
    return result


def make_feed(settings, store, employee, now=None):
    now = time.time() if now is None else now
    if employee not in settings.allowed_employees or employee not in settings.employees:
        raise Review('feed_employee_not_enabled')
    provider = settings.employees[employee]['id']
    bookings, updated = store.get('bookings')
    schedules, schedule_at = store.get('schedule:' + employee)
    if bookings is None or now - updated > settings.snapshot_max_age:
        raise Review('booking_snapshot_stale')
    if schedules is None or now - schedule_at > settings.schedule_max_age:
        raise Review('schedule_snapshot_stale')
    # An unowned create could otherwise come back as a second block.
    def affects(key):
        scope = store.get('feed-scope:' + key)[0]
        # Legacy/unknown scope keeps the global safety fence.
        return not isinstance(scope, list) or not scope or employee in scope
    for intent in store.rows("SELECT booking FROM intents WHERE state!='done'"):
        if affects('intent:' + intent['booking']):
            raise Review('feed_paused_for_uncertain_mutation')
    for issue in store.rows("SELECT key FROM issues WHERE resolved=0 AND (key LIKE 'drift:%' OR key LIKE 'scope:%')"):
        if affects(issue['key']):
            raise Review('feed_paused_for_source_drift')
    start, end = bounds(now, settings.horizon_days)
    blocks = schedule_blocks(schedules, start, end, provider)
    linked = {r['target'] for r in store.rows('SELECT target FROM links WHERE target IS NOT NULL')}
    buffers, buffer_at = store.get('buffers')
    if buffers is None or now - buffer_at > settings.schedule_max_age:
        raise Review('service_buffers_stale')
    for booking in bookings:
        if booking.get('provider_id') != provider or booking['id'] in linked:
            continue
        status = booking.get('status')
        if status == 'canceled':
            continue  # SrediMe import ignores STATUS. Remove the VEVENT entirely.
        if status not in ('confirmed', 'pending'):
            raise Review('unknown_simplybook_booking_status')
        first, last = local_stamp(booking['start_datetime']), local_stamp(booking['end_datetime'])
        service_key = str(booking.get('service_id'))
        if service_key not in buffers:
            raise Review('unknown_simplybook_service_buffer')
        after = buffers[service_key]
        if type(after) is not int or after < 0:
            raise Review('invalid_simplybook_service_buffer')
        last += timedelta(minutes=after)
        if last <= first:
            raise Review('invalid_simplybook_booking_bounds')
        blocks.append((event_uid('sb-booking', booking['id']), first, last))
    calendar = Calendar()
    calendar.add('prodid', '-//Studio Andjelija SG//Private Availability//SR')
    calendar.add('version', '2.0')
    calendar.add('x-wr-timezone', 'Europe/Belgrade')
    seen = set()
    for uid, first, last in sorted(blocks):
        if last <= start or first >= end or uid in seen:
            continue
        seen.add(uid)
        item = Event()
        item.add('uid', uid)
        item.add('dtstamp', datetime.fromtimestamp(updated, UTC))
        item.add('dtstart', max(first, start).astimezone(UTC))
        item.add('dtend', min(last, end).astimezone(UTC))
        item.add('summary', 'Zauzeto')
        calendar.add_component(item)
    return calendar.to_ical(), len(seen)


def parse_sredime_feed(body):
    if len(body) > 5_000_000:
        raise Review('source_calendar_too_large')
    try:
        calendar = Calendar.from_ical(body)
        if calendar.name != 'VCALENDAR' or str(calendar.get('version')) != '2.0':
            raise ValueError()
        result = []
        seen = set()
        for component in calendar.walk('VEVENT'):
            if any(key in component for key in ('RRULE', 'RECURRENCE-ID', 'RDATE', 'EXDATE')):
                raise Review('unexpected_source_recurrence')
            uid = str(component['UID'])
            if not uid or uid in seen:
                raise ValueError()
            seen.add(uid)
            first, last = component.decoded('DTSTART'), component.decoded('DTEND')
            if not isinstance(first, datetime) or not isinstance(last, datetime) or first.utcoffset() is None or last.utcoffset() is None:
                raise ValueError()
            # Export is documented as Europe/Belgrade. Verify timezone fold/gap.
            first, last = first.astimezone(UTC), last.astimezone(UTC)
            if last <= first:
                raise ValueError()
            modified = component.decoded('LAST-MODIFIED', component.decoded('DTSTAMP', None))
            if not isinstance(modified, datetime) or modified.utcoffset() is None:
                raise ValueError()
            status = str(component.get('STATUS', ''))
            if status not in ('CONFIRMED', 'TENTATIVE', 'CANCELLED'):
                raise ValueError()
            result.append({'uid': uid, 'start': first.isoformat(), 'end': last.isoformat(),
                           'modified': modified.astimezone(UTC).isoformat(),
                           'sequence': int(component.get('SEQUENCE', 0)), 'status': status,
                           'service_external_id': str(component.get('X-SERVICE-ID', ''))})
        return result
    except Review:
        raise
    except Exception:
        raise Review('invalid_source_calendar') from None


def reconcile_feed(store, employee, body, now=None):
    """Calendar evidence is never sufficient to create clients or infer every status."""
    now = time.time() if now is None else now
    items = parse_sredime_feed(body)
    previous = store.get('source-feed:' + employee)[0] or {}
    for item in items:
        old = previous.get(item['uid'])
        if old and (stamp(item['modified']) < stamp(old['modified']) or item['sequence'] < old['sequence']):
            continue
        previous[item['uid']] = item
        issue_key = 'ics:' + employee + ':' + hashlib.sha256(item['uid'].encode()).hexdigest()
        binding = store.rows('SELECT booking FROM source_bindings WHERE employee=? AND uid=?', (employee, item['uid']))
        link = store.rows('SELECT snapshot FROM links WHERE booking=?', (binding[0]['booking'],)) if binding else []
        consistent = False
        if link and link[0]['snapshot']:
            source = json.loads(link[0]['snapshot'])
            status = source['status']
            exported_status = 'CONFIRMED' if status > 0 else ('TENTATIVE' if status == 0 else 'CANCELLED')
            try:
                consistent = (stamp(source['start_at']) == stamp(item['start'])
                              and stamp(source['end_at']) == stamp(item['end'])
                              and exported_status == item['status']
                              and source.get('employee', {}).get('id') == employee)
            except (KeyError, Review):
                pass
        if consistent:
            store.execute('UPDATE issues SET resolved=1 WHERE key=?', (issue_key,))
        else:
            store.issue(issue_key, 'calendar_change_requires_webhook_or_manual_review', now)
    # Missing items are deliberately retained: rolling window/move is not deletion.
    store.put('source-feed:' + employee, previous, now)
    return len(items)
