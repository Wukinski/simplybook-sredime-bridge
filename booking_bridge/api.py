import hashlib
import hmac
import json
import re
import sqlite3
import time

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import Response, JSONResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict

from .calendar import feed_version, make_feed
from .event_envelope import envelope
from .model import Review, Settings, positive
from .store import Store

LIMIT = 131072


async def raw_body(request):
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > LIMIT:
            raise HTTPException(413, 'body_limit')
    return bytes(body)


def signature(body, supplied, secret, prefix=''):
    if not secret:
        return False
    expected = prefix + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.encode(), (supplied or '').encode())


class LinkRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    target: int
    verified_ownership: bool


def create_app(settings=None, store=None):
    settings = settings or Settings.load()
    store = store or Store(settings.state / 'bridge.sqlite')
    app = FastAPI(title='Andjelija booking connector', docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store

    @app.exception_handler(sqlite3.OperationalError)
    async def database_unavailable(request, exc):
        # A busy/full/unavailable DB is never a successful delivery acknowledgement.
        return JSONResponse({'detail': 'storage_temporarily_unavailable'}, status_code=503,
                            headers={'Retry-After': '2'})

    def admin(x_api_key: str = Header(default='')):
        if len(settings.admin_key) < 32 or not hmac.compare_digest(x_api_key.encode(), settings.admin_key.encode()):
            raise HTTPException(401, 'unauthorized')

    @app.get('/health/live')
    def live():
        return {'alive': True}

    @app.get('/health/ready', dependencies=[Depends(admin)])
    def ready():
        if not store.is_ready():
            raise HTTPException(503, 'operator_attention_required')
        return {'ready': True, 'mode': settings.mode}

    @app.post('/sredime/webhook', status_code=202)
    async def sredime(request: Request):
        body = await raw_body(request)
        if not signature(body, request.headers.get('x-sredime-signature'), settings.webhook_secret, 'sha256='):
            raise HTTPException(401, 'invalid_signature')
        # The timestamp is unsigned queue metadata. It is not a freshness gate.
        # Hours-old retries are accepted; signed event time orders the snapshots.
        value = envelope(body, settings.approvals.get('customer_contacts') is True)
        try:
            await run_in_threadpool(store.ingest, value)
        except Review:
            store.issue('webhook-collision', 'event_id_payload_collision')
            raise HTTPException(409, 'event_id_conflict') from None
        return {'received': True}

    @app.post('/simplybook/webhook', status_code=202)
    async def simplybook(request: Request):
        body = await raw_body(request)
        if not signature(body, request.headers.get('x-signature'), settings.simplybook_webhook_secret):
            raise HTTPException(401, 'invalid_signature')
        # Payload shape/event field is not sufficiently specified in current docs.
        # A signed delivery is ONLY a durable hint to re-read authoritative REST.
        try:
            payload = json.loads(body)
        except ValueError:
            raise HTTPException(400, 'invalid_json') from None
        def hint():
            # Coalesce state, not receipt: dropping hints could lose the last change.
            # Scheduler and transport separately enforce outbound request limits.
            now = time.time()
            # Keep a small auditable receipt, never the provider payload or its
            # customer fields. Receipt and hint share the acknowledgement commit.
            with store.connect() as conn:
                row = conn.execute('SELECT value FROM cache WHERE key=?',
                                   ('sb-webhook-receipt',)).fetchone()
                previous = json.loads(row['value']) if row else {}
                count = previous.get('receipt_count', 0) if isinstance(previous, dict) else 0
                count = count if type(count) is int and count >= 0 else 0
                event = payload.get('event') if isinstance(payload, dict) else None
                allowed = ('new_booking', 'change_booking', 'cancel_booking', 'new_client',
                           'change_client', 'delete_client', 'new_offer', 'new_invoice')
                receipt = {'signature_verified': True, 'receipt_count': count + 1,
                           'received_at': now, 'json_object': isinstance(payload, dict),
                           'timestamp_present': isinstance(payload, dict) and 'webhook_timestamp' in payload,
                           'algorithm_sha256': isinstance(payload, dict) and payload.get('signature_algo') == 'sha256',
                           'event_type': event if event in allowed else None}
                for key, value in [('sb-change-hint', True), ('sb-webhook-receipt', receipt)]:
                    conn.execute('INSERT OR REPLACE INTO cache VALUES(?,?,?)',
                                 (key, json.dumps(value), now))
        await run_in_threadpool(hint)
        return {'received': True}

    @app.get('/ics/{employee}/{token}.ics')
    def feed(employee: str, token: str):
        expected = settings.feed_tokens.get(employee, '')
        if not expected or not hmac.compare_digest(token.encode(), expected.encode()):
            raise HTTPException(404, 'not_found')
        try:
            body, count = make_feed(settings, store, employee)
        except Review as exc:
            store.issue('feed:' + employee, str(exc))
            raise HTTPException(503, 'calendar_temporarily_unavailable', headers={'Retry-After': '300'}) from None
        store.observe_feed_fetch(employee, feed_version(body), count)
        return Response(body, media_type='text/calendar; charset=utf-8',
                        headers={'Cache-Control': 'private, no-store', 'X-Robots-Tag': 'noindex, nofollow'})

    @app.get('/ops/events', dependencies=[Depends(admin)])
    def events():
        return store.rows('SELECT id,booking,state,reason,attempts,created,received,due FROM events ORDER BY received DESC LIMIT 200')

    @app.get('/ops/issues', dependencies=[Depends(admin)])
    def issues():
        return store.rows('SELECT * FROM issues WHERE resolved=0 ORDER BY updated DESC LIMIT 200')

    @app.get('/ops/intents', dependencies=[Depends(admin)])
    def intents():
        # Expose no client fields, raw responses, URLs, or secrets.
        return store.rows('SELECT booking,event,kind,target,result,state,started FROM intents ORDER BY started DESC LIMIT 200')

    @app.post('/ops/availability/{employee}/refresh', dependencies=[Depends(admin)], status_code=202)
    def refresh_availability(employee: str):
        if employee not in settings.allowed_employees:
            raise HTTPException(404, 'not_found')
        if not store.rate('manual-availability:' + employee, 1, window=60):
            raise HTTPException(429, 'refresh_already_requested', headers={'Retry-After': '60'})
        store.put('schedule-request:' + employee, True)
        store.put('sb-change-hint', True)
        return {'queued': True, 'import_confirmed': False}

    @app.get('/ops/availability', dependencies=[Depends(admin)])
    def availability():
        from .latency import employee_latency
        now = time.time()
        result = []
        for employee in settings.allowed_employees:
            ready, ready_at = store.get('feed-ready:' + employee)
            fetched, fetched_at = store.get('feed-last-served:' + employee)
            _, requested_at = store.get('refresh-scheduled:' + employee)
            result.append({'employee': employee, 'feed_ready_at': ready_at or None,
                           'refresh_scheduled_at': requested_at or None,
                           'feed_fetched_at': fetched_at or None,
                           'current_version_fetched': bool(ready and fetched and ready['version'] == fetched.get('version')),
                           'feed_ready_age_seconds': max(0, now-ready_at) if ready_at else None,
                           'import_confirmed': False, 'latency': employee_latency(store, employee, now)})
        return {'availability_target_seconds': 60, 'subminute_verified': False, 'employees': result}

    @app.get('/ops/availability/{employee}/history', dependencies=[Depends(admin)])
    def availability_history(employee: str, limit: int = Query(default=50, ge=1, le=200)):
        from .latency import observation
        if employee not in settings.allowed_employees:
            raise HTTPException(404, 'not_found')
        now = time.time()
        rows = store.rows('SELECT * FROM availability_observations WHERE employee=? ORDER BY id DESC LIMIT ?', (employee, limit))
        return {'measurement_scope': 'feed_ready_to_http_fetch', 'import_confirmed': False,
                'observations': [observation(row, now) for row in rows]}

    @app.post('/ops/events/{event}/retry', dependencies=[Depends(admin)])
    def retry(event: str):
        try:
            store.retry(event)
        except Review as exc:
            raise HTTPException(409, str(exc)) from None
        return {'queued': True}

    @app.post('/ops/source-feeds/{employee}/reset', dependencies=[Depends(admin)])
    def reset(employee: str):
        if employee not in settings.allowed_employees:
            raise HTTPException(404, 'not_found')
        store.execute('DELETE FROM feed_health WHERE employee=?', (employee,))
        return {'reset': True}

    return app


app = create_app()
