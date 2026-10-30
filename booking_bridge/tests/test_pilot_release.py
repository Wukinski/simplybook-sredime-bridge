import hashlib
import json
import tarfile

from booking_bridge.deploy.build_pilot_release import make_release


def test_release_keeps_public_mapping_contract_and_excludes_private_account_data(tmp_path):
    root = tmp_path/'workspace'
    included = ['booking_bridge/api.py', 'booking_bridge/mappings/services.csv',
                'booking_bridge/mappings/employees.csv', 'booking_bridge/deploy/Dockerfile',
                'booking_bridge/deploy/ingress.env.example', 'booking_bridge/deploy/worker.env.example',
                'provider_assignment/client.py', 'provider_assignment/requirements.txt', '.dockerignore']
    private = ['booking_bridge/state/contacts.json', 'booking_bridge/secrets/pilot.env',
               'booking_bridge/.env', 'booking_bridge/.env.backup', 'booking_bridge/config.local.json',
               'booking_bridge/mappings/services.local.csv', 'booking_bridge/mappings/employees.local.csv',
               'booking_bridge/deploy/publisher-task.local.xml',
               'booking_bridge/deploy/prepare_publisher_task.ps1',
               'provider_assignment/state/tokens.json', 'service_importer/progress_log.json',
               'booking_bridge/unapproved-export.csv']
    for name in included+private:
        f=root/name;f.parent.mkdir(parents=True,exist_ok=True)
        f.write_text('PUBLIC' if name in included else 'DO_NOT_TRANSFER_PRIVATE_DATA',encoding='utf-8')
    archive, manifest = tmp_path/'release.tar.gz', tmp_path/'manifest.json'
    report=make_release(root,archive,manifest)
    hashes=json.loads(manifest.read_text(encoding='utf-8'))
    assert set(hashes)==set(included) and report['private_paths_excluded'] is True
    with tarfile.open(archive,'r:gz') as data:
        assert {member.name for member in data.getmembers()}==set(included)
        for member in data.getmembers():
            body=data.extractfile(member).read()
            assert b'DO_NOT_TRANSFER' not in body
            assert hashlib.sha256(body).hexdigest()==hashes[member.name]
