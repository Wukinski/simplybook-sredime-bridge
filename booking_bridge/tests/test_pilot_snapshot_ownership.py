import copy
import json

import pytest

from booking_bridge.model import Review
from booking_bridge.pilot_snapshot import capture_packet
from booking_bridge.tests.test_pilot_exchange import scoped, seed
from booking_bridge.tests.test_pilot_snapshot import ReadAccount
from booking_bridge.worker import FIELDS


@pytest.fixture
def owned(scoped, store, now):
    seed(scoped, store, now - 60)
    booking = store.get('bookings')[0][0]
    applied = {key: booking[key] for key in FIELDS}
    snapshot = {'employee': {'id': '11772'}}
    store.execute('INSERT INTO links VALUES(?,?,?,?,?)',
                  ('source-booking', booking['id'], now - 60, json.dumps(snapshot), 'active'))
    store.put('applied:source-booking', applied, now - 60)
    return booking, applied


class Account(ReadAccount):
    def __init__(self, bookings, detail=None):
        super().__init__()
        self.items = bookings
        self.detail_value = detail
        self.details = []

    def bookings(self, start, end):
        self.reads += 1
        return self.items

    def services(self):
        self.reads += 1
        return [{'id': 496, 'buffer_time_after': 0}]

    def detail(self, target):
        self.reads += 1
        self.details.append(target)
        return self.detail_value


@pytest.mark.parametrize('change', [
    {'start_datetime': '2026-10-27 11:00:00', 'end_datetime': '2026-10-27 11:30:00'},
    {'status': 'canceled'},
    {'provider_id': 1000}])
def test_new_owned_target_drift_blocks_before_published_cache_changes(scoped, store, now, owned, change):
    booking, applied = owned
    before = {key: store.get(key) for key in ('bookings', 'buffers', 'schedule:11772')}
    links = store.rows('SELECT * FROM links')
    actual = {**booking, **change}
    with pytest.raises(Review, match='source_drift'):
        capture_packet(scoped, store, Account([actual]), clock=lambda: now + 1)
    assert {key: store.get(key) for key in before} == before
    assert store.rows('SELECT * FROM links') == links
    assert store.get('applied:source-booking')[0] == applied
    assert store.rows('SELECT reason,resolved FROM issues WHERE key=?', ('drift:source-booking',)) == [
        {'reason': 'source_booking_changed_in_simplybook', 'resolved': 0}]
    assert store.get('feed-scope:drift:source-booking')[0] == ['11772']
    assert not store.rows('SELECT * FROM events')
    assert not store.rows('SELECT * FROM intents')


def test_unchanged_owned_booking_clears_previous_drift_and_stays_out_of_packet(scoped, store, now, owned):
    booking, _ = owned
    store.issue('drift:source-booking', 'source_booking_changed_in_simplybook', now - 1, scope=['11772'])
    _, packet = capture_packet(scoped, store, Account([booking]), clock=lambda: now + 1)
    assert packet['entries'][0]['value'] == []
    assert store.rows('SELECT resolved FROM issues WHERE key=?', ('drift:source-booking',)) == [{'resolved': 1}]
    assert store.rows('SELECT target FROM links') == [{'target': 101}]


def test_absent_owned_booking_uses_detail_instead_of_inferring_cancellation(scoped, store, now, owned):
    booking, _ = owned
    account = Account([], detail=booking)
    _, packet = capture_packet(scoped, store, account, clock=lambda: now + 1)
    assert account.details == [101]
    assert packet['entries'][0]['value'] == []
    assert not store.rows("SELECT * FROM issues WHERE key LIKE 'drift:%' AND resolved=0")


def test_canceled_owned_booking_uses_detail_and_does_not_create_a_return_block(scoped, store, now, owned):
    booking, _ = owned
    store.execute("UPDATE links SET state='canceled'")
    account = Account([], detail={**booking, 'status': 'canceled'})
    _, packet = capture_packet(scoped, store, account, clock=lambda: now + 1)
    assert account.details == [101]
    assert packet['entries'][0]['value'] == []
    assert not store.rows("SELECT * FROM issues WHERE key LIKE 'drift:%' AND resolved=0")


def test_newer_concurrent_ownership_cannot_be_cleared_by_older_capture(scoped, store, now, owned):
    booking, applied = owned
    store.issue('drift:source-booking', 'source_booking_changed_in_simplybook', now - 1, scope=['11772'])
    before = store.get('bookings')

    class ConcurrentAccount(Account):
        def bookings(self, start, end):
            store.put('applied:source-booking', {**applied, 'provider_id': 1000}, now + 1)
            return super().bookings(start, end)

    with pytest.raises(Review, match='owned_booking_changed_during_capture'):
        capture_packet(scoped, store, ConcurrentAccount([booking]), clock=lambda: now + 1)
    assert store.get('bookings') == before
    assert store.rows('SELECT resolved FROM issues WHERE key=?', ('drift:source-booking',)) == [{'resolved': 0}]
    assert store.get('applied:source-booking')[0]['provider_id'] == 1000


def test_capture_preserves_pending_source_inbox_and_head(scoped, store, now, event):
    pending = copy.deepcopy(event)
    pending['data']['employee']['id'] = '11772'
    store.ingest(pending, now)
    events = store.rows('SELECT * FROM events')
    heads = store.rows('SELECT * FROM booking_heads')
    _, packet = capture_packet(scoped, store, Account([]), clock=lambda: now + 1)
    assert packet['entries'][0]['value'] == []
    assert store.rows('SELECT * FROM events') == events
    assert store.rows('SELECT * FROM booking_heads') == heads
    assert store.rows('SELECT state,attempts FROM events') == [{'state': 'queued', 'attempts': 0}]
    assert not store.rows('SELECT * FROM intents')
    assert not store.rows('SELECT * FROM links')


def test_unmapped_capture_employee_fails_before_account_reads(scoped, store, now):
    scoped.employees = {}
    account = Account([])
    with pytest.raises(Review, match='single_employee_test_service_scope'):
        capture_packet(scoped, store, account, clock=lambda: now + 1)
    assert account.reads == 0
    assert not store.get('bookings')[0]
