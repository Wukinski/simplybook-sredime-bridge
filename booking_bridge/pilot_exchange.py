"""Scoped, PII-free availability exchange for the existing simulation pilot.

This module makes no network calls. The publisher authenticates its transport;
this receiver never needs SimplyBook administrative credentials or processes the
booking inbox. Source cache timestamps are preserved, including on duplicate runs.
"""
import argparse
import json
import math
import re
import sys
import time
from datetime import date, timedelta

from .calendar import bounds, feed_version, make_feed
from .model import BELGRADE, Review, Settings, digest, local_stamp, positive
from .store import Store

MAX_PACKET_BYTES = 1_000_000
FUTURE_SKEW_SECONDS = 5
TOP_KEYS = {'schema_version', 'salon', 'source_employee_id', 'target_provider_id',
            'target_service_ids', 'horizon_days', 'captured_at', 'entries', 'feed_version'}
BOOKING_KEYS = {'id', 'provider_id', 'service_id', 'start_datetime', 'end_datetime', 'status'}
DAY_KEYS = {'date', 'from', 'to', 'is_day_off', 'breaktimes', 'blocked', 'notes'}
BLOCK_KEYS = {'id', 'from', 'to'}
NOTE_KEYS = BLOCK_KEYS | {'time_blocked', 'provider_id', 'service_id'}


