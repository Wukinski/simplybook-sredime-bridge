from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
HOME = Path(__file__).resolve().parent
UTC = timezone.utc
BELGRADE = ZoneInfo('Europe/Belgrade')


class Review(Exception):
    """Fixed, non-PII reason code suitable for the operations interface."""


class Temporary(Exception):
    pass


class Uncertain(Exception):
    pass


def stamp(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.utcoffset() is None:
            raise ValueError()
        return result.astimezone(UTC)
    except (ValueError, TypeError, AttributeError):
        raise Review('invalid_aware_datetime') from None


def local_stamp(value: str) -> datetime:
    """REST has naive company times. Reject DST gaps AND ambiguous folds."""
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo:
            return dt.astimezone(UTC)
        first = dt.replace(tzinfo=BELGRADE, fold=0)
        second = dt.replace(tzinfo=BELGRADE, fold=1)
        if first.utcoffset() != second.utcoffset():
            raise ValueError()
        if first.astimezone(UTC).astimezone(BELGRADE).replace(tzinfo=None) != dt:
            raise ValueError()
        return first.astimezone(UTC)
    except (TypeError, ValueError):
        raise Review('ambiguous_or_invalid_company_time') from None


def company_time(value: str) -> str:
    instant = stamp(value)
    local = instant.astimezone(BELGRADE)
    formatted = local.strftime('%Y-%m-%d %H:%M:%S')
    # REST cannot disambiguate the repeated autumn hour.
    if local_stamp(formatted) != instant:
        raise Review('company_timezone_mismatch')
    return formatted


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def positive(value) -> int:
    if type(value) is not int or value <= 0:
        raise Review('invalid_target_id')
    return value


def mapping_source(value) -> str:
    """An exact webhook identifier, without decoding or native-ID fallback."""
    if (not isinstance(value, str) or not value or value != value.strip() or
            any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise Review('invalid_source_mapping_id')
    return value


def native_mapping_id(value) -> str:
    """Optional native UI metadata has no authority over webhook routing."""
    if not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]*', value):
        raise Review('invalid_native_mapping_id')
    return value


def csv_mapping_source(row, *, explicit):
    legacy = row.get('sredime_id', '').strip()
    if not explicit:
        return mapping_source(legacy) if legacy else ''
    source = row.get('sredime_webhook_id', '')
    if legacy and source != legacy:
        raise Review('conflicting_source_mapping_columns')
    return mapping_source(source) if source else ''


def unique_configuration(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Review('duplicate_configuration_key')
        result[key] = value
    return result


def affected_sources(settings, *snapshots, provider_ids=()):
    """Known source IDs including old/new staff; None means scope is unknown."""
    sources = set()
    for snapshot in snapshots:
        if isinstance(snapshot, dict):
            employee = snapshot.get('employee') or {}
            source = employee.get('id') if isinstance(employee, dict) else None
            if isinstance(source, str) and source:
                sources.add(source)
    for source, row in settings.employees.items():
        if row['id'] in provider_ids:
            sources.add(source)
    return sorted(sources) or None


@dataclass
class Settings:
    mode: str = 'simulation'
    state: Path = HOME / 'state'
    salon: str = 'studioandjelija'
    webhook_secret: str = ''
    simplybook_webhook_secret: str = ''
    admin_key: str = ''
    employees: dict = field(default_factory=dict)
    services: dict = field(default_factory=dict)
    clients: dict = field(default_factory=dict)
    allowed_employees: list = field(default_factory=list)
    policies: dict = field(default_factory=dict)
    approvals: dict = field(default_factory=dict)
    feed_tokens: dict = field(default_factory=dict)
    export_urls: dict = field(default_factory=dict)
    horizon_days: int = 60
    snapshot_max_age: int = 900
    schedule_max_age: int = 4500
    max_attempts: int = 8
    alerts_url: str = ''
    reads_enabled: bool = False
    require_subminute_availability: bool = True
    refresh_coalesce_seconds: int = 5
    expected_rest_base: str = ''
    pilot_client_ids: list = field(default_factory=list)
    pilot_service_ids: list = field(default_factory=list)
    schedule_service_ids: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None = None, *, read_only=False, isolated_profile=False):
        from dotenv import load_dotenv
        secret_file = os.getenv('BRIDGE_ENV_FILE')
        if secret_file:
            load_dotenv(secret_file)
        load_dotenv(HOME / '.env')
        if isolated_profile and not read_only:
            raise Review('isolated_profile_requires_read_only')
        path = path or Path(os.getenv('BRIDGE_CONFIG_FILE', str(HOME / 'config.local.json')))
        if isolated_profile and not path.is_file():
            raise Review('isolated_profile_file_required')
        data = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_configuration) if path.exists() else {}
        data['state'] = Path(os.getenv('BRIDGE_STATE', str(HOME / 'state')))
        for name, env in [('webhook_secret', 'SREDIME_WEBHOOK_SECRET'),
                          ('simplybook_webhook_secret', 'SIMPLYBOOK_WEBHOOK_SECRET'),
                          ('admin_key', 'BRIDGE_ADMIN_KEY'), ('alerts_url', 'BRIDGE_ALERTS_URL')]:
            data[name] = os.getenv(env, '')
        # Private feed URLs/tokens live only in ignored .env or secret-manager env.
        data['feed_tokens'] = json.loads(os.getenv('BRIDGE_FEED_TOKENS', '{}'))
        data['export_urls'] = json.loads(os.getenv('SREDIME_EXPORT_URLS', '{}'))
        config = cls(**data)
        for kind in ('employees', 'services'):
            if isolated_profile:
                continue
            table = HOME / 'mappings' / f'{kind}.local.csv'
            if not table.exists():
                continue
            with table.open(encoding='utf-8-sig', newline='') as handle:
                reader = csv.DictReader(handle)
                explicit = 'sredime_webhook_id' in (reader.fieldnames or [])
                rows = list(reader)
            mapping = {}
            targets = set()
            for row in rows:
                source = csv_mapping_source(row, explicit=explicit)
                if not source:
                    continue
                if source in mapping:
                    raise Review('duplicate_source_mapping')
                target = positive(int(row['simplybook_id']))
                if kind == 'employees' and target in targets:
                    raise Review('duplicate_employee_target')
                targets.add(target)
                mapping[source] = {'id': target, 'external_id': row.get('external_id', ''),
                                   'duration': int(row.get('duration_minutes') or 0),
                                   'timing_verified': row.get('timing_verified') == 'yes',
                                   'resources_verified': row.get('resources_verified') == 'yes'}
                native = row.get('sredime_native_id', '')
                if native:
                    mapping[source]['native_id'] = native_mapping_id(native)
            if getattr(config, kind) and getattr(config, kind) != mapping:
                raise Review('conflicting_' + kind + '_mapping_sources')
            setattr(config, kind, mapping)
        config.validate(read_only=read_only)
        return config

    def validate(self, *, read_only=False):
        if type(self.refresh_coalesce_seconds) is not int or not 1 <= self.refresh_coalesce_seconds <= 30:
            raise Review('invalid_refresh_coalescing_interval')
        if type(self.require_subminute_availability) is not bool:
            raise Review('invalid_subminute_requirement')
        if self.mode not in ('simulation', 'pilot', 'production'):
            raise Review('invalid_mode')
        if not 1 <= self.horizon_days <= 60:
            raise Review('unsupported_horizon')
        for kind in ('employees', 'services', 'clients'):
            mapping = getattr(self, kind)
            if not isinstance(mapping, dict):
                raise Review('invalid_' + kind + '_mapping')
            targets = set()
            for source, row in mapping.items():
                mapping_source(source)
                if kind == 'clients':
                    positive(row)
                    continue
                if not isinstance(row, dict):
                    raise Review('invalid_' + kind + '_mapping')
                target = positive(row.get('id'))
                if kind == 'employees' and target in targets:
                    raise Review('duplicate_employee_target')
                targets.add(target)
                if 'native_id' in row:
                    native_mapping_id(row['native_id'])
        for token in self.feed_tokens.values():
            if not isinstance(token, str) or len(token) < 32:
                raise Review('weak_feed_token')
        if self.mode != 'simulation' and not read_only:
            if self.mode == 'production' and self.require_subminute_availability:
                # The current ICS adapter has no bounded import or commit receipt.
                # Credentials or an approval flag cannot supply that capability.
                raise Review('subminute_availability_transport_not_available')
            required = ('live_writes', 'business_rules', 'hosting', 'privacy')
            if self.mode == 'production':
                required += ('notification_behavior', 'account_booking_trial', 'calendar_blocks_trial', 'empty_feed_trial')
            else:
                # SimplyBook is approved for testing; source scope must still
                # protect real SrediMe availability and controlled contacts.
                required += ('pilot_scope_reviewed',)
            if not all(self.approvals.get(key) is True for key in required):
                raise Review('live_approval_missing')
            if not self.allowed_employees:
                raise Review('employee_allowlist_required')
            if not re.fullmatch('[a-fA-F0-9]{64}', self.webhook_secret) or len(self.admin_key) < 32:
                raise Review('missing_private_credentials')
            if not self.reads_enabled:
                raise Review('live_reads_required')
            if self.mode == 'pilot' and (not self.pilot_client_ids or not self.pilot_service_ids):
                raise Review('pilot_test_clients_and_services_required')
            for value in self.pilot_client_ids + self.pilot_service_ids:
                positive(value)

    def target(self, kind: str, entity: dict) -> dict:
        row = getattr(self, kind).get(entity.get('id'))
        if not row:
            raise Review('unmapped_' + kind)
        positive(row['id'])
        external = entity.get('external_id')
        # external_id is a cross-check, never implicit authority over 490 rows.
        if external and row.get('external_id') != str(external):
            raise Review('external_id_mismatch')
        return row

    def action(self, status: int, event_type: str) -> str:
        if event_type == 'booking.deleted' or status in (-2, -101, -901):
            return 'cancel'
        if status == 1:
            return 'upsert'
        if status == 0:
            return {'hold': 'upsert', 'wait': 'wait'}.get(self.policies.get('pending'), 'review')
        if status == -902:
            return 'retain' if self.policies.get('no_show') == 'retain' else 'review'
        return 'review'
