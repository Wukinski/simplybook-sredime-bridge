"""Locally observed stages only; neither fetch nor refresh proves remote import."""


def observation(row, now):
    if not row:
        return None
    result = dict(row)
    fetched = row['fetched']
    anomaly = row['ready'] > now or any(t is not None and not row['ready'] <= t <= now
                                       for t in (row['scheduled'], fetched))
    result['clock_anomaly'] = anomaly
    result['ready_to_fetch_seconds'] = (fetched-row['ready'] if fetched is not None and not anomaly else None)
    result['ready_to_refresh_seconds'] = (row['scheduled']-row['ready']
        if row['scheduled'] is not None and not anomaly else None)
    result['fetch_deadline_missed'] = (None if anomaly else
        ((fetched-row['ready'] >= 60) if fetched is not None else now-row['ready'] >= 60))
    result['import_confirmed'] = False
    return result


def employee_latency(store, employee, now):
    latest = store.rows('SELECT * FROM availability_observations WHERE employee=? ORDER BY id DESC LIMIT 1', (employee,))
    values = store.rows('''SELECT COUNT(*) AS changes,
        COALESCE(SUM(CASE WHEN fetched>=ready AND fetched<=? AND fetched-ready<60
            AND (scheduled IS NULL OR (scheduled>=ready AND scheduled<=?)) THEN 1 ELSE 0 END),0) AS fetched_under_60,
        COALESCE(SUM(CASE WHEN fetched-ready>=60 THEN 1 ELSE 0 END),0) AS fetched_at_or_over_60,
        COALESCE(SUM(CASE WHEN fetched IS NULL AND id!=? THEN 1 ELSE 0 END),0) AS superseded_without_observed_fetch,
        COALESCE(SUM(CASE WHEN fetched IS NULL AND id=? AND ready<=? THEN 1 ELSE 0 END),0) AS pending_at_or_over_60
        FROM availability_observations WHERE employee=? AND kind='change' AND ready>=?''',
        (now, now, latest[0]['id'] if latest else 0, latest[0]['id'] if latest else 0, now-60, employee, now-7*86400))[0]
    return {'latest': observation(latest[0], now) if latest else None,
            'seven_day_observations': values,
            'measurement_scope': 'feed_ready_to_http_fetch',
            'source_commit_time_known': False, 'remote_import_time_known': False}
