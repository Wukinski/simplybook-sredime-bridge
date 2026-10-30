"""Offline review ledger bound to an exact production profile; no approval is inferred.

Artifacts are operator-reviewed evidence, not automatic proof of a remote fact.
Only hashes, fixed gate codes and statuses leave this module. Missing, changed
or stale evidence keeps production closed; it never alters configuration flags.
"""
import argparse
import hashlib
import json
import math
import os
import time
from pathlib import Path

from .model import Review, Settings, digest, stamp, unique_configuration

GATES = ('state_reconciliation', 'identity_mappings', 'business_rules',
         'notification_delivery', 'original_created_delivery', 'availability_latency',
         'empty_feed_removal', 'external_monitoring', 'encrypted_off_host_restore',
         'tls_renewal', 'linux_http_validation', 'soak_72h',
         'server_credentials_review', 'diagnostic_qwen_readonly', 'diagnostic_email_delivery', 'activation')
MAX_MANIFEST = 65536
MAX_ARTIFACT = 8 * 1024 * 1024
MAX_TOTAL_ARTIFACTS = 16 * 1024 * 1024
MAX_AGE = 7 * 86400


def profile_digest(settings):
    return digest({name: getattr(settings, name) for name in (
        'mode', 'reads_enabled', 'salon', 'employees', 'services', 'clients', 'allowed_employees', 'policies',
        'approvals', 'schedule_service_ids', 'horizon_days', 'snapshot_max_age',
        'schedule_max_age', 'expected_rest_base', 'require_subminute_availability',
        'refresh_coalesce_seconds', 'max_attempts')})


def template(settings=None):
    return {'schema_version': 1, 'profile_digest': profile_digest(settings) if settings else None,
            'checks': {code: {'status': 'pending', 'reviewed': False, 'artifact': None,
                             'sha256': None, 'observed_at': None} for code in GATES}}


def inspect_evidence(settings, path=None, *, now=None):
    now = time.time() if now is None else now
    path = Path(path) if path else None
    rows = [{'code': 'production_' + code, 'ok': False, 'status': 'missing'} for code in GATES]
    manifest_ok = False
    try:
        if path is None or path.is_symlink() or path.stat().st_size > MAX_MANIFEST:
            raise ValueError()
        data = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_configuration)
        if (set(data) != {'schema_version', 'profile_digest', 'checks'} or
                type(data['schema_version']) is not int or data['schema_version'] != 1 or
                data['profile_digest'] != profile_digest(settings) or
                not isinstance(data['checks'], dict) or set(data['checks']) != set(GATES) or
                type(now) not in (int, float) or not math.isfinite(now) or now <= 0):
            raise ValueError()
        manifest_ok = True
        root = path.parent.resolve()
        artifact_hashes, total_bytes = {}, 0
        for row, code in zip(rows, GATES):
            entry = data['checks'][code]
            row['status'] = 'invalid'
            try:
                if not isinstance(entry, dict) or set(entry) != {
                        'status', 'reviewed', 'artifact', 'sha256', 'observed_at'}:
                    raise ValueError()
                if entry['status'] == 'pending' and entry['reviewed'] is False:
                    row['status'] = 'pending'
                    continue
                if (entry['status'] != 'verified' or entry['reviewed'] is not True or
                        not isinstance(entry['artifact'], str) or not entry['artifact'] or
                        not isinstance(entry['sha256'], str) or len(entry['sha256']) != 64 or
                        any(c not in '0123456789abcdef' for c in entry['sha256'])):
                    raise ValueError()
                age = now - stamp(entry['observed_at']).timestamp()
                if age < 0 or age > MAX_AGE:
                    row['status'] = 'expired'
                    continue
                relative = Path(entry['artifact'])
                artifact = root / relative
                if (relative.is_absolute() or '..' in relative.parts or
                        artifact.is_symlink() or not artifact.resolve().is_relative_to(root) or
                        artifact.resolve() == path.resolve() or artifact.stat().st_size > MAX_ARTIFACT):
                    raise ValueError()
                resolved = artifact.resolve()
                if resolved not in artifact_hashes:
                    total_bytes += artifact.stat().st_size
                    if total_bytes > MAX_TOTAL_ARTIFACTS:
                        raise ValueError()
                    artifact_hashes[resolved] = hashlib.sha256(artifact.read_bytes()).hexdigest()
                if artifact_hashes[resolved] != entry['sha256']:
                    row['status'] = 'changed'
                    continue
                row.update(ok=True, status='reviewed')
            except (OSError, ValueError, TypeError, KeyError, Review):
                pass
    except (OSError, ValueError, TypeError, KeyError, AttributeError, Review, OverflowError):
        pass
    checks = [{'code': 'production_evidence_manifest', 'ok': manifest_ok,
               'status': 'reviewed' if manifest_ok else 'missing_or_invalid'}, *rows]
    return {'ready': all(row['ok'] for row in checks), 'checks': checks,
            'external_validation_performed': False}


def require_production_evidence(settings):
    if settings.mode == 'production':
        path = os.getenv('BRIDGE_PRODUCTION_READINESS_FILE')
        if not inspect_evidence(settings, path)['ready']:
            raise Review('production_evidence_incomplete_or_expired')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--template', action='store_true')
    mode.add_argument('--check', action='store_true')
    parser.add_argument('--config', type=Path)
    parser.add_argument('--readiness', type=Path)
    args = parser.parse_args(argv)
    try:
        settings = (Settings.load(args.config, read_only=True, isolated_profile=True)
                    if args.config else None)
        if args.template:
            print(json.dumps(template(settings), indent=2))
            return 0
        if settings is None:
            raise Review('explicit_profile_required')
        result = inspect_evidence(settings, args.readiness)
        print(json.dumps(result))
        return 0 if result['ready'] else 2
    except (OSError, ValueError, TypeError, Review):
        print(json.dumps({'ready': False, 'reason': 'production_readiness_unavailable'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