def _moment(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise Review('invalid_packet_timestamp')
    return value


def _scope(settings):
    if (settings.mode != 'simulation' or settings.reads_enabled is not False or
            settings.approvals.get('pilot_read_snapshots') is not True or
            settings.approvals.get('pilot_scope_reviewed') is not True):
        raise Review('explicit_read_only_pilot_profile_required')
    settings.validate(read_only=True)
    if (type(settings.horizon_days) is not int or
            any(type(getattr(settings, name)) is not int or getattr(settings, name) <= 0
                for name in ('snapshot_max_age', 'schedule_max_age'))):
        raise Review('invalid_pilot_freshness_profile')
    if len(settings.allowed_employees) != 1:
        raise Review('single_employee_test_service_scope_required')
    employee = settings.allowed_employees[0]
    if not isinstance(employee, str) or not employee or employee not in settings.employees:
        raise Review('single_employee_test_service_scope_required')
    provider = positive(settings.employees[employee].get('id'))
    service_ids = [positive(s.get('id')) for s in settings.services.values()]
    allowed = [positive(s) for s in settings.pilot_service_ids]
    if (not service_ids or len(service_ids) != len(set(service_ids)) or
            len(allowed) != len(set(allowed)) or set(service_ids) != set(allowed) or
            settings.schedule_service_ids.get(employee) not in service_ids or
            settings.approvals.get('schedule_reference_verified') is not True):
        raise Review('single_employee_test_service_scope_required')
    return employee, provider, sorted(service_ids)


class _PacketView:
    """Read-only Store subset for pure candidate validation."""
    def __init__(self, entries):
        self.entries = {e['key']: (e['value'], e['updated']) for e in entries}

    def get(self, key):
        return self.entries.get(key, (None, 0))

    def rows(self, sql, args=()):
        return []


class _TransactionView:
    """Use the writer's SQLite snapshot, without nested BEGIN IMMEDIATE."""
    def __init__(self, conn):
        self.conn = conn

    def get(self, key):
        row = self.conn.execute('SELECT value,updated FROM cache WHERE key=?', (key,)).fetchone()
        return (json.loads(row['value']), row['updated']) if row else (None, 0)

    def rows(self, sql, args=()):
        return [dict(r) for r in self.conn.execute(sql, args).fetchall()]


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise Review('invalid_packet_schedule_day')
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise Review('invalid_packet_schedule_day') from None


def _time_value(value):
    pattern = (r'(?:\d{2}:\d{2}(?::\d{2})?|'
               r'\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?'
               r'(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?)')
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise Review('invalid_packet_time')
    if len(value) <= 8:
        numbers = [int(part) for part in value.split(':')]
        hour, minute = numbers[:2]
        second = numbers[2] if len(numbers) == 3 else 0
        if not (0 <= minute < 60 and 0 <= second < 60 and
                (0 <= hour < 24 or (hour == 24 and minute == second == 0))):
            raise Review('invalid_packet_time')
    else:
        local_stamp(value)


def _block(item, *, note=False):
    allowed = NOTE_KEYS if note else BLOCK_KEYS
    if (not isinstance(item, dict) or not {'from', 'to'}.issubset(item) or
            not set(item).issubset(allowed)):
        raise Review('invalid_or_nonminimal_packet_block')
    for key in ('from', 'to'):
        _time_value(item[key])
    if 'id' in item and (type(item['id']) is not int or item['id'] < 0):
        raise Review('invalid_packet_block_identity')
    if note:
        if item.get('time_blocked') is not True:
            raise Review('nonblocking_packet_note')
        for name in ('provider_id', 'service_id'):
            if name in item and item[name] is not None and (type(item[name]) is not int or item[name] < 0):
                raise Review('invalid_packet_block_scope')


def _validate_values(settings, entries, employee, provider, service_ids, now, captured_at):
    required = {'bookings', 'buffers', 'schedule:' + employee}
    if not isinstance(entries, list) or len(entries) != 3:
        raise Review('packet_requires_three_snapshots')
    by_key = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {'key', 'value', 'updated'}:
            raise Review('invalid_or_nonminimal_packet_entry')
        key = entry['key']
        if not isinstance(key, str) or key not in required or key in by_key:
            raise Review('unexpected_or_duplicate_packet_cache_key')
        updated = _moment(entry['updated'])
        limit = settings.snapshot_max_age if key == 'bookings' else settings.schedule_max_age
        if updated > captured_at or now - updated < -FUTURE_SKEW_SECONDS or now - updated > limit:
            raise Review('packet_snapshot_stale_or_future')
        by_key[key] = entry['value']
    buffers = by_key['buffers']
    if (not isinstance(buffers, dict) or set(buffers) != {str(s) for s in service_ids} or
            any(type(v) is not int or v < 0 for v in buffers.values())):
        raise Review('packet_buffers_outside_scope_or_invalid')
    first, last = bounds(now, settings.horizon_days)
    bookings = by_key['bookings']
    if not isinstance(bookings, list):
        raise Review('invalid_packet_booking_list')
    seen = set()
    for booking in bookings:
        if not isinstance(booking, dict) or set(booking) != BOOKING_KEYS:
            raise Review('invalid_or_nonminimal_packet_booking')
        booking_id = positive(booking['id'])
        if (booking_id in seen or type(booking['provider_id']) is not int or
                booking['provider_id'] != provider or type(booking['service_id']) is not int or
                booking['service_id'] not in service_ids):
            raise Review('packet_booking_outside_scope_or_duplicate')
        seen.add(booking_id)
        if booking['status'] not in ('confirmed', 'pending', 'canceled'):
            raise Review('unknown_simplybook_booking_status')
        for field in ('start_datetime', 'end_datetime'):
            _time_value(booking[field])
        booking_first, booking_last = local_stamp(booking['start_datetime']), local_stamp(booking['end_datetime'])
        if booking_last <= booking_first:
            raise Review('invalid_simplybook_booking_bounds')
        if booking_first >= last or booking_last + timedelta(minutes=buffers[str(booking['service_id'])]) <= first:
            raise Review('packet_booking_outside_horizon')
    schedule = by_key['schedule:' + employee]
    if not isinstance(schedule, dict):
        raise Review('invalid_packet_schedule')
    start, end = first.astimezone(BELGRADE).date(), last.astimezone(BELGRADE).date()
    expected = {str(start + timedelta(days=n)) for n in range((end - start).days)}
    if set(schedule) != expected:
        raise Review('packet_schedule_coverage_mismatch')
    for day, column in schedule.items():
        _date(day)
        if (not isinstance(column, dict) or set(column) != DAY_KEYS or column['date'] != day or
                type(column['is_day_off']) is not bool):
            raise Review('invalid_or_nonminimal_packet_schedule')
        for field in ('from', 'to'):
            _time_value(column[field])
        for kind in ('breaktimes', 'blocked', 'notes'):
            if not isinstance(column[kind], list):
                raise Review('invalid_packet_block_collection')
            for item in column[kind]:
                _block(item, note=kind == 'notes')
                if kind == 'notes' and item.get('provider_id') not in (None, 0, provider):
                    raise Review('packet_note_outside_provider_scope')


def validate_packet(settings, packet, *, now=None):
    """Pure strict validation before transport as well as before receiving."""
    now = _moment(time.time() if now is None else now)
    employee, provider, service_ids = _scope(settings)
    if not isinstance(packet, dict) or set(packet) != TOP_KEYS:
        raise Review('invalid_or_nonminimal_pilot_packet')
    if (type(packet['schema_version']) is not int or packet['schema_version'] != 1 or
            packet['salon'] != settings.salon or packet['source_employee_id'] != employee or
            type(packet['target_provider_id']) is not int or packet['target_provider_id'] != provider or
            not isinstance(packet['target_service_ids'], list) or
            any(type(i) is not int for i in packet['target_service_ids']) or
            packet['target_service_ids'] != service_ids or type(packet['horizon_days']) is not int or
            packet['horizon_days'] != settings.horizon_days):
        raise Review('pilot_packet_scope_mismatch')
    captured_at = _moment(packet['captured_at'])
    if not -FUTURE_SKEW_SECONDS <= now - captured_at <= settings.snapshot_max_age:
        raise Review('pilot_packet_stale_or_future')
    _validate_values(settings, packet['entries'], employee, provider, service_ids, now, captured_at)
    if not isinstance(packet['feed_version'], str) or not re.fullmatch('[a-f0-9]{64}', packet['feed_version']):
        raise Review('invalid_packet_feed_version')
    body, count = make_feed(settings, _PacketView(packet['entries']), employee, now)
    if feed_version(body) != packet['feed_version']:
        raise Review('pilot_packet_feed_version_mismatch')
    try:
        if len(json.dumps(packet, allow_nan=False).encode('utf-8')) > MAX_PACKET_BYTES:
            raise Review('pilot_packet_too_large')
    except (TypeError, ValueError):
        raise Review('invalid_pilot_packet_json') from None
    return {'source_employee_id': employee, 'target_provider_id': provider,
            'feed_version': packet['feed_version'], 'occupancy_events': count}


def build_packet(settings, store, *, now=None):
    """Project local authoritative snapshots onto an explicit occupancy schema."""
    now = _moment(time.time() if now is None else now)
    employee, provider, service_ids = _scope(settings)
    raw_bookings, booking_at = store.get('bookings')
    raw_buffers, buffer_at = store.get('buffers')
    raw_schedule, schedule_at = store.get('schedule:' + employee)
    if not isinstance(raw_bookings, list) or not isinstance(raw_buffers, dict) or not isinstance(raw_schedule, dict):
        raise Review('pilot_capture_incomplete')
    # Projection must not turn a paused local feed into an apparently safe one.
    # In particular, _PacketView deliberately has no inbox/links/issues, so the
    # authoritative source fences must be checked before using that pure view.
    make_feed(settings, store, employee, now)
    owned = {row['target'] for row in store.rows('SELECT target FROM links WHERE target IS NOT NULL')}
    first, last = bounds(now, settings.horizon_days)
    bookings = []
    for row in raw_bookings:
        if not isinstance(row, dict):
            raise Review('invalid_booking_response')
        if (row.get('provider_id') == provider and row.get('status') != 'canceled'
                and row.get('id') not in owned and row.get('service_id') not in service_ids):
            # Provider capacity is shared across services. Silently filtering this
            # record would publish a falsely free interval; expanding the pilot
            # service allowlist automatically would be equally incorrect.
            raise Review('pilot_provider_booking_outside_test_service_scope')
        if (row.get('provider_id') == provider and row.get('service_id') in service_ids
                and row.get('status') != 'canceled' and row.get('id') not in owned):
            buffer = raw_buffers.get(str(row['service_id']))
            if type(buffer) is not int or buffer < 0:
                raise Review('packet_buffers_outside_scope_or_invalid')
            if (local_stamp(row.get('start_datetime')) >= last or
                    local_stamp(row.get('end_datetime')) + timedelta(minutes=buffer) <= first):
                continue
            bookings.append({key: row[key] for key in BOOKING_KEYS if key in row})
    buffers = {str(s): raw_buffers[str(s)] for s in service_ids if str(s) in raw_buffers}
    first, last = bounds(now, settings.horizon_days)
    start, end = first.astimezone(BELGRADE).date(), last.astimezone(BELGRADE).date()
    schedule = {}
    for offset in range((end-start).days):
        day = str(start + timedelta(days=offset))
        row = raw_schedule.get(day)
        if not isinstance(row, dict) or type(row.get('is_day_off')) is not bool:
            raise Review('pilot_schedule_capture_incomplete')
        column = {'date': day, 'is_day_off': row['is_day_off'],
                  'from': '00:00:00' if row['is_day_off'] else row.get('from'),
                  'to': '00:00:00' if row['is_day_off'] else row.get('to')}
        for kind in ('breaktimes', 'blocked', 'notes'):
            if row['is_day_off']:
                column[kind] = []
                continue
            if not isinstance(row.get(kind), list):
                raise Review('missing_calendar_block_collection')
            values = row[kind]
            if any(not isinstance(v, dict) for v in values):
                raise Review('invalid_packet_block_collection')
            if kind == 'notes':
                values = [v for v in values if v.get('time_blocked') is True and v.get('provider_id') in (None, 0, provider)]
            keys = NOTE_KEYS if kind == 'notes' else BLOCK_KEYS
            column[kind] = [{k: v[k] for k in keys if k in v} for v in values if isinstance(v, dict)]
        schedule[day] = column
    entries = [{'key': 'bookings', 'value': bookings, 'updated': booking_at},
               {'key': 'buffers', 'value': buffers, 'updated': buffer_at},
               {'key': 'schedule:' + employee, 'value': schedule, 'updated': schedule_at}]
    body, _ = make_feed(settings, _PacketView(entries), employee, now)
    packet = {'schema_version': 1, 'salon': settings.salon, 'source_employee_id': employee,
              'target_provider_id': provider, 'target_service_ids': service_ids,
              'horizon_days': settings.horizon_days, 'captured_at': now,
              'entries': entries, 'feed_version': feed_version(body)}
    validate_packet(settings, packet, now=now)
    return packet


def import_packet(settings, store, packet, *, now=None):
    """Commit the complete cache, version and pending refresh, or change nothing."""
    now = _moment(time.time() if now is None else now)
    checked = validate_packet(settings, packet, now=now)
    employee = checked['source_employee_id']
    fingerprint = digest(packet)
    metadata_key = 'pilot-packet:' + employee
    with store.connect() as conn:
        view = _TransactionView(conn)
        previous = view.get(metadata_key)[0]
        if isinstance(previous, dict) and packet['captured_at'] < previous['captured_at']:
            raise Review('pilot_packet_replay_rollback')
        duplicate = isinstance(previous, dict) and packet['captured_at'] == previous['captured_at']
        if duplicate and previous.get('digest') != fingerprint:
            raise Review('pilot_packet_same_timestamp_conflict')
        for entry in packet['entries']:
            current, updated = view.get(entry['key'])
            if updated > entry['updated']:
                raise Review('pilot_packet_snapshot_rollback')
            if updated == entry['updated'] and current is not None and current != entry['value']:
                raise Review('pilot_packet_snapshot_timestamp_conflict')
            if duplicate and (current != entry['value'] or updated != entry['updated']):
                raise Review('pilot_packet_duplicate_state_mismatch')
        if duplicate:
            return {'accepted': True, 'duplicate': True, **checked, 'remote_import_confirmed': False}
        for entry in packet['entries']:
            conn.execute('INSERT OR REPLACE INTO cache VALUES(?,?,?)',
                         (entry['key'], json.dumps(entry['value']), entry['updated']))
        body, count = make_feed(settings, view, employee, now)
        if feed_version(body) != packet['feed_version']:
            raise Review('pilot_packet_destination_feed_mismatch')
        store._publish_feed(conn, employee, packet['feed_version'], count, now, scoped_retention=True)
        conn.execute('INSERT OR REPLACE INTO cache VALUES(?,?,?)',
                     (metadata_key, json.dumps({'captured_at': packet['captured_at'], 'digest': fingerprint}), now))
        conn.execute("UPDATE issues SET resolved=1 WHERE key=? AND reason IN "
                     "('booking_snapshot_stale','schedule_snapshot_stale','service_buffers_stale')", ('feed:' + employee,))
        if count:
            conn.execute('UPDATE issues SET resolved=1 WHERE key=?', ('empty-out:' + employee,))
        else:
            conn.execute('INSERT INTO issues VALUES(?,?,?,?,0) ON CONFLICT(key) DO UPDATE SET '
                         'reason=excluded.reason,updated=excluded.updated,resolved=0',
                         ('empty-out:' + employee, 'empty_outbound_feed_support_check_required', now, now))
    return {'accepted': True, 'duplicate': False, **checked, 'remote_import_confirmed': False}


def _unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Review('duplicate_packet_json_key')
        result[key] = value
    return result


def decode_packet(raw):
    """Bounded, strict JSON decoding; exposed for CLI and publisher tests."""
    if not isinstance(raw, bytes) or len(raw) > MAX_PACKET_BYTES:
        raise Review('pilot_packet_too_large')
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_json,
                          parse_constant=lambda value: (_ for _ in ()).throw(Review('invalid_packet_number')))
    except (ValueError, UnicodeError, RecursionError):
        raise Review('invalid_pilot_packet_json') from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--read-only', action='store_true', required=True)
    parser.add_argument('--stdin', action='store_true', required=True)
    parser.parse_args()
    try:
        packet = decode_packet(sys.stdin.buffer.read(MAX_PACKET_BYTES + 1))
        settings = Settings.load(read_only=True, isolated_profile=True)
        # Invalid transport input must not initialize or migrate a state database.
        validate_packet(settings, packet)
        result = import_packet(settings, Store(settings.state / 'bridge.sqlite'), packet)
    except Review as exc:
        print(json.dumps({'accepted': False, 'reason': str(exc)}))
        return 1
    except Exception:
        print(json.dumps({'accepted': False, 'reason': 'pilot_packet_import_failed'}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
