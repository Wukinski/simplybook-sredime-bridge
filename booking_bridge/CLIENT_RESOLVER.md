# Dormant client resolver

`client_resolver.py` prepares explicitly authorized SimplyBook client linking
and creation. It is not connected to ingress, the booking worker, Qwen, or an
operator endpoint. It does not enable production or construct a network client.
The owner now permits client storage in SimplyBook; that permission does not
establish which source can supply verified contact fields.

The caller supplies an existing `Store`, the guarded SimplyBook `Gateway`, an
explicit `ClientResolverPolicy`, and authorized contacts for one opaque source
customer ID. Keep the normal worker singleton, account identity, persistent
quotas, recovery and production checks. Do not replace the guarded write adapter
with a transport that retries POST requests.

The policy separates storage/linking approval, creation approval, and verified
required-field metadata. The actual account metadata reviewed on 30 October
requires **name, email and phone**. Missing mandatory values stop before any
request; no placeholder values or contact guesses are generated. A different
required-field policy needs independently verified same-account metadata.

The external caller must set `contacts_verified=True` only after obtaining the
fields through an authorized source. The default documented SrediMe webhook
contains only a customer ID and cannot supply these contacts. This module does
not fetch native SrediMe customer records, change webhook payloads, or alter
stored event hashes.

## Matching

Search uses the documented paginated `GET /admin/clients?filter[search]=...` for
each supplied contact. Fuzzy candidates are never selected by similarity. A
link requires a single candidate whose normalized name and every supplied
contact agree, followed by an exact-ID detail read. Both supplied email and
phone must agree. Shared contacts, split matches, name-only matches, changing or
incomplete pages, and existing one-to-one mapping conflicts require review.

Email normalization trims/case-folds and normalizes the domain without removing
mailbox dots or plus tags. Phone normalization accepts an explicit `+` or `00`
international prefix and presentation separators. It never infers a country
from a foreign local number. Names use Unicode normalization, case-folded
comparison, and whitespace normalization; there is no fuzzy name matching.

Readback never overwrites contacts, unblocks a customer, or replaces a mapping.
An explicitly persisted mapping is verified directly instead of searched again.
The current defaults bound searches to five pages per term, 100 rows per page,
500 distinct candidates, and one MiB per parsed response. Exhausted or invalid
coverage stops instead of treating it as proof that no customer exists.

## Durable outcomes

The existing `clients` table enforces source-to-target and target-to-source
uniqueness. The existing `cache` table stores `client-intent:<source>` and
hashed email/phone reservations, without a schema migration. Contact values are
not copied into the journal. Treat its hashes and source IDs as private state.

| Stored state | Permitted behavior |
|---|---|
| No intent/mapping | Verified search, then an explicitly approved link or creation |
| `started` / `uncertain` creation | Operator review; no search-based ownership and no further POST |
| `result_saved` | GET the pinned returned/candidate ID; retrying GET is allowed |
| `done` with matching persisted mapping | GET and verify that exact client |
| Older CLI intent, inconsistent mapping or recovery hold | Review; no automatic reset |

A creation intent and contact reservations commit **before** POST. A successful
returned ID commits **before** readback. The final client link and completed
journal commit together. A lost response, malformed creation result, or crash
before the ID is saved does not authorize a second creation, even if fuzzy
search later finds a matching customer. A saved ID survives readback/local-link
failure and resumes through GET only. No client is deleted automatically.

Cache reservations also prevent two concurrent unknown source IDs from creating
customers sharing a contact. Deleting an intent alone does not release its
reservation or authorize recreation. Operator reconciliation must review the
specific source, target, intent, and contact claims; there is no automatic
expiry or destructive reset command.

The module emits no logs and uses fixed error codes. Keep HTTP debug logging
disabled: outgoing search URLs naturally contain the authorized search term.
No live account operations were performed during this implementation. Tests
use synthetic contacts, fake gateway responses, and temporary SQLite stores.
