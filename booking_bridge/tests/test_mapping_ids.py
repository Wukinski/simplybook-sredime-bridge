import csv
import json

import pytest

from booking_bridge import model, prepare_mappings
from booking_bridge.model import Review, Settings


def load_csv(tmp_path, monkeypatch, content, *, kind='employees', config=None):
    (tmp_path / 'mappings').mkdir(exist_ok=True)
    (tmp_path / 'mappings' / (kind + '.local.csv')).write_text(content, encoding='utf-8')
    path = tmp_path / 'profile.json'
    path.write_text(json.dumps(config or {}), encoding='utf-8')
    monkeypatch.setattr(model, 'HOME', tmp_path)
    monkeypatch.setenv('BRIDGE_FEED_TOKENS', '{}')
    monkeypatch.setenv('SREDIME_EXPORT_URLS', '{}')
    return Settings.load(path, read_only=True)


def test_explicit_webhook_id_routes_exactly_and_native_id_is_only_metadata(tmp_path, monkeypatch):
    settings = load_csv(tmp_path, monkeypatch,
                        'sredime_webhook_id,sredime_native_id,simplybook_id,external_id\n'
                        'Opaque-A,12345,81,81\n')
    row = settings.target('employees', {'id': 'Opaque-A', 'external_id': '81'})
    assert row['id'] == 81 and row['native_id'] == '12345'
    for source in ('12345', 'opaque-a'):
        with pytest.raises(Review, match='unmapped_employees'):
            settings.target('employees', {'id': source})


def test_native_only_row_stays_unmapped(tmp_path, monkeypatch):
    settings = load_csv(tmp_path, monkeypatch,
                        'sredime_webhook_id,sredime_native_id,simplybook_id\n'
                        ',12345,81\n')
    assert settings.employees == {}


def test_legacy_numeric_source_key_still_loads_without_native_metadata(tmp_path, monkeypatch):
    settings = load_csv(tmp_path, monkeypatch, 'sredime_id,simplybook_id\n12345,81\n')
    assert settings.target('employees', {'id': '12345'})['id'] == 81
    assert 'native_id' not in settings.employees['12345']


def test_matching_deprecated_column_is_accepted(tmp_path, monkeypatch):
    settings = load_csv(tmp_path, monkeypatch,
                        'sredime_webhook_id,sredime_id,simplybook_id\nOpaque-A,Opaque-A,81\n')
    assert list(settings.employees) == ['Opaque-A']


@pytest.mark.parametrize('explicit', ['Opaque-A', ''])
def test_native_legacy_key_cannot_override_explicit_column(tmp_path, monkeypatch, explicit):
    with pytest.raises(Review, match='conflicting_source_mapping_columns'):
        load_csv(tmp_path, monkeypatch,
                 'sredime_webhook_id,sredime_native_id,sredime_id,simplybook_id\n'
                 f'{explicit},12345,12345,81\n')


@pytest.mark.parametrize('rows,reason', [
    ('Opaque-A,12345,81\nOpaque-A,54321,82\n', 'duplicate_source_mapping'),
    ('Opaque-A,12345,81\nOpaque-B,54321,81\n', 'duplicate_employee_target'),
    (' Opaque-A,12345,81\n', 'invalid_source_mapping_id'),
    ('Opaque-A,not-a-native-id,81\n', 'invalid_native_mapping_id'),
])
def test_invalid_explicit_csv_is_rejected(tmp_path, monkeypatch, rows, reason):
    with pytest.raises(Review, match=reason):
        load_csv(tmp_path, monkeypatch,
                 'sredime_webhook_id,sredime_native_id,simplybook_id\n' + rows)


def test_service_csv_preserves_timing_and_resource_evidence(tmp_path, monkeypatch):
    settings = load_csv(tmp_path, monkeypatch,
                        'sredime_webhook_id,sredime_native_id,simplybook_id,duration_minutes,'
                        'timing_verified,resources_verified\nOpaque-Service,23456,91,30,yes,yes\n',
                        kind='services')
    assert settings.services['Opaque-Service'] == {
        'id': 91, 'native_id': '23456', 'external_id': '', 'duration': 30,
        'timing_verified': True, 'resources_verified': True,
    }


@pytest.mark.parametrize('field,value,reason', [
    ('employees', {12345: {'id': 81}}, 'invalid_source_mapping_id'),
    ('services', {' ': {'id': 91}}, 'invalid_source_mapping_id'),
    ('clients', {'client\n': 71}, 'invalid_source_mapping_id'),
    ('employees', {'Opaque-A': {'id': 81, 'native_id': 12345}}, 'invalid_native_mapping_id'),
    ('employees', {'Opaque-A': {'id': 81}, 'Opaque-B': {'id': 81}}, 'duplicate_employee_target'),
    ('clients', {'Opaque-Client': True}, 'invalid_target_id'),
])
def test_json_mapping_validation_is_consistent(field, value, reason):
    settings = Settings(**{field: value})
    with pytest.raises(Review, match=reason):
        settings.validate(read_only=True)


def test_json_native_metadata_never_establishes_a_webhook_alias():
    settings = Settings(employees={'Opaque-A': {'id': 81, 'native_id': '12345'}})
    settings.validate(read_only=True)
    assert settings.target('employees', {'id': 'Opaque-A'})['id'] == 81
    with pytest.raises(Review, match='unmapped_employees'):
        settings.target('employees', {'id': '12345'})


def test_duplicate_source_keys_in_json_cannot_silently_replace_target(tmp_path, monkeypatch):
    path = tmp_path / 'profile.json'
    path.write_text('{"employees":{"Opaque-A":{"id":81},"Opaque-A":{"id":82}}}', encoding='utf-8')
    monkeypatch.setattr(model, 'HOME', tmp_path)
    with pytest.raises(Review, match='duplicate_configuration_key'):
        Settings.load(path, read_only=True)


def test_prepare_catalog_keeps_identifiers_blank_and_separate(tmp_path, monkeypatch):
    home = tmp_path / 'bridge'
    (home / 'evidence').mkdir(parents=True)
    (tmp_path / 'service_importer').mkdir()
    checkpoint = {'rows': {'2': {'status': 'confirmed', 'remote_id': 91,
                                'normalized': {'name': 'Synthetic service', 'duration_minutes': 30}}}}
    (tmp_path / 'service_importer/progress_log.json').write_text(json.dumps(checkpoint), encoding='utf-8')
    (home / 'evidence/account-read-check.json').write_text(
        json.dumps({'providers': [{'id': 81, 'name': 'Synthetic employee'}]}), encoding='utf-8')
    monkeypatch.setattr(prepare_mappings, 'HOME', home)
    monkeypatch.setattr(prepare_mappings, 'ROOT', tmp_path)
    prepare_mappings.main()
    for kind, target in [('employees', '81'), ('services', '91')]:
        with (home / 'mappings' / (kind + '.csv')).open(encoding='utf-8-sig', newline='') as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == 1 and rows[0]['simplybook_id'] == target
        assert all(rows[0][column] == '' for column in (
            'sredime_webhook_id', 'sredime_native_id', 'sredime_id'))
