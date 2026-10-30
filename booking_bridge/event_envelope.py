"""Canonical source-envelope parsing without settings, application or DB setup."""
import json
import re

from fastapi import HTTPException

from .model import Review, stamp


def envelope(body, contacts_allowed=False):
    try:
        # Reject duplicate keys: different decoders must not disagree on identity/test.
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError()
                result[key] = value
            return result
        value = json.loads(body, object_pairs_hook=unique)
        if not isinstance(value, dict) or not re.fullmatch('[a-f0-9]{32}', value.get('id', '')):
            raise ValueError()
        if value.get('type') not in ('booking.created', 'booking.updated', 'booking.deleted'):
            raise ValueError()
        stamp(value['created_at'])
        if type(value.get('test', False)) is not bool:
            raise ValueError()
        value['test'] = value.get('test', False)
        data = value['data']
        if not isinstance(data, dict) or not isinstance(data.get('id'), str) or not data['id'] or len(data['id']) > 1024:
            raise ValueError()
        if type(data.get('status')) is not int:
            raise ValueError()
        # Preserve the booking snapshot and unknown status; discard notes and contact
        # fields that are unnecessary or not approved for this integration.
        value = {k: value[k] for k in ('id', 'type', 'created_at', 'test', 'data')}
        data = {k: data[k] for k in ('id', 'status', 'start_at', 'end_at', 'duration', 'service', 'employee', 'customer', 'changes') if k in data}
        for key in ('service', 'employee', 'customer', 'changes'):
            if key in data and not isinstance(data[key], dict):
                raise ValueError()
        if 'customer' in data:
            allowed = ('id', 'name', 'email', 'phone') if contacts_allowed else ('id',)
            data['customer'] = {k: data['customer'][k] for k in allowed if k in data['customer']}
        value['data'] = data
        return value
    except (KeyError, TypeError, ValueError, Review):
        raise HTTPException(400, 'invalid_event_envelope') from None
