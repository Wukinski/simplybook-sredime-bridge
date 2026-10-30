"""Build an explicit public operations bundle; never include private inputs."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile

PUBLIC_OPERATIONS = (
    'README.md', 'Dockerfile', 'requirements.lock.txt', 'operations.env.example',
    'backup.example.json', 's3-credentials.example.json',
    'monitor.host.example.json', 'monitor.external.example.json',
    'compose.host-operations.yaml', 'compose.external-monitor.yaml',
    'booking-bridge-offhost-backup.service', 'booking-bridge-offhost-backup.timer',
    'booking-bridge-offhost-restore-drill.service', 'booking-bridge-offhost-restore-drill.timer',
    'booking-bridge-host-monitor.service', 'booking-bridge-host-monitor.timer',
    'booking-bridge-external-monitor.service', 'booking-bridge-external-monitor.timer',
)
PUBLIC_FILES = ('booking_bridge/deploy/offhost_backup.py',
                'booking_bridge/deploy/operations_monitor.py',
                *('booking_bridge/deploy/operations/' + name for name in PUBLIC_OPERATIONS))


def make_bundle(workspace, output, manifest_path):
    workspace, output, manifest_path = Path(workspace).resolve(), Path(output), Path(manifest_path)
    if any(path.exists() or path.is_symlink() for path in (output, manifest_path)):
        raise ValueError('operations_output_exists')
    if any(not path.parent.is_dir() for path in (output, manifest_path)):
        raise ValueError('operations_output_parent_required')
    sources = []
    for relative in sorted(PUBLIC_FILES):
        path = workspace / relative
        if (path.is_symlink() or not path.is_file() or
                not path.resolve().is_relative_to(workspace) or path.stat().st_size > 4 * 1024 * 1024):
            raise ValueError('operations_public_source_invalid')
        sources.append((relative, path.read_bytes()))
    manifest = {}
    with output.open('xb') as destination:
        with tarfile.open(fileobj=destination, mode='w:gz') as archive:
            for relative, body in sources:
                entry = tarfile.TarInfo(relative)
                entry.mode, entry.size = 0o644, len(body)
                archive.addfile(entry, io.BytesIO(body))
                manifest[relative] = hashlib.sha256(body).hexdigest()
    with manifest_path.open('x', encoding='utf-8') as handle:
        json.dump(manifest, handle, indent=2); handle.write('\n')
    return {'files': len(manifest), 'archive_sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
            'archive_bytes': output.stat().st_size, 'private_inputs_included': False,
            'installed_or_activated': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(make_bundle(args.workspace, args.output, args.manifest)))
        return 0
    except Exception:
        print(json.dumps({'reason': 'operations_bundle_requires_review', 'installed_or_activated': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
