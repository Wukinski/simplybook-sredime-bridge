# Provider requests — prepared, not sent

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


22 October 2026. No support message has been sent. Existing test preparation and
callback configuration authorization remains valid; these requests need explicit
authorization to send, or the owner can send the text directly.

## SrediMe / Buker

Subject: Supported subminute availability interface and isolated integration test

We are integrating Studio Anđelija SG (vendor 1404) with SimplyBook.me. Every
availability change must become effective on the other booking surface in less
than 60 seconds, including cancellations, staff moves, shifts and manual blocks.
The supplied partner guide (2026-09-10-1) describes asynchronous ICS imports;
refresh acceptance and HTTP fetch are insufficient to establish completion.

Please provide:

1. A supported availability update API or expedited import contract with a maximum
   propagation delay, version-specific completion receipt, authentication,
   idempotency and account/package eligibility. If none exists, please confirm.
2. Complete availability-change event coverage, delivery bound, ordering/replay
   and retry behavior, including manual blocks, schedules, resources and timing.
3. Current GET/POST quotas, minimum spacing if any, sustained burst capacity and
   whether a queued import consumes the latest version. Confirm empty-feed and
   last-block removal behavior, failed-import backoff and recovery/reset.
4. Behavior when freshness cannot be proved: supported remote closing/reopening
   and, separately, any atomic external availability check-and-hold before booking.
5. An isolated employee/test scope, webhook signing-secret setup and import
   diagnostics suitable for timed tests without affecting real customers.

Answers 1–3 block transport design and a credible subminute acceptance contract.
Answer 4 blocks safe outage behavior. Answer 5 blocks real payload/import trials.
An atomic hold alone would not establish the displayed-availability deadline.

## SimplyBook.me

Subject: Provider isolation contract discrepancy and availability-change events

For account studioandjelija, an authorized hidden test provider (ID 8) was created
with `services: []`, but it inherited 12 existing services; PUT with the same
field did not clear them. We deleted only that new provider and restored the
baseline. No pilot bookings were created. We must not alter existing assignments.

The public OpenAPI schema retrieved on 22 October explicitly says an empty
`ProviderWritableEntity.services` array clears connections. MCP create/update
provider tools expose visibility but no service-assignment parameter.

1. Explain the discrepancy and provide the supported atomic procedure for a new
   hidden provider with zero inherited existing services. Is this account-specific
   behavior or a schema/implementation defect? Provide an account-applicable fix
   or isolated test environment before we retry provisioning.
2. Confirm exclusion from all customer booking paths, including Any Employee,
   widgets and direct links, throughout creation/setup. UI assignment controls
   after creation do not prove absence of an exposure window. Specify read-back
   and public availability checks that establish isolation.
3. Provide supported events for schedule/break/manual-block/resource/service-time
   changes, delivery bounds and replay/recovery. The current webhook event list
   documents bookings but does not establish these changes or a delivery deadline.
4. Confirm this account's shared REST/MCP quota and throttling behavior, and any
   supported capacity needed for the resulting design. No paid upgrade requested.

Answers 1–2 block pilot provisioning. Answers 3–4 block complete, bounded change
coverage and capacity planning. No isolation flag will be manually asserted.

## Evidence and capability review

- [Fresh public OpenAPI snapshot](evidence/admin-openapi-recheck.json): retrieved
  with unauthenticated GET, HTTP 200; `services: []` contract contradicts the
  recorded account result. [Original trial](evidence/pilot-provisioning-check.json).
- [Official provider setup](https://help.simplybook.me/wiki/Adding_services,_providers_and_availability(new_interface))
  documents service attachment through the UI, but supplies no atomic isolated
  creation guarantee. Cloning existing staff/services is not an isolation proof.
- [Official visibility clarification](https://tech-support.simplybook.me/t/724-if-i-set-providers-hidden-for-website-does-that-mean-provider-is-not-active/730)
  distinguishes hidden from inactive; it does not certify Any Employee isolation.
- [Current webhook contract](https://help.simplybook.me/wiki/REST_API_webhooks):
  booking create/change/cancel events, signed raw bodies, increasing retry delays
  with eventual retry termination; no published maximum delivery delay.
- [Official API quota](https://simplybook.me/en/api/developer-api/ref): common
  servers 5,000/day, two concurrent, five/second. Account applicability still needs
  confirmation; the local 4,500/day guard remains.
- SrediMe's public developer URL remained inaccessible through web retrieval.
  The supplied local guide remains the evidence, not a freshly confirmed contract.
  See [availability research](AVAILABILITY_LATENCY.md).
- Available connected capabilities were inspected: SimplyBook provider reads and
  schedule reads/writes exist; no SrediMe connector, import-completion method or
  SimplyBook schedule-change subscription tool was found. Tool absence does not
  prove the provider has no other supported interface.

No supported method establishing safe isolation or consistently subminute
availability was found in this review. The correct next implementation depends
on these answers; neither a guessed API nor another optimization pass resolves it.
