# Availability below one minute: research and implementation

## Current direction - 23 October 2026

The owner has approved testing on the currently unused SimplyBook account;
complete provider isolation is no longer a pilot prerequisite. Use supported
SrediMe webhooks/ICS and measure actual behavior now. Under 60 seconds is an
optimization target for the pilot, not an entry gate; support commitments and
import-completion guarantees are not prerequisites. Production activation,
customer-data safeguards, signatures, controlled contacts and recovery remain
separate. SrediMe real availability/customers must be protected.

The current decision register is [DECISION_CHECKLIST.md](../DECISION_CHECKLIST.md).
The current records are SrediMe employee 11772 / inactive service 233160 and
SimplyBook hidden provider 9 / hidden service 496. See the current progress and
`evidence/controlled-pilot-validation.json`. Earlier requirements and blockers
below are historical wherever they conflict with this direction.

## Prior checkpoint / historical detail


Research date: 2026-10-22. Required outcome: a change becomes effective in the
other system in **less than 60 seconds consistently**, including bookings,
cancellations, employee moves, breaks, manual blocks and opening-hours changes.
This replaces the earlier proposed five-minute/p95 target. It has not been met.

## What the supported interfaces establish

| Path | Evidence | Consequence |
| --- | --- | --- |
| SrediMe external ICS import | Supplied developer guide: approximately 15-minute polling, approximately 5 minutes with instant confirmation; timings are operational targets | Cannot establish a subminute bound |
| SrediMe early-refresh POST | Same guide: queues import for the next worker run; `refresh_scheduled` acknowledges scheduling only; at most 60 calls/employee/hour | Lower bridge delay helps, but provides no import deadline or completion receipt |
| SrediMe export GET | Same guide: at most 12 calls/employee/hour | Subminute source polling is unsupported |
| SrediMe booking webhooks | Same guide: asynchronous booking create/update/delete snapshots | Useful fast path; delivery timing, complete change coverage and runtime configuration need account validation |
| SimplyBook webhooks | Official REST webhook guide lists booking create/change/cancel; no schedule/break/block event is listed | Booking hints can accelerate REST reads; manual schedule changes still need polling or another supported event source |
| SimplyBook quota | Official API reference publishes 5,000 requests/day on common servers, at most two parallel and five/second | Repeated whole-account polling cannot provide the requested bound within this budget |

Sources:

