# Anonymous booking capability experiment — preparation only

`booking_bridge.anonymous_booking_probe` is a separate narrowly fenced experiment,
not a production worker mode. It is dormant: no transport is constructed at
import and no live preparation reads or business writes were performed. It
changes no gateway, worker, profile, readiness or ownership state from the bridge.

The experiment uses only the existing SimplyBook account
`studioandjelija` at `https://user-api-v2.simplybook.me`, provider **9** named
**TEST integracija A**, and hidden service **496** named
**TEST integracija 30 min**. This is a new anonymous-booking capability question,
not a repeat or replay of the completed SrediMe create/move/cancel trial.
It never calls SrediMe or changes source callbacks, staff, services or customers.

## Decision and risk that still need the owner

The owner has requested that SimplyBook store no clients. Clarification remains
pending: zero client objects at all, or no customer details while an anonymous
technical record is acceptable. The current schema says `client_id` is not a
required field of `AdminBookingBuildEntity`; this alone does not guarantee that
the server will accept the omission or avoid creating a client object internally.
The worker's current client requirement is not changed by this experiment.
[Official Admin schema](https://simplybook.me/api/swagger-admin).

An actual experiment could cause the server to create an anonymous client object
even though no client value was sent. That risk needs explicit scoped consent
before the single booking POST. This probe is never allowed to delete any client,
including an auto-created one. It will cancel only its exact proven new test
booking, retain the diagnostic failure and require the owner's review. A strict
promise of zero server-side client objects cannot be made before that behavior
is known. Existing clients are never removed by this tool.

## Read-only preparation

Root can call `prepare(Probe(existing_paced_transport), new_private_directory,
candidate_dates)` after reviewing the code. It checks fresh provider/service
identity, active/hidden state, provider capacity 1, the exact relationship,
30-minute duration, zero price and zero after-buffer. Provider contact fields
must be empty so this experiment does not introduce a real staff recipient.
Changed identity or settings stop the preparation; the tool never edits them.

At most seven explicitly supplied future dates in the next week are considered.
The supported `/admin/schedule/available-slots` GET chooses an offered future
slot; the matching complete daily booking inventory also must show no overlap
for provider 9. No calendar availability is invented or opened. Preparation
retains a private immutable plan containing only IDs, status/time metadata,
sanitized client presence categories and aggregate client counts. It records
no notes, names or contacts from bookings/clients. The plan expires after ten
minutes. Execution rechecks identities, the full baseline, client count, and slot.

The one booking payload contains exactly:

```json
{
  "service_id": 496,
  "provider_id": 9,
  "count": 1,
  "start_datetime": "<fresh offered future slot>",
  "end_datetime": "<exactly 30 minutes later>"
}
```

No `client_id`, customer name, email, phone, intake answers, comments, payment
instruction, shared client or placeholder client is submitted.

## Scoped execution and reconciliation

`authorization_for_review(plan_sha256)` returns a deliberately non-executable
template. The operator may fill its two consent booleans only from the owner's
concrete experimental authorization, bound to the reviewed plan hash. There is
no generic write entry point or production approval override.

The separate journal is locked and saved durably **before** reserving the one
POST. The existing paced transport is invoked once. Any exception or malformed
result is uncertain, not a reason to POST again. Reopening the same journal can
only reconcile that attempt and perform the remaining one exact cleanup if
ownership has been proven.

A successful response must identify exactly one new booking ID outside the
immutable baseline, and its fresh detail must match the exact test provider,
service and interval. Only that ID can be canceled, at most once. The exact
identity is re-read immediately before cancellation. If cancellation is uncertain,
GET readback determines whether it is canceled/absent; no DELETE is replayed.
All pre-existing booking metadata must remain unchanged.

A unique new booking with matching fields after a lost POST response is useful
reconciliation evidence, **not proof of ownership**. Another operator could have
created it concurrently. The documented build entity provides no supported unique
probe nonce/idempotency field. The probe therefore leaves an unowned candidate
for manual ownership review, with no cancellation. It never guesses a new nonce
field, reuses the completed trial's ID, or cancels a baseline booking. There is
also no documented conditional cancel, so a final detail read limits but cannot
eliminate every race with a separate operator modifying the same test record.

Any non-null `client_id` (including `0`), any non-null nested `client` object,
contact values on the new booking, or a changed client count makes the client
requirement check fail. Failure stays recorded even after safe booking cleanup;
it never silently accepts a shared or technical client. A positive narrow
capability result means only that this test booking was created without observed
client linkage/net count change and canceled safely. The result always reports
`zero_client_objects_proven=false`; it is not production readiness.

## Client-count minimization and its limits

`GET /admin/clients?page=1&on_page=1` supplies `metadata.items_count`. The tool
retains only that count, pagination integers, and returned-row count; it never
persists any client row or contact field. This is sufficient to detect a **net**
count increase, including after an uncertain booking POST. A concurrent deletion
can mask a new client and concurrent unrelated creation can raise the count, so
count equality alone does not prove identity or causation.

The documented endpoint has no metadata-only or field-selection parameter. It
can still send a client row containing personal fields in the HTTPS response,
and this account's list endpoints have sometimes returned complete arrays despite
page parameters. The existing transport decodes that response in memory. The
fields are immediately discarded and never written to plans, journals, receipts,
logs or errors. If even transient receipt of existing client fields is prohibited,
this documented endpoint cannot supply the requested count check within that
constraint; a provider-supported aggregate endpoint would be needed.

No live test is authorized or implied by the fake-transport test results. Root
must decide the concrete scope and receive the pending owner clarification before
preparing or executing against the real account.
