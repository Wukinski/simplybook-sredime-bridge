"""Model isolation invariants; Compose parsing never starts containers."""
import json
import os
import shutil
import subprocess

import pytest

from booking_bridge.model import HOME


@pytest.fixture(scope='module')
def diagnostics_compose():
    docker = shutil.which('docker')
    if docker is None:
        pytest.skip('Offline Docker Compose parser is not installed')
    result = subprocess.run([
        docker, 'compose', '-f', str(HOME / 'deploy' / 'compose.diagnostics.yaml'),
        '--profile', 'model', '--profile', 'bootstrap', '--profile', 'watchdog',
        'config', '--format', 'json',
    ], capture_output=True, text=True, timeout=30,
       env={**os.environ, 'COMPOSE_DISABLE_ENV_FILE': '1'})
    assert result.returncode == 0, 'Diagnostic Compose must validate offline'
    return json.loads(result.stdout)


def test_model_has_only_own_storage_and_loopback_access(diagnostics_compose):
    service = diagnostics_compose['services']['qwen']
    assert service['image'].startswith('ollama/ollama:0.40.12@sha256:')
    assert service['user'] == '10002:10002' and service['read_only'] is True
    assert service['cap_drop'] == ['ALL'] and 'no-new-privileges:true' in service['security_opt']
    assert int(service['mem_limit']) == int(service['memswap_limit']) == 8 * 1024**3
    assert float(service['cpus']) == 2
    assert len(service['volumes']) == 1 and service['volumes'][0]['target'] == '/ollama'
    assert service['volumes'][0]['type'] == 'volume'
    assert not service.get('secrets') and not service.get('privileged', False)
    assert len(service['ports']) == 1 and service['ports'][0]['host_ip'] == '127.0.0.1'
    assert service['ports'][0]['target'] == 11434
    assert set(service['networks']) == {'diagnostics'}
    assert diagnostics_compose['networks']['diagnostics']['internal'] is True


def test_model_resource_and_cloud_controls_are_fixed(diagnostics_compose):
    env = diagnostics_compose['services']['qwen']['environment']
    assert env['OLLAMA_NUM_PARALLEL'] == env['OLLAMA_MAX_LOADED_MODELS'] == '1'
    assert env['OLLAMA_CONTEXT_LENGTH'] == '4096' and env['OLLAMA_KEEP_ALIVE'] == '-1'
    assert env['OLLAMA_NO_CLOUD'] == '1' and env['OLLAMA_NOHISTORY'] == '1'
    assert not any(name.startswith(('SIMPLYBOOK_', 'SMTP_', 'SREDIME_', 'BRIDGE_ADMIN_')) for name in env)


def test_download_egress_requires_separate_bootstrap_profile(diagnostics_compose):
    model = diagnostics_compose['services']['qwen']
    bootstrap = diagnostics_compose['services']['model-bootstrap']
    assert set(model['profiles']) == {'model', 'watchdog', 'diagnostics_staged'}
    assert bootstrap['profiles'] == ['bootstrap']
    assert set(bootstrap['networks']) == {'model_download'}
    assert not bootstrap.get('ports') and bootstrap['restart'] == 'no'
    assert bootstrap['volumes'] == model['volumes']


def test_collector_and_analyzer_have_separate_data_and_network_rights(diagnostics_compose):
    collector = diagnostics_compose['services']['collector']
    analyzer = diagnostics_compose['services']['analyzer']
    assert set(collector['profiles']) == set(analyzer['profiles']) == {'watchdog', 'diagnostics_staged'}
    assert collector['network_mode'] == 'none' and not collector.get('secrets')
    collector_mounts = {row['target']: row for row in collector['volumes']}
    analyzer_mounts = {row['target']: row for row in analyzer['volumes']}
    assert collector_mounts['/bridge-state']['read_only'] is True
    assert not collector_mounts['/observations'].get('read_only', False)
    assert '/bridge-state' not in analyzer_mounts
    assert analyzer_mounts['/observations']['read_only'] is True
    assert not analyzer_mounts['/diagnostics'].get('read_only', False)
    assert set(analyzer['networks']) == {'diagnostics', 'mail_egress'}
    assert {row['source'] for row in analyzer['secrets']} == {'smtp_env', 'smtp_password'}
    for service in (collector, analyzer):
        assert service['user'] == '10001:10001' and service['read_only'] is True
        assert service['cap_drop'] == ['ALL'] and not service.get('privileged', False)
        assert all('docker.sock' not in row['target'] for row in service['volumes'])


def test_keeper_is_a_separate_trusted_helper_without_model_or_mail_access(diagnostics_compose):
    keeper = diagnostics_compose['services']['keeper']
    assert keeper['command'][:3] == ['python', '-m', 'booking_bridge.watchdog_keeper']
    assert keeper['network_mode'] == 'none' and keeper['user'] == '10001:10001'
    assert keeper['read_only'] is True and keeper['cap_drop'] == ['ALL']
    assert not keeper.get('secrets') and not keeper.get('environment')
    assert len(keeper['volumes']) == 1
    assert keeper['volumes'][0]['target'] == '/bridge-state'
    assert not keeper['volumes'][0].get('read_only', False)
    assert diagnostics_compose['services']['collector']['depends_on']['keeper']['condition'] == 'service_healthy'


def test_diagnostic_health_and_logs_are_bounded_without_repair_actions(diagnostics_compose):
    services = diagnostics_compose['services']
    for service in services.values():
        assert service['logging'] == {'driver': 'json-file', 'options': {'max-size': '5m', 'max-file': '3'}}
    # Resident diagnostics must also start after a Docker/host restart.
    for name in ('qwen', 'keeper', 'collector', 'analyzer'):
        assert services[name]['restart'] == 'unless-stopped'
    assert services['collector']['healthcheck']['test'][1:] == [
        'python', '-m', 'booking_bridge.watchdog_health', 'collector', '--file', '/observations/latest.json', '--max-age', '90']
    assert services['analyzer']['healthcheck']['test'][1:] == [
        'python', '-m', 'booking_bridge.watchdog_health', 'analyzer', '--file', '/diagnostics/watchdog-status.json', '--max-age', '120']
    assert services['analyzer']['depends_on']['collector']['condition'] == 'service_healthy'
    assert services['analyzer']['depends_on']['qwen']['condition'] == 'service_healthy'
