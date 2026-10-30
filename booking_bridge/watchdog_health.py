"""Silent, bounded file healthchecks for diagnostic services; no repairs or network."""
import argparse
import json
import math
import time
from pathlib import Path

MAX_STATUS_BYTES = 8 * 1024 * 1024


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def _constant(value):
    raise ValueError()


def file_health(kind, path, *, now=None, max_age=None):
    """A fresh producer heartbeat is required; analyzer also needs all capabilities."""
    try:
        if kind not in ('collector', 'analyzer'):
            return False
        now = time.time() if now is None else now
        max_age = (90 if kind == 'collector' else 120) if max_age is None else max_age
        if not _number(now) or not _number(max_age):
            return False
        path = Path(path)
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_STATUS_BYTES:
            return False
        with path.open('rb') as handle:
            body = handle.read(MAX_STATUS_BYTES + 1)
        if len(body) > MAX_STATUS_BYTES:
            return False
        data = json.loads(body, object_pairs_hook=_unique, parse_constant=_constant)
        if not isinstance(data, dict) or type(data.get('schema_version')) is not int or data['schema_version'] != 1:
            return False
        timestamp = data.get('collected_at' if kind == 'collector' else 'updated_at')
        if not _number(timestamp) or not 0 <= now - timestamp <= max_age:
            return False
        if kind == 'collector':
            return True
        return (data.get('diagnostics_only') is True and data.get('repairs_enabled') is False and
                all(data.get(key) is True for key in (
                    'healthy', 'email_configured', 'last_model_ok', 'last_model_self_test_ok')))
    except (OSError, ValueError, TypeError, OverflowError):
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=('collector', 'analyzer'))
    parser.add_argument('--file', type=Path, required=True)
    parser.add_argument('--max-age', type=int)
    args = parser.parse_args(argv)
    return 0 if file_health(args.kind, args.file, max_age=args.max_age) else 1


if __name__ == '__main__':
    raise SystemExit(main())
