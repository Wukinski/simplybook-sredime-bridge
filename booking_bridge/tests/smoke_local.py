"""Real localhost HTTP + separate worker process; no account calls or live writes."""
import argparse
import hashlib
import hmac
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

from booking_bridge.model import HOME, ROOT


class SmokeDirectory(tempfile.TemporaryDirectory):
    def cleanup(self):
        # Windows can briefly retain a SQLite SHM handle after child exit.
        # Retry only our own bounded temporary tree; persistent failures still fail.
        target = Path(self.name).resolve()
        if target.parent != Path(tempfile.gettempdir()).resolve() or not target.name.startswith('booking-bridge-smoke-'):
            raise RuntimeError('Unexpected smoke temporary directory')
        for attempt in range(20):
            try:
                super().cleanup()
                return
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(.1)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, help='Optional JSON output path; stdout is always written')
    args = parser.parse_args(argv)
    processes = []
    report = {'mode': 'simulation', 'external_reads': False, 'external_writes': False}
    with SmokeDirectory(prefix='booking-bridge-smoke-') as folder:
        directory = Path(folder)
        config = directory / 'config.json'
        config.write_text((HOME / 'config.example.json').read_text(encoding='utf-8'), encoding='utf-8')
        import secrets
        signing_secret, admin_key = secrets.token_hex(32), secrets.token_urlsafe(48)
        env = dict(os.environ, BRIDGE_CONFIG_FILE=str(config), BRIDGE_STATE=str(directory / 'state'),
                   SREDIME_WEBHOOK_SECRET=signing_secret, BRIDGE_ADMIN_KEY=admin_key,
                   SIMPLYBOOK_WEBHOOK_SECRET='',
                   BRIDGE_FEED_TOKENS='{}', SREDIME_EXPORT_URLS='{}', BRIDGE_ALERTS_URL='')
        env.pop('BRIDGE_ENV_FILE', None)
        with socket.socket() as bound:
            bound.bind(('127.0.0.1', 0)); port = bound.getsockname()[1]
        origin = 'http://127.0.0.1:' + str(port)
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        try:
            api = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'booking_bridge.api:app',
                                    '--host', '127.0.0.1', '--port', str(port), '--no-access-log'],
                                   cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=flags)
            processes.append(api)
            deadline = time.monotonic() + 20
            while True:
                try:
                    if requests.get(origin + '/health/live', timeout=1).status_code == 200: break
                except requests.RequestException:
                    pass
                if time.monotonic() >= deadline: raise RuntimeError('Local API startup timeout')
                time.sleep(.1)
            worker = subprocess.Popen([sys.executable, '-m', 'booking_bridge', 'worker'], cwd=ROOT, env=env,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
            processes.append(worker)
            event = json.loads((HOME / 'fixtures/booking.created.json').read_text(encoding='utf-8'))
            event['test'] = True
            body = json.dumps(event, ensure_ascii=False, indent=2).encode()
            headers = {'Content-Type': 'application/json', 'X-SrediMe-Timestamp': '1',
                       'X-SrediMe-Signature': 'sha256=' + hmac.new(signing_secret.encode(), body, hashlib.sha256).hexdigest()}
            start = time.monotonic()
            response = requests.post(origin + '/sredime/webhook', data=body, headers=headers, timeout=3)
            report['ack_ms'] = round((time.monotonic()-start)*1000)
            report['accepted_status'] = response.status_code
            assert response.status_code == 202
            assert requests.post(origin + '/sredime/webhook', data=body, headers=headers, timeout=3).status_code == 202
            assert requests.post(origin + '/sredime/webhook', data=body, timeout=3).status_code == 401
            ops_headers = {'X-API-Key': admin_key}
            deadline = time.monotonic() + 10
            while True:
                rows = requests.get(origin + '/ops/events', headers=ops_headers, timeout=3).json()
                if rows and rows[0]['state'] == 'test': break
                if time.monotonic() >= deadline: raise RuntimeError('Local worker processing timeout')
                time.sleep(.1)
            assert len(rows) == 1
            deadline = time.monotonic() + 10
            while requests.get(origin + '/health/ready', headers=ops_headers, timeout=3).status_code != 200:
                if time.monotonic() >= deadline: raise RuntimeError('Local worker readiness timeout')
                time.sleep(.1)
            report.update({'deduplicated_rows': len(rows), 'final_state': rows[0]['state'],
                           'invalid_signature_status': 401, 'readiness_status': 200, 'status': 'passed'})
        finally:
            for process in reversed(processes):
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=5)
    if args.report:
        args.report.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__': main()
