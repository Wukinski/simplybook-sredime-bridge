# Minimal mapping review ? 2026-10-22

## Latest provenance review - 30 October 2026

Saved native inventories and the original workbook/import/assignment records
support **10142 -> 5**, **128316 -> 36 (30 minutes)** and
**128275 -> 31 (15 minutes)** as unique inventory matches. The workbook fingerprint,
confirmed import rows and verified target assignment readbacks are recorded in
[the provenance evidence](evidence/production-20261030-mapping-provenance.json).
Reconfirming Tamara's name or these two treatment names adds no new fact to that
inventory correlation; earlier requests below for that reconfirmation are historical.

The native-to-target link remains an inventory inference: the original import did
not retain native SrediMe IDs, and authoritative opaque webhook IDs are still
unknown. The three review CSV rows now say `inventory_matched_webhook_pending`;
identity, timing, resources and notification reviews remain pending. Runtime
mappings and production gates were not changed. Obtaining protocol identifiers
is the agent's technical task, not an ID request for the owner.

Questions should focus on actual differences: nine unique service pairs have
conflicting durations; source employee **6873** and target provider **3** have
different normalized labels and no proven equivalence; provider-specific timing,
physical resources, notification behavior and new-customer rules still need
factual evidence. Saved zero source timing extensions/assets and zero target
after-buffers do not establish every physical resource requirement. The owner's
30 October assent explicitly authorizes credential transfer; that assent supplies
no additional mapping facts. This is a review update, with no account changes.

## Historical direction - 23 October 2026

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


Prepared offline from the authenticated private account snapshots and source-review CSVs. No mappings applied. All candidates remain unapproved. IDs below are business catalog IDs, not customer records.

## Smallest review candidate

Tamara: SrediMe **10142** ? SimplyBook **5**, subject to owner identity confirmation. Start the business review with **Probiotski tretman lica 128316 ? 36 (30 minutes)**; reserve **Mikrodermoabrazija lica 128275 ? 31 (15 minutes)** as a second timing case. Both are active in saved source forms, assigned to source Tamara, and target services permit provider 5. Neither requires changing existing assignments. Matching names and durations do not prove treatment equivalence or resource semantics.

These are real staff/services, not isolated pilot records. Do not run test bookings against them under the existing isolated-test authorization. The technical pilot still needs newly isolated staff/services on both systems with fresh IDs, one controlled client, and an explicit cross-system test mapping. Stage 1 needs one provider pair and one service pair for create/update/cancel; stage 2 adds a second provider pair for reassignment. The previously authorized two-provider/two-service scope remains available. No IDs for future records have been invented.

## Employee review

| SrediMe | SimplyBook candidate | Decision / constraint |
|---|---|---|
| Tamara 10142 | Tamara 5 | Confirm same person; first narrow business-review candidate |
| Olja 5919 | Olja 6 | Name candidate only; not selected for minimal scope |
| Ljilja 6633 | Ljilja 7 | Name candidate; source Madero/HIFU services instead target Olja 6 |
| Vanja 10857 | Vanja 2 | Source employee has no selected services; exclude initially |
| Jelena (vlasnica salona) 5571 | Jelena 4 | Owner suffix needs confirmation; several matching services exclude target 4 |
| Sanja 6873 | No approved target; Sara 3 unresolved | Do not infer identity; source employee has no selected services |

## Exact service review

Times are minutes, source ? target. Target provider IDs: 2 Vanja, 3 Sara, 4 Jelena, 5 Tamara, 6 Olja, 7 Ljilja. All 18 saved source forms have cleanup/start/end duration 0, one required employee and no selected assets. All 18 target baseline rows have after-buffer 0. Target resource constraints and effective provider-specific timing still require verification; absence of a source asset selection is not proof that a physical device is unnecessary.

| Source ID ? target ID | Service | Minutes | Source active / assigned employee IDs | Target provider IDs | Review result |
|---|---|---|---|---|---|
| 116145 ? 404 | Manikir | 45 ? 30 | true / 5571 | 2, 3 | Duration conflict; Staff assignment conflict |
| 222386 ? 453 | Estetski manikir | 30 ? 30 | true / 5571 | 2, 3 | Staff assignment conflict |
| 222405 ? 472 | Korekcija tuđeg rada | 60 ? 75 | true / 5571 | 2, 3, 4, 5, 6, 7 | Duration conflict |
| 222397 ? 464 | Spa pakovanje ruku + estetski pedikir | 60 ? 60 | true / 5571 | 2, 3 | Staff assignment conflict |
| 222398 ? 465 | Spa pakovanje ruku + medicinski pedikir | 60 ? 60 | true / 5571 | 2, 3 | Staff assignment conflict |
| 116152 ? 4 | Estetski pedikir | 60 ? 60 | true / 5571 | 2 | Staff assignment conflict |
| 222409 ? 475 | Spa pedikir kart | 90 ? 90 | true / 5571 | 2, 3 | Staff assignment conflict |
| 116156 ? 5 | Medicinski pedikir | 90 ? 60 | true / 5571 | 2, 3, 4, 5, 6, 7 | Duration conflict |
| 189001 ? 434 | Nega noktiju nakon gljivica | 60 ? 40 | true / 5571 | 2, 3 | Duration conflict; Staff assignment conflict |
| 222383 ? 438 | Uklanjanje gljivica na noktima ND JAG laserom | 30 ? 5 | true / 5571 | 2, 3 | Duration conflict; Staff assignment conflict |
| 207951 ? 6 | Higijenski tretman lica | 90 ? 60 | true / 10142 | 5, 6 | Duration conflict |
| 149351 ? 15 | Higijenski tretman lica mandeličnom kiselinom | 60 ? 50 | true / 10142 | 5, 6 | Duration conflict |
| 128275 ? 31 | Mikrodermoabrazija lica | 15 ? 15 | true / 10142 | 5, 6 | Minimal review candidate; not approved |
| 128316 ? 36 | Probiotski tretman lica | 30 ? 30 | true / 10142 | 5, 6 | Minimal review candidate; not approved |
| 128464 ? 76 | Madero lux terapija | 60 ? 60 | true / 6633 | 6 | Staff assignment conflict |
| 195281 ? 161 | HIFU 7D CELE BUTINE (do 90 kg) | 60 ? 60 | false / 6633 | 6 | Inactive source: exclude; Staff assignment conflict |
| 195282 ? 162 | HIFU 7D CELE BUTINE (preko 90 kg) | 70 ? 60 | false / 6633 | 6 | Duration conflict; Inactive source: exclude; Staff assignment conflict |
| 176064 ? 14 | Hydrafacial tretman lica | 30 ? 50 | false / none | 5, 6 | Duration conflict; Inactive source: exclude |

Nine duration conflicts, three inactive source services (two overlap the duration conflicts). Equal durations alone leave seven of nine equal-duration candidates unsuitable for the minimal staff-compatible scope. Do not change completed SimplyBook assignments to force these matches.

## Required approval evidence

For the chosen real-service mapping, record owner confirmation of person and treatment identity; exact occupied duration including preparation/cleanup; target provider-specific overrides; device/resource requirements; and expected notification behavior. For the technical pilot, separately record freshly created isolated IDs and controlled contact verification. Keep both approvals false until evidence exists.

Private inputs: `state/source-review/employee-candidates.csv`, `state/source-review/service-candidates.csv`, `state/sredime-service-details-private.json`, `state/diagnostics.json`. Public source of account observations: [SREDIME_ACCOUNT_REVIEW.md](SREDIME_ACCOUNT_REVIEW.md).
