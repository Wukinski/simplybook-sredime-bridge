import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from booking_bridge.api import create_app
from booking_bridge.model import Review, Settings, company_time, local_stamp
from conftest import state


def signed(settings, body):
    return {'X-SrediMe-Signature': 'sha256=' + hmac.new(settings.webhook_secret.encode(), body, hashlib.sha256).hexdigest(),
            'X-SrediMe-Timestamp': '1', 'Content-Type': 'application/json'}


def test_raw_signature_accepts_old_unsigned_queue_time(settings, store, event):
    body = json.dumps(event, ensure_ascii=False, indent=2).encode()
    with TestClient(create_app(settings, store)) as app:
        assert app.post('/sredime/webhook', content=body, headers=signed(settings, body)).status_code == 202
        assert state(store, event)['state'] == 'queued'
        assert app.post('/sredime/webhook', content=body, headers=signed(settings, body)).status_code == 202
        assert len(store.rows('SELECT id FROM events')) == 1


@pytest.mark.parametrize('kind', ['missing', 'wrong', 'reencoded'])
def test_invalid_signature_never_persists(settings, store, event, kind):
    body = json.dumps(event).encode(); headers = signed(settings, body)
    if kind == 'missing': headers.pop('X-SrediMe-Signature')
    if kind == 'wrong': headers['X-SrediMe-Signature'] = 'sha256=' + '0' * 64
    if kind == 'reencoded': body += b' '
    with TestClient(create_app(settings, store)) as app:
        assert app.post('/sredime/webhook', content=body, headers=headers).status_code == 401
    assert not store.rows('SELECT id FROM events')


def test_private_notes_and_unapproved_contacts_not_stored(settings, store, event):
    event['data']['note'] = 'PRIVATE CUSTOMER NOTE'
    event['data']['internal_note'] = 'INTERNAL ONLY'
    event['data']['customer'].update(name='Personal Name', email='private@example.invalid', phone='1234')
    body = json.dumps(event).encode()
    with TestClient(create_app(settings, store)) as app:
        assert app.post('/sredime/webhook', content=body, headers=signed(settings, body)).status_code == 202
    payload = state(store, event)['payload']
    for secret in ['PRIVATE CUSTOMER', 'INTERNAL ONLY', 'Personal Name', 'private@example', '1234']:
        assert secret not in payload


def test_test_endpoint_is_accepted_but_never_written(settings, store, worker, gateway, event, now):
    event['test'] = True; body = json.dumps(event).encode()
    with TestClient(create_app(settings, store)) as app:
        assert app.post('/sredime/webhook', content=body, headers=signed(settings, body)).status_code == 202
    worker.once(now)
    assert state(store, event)['state'] == 'test' and not gateway.calls


@pytest.mark.parametrize('field,value', [('id', 'not-hex'), ('test', 'false'), ('type', 'booking.other'), ('created_at', '2026-10-21T10:00:00')])
def test_invalid_envelopes(settings, store, event, field, value):
    event[field] = value; body = json.dumps(event).encode()
    with TestClient(create_app(settings, store)) as app:
        assert app.post('/sredime/webhook', content=body, headers=signed(settings, body)).status_code == 400


def test_duplicate_json_keys_are_rejected(settings, store, event):
    body = json.dumps(event).encode().replace(b'"test": false', b'"test": true, "test": false')
    with TestClient(create_app(settings, store)) as app:
        assert app.post('/sredime/webhook', content=body, headers=signed(settings, body)).status_code == 400


def test_body_size_limit(settings, store):
    body = b' ' * 131073
    with TestClient(create_app(settings, store)) as app:
        assert app.post('/sredime/webhook', content=body, headers=signed(settings, body)).status_code == 413


def test_ops_auth_and_safe_retry(settings, store, event):
    store.ingest(event)
    store.finish(event['id'], 'review', 'unmapped_services')
    with TestClient(create_app(settings, store)) as app:
        assert app.get('/ops/events').status_code == 401
        headers = {'X-API-Key': settings.admin_key}
        result = app.get('/ops/events', headers=headers)
        assert result.status_code == 200 and 'payload' not in result.json()[0]
        assert app.post('/ops/events/' + event['id'] + '/retry', headers=headers).status_code == 200
        assert state(store, event)['state'] == 'queued'


def test_sb_signature_is_distinct_and_only_triggers_reads(settings, store):
    body = b'{"webhook_timestamp":1792570000,"signature_algo":"sha256","event":"new_booking"}'
    header = hmac.new(settings.simplybook_webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    with TestClient(create_app(settings, store)) as app:
        assert app.post('/simplybook/webhook', content=body, headers={'X-Signature': header}).status_code == 202
        assert store.get('sb-change-hint')[0] is True
        assert not store.rows('SELECT id FROM events')
        assert app.post('/simplybook/webhook', content=body, headers={'X-Signature': 'sha256=' + header}).status_code == 401


def test_signed_simplybook_receipt_is_auditable_without_storing_customer_payload(settings, store):
    value = {'webhook_timestamp': 1792570000, 'signature_algo': 'sha256', 'event': 'change_booking',
             'client': {'name': 'PRIVATE CLIENT', 'email': 'DO_NOT_STORE_EMAIL', 'phone': 'DO_NOT_STORE_PHONE'}}
    body = json.dumps(value).encode()
    header = hmac.new(settings.simplybook_webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    with TestClient(create_app(settings, store)) as app:
        for _ in range(2):
            assert app.post('/simplybook/webhook',content=body,headers={'X-Signature':header}).status_code==202
        assert app.post('/simplybook/webhook',content=body,headers={'X-Signature':'bad'}).status_code==401
    receipt, recorded = store.get('sb-webhook-receipt')
    assert receipt['signature_verified'] is True and receipt['receipt_count']==2
    assert receipt['event_type']=='change_booking' and receipt['algorithm_sha256'] is True
    assert recorded==store.get('sb-change-hint')[1]
    assert 'DO_NOT_STORE' not in json.dumps(store.rows('SELECT * FROM cache'))
    assert 'PRIVATE CLIENT' not in json.dumps(store.rows('SELECT * FROM cache'))
    assert not store.rows('SELECT * FROM events') and not store.rows('SELECT * FROM intents')


def test_ics_private_token_and_unready_feed(settings, store):
    with TestClient(create_app(settings, store)) as app:
        assert app.get('/ics/synthetic-employee-A/wrong.ics').status_code == 404
        assert app.get('/ics/synthetic-employee-A/' + 't' * 48 + '.ics').status_code == 503


def test_no_configuration_can_accidentally_enable_live_writes():
    config = Settings(mode='pilot')
    with pytest.raises(Review, match='live_approval'): config.validate()
    with pytest.raises(Review, match='unsupported_horizon'): Settings(horizon_days=61).validate()
    with pytest.raises(Review, match='weak_feed_token'): Settings(feed_tokens={'a': 'short'}).validate()


@pytest.mark.parametrize('timevalue', ['2026-10-25 02:30:00', '2026-03-29 02:30:00'])
def test_rest_rejects_ambiguous_and_nonexistent_dst_hours(timevalue):
    with pytest.raises(Review): local_stamp(timevalue)


def test_company_time_handles_summer_and_winter_offsets():
    assert company_time('2026-07-01T08:00:00Z') == '2026-07-01 10:00:00'
    assert company_time('2026-12-01T08:00:00Z') == '2026-12-01 09:00:00'
