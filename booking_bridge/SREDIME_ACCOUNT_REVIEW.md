# Authenticated SrediMe setup review

Checked 2026-10-22 through the authorized Buker session. Login succeeded for
**Studio Anđelija SG**, salon slug `studio-andjelija-sg`, vendor ID `1404`.
The signed-in employee is Olja with full access. The password was used only for
authentication and was not saved to project files. Session state, raw page
observations and tokenized export URLs are stored under ignored private paths.

No business settings, services, employees, bookings or webhook subscriptions
were created or changed. No customer records were exported. Six employee ICS
feeds were read once under the existing persistent GET allowance; only counts,
property names and parser results were retained in public evidence.

## Confirmed account state

| Area | Observation |
| --- | --- |
| Employees | 9 active, 6 bookable; 3 further employees shown as deactivated |
| Bookable people | Sanja 6873, Jelena (vlasnica salona) 5571, Tamara 10142, Ljilja 6633, Olja 5919, Vanja 10857 |
| Staff identity issue | SimplyBook has Sara, while SrediMe has Sanja; identity is unconfirmed. Jelena has an owner suffix in SrediMe. Neither difference was silently mapped |
| No services assigned | Sanja and Vanja are bookable but currently have no selected services in their SrediMe employee forms |
| Catalog | 677 SrediMe service entries versus 494 SimplyBook services; not all entries were established as active |
| Shared resources | Presoterapija 1 (51), Termo ćebe / Vaccum slim 1 (50), Tesla 1 (49), Lipolaser 1 (48) |
| Employee external IDs | Blank on all 9 active employee forms |
| Calendar imports | Blank on all 9 active employee forms |
| Calendar exports | Present for all 9 active employees; saved privately in `SREDIME_EXPORT_URLS` |
| Webhooks | No existing endpoints; creation form exposes name, URL and active checkbox |
| Booking mode | Instant booking is disabled; it was left unchanged |

Fresh SimplyBook read-only diagnostics confirmed `studioandjelija`, 6 providers,
494 services, and no newly provisioned pilot providers or services, using five direct transport calls. The pre-existing catalog service named `test` is not a pilot record.

The source employee/service identifiers are now known, but verified cross-system
identity and timing cannot be inferred from similar names. The authenticated
account alone does not resolve the existing test-provider isolation issue.

## New offline review command

```powershell
.\.venv\Scripts\python.exe -m booking_bridge prepare-source-review `
  --source booking_bridge/state/sredime-account-private.json `
  --expected-salon studio-andjelija-sg --expected-vendor 1404 `
  --output booking_bridge/state/source-review
```

This command performs no network calls and never initializes the runtime DB or
applies mappings. It verifies both recorded account identities, checks the
SimplyBook baseline hash, rejects duplicate IDs and employee vendor mismatches,
and generates a whitelisted JSON summary and spreadsheet-safe CSV candidates.
Suggested matches always retain `approved=no`, `timing_verified=no` and
`resources_verified=no`. Approximate names and duplicate names are explicitly
marked as suggestions/ambiguities. Missing durations are left unverified.

Private review artifacts:

- `state/source-review/employee-candidates.csv`: four unique normalized-name
  candidates, plus suggestions for the two remaining bookable employees.
- `state/source-review/service-candidates.csv`: 18 unique normalized-name
  candidates and suggestions for other entries. **Nine of the 18 have different
  displayed durations**. Suggestions can also represent different treatments;
  none is approved automatically.
- `state/source-review/account-review.json`: redacted totals and unresolved scope.

The 18 unique-name candidates were also inspected through their live service
edit forms, without submitting them. Those 18 forms show no additional cleanup,
split work periods, required shared assets or multiple simultaneous employees.
That result does not establish these properties for the remaining catalog or
replace an end-to-end resource/booking trial.

Concrete conflicts include:

| Service name | SrediMe duration | SimplyBook duration |
| --- | ---: | ---: |
| Manikir | 45 min | 30 min |
| Korekcija tuđeg rada | 60 min | 75 min |
| Medicinski pedikir | 90 min | 60 min |

No duration or assignment was changed to make a candidate pass validation.

## Export contract check

All six observed bookable employees' private URLs returned parseable iCalendar
2.0. Five feeds were empty, and Jelena's feed contained one cancelled event.
The existing strict parser accepted the samples. The nonempty sample contained
no `X-SERVICE-ID`, so export data cannot establish service identity by itself.
The report records only counts/statuses/schema names, with no event bodies,
client names, descriptions, UID values or private URLs.

This is limited evidence: confirmed/pending booking behavior, employee moves,
last-block removal, retries, webhook delivery and actual import latency remain
untested. No early-refresh POST was sent because there is no approved public
bridge calendar configured for import.

Evidence: `evidence/sredime-account-check.json`,
`evidence/sredime-export-check.json`, `evidence/sredime-access-validation.json`.

## Remaining work

The project remains in simulation with live reads disabled. The nine stored
export URLs do not activate polling because the runtime employee allowlist is
still empty. Cross-system staff/service identity, timing/resource verification,
test isolation, public HTTPS hosting and real webhook samples still need work.

Do not create an endpoint pointed at localhost or an unapproved tunnel merely to
populate the webhook page. A suitable public host is required before configuring
and testing it. The webhook signing-secret behavior must be verified when a
real endpoint can be configured; the blank creation form does not establish it.

The **consistently below 60 seconds** requirement remains blocked by the supported
availability interface, not login. No synchronous block update, atomic external
hold or bounded import-completion interface was established by inspecting these
account settings. The provider questions in
[SREDIME_ACCESS_REQUIRED.md](SREDIME_ACCESS_REQUIRED.md) remain necessary.

## Follow-up mapping review

[Exact-ID review](PILOT_MAPPING_REVIEW.md) joins the saved service forms to the
candidate CSV and target assignments. It identifies three inactive source services
and assignment conflicts beyond the nine duration mismatches. Tamara 10142 ? 5
with services 128316 ? 36 and 128275 ? 31 is the narrow business-review candidate;
no approval or isolated live-test authorization is inferred for real staff.
