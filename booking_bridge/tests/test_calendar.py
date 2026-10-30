import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from icalendar import Calendar, Event

from booking_bridge.api import create_app
from booking_bridge.calendar import bounds, make_feed, parse_sredime_feed, reconcile_feed, schedule_blocks
from booking_bridge.model import BELGRADE, UTC, Review, stamp
from booking_bridge.scheduler import Scheduler


def prime(settings, store, now, bookings=None):
    first, last = bounds(now, settings.horizon_days)
    day = first.astimezone(BELGRADE).date()
    columns = {}
    while day < last.astimezone(BELGRADE).date():
        columns[str(day)] = {'date': str(day), 'from': '00:00:00', 'to': '24:00:00',
                             'is_day_off': False, 'breaktimes': [], 'blocked': [], 'notes': []}
        day += timedelta(days=1)
    for employee in settings.allowed_employees:
        store.put('schedule:' + employee, columns, now)
    store.put('bookings', bookings or [], now)
    store.put('buffers', {'91': 10, '92': 0}, now)
    return columns


def booking(**kwargs):
    result = {'id': 1005, 'provider_id': 81, 'service_id': 91, 'client_id': 71, 'status': 'confirmed',
              'start_datetime': '2026-10-23 10:00:00', 'end_datetime': '2026-10-23 11:00:00',
              'client_name': 'DO NOT EXPORT', 'client_email': 'private@example.invalid'}
    result.update(kwargs)
    return result


def source_calendar(status='CONFIRMED', uid='opaque-source-uid', modified='2026-10-21T09:00:00Z'):
    calendar = Calendar(); calendar.add('version', '2.0'); calendar.add('prodid', '-//Synthetic//EN')
    event = Event(); event.add('uid', uid); event.add('summary', 'SOURCE SUMMARY DO NOT REPUBLISH')
    event.add('dtstart', datetime(2026, 10, 23, 10, tzinfo=BELGRADE))
    event.add('dtend', datetime(2026, 10, 23, 11, tzinfo=BELGRADE))
    event.add('dtstamp', stamp(modified)); event.add('last-modified', stamp(modified)); event.add('status', status)
    calendar.add_component(event)
    return calendar.to_ical()


def test_feed_is_private_minimal_and_applies_cleanup(settings, store, now):
    prime(settings, store, now, [booking()])
    body, count = make_feed(settings, store, 'synthetic-employee-A', now)
    assert count == 1 and b'\r\n' in body
    assert b'DO NOT EXPORT' not in body and b'private@example' not in body
    items = Calendar.from_ical(body).walk('VEVENT')
    assert str(items[0]['SUMMARY']) == 'Zauzeto'
    assert items[0].decoded('DTSTART') == stamp('2026-10-23T08:00:00Z')
    assert items[0].decoded('DTEND') == stamp('2026-10-23T09:10:00Z')
    body2, _ = make_feed(settings, store, 'synthetic-employee-A', now+1)
    assert body == body2


def test_loop_exclusion_survives_move_and_cancellation(settings, store, now):
    store.execute("INSERT INTO links VALUES('source',1005,0,NULL,'active')")
    prime(settings, store, now, [booking(provider_id=82)])
    assert make_feed(settings, store, 'synthetic-employee-B', now)[1] == 0
    store.execute("UPDATE links SET state='canceled'")
    store.put('bookings', [booking(status='canceled')], now)
    assert make_feed(settings, store, 'synthetic-employee-A', now)[1] == 0


def test_canceled_event_removed_entirely_not_status_canceled(settings, store, now):
    prime(settings, store, now, [booking(status='canceled')])
    body, count = make_feed(settings, store, 'synthetic-employee-A', now)
    assert count == 0 and b'BEGIN:VEVENT' not in body
    assert b'STATUS:CANCELLED' not in body


def test_all_source_ids_excluded_even_if_wrong_employee(settings, store, now):
    store.execute("INSERT INTO links VALUES('source',1005,0,NULL,'canceled')")
    prime(settings, store, now, [booking(provider_id=82)])
    assert make_feed(settings, store, 'synthetic-employee-B', now)[1] == 0


@pytest.mark.parametrize('problem', ['booking_stale', 'schedule_stale', 'missing_day', 'unknown_buffer', 'unknown_status', 'uncertain', 'drift'])
def test_incomplete_or_uncertain_feed_fails_closed(settings, store, now, problem):
    columns = prime(settings, store, now, [booking()])
    if problem == 'booking_stale': store.put('bookings', [booking()], now-901)
    if problem == 'schedule_stale': store.put('schedule:synthetic-employee-A', columns, now-4501)
    if problem == 'missing_day':
        columns.pop('2026-10-23'); store.put('schedule:synthetic-employee-A', columns, now)
    if problem == 'unknown_buffer': store.put('buffers', {}, now)
    if problem == 'unknown_status': store.put('bookings', [booking(status='process')], now)
    if problem == 'uncertain': store.execute("INSERT INTO intents VALUES('x','e','create',NULL,'{}','[]','started',NULL,0)")
    if problem == 'drift': store.issue('drift:source', 'source_booking_changed', now)
    with pytest.raises(Review): make_feed(settings, store, 'synthetic-employee-A', now)


