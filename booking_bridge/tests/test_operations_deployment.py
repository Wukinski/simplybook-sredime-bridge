import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

import pytest

from booking_bridge.deploy.build_operations_bundle import PUBLIC_FILES, make_bundle
from booking_bridge.deploy.offhost_backup import validate as validate_backup
from booking_bridge.deploy.operations_monitor import validate as validate_monitor
from booking_bridge.model import HOME, Review

OPERATIONS = HOME / 'deploy/operations'


@pytest.fixture(scope='module', params=['compose.host-operations.yaml', 'compose.external-monitor.yaml'])
def compose_model(request):
    docker = shutil.which('docker')
    if docker is None:
        pytest.skip('Docker Compose parser is not installed; no engine is needed')
    result = subprocess.run([docker, 'compose', '-f', str(OPERATIONS / request.param),
        '--profile', 'operations', 'config', '--format', 'json'], capture_output=True, text=True,
        timeout=30, env={**os.environ, 'COMPOSE_DISABLE_ENV_FILE': '1',
                         'BRIDGE_OPERATIONS_IMAGE': 'sha256:' + 'a' * 64})
    assert result.returncode == 0, 'Dormant operations Compose must validate offline'
    return json.loads(result.stdout)


def test_operations_topology_is_separate_and_restricted(compose_model):
    for name, service in compose_model['services'].items():
        assert service['profiles'] == ['operations']
        assert service['user'] == '10001:10001' and service['read_only'] is True
        assert service['cap_drop'] == ['ALL']
        assert 'no-new-privileges:true' in service['security_opt']
        assert not service.get('ports') and not service.get('privileged')
        assert not service.get('restart')
        secrets = {row['source'] for row in service['secrets']}
        assert secrets == ({'recovery_key', 's3_credentials'} if name == 'backup' else {'smtp_env', 'smtp_password'})
        assert all('/var/run/docker.sock' not in row['target'] for row in service['volumes'])
        assert not service.get('environment')
        for mount in service['volumes']:
            if mount['target'] in ('/bridge-state', '/provider-state'):
                assert mount['read_only'] is True
            if mount['type'] == 'bind':
                assert mount['read_only'] is True and mount['bind']['create_host_path'] is False
    if 'bridge_state' in compose_model['volumes']:
        assert compose_model['volumes']['bridge_state']['external'] is True
        assert compose_model['volumes']['provider_state']['external'] is True


def test_backup_template_cannot_upload_and_monitor_templates_do_not_fake_readiness():
    backup = json.loads((OPERATIONS / 'backup.example.json').read_text())
    with pytest.raises(Review, match='independent_destination_required'):
        validate_backup(backup)
    assert backup['delete_expired'] is False
    assert json.loads((OPERATIONS / 's3-credentials.example.json').read_text()) == {
        'access_key_id': '', 'secret_access_key': ''}
    external = validate_monitor(json.loads((OPERATIONS / 'monitor.external.example.json').read_text()))
    host = validate_monitor(json.loads((OPERATIONS / 'monitor.host.example.json').read_text()))
    assert external['ready_url'] == '' and external['admin_key_file'] is None
    assert host['backup_status_file'] and host['restore_status_file']


def test_operations_bundle_preserves_units_but_excludes_all_private_inputs(tmp_path):
    workspace = tmp_path / 'workspace'
    for relative in PUBLIC_FILES:
        path = workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('public-preparation')
    for relative in ('booking_bridge/deploy/operations/secrets/recovery-key.bin',
                     'booking_bridge/deploy/operations/secrets/s3-credentials.json',
                     'booking_bridge/deploy/operations/backup.json',
                     'booking_bridge/deploy/operations/operations.env',
                     'booking_bridge/state/operations-spool/backup.enc'):
        path = workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('SYNTHETIC_PRIVATE_MUST_NOT_TRANSFER')
    archive, manifest = tmp_path / 'operations.tar.gz', tmp_path / 'manifest.json'
    report = make_bundle(workspace, archive, manifest)
    assert report['private_inputs_included'] is False and report['installed_or_activated'] is False
    assert set(json.loads(manifest.read_text())) == set(PUBLIC_FILES)
    with tarfile.open(archive) as package:
        assert {item.name for item in package} == set(PUBLIC_FILES)
        assert any(item.name.endswith('.timer') for item in package)
        assert all(b'SYNTHETIC_PRIVATE' not in package.extractfile(item).read() for item in package)