- [SrediMe partner integration guide](https://www.sredime.com/developers/partner-integrations.html).
  Public retrieval was unavailable during this research; details above come from
  the supplied `C:/Users/aaaaz/Downloads/SrediMe for Developers.html`, saved from
  that URL, version 2026-09-10-1. Account applicability and current revision need
  SrediMe confirmation. No newer private contract has been inspected.
- [SrediMe partner information](https://www.sredime.rs/partner) and
  [marketplace information](https://www.sredime.rs/partner/marketplace) describe
  calendar integration, without a published subminute commitment.
- [SimplyBook REST webhook contract](https://help.simplybook.me/wiki/REST_API_webhooks).
  Raw-body HMAC verification is required; delivery retries have increasing delay.
- [SimplyBook API reference](https://simplybook.me/en/api/developer-api/ref).
  Confirm this account's actual quota and how MCP/other applications share it.

These are interface limitations, not evidence that a private SrediMe API exists.
No undocumented endpoints, browser automation or fabricated payload contracts
have been added.

## Implemented locally

- Signed SimplyBook hints permit an authoritative booking snapshot after ten
  seconds since the previous attempt. Hints arriving during a read remain pending;
  failures do not consume the hint. A separate limit allows 60 accelerated
  snapshots per rolling hour; the five-minute reconciliation fallback remains.
  Snapshot pagination still counts each underlying call against the transport cap.
- Every valid signed hint updates a single durable cache entry. Outbound limits
  apply in the scheduler, avoiding loss of the final change in a webhook burst.
- The first SrediMe refresh notification is immediately eligible after complete,
  fresh feed validation. Subsequent attempts coalesce over five seconds by default
  (`refresh_coalesce_seconds`, valid range 1–30). The rolling 60/hour cap remains;
  the earlier mandatory 60-second gap was our implementation choice, not a stated
  provider requirement, and has been removed. Bursts preserve a trailing notification,
  including changes arriving during the HTTP request and process restarts.
  Temporary failure retries start after five seconds with exponential backoff to
  120 seconds; invalid/stale feeds are rechecked after the coalescing interval.
  Every HTTP attempt consumes allowance, including failures. Quota exhaustion
  persists the next eligible time and opens an incident; it is never a silent pass.
- Source booking copies request a durable feed recheck, not an unconditional POST.
  If outbound occupancy is unchanged, no refresh allowance is consumed. Feed hash,
  timing observation and pending notification are committed atomically.
- Full schedule scans are durable jobs. Each scheduler step makes at most one
  provider-reference or calendar-week call, with booking work between steps.
  Full coverage is validated before publication. The worker checks scheduler work
  each second; network calls, pagination and retries can still take longer.
- Full schedule scans remain hourly. Between full scans, the first two calendar
  weeks are checked every 15 minutes. A near-week merge preserves the timestamp
  of the full snapshot, so distant dates cannot appear artificially fresh.
  Jobs restart when the date horizon, provider or reference service changes.
- Authenticated `POST /ops/availability/{employee}/refresh` prioritizes an enabled
  employee's schedule scan and requests a booking reread. It queues local work,
  permits one request per employee per minute, and performs no remote work in the
  HTTP handler. It does not bypass freshness, quotas or approval requirements.
- Authenticated `GET /ops/availability` reports feed-ready, refresh-scheduled and
  feed-fetched stages. An occupancy hash identifies the exact fetched version,
  ignoring DTSTAMP changes. `import_confirmed` and `subminute_verified` remain
  false: fetching a feed is not proof that SrediMe applied its contents.
- Authenticated `GET /ops/availability/{employee}/history` exposes up to 200
  observations with first refresh-acceptance and HTTP-fetch timestamps. History
  survives restart and retains seven days plus the latest per employee. Initial
  snapshots/upgrade backfills are baselines, not evidence of a real source change.
  Repeated content A→B→A has separate observations. Exactly 60 seconds is a miss;
  superseded versions without a fetch remain visible and are never counted as
  passes. Clock anomalies are marked rather than reported as valid fast delivery.
- A queued source event older than ten seconds opens a local processing incident.
  A latest feed without an observed fetch after 60 seconds opens a fetch incident.
  These guards cannot remotely stop SrediMe booking; they expose local problems
  and missing observations. An observed HTTP fetch does not identify the caller
  as SrediMe or prove completion of its import.
- `require_subminute_availability` defaults to true. With the current ICS adapter,
  production startup and production preflight reject that requirement with
  `subminute_availability_transport_not_available` /
  `subminute_availability_transport`. Pilot measurements remain possible after
  their existing safeguards are satisfied. Disabling the requirement would accept
  a different product requirement; it would not improve or certify this adapter.

None of these changes enables live reads/writes, creates remote records, installs
webhook subscriptions or exposes a public endpoint. The local profile remains in
simulation. Existing provider-isolation safeguards remain in place.

## API budget and remaining local limits

For six employees and a 60-day horizon, a full scan needs roughly 60–66 reads.
Hourly scans cost roughly 1,440–1,584/day. Three intervening near scans per hour
at three reads/employee add roughly 1,296/day. Booking fallback adds at least
288/day, and 494-service buffer inventory typically adds around 120/day.
That is roughly 3,144–3,288/day before accelerated snapshots, mutations, auth,
pagination changes and retries. Accelerated snapshots may add up to 1,440/day
before pagination. At high activity this can exceed the shared 4,500/day local
safety cap. The cap is retained; this is not a reserved production capacity plan.
Other clients and MCP usage are not all visible to the local counter.

The 15-minute near scan improves ordinary delay; it is not a route to subminute
availability. Polling just one week for six employees every 30 seconds would
already require 17,280 reads/day, before reference reads and all other work.
No faster unsupported polling setting has been introduced.

Inventory and booking background reads now use a separate read-only facade with
2-second connect / 4-second read timeouts and one HTTP GET attempt per call. Before
each read, the singleton worker services booking work, rechecks changed feeds and
flushes eligible refreshes. Private source-feed polling also yields between
employees. Source events can therefore progress between inventory pages. Snapshot
  drift updates use a transactional comparison so a pre-yield observation cannot
  raise or clear drift after local linkage/applied state changes.

Failed background snapshots/inventories become eligible again after ten seconds
instead of waiting their full five-minute/hourly interval. Accelerated recovery
is limited to 12 attempts/task/rolling hour, persisted across restart; booking
recovery also shares the 60/hour accelerated snapshot allowance. Normal fallback
checks remain. Schedule steps retain their separate 60-second error backoff.

There is still one mutation owner. Foreground validation/writes retain their
existing transport policy and ambiguous-result safeguards. Work remains
synchronous: in-flight requests, authentication, mutation verification, large
reconciliation batches and another job using the shared transport can still
delay work. Socket timeout values are not hard end-to-end deadlines. No supported
remote delivery/import guarantee is supplied by these local improvements.

Five-second coalescing can absorb ordinary bursts without imposing a minute's
delay, but it cannot sustain more than 60 refresh attempts/employee/hour. A stream
of changes may exhaust the allowance within several minutes. The pending state
and quota incident remain visible; increasing polling or bypassing the cap is
not a valid solution. A changed feed might be fetched by an already queued
import, but no version-consumption guarantee is assumed.

## What can actually meet the requirement

SrediMe must confirm a supported synchronous availability/block update interface
with a commit receipt and bounded propagation to all customer booking surfaces,
or a contracted expedited import path with a deadline and import receipt.
Reliable source events must cover every availability-changing operation on both
systems, including manual blocks and schedules. Otherwise editing those fields
must move to a controlled path that publishes the change immediately.

A synchronous availability recheck plus an atomic hold/reservation before booking
confirmation can address conflicts during propagation. It does **not** by itself
make the displayed calendar update within a minute. Both requirements must be
specified separately with SrediMe. An optimistic precheck followed by independent
writes leaves a race; it is not an atomic reservation.

No finite propagation deadline can be guaranteed through an arbitrary outage.
The agreed contract must specify degraded behavior: prevent confirmation or mark
the affected employee unavailable when authoritative freshness/commit cannot be
proved, and define recovery. Our 503 or stopped worker does not remotely close
SrediMe availability by itself; that behavior needs provider support and testing.

## Acceptance evidence still needed

Record synchronized source commit, webhook receipt, bridge application,
feed/version readiness, refresh acceptance, actual import commit and visible
customer availability timestamps. Count every case at or above 60 seconds as a
failure; do not replace the requirement with p95, an average, or POST duration.
Test both directions, boundary timing just after polling/refresh, simultaneous
bookings, reassignment, cancellation/last-block removal, shifts, breaks, resources,
DST, webhook retries, bursts above one change/minute, restart and quota exhaustion.
Repeated successful trials alone do not establish a delivery guarantee without a
supported provider contract. All live tests require the isolated pilot scope.

See [SREDIME_ACCESS_REQUIRED.md](SREDIME_ACCESS_REQUIRED.md) for the access and
provider answers needed to continue.

## Follow-up blocker review ? 2026-10-22

Current official SimplyBook schema/webhook documentation and connected tool
capabilities were rechecked. No bounded import-completion interface or full
schedule/block event coverage was established. Prepared, unsent requests and the
schema/account isolation discrepancy are in [PROVIDER_SUPPORT_REQUESTS.md](PROVIDER_SUPPORT_REQUESTS.md).
The exact candidate scope is in [PILOT_MAPPING_REVIEW.md](PILOT_MAPPING_REVIEW.md);
public-host prerequisites are in [deploy/PILOT_RUNBOOK.md](deploy/PILOT_RUNBOOK.md).
Authentication is complete. The remaining dependency is provider capability,
verified isolation and live-test setup, not another login or polling optimization.