def test_break_day_off_manual_block_and_nonworking_hours(settings, store, now):
    columns = prime(settings, store, now)
    columns['2026-10-23'].update({'from': '09:00:00', 'to': '18:00:00',
        'breaktimes': [{'from': '12:00:00', 'to': '12:30:00'}],
        'blocked': [{'from': '14:00:00', 'to': '15:00:00'}],
        'notes': [{'id': 1, 'provider_id': 81, 'time_blocked': True, 'from': '16:00:00', 'to': '17:00:00', 'note': 'PRIVATE'}]})
    columns['2026-10-24']['is_day_off'] = True
    store.put('schedule:synthetic-employee-A', columns, now)
    body, count = make_feed(settings, store, 'synthetic-employee-A', now)
    assert count == 6
    assert b'PRIVATE' not in body


def test_dst_day_length_is_25_hours_for_day_off(settings, store):
    now = stamp('2026-10-25T12:00:00+01:00').timestamp()
    columns = prime(settings, store, now)
    columns['2026-10-25']['is_day_off'] = True
    store.put('schedule:synthetic-employee-A', columns, now)
    body, count = make_feed(settings, store, 'synthetic-employee-A', now)
    event = Calendar.from_ical(body).walk('VEVENT')[0]
    assert (event.decoded('DTEND')-event.decoded('DTSTART')).total_seconds() == 25*3600


def test_range_intersection_and_cutoff(settings, store, now):
    first, last = bounds(now)
    before = booking(id=1, start_datetime=(first-timedelta(hours=2)).astimezone(BELGRADE).strftime('%Y-%m-%d %H:%M:%S'),
                     end_datetime=(first-timedelta(hours=1)).astimezone(BELGRADE).strftime('%Y-%m-%d %H:%M:%S'))
    beyond = booking(id=2, start_datetime=last.astimezone(BELGRADE).strftime('%Y-%m-%d %H:%M:%S'),
                     end_datetime=(last+timedelta(hours=1)).astimezone(BELGRADE).strftime('%Y-%m-%d %H:%M:%S'))
    prime(settings, store, now, [before, beyond, booking()])
    assert make_feed(settings, store, 'synthetic-employee-A', now)[1] == 1


def test_empty_feed_is_valid_and_never_invents_appointments(settings, store, now):
    prime(settings, store, now)
    body, count = make_feed(settings, store, 'synthetic-employee-A', now)
    assert count == 0 and len(Calendar.from_ical(body).walk('VEVENT')) == 0


def test_source_feed_not_republished_and_missing_is_not_cancel(store, now):
    assert reconcile_feed(store, 'employee', source_calendar(), now) == 1
    assert reconcile_feed(store, 'employee', b'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:TEST\r\nEND:VCALENDAR\r\n', now+10) == 0
    snapshot = store.get('source-feed:employee')[0]
    assert len(snapshot) == 1
    assert 'SOURCE SUMMARY' not in json.dumps(snapshot)


def test_source_cancelled_is_evidence_for_review_not_delete(store, now):
    reconcile_feed(store, 'employee', source_calendar('CANCELLED'), now)
    assert store.get('source-feed:employee')[0]['opaque-source-uid']['status'] == 'CANCELLED'
    assert not store.rows('SELECT * FROM links')
    assert store.rows('SELECT * FROM issues WHERE resolved=0')


def test_source_older_update_does_not_overwrite_newer(store, now):
    reconcile_feed(store, 'employee', source_calendar('CONFIRMED', modified='2026-10-21T10:00:00Z'), now)
    reconcile_feed(store, 'employee', source_calendar('CANCELLED', modified='2026-10-20T10:00:00Z'), now+1)
    assert store.get('source-feed:employee')[0]['opaque-source-uid']['status'] == 'CONFIRMED'


@pytest.mark.parametrize('data', [b'', b'not ICS', b'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:a\r\nEND:VEVENT\r\nEND:VCALENDAR'])
def test_invalid_source_feed(data):
    with pytest.raises(Review): parse_sredime_feed(data)


