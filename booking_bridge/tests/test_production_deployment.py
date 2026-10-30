"""Inspect dormant deployment topology and packaging; never start a container."""
import json
import os
import shutil
import subprocess
import tarfile

import pytest

from booking_bridge.deploy.build_pilot_release import make_release
from booking_bridge.model import HOME


@pytest.fixture(scope='module')
def compose_model():
    docker = shutil.which('docker')
    if docker is None:
        pytest.skip('Compose configuration parser is not installed; no engine required')
    result = subprocess.run([
        docker, 'compose', '-f', str(HOME / 'deploy' / 'compose.production.yaml'),
        '--profile', 'production', 'config', '--format', 'json',
    ], capture_output=True, text=True, timeout=30,
       env={**os.environ, 'COMPOSE_DISABLE_ENV_FILE': '1'})
    assert result.returncode == 0, 'Dormant production Compose configuration must validate offline'
    return json.loads(result.stdout)


def test_production_api_cannot_receive_worker_rest_secrets_or_provider_state(compose_model):
    api, worker = (compose_model['services'][name] for name in ('api', 'worker'))
    assert {row['source'] for row in api['secrets']} == {'ingress_env'}
    assert {row['source'] for row in worker['secrets']} == {'worker_env'}
    assert api['environment']['BRIDGE_ENV_FILE'] != worker['environment']['BRIDGE_ENV_FILE']
    assert not any(key.startswith('SIMPLYBOOK_ADMIN_') or key.startswith('SIMPLYBOOK_REST_')
                   for key in api['environment'])
    api_targets = {row['target'] for row in api['volumes']}
    assert '/app/provider_assignment/state' not in api_targets
    assert '/run/bridge/production-evidence' not in api_targets
    assert '/app/provider_assignment/state' in {row['target'] for row in worker['volumes']}
    assert len(api['ports']) == 1
    assert api['ports'][0]['host_ip'] == '127.0.0.1'
    assert api['ports'][0]['target'] == 8000 and str(api['ports'][0]['published']) == '8000'
    # The public ingress template also excludes REST credentials, beyond Compose
    # environment topology (the actual secret contents stay operator-private).
    ingress = (HOME / 'deploy' / 'ingress.env.example').read_text(encoding='utf-8')
    assert 'SIMPLYBOOK_ADMIN_LOGIN=' not in ingress and 'SIMPLYBOOK_ADMIN_SECRET=' not in ingress


def test_production_services_require_explicit_profile_and_guarded_worker(compose_model):
    for service in compose_model['services'].values():
        assert service['profiles'] == ['production']
        assert service['user'] == '10001:10001' and service['read_only'] is True
        assert service['cap_drop'] == ['ALL']
        assert 'no-new-privileges:true' in service['security_opt']
        assert not service.get('privileged', False)
        assert service['healthcheck']['test'][0] == 'CMD'
    worker = compose_model['services']['worker']
    assert worker['command'][:3] == ['python', '-m', 'booking_bridge.server_worker']
    assert '--readiness' in worker['command'] and '--config' in worker['command']
    readiness = worker['command'][worker['command'].index('--readiness') + 1]
    assert readiness == worker['environment']['BRIDGE_PRODUCTION_READINESS_FILE']
    assert readiness.startswith('/run/bridge/production-evidence/')
    assert worker['healthcheck']['test'][1:] == [
        'python', '-m', 'booking_bridge.production_monitor', '--local-state', '/state/bridge.sqlite']
    for name in ('api', 'worker'):
        for volume in compose_model['services'][name]['volumes']:
            if volume['type'] == 'bind':
                assert volume['read_only'] is True
                assert '/secrets/' in volume['source'].replace('\\', '/')
    assert all('/secrets/' in row['file'].replace('\\', '/')
               for row in compose_model['secrets'].values())


def test_public_production_templates_cannot_enable_runtime():
    config = json.loads((HOME / 'deploy' / 'production-config.example.json').read_text(encoding='utf-8'))
    assert config['mode'] == 'simulation' and config['reads_enabled'] is False
    assert config['require_subminute_availability'] is True
    assert config['allowed_employees'] == []
    assert config['employees'] == config['services'] == config['clients'] == {}
    assert all(value is False for value in config['approvals'].values())
    readiness = json.loads((HOME / 'deploy' / 'production-readiness.example.json').read_text(encoding='utf-8'))
    assert all(row['status'] == 'pending' and row['reviewed'] is False
               for row in readiness['checks'].values())


def test_release_includes_public_secret_templates_but_excludes_filled_server_inputs(tmp_path):
    workspace = tmp_path / 'workspace'
    included = {'booking_bridge/deploy/ingress.env.example', 'booking_bridge/deploy/worker.env.example',
                'booking_bridge/deploy/production-config.example.json',
                'booking_bridge/deploy/production-readiness.example.json',
                'booking_bridge/deploy/compose.production.yaml'}
    private = {'booking_bridge/deploy/secrets/ingress.env', 'booking_bridge/deploy/secrets/worker.env',
               'booking_bridge/deploy/secrets/production-config.json',
               'booking_bridge/deploy/secrets/production-evidence/readiness.json',
               'booking_bridge/deploy/secrets/production-evidence/private-readback.json',
               'booking_bridge/deploy/unapproved.env.example'}
    for name in included | private:
        path = workspace / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('public-template' if name in included else 'DO_NOT_TRANSFER_PRIVATE_SERVER_DATA')
    archive, manifest = tmp_path / 'source.tar.gz', tmp_path / 'manifest.json'
    make_release(workspace, archive, manifest)
    assert set(json.loads(manifest.read_text(encoding='utf-8'))) == included
    with tarfile.open(archive, 'r:gz') as package:
        assert {row.name for row in package.getmembers()} == included
        assert all(b'DO_NOT_TRANSFER' not in package.extractfile(row).read() for row in package.getmembers())
