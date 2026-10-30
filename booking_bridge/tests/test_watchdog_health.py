import json

import pytest

from booking_bridge.watchdog_health import file_health, main


def save(path, data):
    path.write_text(json.dumps(data), encoding='utf-8')
    return path


def healthy_analyzer(now):
    return {'schema_version': 1, 'updated_at': now, 'healthy': True,
            'diagnostics_only': True, 'repairs_enabled': False,
            'email_configured': True, 'last_model_ok': True, 'last_model_self_test_ok': True}


def test_collector_freshness_boundaries_and_schema(tmp_path, now):
    path = tmp_path / 'latest.json'
    for age, expected in ((0, True), (90, True), (90.001, False), (-1, False)):
        save(path, {'schema_version': 1, 'collected_at': now - age})
        assert file_health('collector', path, now=now) is expected
    for schema in (True, '1', 2, None):
        save(path, {'schema_version': schema, 'collected_at': now})
        assert file_health('collector', path, now=now) is False


@pytest.mark.parametrize('field,value', [('healthy', False), ('email_configured', False),
    ('last_model_ok', False), ('last_model_self_test_ok', False), ('diagnostics_only', False),
    ('repairs_enabled', True), ('last_model_ok', 1), ('repairs_enabled', 0)])
def test_analyzer_is_unhealthy_until_every_required_capability_passes(tmp_path, now, field, value):
    path = save(tmp_path / 'status.json', healthy_analyzer(now))
    assert file_health('analyzer', path, now=now) is True
    data = healthy_analyzer(now)
    data[field] = value
    save(path, data)
    assert file_health('analyzer', path, now=now) is False


def test_analyzer_health_timestamp_cannot_be_future_or_stale(tmp_path, now):
    data = healthy_analyzer(now)
    path = save(tmp_path / 'status.json', data)
    assert file_health('analyzer', path, now=now + 120) is True
    assert file_health('analyzer', path, now=now + 121) is False
    assert file_health('analyzer', path, now=now - 1) is False


def test_missing_and_invalid_status_are_silent_and_do_not_create_files(tmp_path, capsys):
    path = tmp_path / 'missing.json'
    assert main(['collector', '--file', str(path)]) == 1
    assert not path.exists()
    path.write_text('{"schema_version":1,"schema_version":2,"raw":"PRIVATE_PAYLOAD"}')
    before = path.read_bytes()
    assert main(['collector', '--file', str(path)]) == 1
    assert path.read_bytes() == before
    output = capsys.readouterr()
    assert output.out == output.err == ''


def test_oversized_or_nonfinite_status_is_rejected(tmp_path, now, monkeypatch):
    path = tmp_path / 'status.json'
    path.write_text('{"schema_version":1,"collected_at":NaN}')
    assert not file_health('collector', path, now=now)
    save(path, {'schema_version': 1, 'collected_at': now})
    monkeypatch.setattr('booking_bridge.watchdog_health.MAX_STATUS_BYTES', 4)
    assert not file_health('collector', path, now=now)
