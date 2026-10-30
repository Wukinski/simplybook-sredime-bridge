"""Host-only checks/backups for /opt/booking-bridge-pilot; no account API calls."""
import argparse
import json
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path('/opt/booking-bridge-pilot')


def backup():
    destination = ROOT / 'backups'
    destination.mkdir(mode=0o700, exist_ok=True)
    compose = ['docker', 'compose', '-f', str(ROOT / 'compose.yaml')]
    subprocess.run(compose + ['exec', '-T', 'worker', 'python', '-m', 'booking_bridge',
                   'backup', '--destination', '/state/host-backup.sqlite'], check=True)
    container = subprocess.check_output(compose + ['ps', '-q', 'worker'], text=True).strip()
    if not container or not container.isalnum():
        raise RuntimeError('single_worker_container_required')
    target = destination / ('bridge-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.sqlite')
    subprocess.run(['docker', 'cp', container + ':/state/host-backup.sqlite', str(target)], check=True)
    target.chmod(0o600)
    with sqlite3.connect(target.as_uri() + '?mode=ro', uri=True) as conn:
        if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('backup_integrity_failed')
    print(json.dumps({'local_backup': 'ok', 'integrity_check': 'ok',
                      'off_host_backup': False, 'encrypted_backup': False}))


def check():
    # This file is generated locally with a plain URL-safe key. Never print it.
    env = (ROOT / 'pilot.env').read_text()
    key = next((line.split('=', 1)[1].strip().strip("'\"") for line in env.splitlines()
                if line.startswith('BRIDGE_ADMIN_KEY=')), '')
    if len(key) < 32:
        raise RuntimeError('admin_key_missing')
    req = Request('http://127.0.0.1:8000/health/ready', headers={'X-API-Key': key})
    with urlopen(req, timeout=5) as response:
        if response.status != 200:
            raise RuntimeError('readiness_failed')
    print(json.dumps({'private_readiness': 'ok', 'external_alerts_configured': False}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['backup', 'check'])
    args = parser.parse_args()
    (backup if args.operation == 'backup' else check)()
