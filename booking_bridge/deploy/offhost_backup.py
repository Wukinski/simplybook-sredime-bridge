"""Encrypted, verified S3-compatible backups. No booking writes or restores.

This runner is dormant until an explicit private destination configuration is
supplied. It uses the existing authenticated recovery format and never uploads
the encryption key, plaintext database, local manifest, or provider credentials.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time
from urllib.parse import urlsplit
import uuid

from provider_assignment.core import lock
from booking_bridge import recovery
from booking_bridge.model import Review

MAX_OBJECT = recovery.MAX_BUNDLE_BYTES + len(recovery.MAGIC) + 28
NAME = re.compile(r'backup-([0-9]{8}T[0-9]{6}Z)-[a-f0-9]{32}\.enc')


def require(condition, code='offhost_configuration_invalid'):
    if not condition:
        raise Review(code)


def private_json(path, limit=65536):
    path = Path(path)
    require(not path.is_symlink() and path.is_file() and path.stat().st_size <= limit)
    if os.name != 'nt':
        require(stat.S_IMODE(path.stat().st_mode) & 0o077 == 0, 'offhost_private_permissions_required')
    return recovery._json(path.read_bytes())


def atomic_json(path, data):
    path = Path(path)
    require(not path.is_symlink() and path.parent.is_dir(), 'offhost_state_path_invalid')
    descriptor, temporary = tempfile.mkstemp(prefix='.backup-', dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600) if hasattr(os, 'fchmod') else None
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            json.dump(data, handle, sort_keys=True, allow_nan=False)
            handle.write('\n'); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def validate(config):
    required = {'source_database', 'key_file', 'spool_directory', 'credentials_file',
                'endpoint_url', 'region', 'bucket', 'prefix', 'destination_independent_of_source',
                'retention_days', 'keep_last', 'delete_expired', 'budget_files', 'budget_floors'}
    require(isinstance(config, dict) and set(config) == required)
    for key in ('source_database', 'key_file', 'spool_directory', 'credentials_file'):
        require(isinstance(config[key], str) and config[key] and '\x00' not in config[key])
    endpoint = urlsplit(config['endpoint_url'])
    require(endpoint.scheme == 'https' and endpoint.hostname and not endpoint.username and
            not endpoint.password and not endpoint.query and not endpoint.fragment and
            endpoint.path in ('', '/') and endpoint.hostname not in
            ('localhost', '127.0.0.1', '::1', '169.58.118.33', 'vmi3688215.contaboserver.net'))
    require(config['destination_independent_of_source'] is True,
            'offhost_independent_destination_required')
    require(isinstance(config['region'], str) and re.fullmatch(r'[A-Za-z0-9-]{1,63}', config['region']))
    require(isinstance(config['bucket'], str) and re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', config['bucket']))
    prefix = config['prefix']
    require(isinstance(prefix, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9/_.-]{0,126}/', prefix)
            and all(part not in ('', '.', '..') for part in prefix[:-1].split('/')))
    require(type(config['retention_days']) is int and 1 <= config['retention_days'] <= 3650)
    require(type(config['keep_last']) is int and 2 <= config['keep_last'] <= 10000)
    require(type(config['delete_expired']) is bool)
    for key in ('budget_files', 'budget_floors'):
        require(isinstance(config[key], list) and len(config[key]) <= 16 and
                all(isinstance(path, str) and path and '\x00' not in path for path in config[key]))
    return config


class S3Transport:
    """Restricted explicit credentials; verified HTTPS, finite SDK retries."""
    def __init__(self, config, *, client=None):
        self.config = validate(config)
        if client is None:
            credentials = private_json(config['credentials_file'], 16384)
            require(isinstance(credentials, dict) and
                    set(credentials) in ({'access_key_id', 'secret_access_key'},
                                         {'access_key_id', 'secret_access_key', 'session_token'}))
            require(all(isinstance(value, str) and value and len(value) <= 4096 and
                        not any(char in value for char in '\r\n\x00') for value in credentials.values()))
            try:
                import boto3
                from botocore.config import Config
            except ImportError:
                raise Review('offhost_s3_dependency_unavailable') from None
            session = boto3.session.Session(aws_access_key_id=credentials['access_key_id'],
                aws_secret_access_key=credentials['secret_access_key'],
                aws_session_token=credentials.get('session_token'), region_name=config['region'])
            client = session.client('s3', endpoint_url=config['endpoint_url'], verify=True,
                config=Config(signature_version='s3v4', connect_timeout=5, read_timeout=30,
                              request_checksum_calculation='when_required',
                              response_checksum_validation='when_required',
                              retries={'mode': 'standard', 'total_max_attempts': 2}))
        self.client = client

    def upload(self, key, body, digest):
        self.client.put_object(Bucket=self.config['bucket'], Key=key, Body=body,
                               ContentType='application/octet-stream',
                               Metadata={'ciphertext-sha256': digest}, IfNoneMatch='*')

    def download(self, key):
        response = self.client.get_object(Bucket=self.config['bucket'], Key=key)
        stream = response['Body']
        try:
            require(type(response.get('ContentLength')) is int and
                    0 < response['ContentLength'] <= MAX_OBJECT, 'offhost_download_size_invalid')
            pieces, total = [], 0
            while True:
                piece = stream.read(min(1024 * 1024, MAX_OBJECT - total + 1))
                if not piece:
                    break
                total += len(piece)
                require(total <= MAX_OBJECT, 'offhost_download_size_invalid')
                pieces.append(piece)
            require(total == response['ContentLength'], 'offhost_download_truncated')
            return b''.join(pieces)
        finally:
            stream.close()

    def objects(self):
        result, token = [], None
        for _ in range(10):
            options = {'Bucket': self.config['bucket'], 'Prefix': self.config['prefix'], 'MaxKeys': 1000}
            if token is not None:
                options['ContinuationToken'] = token
            page = self.client.list_objects_v2(**options)
            result.extend(item['Key'] for item in page.get('Contents', []))
            require(len(result) <= 10000, 'offhost_listing_limit')
            if not page.get('IsTruncated'):
                return result
            next_token = page.get('NextContinuationToken')
            require(isinstance(next_token, str) and next_token and next_token != token,
                    'offhost_listing_invalid')
            token = next_token
        raise Review('offhost_listing_limit')

    def delete(self, key):
        self.client.delete_object(Bucket=self.config['bucket'], Key=key)


def destination_fingerprint(config):
    return hashlib.sha256(json.dumps({key: config[key] for key in
        ('endpoint_url', 'region', 'bucket', 'prefix')}, sort_keys=True).encode()).hexdigest()


def verified_catalog(spool, config):
    """Only this destination's durable verified receipts count toward retention."""
    result = set()
    receipts = list(spool.glob('backup-*.enc.uploaded.json'))
    require(len(receipts) <= 10000, 'offhost_catalog_limit')
    for path in receipts:
        name = path.name.removesuffix('.uploaded.json')
        if not NAME.fullmatch(name) or path.is_symlink() or not path.is_file():
            continue
        data = private_json(path)
        key = config['prefix'] + name
        if (data.get('off_host_export_performed') is True and
                data.get('remote_readback_verified') is True and
                data.get('destination_fingerprint') == destination_fingerprint(config) and
                data.get('remote_reference') == hashlib.sha256(key.encode()).hexdigest() and
                data.get('remote_removed') is not True):
            result.add(key)
    return result


