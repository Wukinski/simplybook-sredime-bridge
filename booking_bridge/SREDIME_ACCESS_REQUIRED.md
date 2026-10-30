# Work blocked by SrediMe access or provider confirmation

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


Updated 2026-10-22. Required end-to-end availability delay: consistently **<60s**.
Account access is now available: authentication succeeded and account identity,
employee IDs, export URLs, resources, booking mode and webhook controls were
inspected. See [SREDIME_ACCOUNT_REVIEW.md](SREDIME_ACCOUNT_REVIEW.md). Local export
URLs and mapping-review artifacts are prepared; no business settings were changed.
The current ICS contract cannot establish that requirement. Local improvements
are described in [AVAILABILITY_LATENCY.md](AVAILABILITY_LATENCY.md).
No support message has been sent and no SrediMe settings have been changed.

## Access step completed; configuration still pending

The authorized Buker session was used to inspect **Employees > employee >
integration fields** and salon webhook settings. Identity and full access were
confirmed. Review the generated mapping candidates before configuring anything. Store private
URLs, signing secrets and tokens in the ignored local environment/secret manager;
do not paste passwords or tokenized URLs into chat or this document.

Account access alone may not remove the timing limitation. The first provider
question is whether SrediMe offers a supported interface that can satisfy the
deadline; do not enable production on the assumption that early-refresh POST does.

## Items requiring the Buker account

| Item | Work to complete with access | Evidence needed |
| --- | --- | --- |
| Salon and employee identity | Verify salon, employee IDs and exact mapping to SimplyBook providers | Reviewed allowlist and mappings; no inferred identity from names alone |
| Services and resources | Verify service IDs, duration, buffers, shared resources and employee assignments | Approved mapping and timing/resource trials |
| Employee ICS settings | Inspect existing integrations before changing them; obtain private export URLs and configure approved bridge import URLs only for isolated pilot staff | Per-employee import/export setup and successful fetch; keep secrets out of evidence |
| Webhooks | Inspect current subscriptions, select booking create/update/delete, configure approved public HTTPS receiver and signing secret, run Buker Test | Valid signature, durable 202 and real payload shape; Test creates no live booking |
| Actual event semantics | Verify booking IDs, employee moves, pending, no-show, cancellations, retries and events from all booking channels | Sanitized schema and isolated test results; no invented statuses or notification assumptions |
| Import operation | Inspect importer state/backoff, enabled instant confirmation and any last-import information | Actual fetch/import timestamps and which booking surfaces changed |
| Empty feed and last block | Test removing the last imported event, empty/invalid response handling and recovery/reset | Verified removal semantics; no fake placeholder event |
| Live latency | Perform isolated trials across the timing boundaries listed in AVAILABILITY_LATENCY.md | Source commit to actual visible availability and conflict behavior in both directions |
| Business rules and notifications | Confirm pending/no-show treatment, editing authority, client consent and which system sends each notification | Approved decisions plus trials showing no duplicate customer notifications |

## Answers/documents needed from SrediMe

These questions are prepared for the owner or an explicitly authorized support
conversation. They have not been sent.

1. Is there a supported API to create/update/remove employee availability blocks
   synchronously? Provide authentication/scopes, schema, idempotency behavior,
   rate limits, commit acknowledgement and propagation deadline to website,
   widget, app and Buker. Are those capabilities enabled for this salon/package?
2. If ICS is the only path, can you contractually keep source change to effective
   availability below 60 seconds? What is the maximum early-refresh queue delay,
   and can we receive an import completion/version acknowledgement? A response
   containing `refresh_scheduled: true` is insufficient evidence.
3. The supplied guide limits POST to 60/employee/hour. We now coalesce short bursts
   without imposing a full-minute gap. Is there a separate minimum spacing rule,
   and what supported API/capacity handles sustained traffic above this allowance?
   Can an outstanding import consume the newest version, and how is that version
   acknowledged before the 60-second deadline?
4. Can SrediMe call an authoritative availability check and acquire an atomic
   external hold before confirming a booking? Specify hold expiry, idempotency,
   concurrent booking protection, failure behavior and reconciliation. Does the
   displayed availability also update promptly, independently of confirmation?
5. Do events cover employee shifts, breaks, manual blocks, resources, leave and
   service timing changes as well as bookings? Provide a delivery deadline,
   retries, ordering/deduplication identifiers and recovery/replay mechanism.
6. If an import or authoritative check is unavailable/stale, can the affected
   employee stop accepting bookings until freshness is restored? What does the
   customer see, and how is reopening acknowledged?
7. Confirm the current guide revision, salon-specific quotas, instant-confirmation
   behavior, empty-feed/last-block removal and how to reset stopped imports.
8. Can you provide a test salon/employee scope, import diagnostics and an
   availability/booking sandbox so simultaneous and failure tests do not affect
   real customers?

Do not change notification or confirmation policy as a workaround without the
owner's business decision. Manual confirmation can reduce conflict impact but
does not meet the displayed-availability timing requirement.

## Other prerequisites (SrediMe login cannot resolve these)

- SimplyBook test-provider isolation is still blocked: REST ignores `services: []`.
  The earlier newly created provider was rolled back. See PILOT_SETUP_REVIEW.md;
  do not retry provisioning or set the isolation approval without proof.
- SimplyBook needs a supported event path for manual schedule/break/block changes,
  or a reviewed operational restriction that routes those edits through an
  immediately publishing path. Its documented booking webhook list does not
  establish this coverage. Actual signed booking payloads still need verification.
- Verify SimplyBook quota shared by all clients/MCP, and any supported increase
  if the final design needs it. No paid plan change is authorized here.
- An approved always-on host, domain/DNS, public HTTPS, secret storage, monitoring,
  backup/restore and outage response remain necessary. Local Docker availability
  does not deploy a public service. Customer test contacts and test scope also
  need confirmation.
- If SrediMe offers a suitable new interface, implement and test its adapter,
  acknowledgement/freshness rules and booking safety protocol before removing
  the production capability gate. An approval flag alone is not a transport.

Until these are resolved the project stays in simulation. The protected pilot
can proceed only when its existing isolation and configuration checks pass.

## Follow-up blocker review ? 2026-10-22

Current official SimplyBook schema/webhook documentation and connected tool
capabilities were rechecked. No bounded import-completion interface or full
schedule/block event coverage was established. Prepared, unsent requests and the
schema/account isolation discrepancy are in [PROVIDER_SUPPORT_REQUESTS.md](PROVIDER_SUPPORT_REQUESTS.md).
The exact candidate scope is in [PILOT_MAPPING_REVIEW.md](PILOT_MAPPING_REVIEW.md);
public-host prerequisites are in [deploy/PILOT_RUNBOOK.md](deploy/PILOT_RUNBOOK.md).
Authentication is complete. The remaining dependency is provider capability,
verified isolation and live-test setup, not another login or polling optimization.
