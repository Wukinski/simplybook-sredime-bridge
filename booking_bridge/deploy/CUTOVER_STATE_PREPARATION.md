# Preparing a held production database and calendar contract

This procedure prepares reviewable inputs. It never starts the worker, releases
a recovery hold, changes a callback/import, or treats an old trial as an active
production pipeline. Profile/readiness edits and actual cutover remain separate.

## Fresh state, without repeating the completed trial

1. Capture a **new SQLite online backup** of the VPS receiver database and a new
   online backup of the local completed-trial database into a new private run
   directory. Keep both originals and capture timestamps/hashes. Copying the live
   `.sqlite` file without its WAL is not an online backup. Do not infer a capture
   time from a manually updated file timestamp. A physical WAL-mode file hash can
   differ from the normalized online-backup/VACUUM image; compare the exact
   returned snapshot with its corresponding capture receipt.
2. Preserve every newly captured receipt and authoritative booking head. A new
   receipt stays unprocessed until reviewed. Do not replay a captured backlog as
   an activation shortcut, or overwrite it with the older held-stage database.
3. Read back the known owned target booking(s) through the existing read-only
   account client. The historical completed test owns target booking 5, which
   must still be canceled. Its original source booking, identity aliases, three
   phase receipts/readbacks and ACKs are already saved; do not repeat that cycle.
   Any new or uncertain ownership requires its own readback and review.
4. Run the existing proof-verifying stage builder with the **new snapshots** and
   the preserved original proof files. Use a new output path, never an existing
   database. The existing CLI is:

   ```text
   python -m booking_bridge.reconcile_trial --host-snapshot NEW_HOST.sqlite --local-snapshot NEW_LOCAL.sqlite --binding ORIGINAL_BINDING.json --journal ORIGINAL_JOURNAL.json --cycle ORIGINAL_CYCLE.json --readbacks-dir ORIGINAL_READBACKS --output NEW_HELD_STAGE/bridge.sqlite
   ```

   The binding/journal/readbacks live in the ignored private integration run
   directory. The older reviewed stage under
   `state/activation-staging-20261028-2eb16604328e4084a36158eb08c6c90c/held-stage/`
   is an ownership baseline, not a substitute for the new VPS snapshot.
   `reconcile_trial` verifies the preserved proofs again and carries raw host
   events/heads forward without rewriting their identities or freshness.
5. Verify the candidate using the additional preservation check:

   ```text
   python -m booking_bridge.cutover_review --current-host NEW_HOST.sqlite --candidate NEW_HELD_STAGE/bridge.sqlite --owned-baseline PREVIOUS_REVIEWED_HELD_STAGE/bridge.sqlite --quota-origin NEW_LOCAL.sqlite
   ```

   Exit 0 means the offline preservation checks passed. Output always states
   `activation_ready=false`, `worker_start_allowed=false` and
   `promotion_performed=false`. It also reports queued receipts/open incidents
   for operator review. No hold is removed, timestamp refreshed, or SQL executed
   against the originals. Standalone snapshots with WAL/SHM/journal sidecars,
   invalid schema/event hashes, changed receipts, missing ownership/clients,
   deduplicated quotas or rewritten cache timestamps fail.
6. Preserve and reconcile the **external** REST budget/last-request files and
   daily budget floors as well. SQLite rate rows alone do not cover those
   credential-wide budgets. Keep overlapping windows conservatively; do not
   reset a request counter when moving the worker to a new container/volume.
7. Resolve current incidents from fresh factual reads. Regenerate booking,
   buffer and schedule snapshots from successful reads after configuration is
   complete; do not make old values look fresh by altering `updated` fields.
   Database promotion and hold release require a separate factual review after
   the production preflight and calendar checks are complete.

When passive ingress remains active, a candidate can become obsolete immediately
after a snapshot. Final cutover needs a lossless ingress boundary and a last
receipt-watermark comparison. Do not replace a SQLite file underneath open
API/keeper connections. Disabling the native callback alone is not proven to
replay bookings that occur during the disabled interval. This offline checker
does not implement an atomic live migration or guarantee future receipts are in
an already-captured candidate.

## Private calendar contract to review before installation

For every selected real employee, retain these fields privately:

| Field | Required fact |
|---|---|
| Native employee ID and exact webhook employee ID | Traceable entity identity; native IDs are not implicit webhook aliases |
| Target provider and reference service | Correct provider; neutral reference exposes the provider's actual working schedule |
| Existing source export URL | Exact populated read-only export field; keep access material private |
| Existing source import URL | Read before editing; preserve or explicitly review any existing subscription |
| Proposed bridge import URL | Owned HTTPS origin and `/ics/{exact_employee}/{unique_secret}.ics` route |
| Unique feed token | At least 32 characters, present only in private ingress/worker env |
| Timing/resources | Verified occupied duration, target provider overrides, buffers and physical resource requirements |
| Feed behavior | Native import fetch, changed occupied intervals, cancellation/removal, empty feed and measured delay |

Do not print token-bearing URLs, entire employee pages, contact fields or env
files in the review output. The populated export control can be read without
creating or rotating an export key. The export is not an identity directory:
saved native exports lack `X-SERVICE-ID`, and the calendar reconciliation code
never creates customers/appointments from ICS alone.

The implemented return direction publishes **busy periods** into SrediMe; it
does not create full SrediMe customer appointments. Starting `server_worker`
alone cannot install a native calendar subscription or enable source delivery.
The native callback has no observed employee filter, so only exact application
mapping/allowlist and diagnostic handling define the processing scope.

For identity discovery, the existing HMAC receiver plus receiver-only daemon can
capture natural events without a source browser session on the VPS. The customer
object is reduced to its ID when contacts are unapproved; arbitrary `changes`
and employee/service metadata are still retained. Export only a strict identity
projection on the VPS before SSH output, preserving the original stored payload
and hash. Do not describe the entire normalized payload as contact/note-free.
Enabling persistent passive delivery must be
a separately prepared operation; do not extend the completed short lease or run
the original booking trial again. Capturing a receipt is not processing it, and
neither action proves a production calendar import was applied.