def retention_candidates(keys, config, now, verified_key, verified_keys):
    """Only generated names in the exact prefix; age AND minimum copies apply."""
    eligible = []
    prefix = config['prefix']
    for key in keys:
        if not isinstance(key, str) or not key.startswith(prefix) or key not in verified_keys:
            continue
        match = NAME.fullmatch(key[len(prefix):])
        if match is None:
            continue
        try:
            timestamp = datetime.strptime(match.group(1), '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
        if timestamp <= now + 5:
            eligible.append((timestamp, key))
    require(len({key for _, key in eligible}) == len(eligible), 'offhost_listing_invalid')
    require(verified_key in {key for _, key in eligible}, 'offhost_uploaded_object_not_listed')
    keep = {key for _, key in sorted(eligible, reverse=True)[:config['keep_last']]}
    cutoff = now - config['retention_days'] * 86400
    return [key for timestamp, key in sorted(eligible) if timestamp < cutoff and key not in keep and key != verified_key][:32]


def cleanup_local(spool, config, now, newest_name):
    """Prune only old local ciphertext with a matching verified-upload receipt."""
    candidates = []
    for path in spool.iterdir():
        match = NAME.fullmatch(path.name)
        if match is None or path.is_symlink() or not path.is_file():
            continue
        try:
            timestamp = datetime.strptime(match.group(1), '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
        if timestamp <= now + 5:
            candidates.append((timestamp, path))
    keep = {path.name for _, path in sorted(candidates, reverse=True)[:config['keep_last']]}
    cutoff, deleted = now - config['retention_days'] * 86400, 0
    for timestamp, path in sorted(candidates):
        if timestamp >= cutoff or path.name in keep or path.name == newest_name or deleted >= 32:
            continue
        receipt, manifest = Path(str(path) + '.uploaded.json'), Path(str(path) + '.manifest.json')
        if any(p.is_symlink() or not p.is_file() for p in (receipt, manifest)):
            continue
        evidence = private_json(receipt)
        expected = evidence.get('ciphertext_sha256')
        if not (evidence.get('off_host_export_performed') is True and
                evidence.get('remote_readback_verified') is True and
                evidence.get('destination_fingerprint') == destination_fingerprint(config) and
                isinstance(expected, str) and re.fullmatch('[a-f0-9]{64}', expected)):
            continue
        require(hashlib.sha256(recovery._bytes(path, MAX_OBJECT)).hexdigest() == expected,
                'offhost_local_retention_hash_mismatch')
        metadata = private_json(manifest)
        require(metadata.get('encrypted') is True and metadata.get('ciphertext_sha256') == expected,
                'offhost_local_retention_hash_mismatch')
        # Exact files under the checked spool only; no recursive deletion.
        path.unlink(); manifest.unlink()
        # Keep the small verification catalog after pruning local ciphertext;
        # it is still needed to apply a safe remote minimum-copy floor later.
        if evidence.get('remote_removed') is True:
            receipt.unlink()
        deleted += 1
    return deleted


def run_backup(config, *, transport_factory=S3Transport, clock=time.time, restore_drill=False):
    config = validate(config)
    now = clock()
    require(type(now) in (float, int) and 0 < now < 253402300799, 'offhost_clock_invalid')
    spool = Path(config['spool_directory'])
    require(not spool.is_symlink(), 'offhost_spool_invalid')
    spool.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(spool.is_dir(), 'offhost_spool_invalid')
    if os.name != 'nt':
        require(stat.S_IMODE(spool.stat().st_mode) & 0o077 == 0, 'offhost_private_permissions_required')
    status_path = spool / 'backup-status.json'
    with lock(spool / 'backup.lock'):
        stamp = datetime.fromtimestamp(now, timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        name = 'backup-' + stamp + '-' + uuid.uuid4().hex + '.enc'
        output, downloaded = spool / name, spool / ('.verify-' + uuid.uuid4().hex + '.enc')
        report = {'schema_version': 1, 'started_at': now, 'status': 'running',
                  'encrypted': True, 'off_host_export_performed': False,
                  'remote_readback_verified': False, 'restore_drill_performed': False,
                  'worker_start_allowed': False, 'booking_writes': 0, 'remote_deleted': 0,
                  'local_deleted': 0}
        atomic_json(status_path, report)
        if restore_drill:
            atomic_json(spool / 'restore-drill-status.json', report)
        try:
            recovery.backup(config['source_database'], output, config['key_file'],
                            budget_files=config['budget_files'], budget_floors=config['budget_floors'])
            verified = recovery.verify(output, config['key_file'])
            body = output.read_bytes()
            transport = transport_factory(config)
            key = config['prefix'] + name
            transport.upload(key, body, verified['ciphertext_sha256'])
            remote = transport.download(key)
            require(hashlib.sha256(remote).hexdigest() == verified['ciphertext_sha256'],
                    'offhost_remote_hash_mismatch')
            recovery._exclusive_write(downloaded, remote)
            readback = recovery.verify(downloaded, config['key_file'])
            require(readback == verified, 'offhost_remote_verification_mismatch')
            if restore_drill:
                # An owned isolated directory only; restore retains the durable hold.
                with tempfile.TemporaryDirectory(prefix='.restore-drill-', dir=spool) as directory:
                    require(Path(directory).resolve().is_relative_to(spool.resolve()),
                            'offhost_restore_directory_invalid')
                    restored_path = Path(directory) / 'held.sqlite'
                    restored = recovery.restore(downloaded, restored_path, config['key_file'])
                    require(restored['source_database_sha256'] == verified['database_sha256'] and
                            restored['worker_start_allowed'] is False and
                            recovery.recovery_start_allowed(restored_path) is False,
                            'offhost_restore_hold_invalid')
                report['restore_drill_performed'] = True
            report.update(off_host_export_performed=True, remote_readback_verified=True,
                          ciphertext_sha256=verified['ciphertext_sha256'],
                          database_sha256=verified['database_sha256'],
                          budget_files=verified['budget_files'], budget_floors=verified['budget_floors'],
                          destination_fingerprint=destination_fingerprint(config),
                          remote_reference=hashlib.sha256(key.encode()).hexdigest())
            # Durably record the verified upload BEFORE any retention deletion.
            atomic_json(spool / (name + '.uploaded.json'), report)
            candidates = retention_candidates(transport.objects(), config, now, key,
                                              verified_catalog(spool, config))
            report['remote_expired_candidates'] = len(candidates)
            if config['delete_expired']:
                for old_key in candidates:
                    transport.delete(old_key)
                    report['remote_deleted'] += 1
                    old_receipt = spool / (old_key[len(config['prefix']):] + '.uploaded.json')
                    evidence = private_json(old_receipt)
                    evidence['remote_removed'] = True
                    atomic_json(old_receipt, evidence)
                    if not (spool / old_key[len(config['prefix']):]).exists():
                        old_receipt.unlink()
                report['local_deleted'] = cleanup_local(spool, config, now, name)
            report.update(status='verified', completed_at=clock(), reason='ok')
            atomic_json(status_path, report)
            if restore_drill:
                atomic_json(spool / 'restore-drill-status.json', report)
            return report
        except Exception:
            # Network exceptions may contain endpoint URLs or credentials.
            report.update(status='failed', completed_at=clock(), reason='offhost_backup_requires_review')
            atomic_json(status_path, report)
            if restore_drill:
                atomic_json(spool / 'restore-drill-status.json', report)
            raise Review('offhost_backup_requires_review') from None
        finally:
            if downloaded.exists() and not downloaded.is_symlink():
                downloaded.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--restore-drill', action='store_true',
                        help='Also restore the downloaded backup into an isolated temporary hold')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(run_backup(private_json(args.config), restore_drill=args.restore_drill)))
        return 0
    except Exception:
        print(json.dumps({'status': 'failed', 'reason': 'offhost_backup_requires_review',
                          'worker_start_allowed': False, 'booking_writes': 0}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
