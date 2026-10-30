"""Build a source-only pilot archive; private state and credentials never enter it."""
import argparse
import hashlib
import io
import json
import tarfile
from pathlib import Path

SUFFIXES = {'.py', '.txt', '.json', '.md', '.yaml', '.conf', '.xml'}
EXCLUDED_DIRS = {'state', 'secrets', '__pycache__', '.pytest_cache'}
PUBLIC_TABLES = {'mappings/services.csv', 'mappings/employees.csv'}
PUBLIC_TEMPLATES = {'deploy/ingress.env.example', 'deploy/worker.env.example',
                    'deploy/diagnostic-smtp.env.example'}


def make_release(workspace, archive_path, manifest_path):
    workspace = Path(workspace).resolve()
    files = []
    for name in ('booking_bridge', 'service_importer', 'provider_assignment'):
        for file in (workspace/name).rglob('*'):
            if not file.is_file() or file.is_symlink():
                continue
            relative = file.relative_to(workspace)
            if (EXCLUDED_DIRS.intersection(relative.parts) or file.name.startswith('.env') or
                    file.name == 'config.local.json' or '.local.' in file.name):
                continue
            if name != 'booking_bridge':
                if len(relative.parts) != 2 or (file.suffix != '.py' and file.name != 'requirements.txt'):
                    continue
            elif (file.suffix.lower() not in SUFFIXES and file.name not in ('Dockerfile', 'Caddyfile') and
                  file.relative_to(workspace/'booking_bridge').as_posix() not in PUBLIC_TABLES | PUBLIC_TEMPLATES):
                continue
            files.append(file)
    dockerignore = workspace/'.dockerignore'
    if dockerignore.is_file():
        files.append(dockerignore)
    archive_path, manifest_path = Path(archive_path), Path(manifest_path)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {}
    with tarfile.open(archive_path, 'w:gz') as archive:
        for file in sorted(files):
            # Snapshot each file once: the manifest always describes the bytes
            # actually archived, even if a source editor writes concurrently.
            body = file.read_bytes()
            name = file.relative_to(workspace).as_posix()
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(body), 0o644
            archive.addfile(info, io.BytesIO(body))
            manifest[name] = hashlib.sha256(body).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    return {'files': len(manifest), 'archive_bytes': archive_path.stat().st_size,
            'archive_sha256': hashlib.sha256(archive_path.read_bytes()).hexdigest(),
            'private_paths_excluded': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(make_release(args.workspace, args.output, args.manifest)))


if __name__ == '__main__':
    main()
