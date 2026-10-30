# Catalog comparison and source-authoritative dry-run plan

The completed review is under the ignored private directory
`state/catalog-alignment-20261030/full-current-source-authoritative-review-final/`.
Its manifest binds the JSON, CSVs and plan by hash. The public count/hash receipt
is [catalog-comparison-full](evidence/production-20261030-catalog-comparison-full.json).
No account, booking, runtime profile or readiness changes were performed by this
comparison. Historical October 22 and earlier partial reports remain separate.

The scope is all **678 source index records**, individually inspected source
service forms, nine real active source employee forms, and **495 target services
with seven providers**. The target inventory was read at the timestamp recorded
in the report; the source forms were read over a longer recorded interval. This
is a complete comparison of those observations, not an atomic snapshot of both
accounts or certification of every unreturned API property.

Source forms establish 507 active and 171 inactive services. One inactive source
service, one target service and one target provider are the preserved controlled
test records. They are marked separately and excluded from business questions.
Thirty-five source services select physical assets, including 33 active services.
Target resource allocation is unobserved; numeric resource IDs from different
systems are never equated. Zero observed variant controls does not certify every
possible hidden/provider-specific timing behavior.

The full review distinguishes:

- 18 strict unique business-name pairs plus one controlled test pair;
- 32 punctuation/word-sequence candidates, whose identity remains unresolved;
- 14 source duplicate-name groups and one cross-catalog ambiguity:
  source Fototerapija lica 208008/128323 versus target 51;
- 625 source and 443 target records without an exact or word-sequence candidate.

The last group does **not** prove treatments are absent from the opposite account.
`unpaired-review.csv` retains every such record for equivalence/scope review.
No fuzzy matching or automatic runtime aliases are generated.

The owner selected SrediMe as catalog authority. The authority record resolves
T01–T09 to their source durations; source-inactive T08/T09 stay inactive. The plan
selects source values for 58 observed field disagreements. It does not ask again
which catalog supplies duration/price/activity/resolved assignments. Treatment
and person identities, unknown semantics, resource correspondence and execution
contracts remain separate. The 90 baseline difference rows include 32 treatment
identity questions and conditional comparisons; they are not 90 new authority
questions or proven booking bugs.

`source-authoritative-plan.json` separates unique inventory candidates,
punctuation/ambiguous identities, potential source-only target creations and
target-only preservation. All execution approvals remain false. Service 377 is
protected because a later independent root read found existing future
native-origin target bookings. It must not be hidden/deleted or backfilled as a
new copy before its source equivalent/origin is resolved. Every target metadata
change needs a fresh future-booking safety check.

Both source assignment views are retained. Service 129090, Konsultacije, selects
5571/5919 in its service form, while nonbookable employee 6140 also selects that
service in her employee form. Possible nonbookable filtering is unproven. Global
source authority does not choose between these different source projections.

The original workbook matches its import checkpoint; all 490 imported target row
hashes are checked. The bulk assignment journal has 481 verified row statuses,
477 direct observed-readback references and four rows without a direct reference
in that journal (6/69/364/401). That distinction is retained. Neither the import
nor this comparison reconstructs a native-to-webhook identity crosswalk.

To regenerate after obtaining a **new** target inventory or other changed inputs,
run `python -m booking_bridge.catalog_alignment --help` and choose a new output
directory. Use the completed source detail manifest and continuation hashes;
never change the original stopped-partial collection into a successful run.
The command performs no HTTP requests and does not construct account clients.
The completed comparison has [36 focused validation tests](evidence/production-20261030-catalog-alignment-tests.xml).
