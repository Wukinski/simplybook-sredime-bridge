from datetime import timedelta

import pytest

from booking_bridge.calendar import make_feed
from booking_bridge.model import Review
from booking_bridge.pilot_snapshot import capture


class ReadAccount:
    def __init__(self): self.reads = 0

    def bookings(self, start, end):
        self.reads += 1
        return []

    def services(self):
        self.reads += 1
        return [{'id': 91, 'buffer_time_after': 0}, {'id': 92, 'buffer_time_after': 0}]

    def provider_schedule(self, provider, service, start, end):
        self.reads += 1
        return {}

    def calendar_week(self, provider, start, reference):
        self.reads += 1
        return {str(start + timedelta(days=i)): {'is_day_off': False, 'from': '09:00:00',
                'to': '17:00:00', 'breaktimes': [], 'blocked': [], 'notes': []} for i in range(7)}

    def write(self, *args):
        raise AssertionError('No account mutation allowed')


def prepare(settings):
    settings.allowed_employees = settings.allowed_employees[:1]
    settings.pilot_service_ids = [91, 92]
    settings.horizon_days = 7
    settings.schedule_service_ids = {settings.allowed_employees[0]: 91}
    settings.approvals.update(pilot_read_snapshots=True, pilot_scope_reviewed=True,
                              schedule_reference_verified=True)


def test_capture_renders_actual_read_data_without_inbox_or_account_writes(settings, store, now):
    prepare(settings)
    account = ReadAccount()
    # Different stages complete at different times, as on a real network.
    ticks = iter(now + i / 10 for i in range(100))
    result = capture(settings, store, account, clock=lambda: next(ticks))
    assert result['account_mutations'] == 0 and account.reads >= 4
    assert make_feed(settings, store, settings.allowed_employees[0], now + 10)[1] > 0
    assert not store.rows('SELECT * FROM events')
    assert not store.rows('SELECT * FROM intents')
    assert not store.rows('SELECT * FROM links')


@pytest.mark.parametrize('mode,reads,approved', [('pilot', False, True),
                                               ('simulation', True, True),
                                               ('simulation', False, False)])
def test_capture_refuses_unapproved_or_active_mutation_profiles(settings, store, mode, reads, approved):
    prepare(settings)
    settings.mode, settings.reads_enabled = mode, reads
    settings.approvals['pilot_read_snapshots'] = approved
    account = ReadAccount()
    with pytest.raises(Review, match='explicit_read_only_pilot'):
        capture(settings, store, account)
    assert account.reads == 0