def test_empty_source_backoff_stops_after_100_and_survives_restart(settings, store, gateway, worker, now):
    settings.export_urls = {'synthetic-employee-A': 'https://example.invalid/private'}
    calls = []
    empty = b'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:TEST\r\nEND:VCALENDAR\r\n'
    def get(url, method='GET'):
        calls.append(method); return empty
    scheduler = Scheduler(settings, store, gateway, worker, request=get)
    scheduler.poll_source(now)
    row = store.rows('SELECT * FROM feed_health')[0]
    assert row['failures'] == 1 and row['due'] == now + 1800
    scheduler.poll_source(now+1); assert len(calls) == 1
    store.execute('UPDATE feed_health SET failures=99,due=0')
    scheduler.poll_source(now+3600)
    assert store.rows('SELECT * FROM feed_health')[0]['state'] == 'stopped'
    Scheduler(settings, store, gateway, worker, request=get).poll_source(now+86400)
    assert len(calls) == 2


def test_persistent_rate_limits_and_coalescing(store, now):
    assert all(store.rate('get', 12, now=now) for _ in range(12))
    assert not store.rate('get', 12, now=now)
    assert store.rate('get', 12, now=now+3601)
    assert all(store.rate('post', 60, now=now) for _ in range(60))
    assert not store.rate('post', 60, now=now)
    store.refresh('employee', now); store.refresh('employee', now+30)
    assert store.rows('SELECT * FROM refresh') == [{'employee': 'employee', 'due': now}]


def test_first_refresh_is_immediate_after_fresh_feed(settings, store, gateway, worker, now, monkeypatch):
    prime(settings, store, now)
    settings.mode = 'pilot'; settings.approvals['sredime_refresh'] = True
    settings.export_urls = {'synthetic-employee-A': 'https://example.invalid/private'}
    calls = []
    scheduler = Scheduler(settings, store, gateway, worker, request=lambda url, method='GET': calls.append(method))
    store.refresh('synthetic-employee-A', now)
    scheduler.refresh_source(now); assert calls == ['POST']
    assert not store.rows('SELECT * FROM refresh')
    assert store.get('refresh-scheduled:synthetic-employee-A')[0] is True


def test_local_ics_route_no_cache_or_pii(settings, store, monkeypatch):
    import time
    now = time.time(); prime(settings, store, now)
    with TestClient(create_app(settings, store)) as app:
        response = app.get('/ics/synthetic-employee-A/' + 't' * 48 + '.ics')
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'private, no-store'
        settings.feed_tokens['synthetic-employee-A'] = 'n' * 48
        assert app.get('/ics/synthetic-employee-A/' + 't' * 48 + '.ics').status_code == 404


def test_verified_uid_binding_matches_webhook_without_false_alarm(store, event, now):
    store.execute('INSERT INTO links VALUES(?,?,?,?,?)', (event['data']['id'], 123, now, json.dumps(event['data']), 'active'))
    store.execute('INSERT INTO source_bindings VALUES(?,?,?)', ('synthetic-employee-A', 'opaque-source-uid', event['data']['id']))
    reconcile_feed(store, 'synthetic-employee-A', source_calendar(), now)
    assert not store.rows("SELECT * FROM issues WHERE key LIKE 'ics:%' AND resolved=0")
    reconcile_feed(store, 'synthetic-employee-A', source_calendar('CANCELLED', modified='2026-10-21T10:00:00Z'), now+1)
    assert store.rows("SELECT * FROM issues WHERE key LIKE 'ics:%' AND resolved=0")


def test_two_people_in_separate_mapping_stores_cannot_merge(worker, settings, store, gateway, event, now):
    store.execute('INSERT INTO clients VALUES(?,?)', ('different-person', 71))
    store.ingest(event); worker.once(now)
    row = store.rows('SELECT state,reason FROM events')[0]
    assert row['reason'] == 'different_customers_share_target_client'
    assert not gateway.calls


def test_refresh_temporary_failure_resolves_after_success(settings, store, gateway, worker, now):
    from booking_bridge.model import Temporary
    prime(settings, store, now)
    settings.mode = 'pilot'; settings.approvals['sredime_refresh'] = True
    settings.export_urls = {'synthetic-employee-A': 'https://example.invalid/private'}
    calls = []
    def request(url, method='GET'):
        calls.append(method)
        if len(calls) == 1: raise Temporary('temporary_refresh_failure')
    scheduler = Scheduler(settings, store, gateway, worker, request=request)
    store.refresh('synthetic-employee-A', now)
    scheduler.refresh_source(now+60)
    assert store.rows("SELECT 1 FROM issues WHERE key='refresh:synthetic-employee-A' AND resolved=0")
    scheduler.refresh_source(now+181)
    assert calls == ['POST', 'POST']
    assert not store.rows("SELECT 1 FROM issues WHERE key='refresh:synthetic-employee-A' AND resolved=0")
