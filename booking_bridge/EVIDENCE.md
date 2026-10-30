# Current hosted pilot evidence - 23 October 2026

[VPS validation](evidence/vps-pilot-deployment-validation.json): 249 Linux tests
and HTTP smoke passed on the hosted image. Trusted HTTPS and public route fences
verified. Local backup integrity/readiness and certificate renewal dry run passed.
Runtime is simulation, production disabled. Source callback create outcome is
unresolved; no real booking/import or end-to-end availability claim. Earlier local
Docker startup failures remain historical and do not block hosted Linux testing.

# Current pilot evidence - 23 October 2026

[Current validation](evidence/controlled-pilot-validation.json): 385 Windows tests,
40 overlapping focused tests and simulation HTTP smoke passed. Live controlled
record provisioning worked on both systems; only the new SimplyBook provider's
schedule was exercised. Source-to-remote effective availability is unknown. No
clients/bookings/import URLs/webhooks were created. Current code Linux tests were
not run because Docker Desktop could not start; previous 241 Linux passes remain
historical. See the root progress and DECISION_CHECKLIST.md for current direction.

# Latest blocker review ? 2026-10-22

[Review validation](evidence/blocker-review-validation.json): 28 focused mapping/isolation
and one backup test newly passed; Compose validates; source hashes match the prior
373 Windows / 241 final-image Linux checkpoint. One live provider read matched the
saved baseline. No account writes, public deployment, callbacks or end-to-end
availability tests. Production preflight remains blocked. The reports below retain
historical evidence; they do not supersede this status.

# Evidencija mogućnosti i ograničenja

## Subminute pipeline improvements, 2026-10-22

Removed the bridge's artificial one-minute refresh gap: first notification is
immediate and subsequent changes coalesce for five seconds, within the persistent
60/employee/hour cap. Unchanged owned copies no longer consume refresh allowance.
Added cooperative foreground work between background reads, shorter read-only
transport attempts, bounded task recovery, atomic notification publication and
durable per-version observations. Exactly 60 seconds, superseded/unfetched
versions and clock anomalies are not presented as successful subminute delivery.

Validation: **373 Windows repository tests**, **230 Linux connector tests** and
**11 additional Linux transport-policy tests** pass. HTTP smoke runs on Windows
and Linux use synthetic data. A recurring Windows temporary SQLite SHM cleanup
race was reproduced; the smoke harness now verifies its temporary path and permits
20 cleanup attempts with 100 ms pauses, without hiding persistent failures.

Evidence: `evidence/subminute-pipeline-validation.json` and corresponding JUnit/
smoke files. No live account operations or business writes were made in this
iteration. The production capability gate remains in place; actual source commit
to effective SrediMe availability is still unverified. Details:
[AVAILABILITY_LATENCY.md](AVAILABILITY_LATENCY.md).

## Authenticated SrediMe account review, 2026-10-22

SrediMe login and Studio Anđelija SG identity were confirmed. Nine private export
URLs were saved, six bookable employee feeds were read, and an offline mapping
review command was implemented. Source catalog: 677 entries; target catalog:
494 services. Nine of 18 unique-name candidates have duration conflicts. No
runtime mappings or remote business settings were changed. Detailed findings:
[SREDIME_ACCOUNT_REVIEW.md](SREDIME_ACCOUNT_REVIEW.md).

All **335 Windows repository tests** and **203 Linux connector tests** pass;
the local HTTP smoke passes. Evidence: `evidence/sredime-access-validation.json`,
`evidence/sredime-account-check.json`, and `evidence/sredime-export-check.json`.
Production remains blocked for the subminute requirement. Account access alone
does not establish an import deadline or solve test-provider isolation.

## Subminute availability work, 2026-10-22

The requirement is consistently below 60 seconds, not the earlier proposed
five-minute p95 target. It remains unmet with the supported asynchronous ICS
contract. Research: [AVAILABILITY_LATENCY.md](AVAILABILITY_LATENCY.md).
Access-dependent work: [SREDIME_ACCESS_REQUIRED.md](SREDIME_ACCESS_REQUIRED.md).

Validation: **316 Windows repository tests**, **184 Linux connector tests**, and
both HTTP smoke runs pass. The first Windows smoke encountered a transient
temporary SQLite SHM cleanup permission error; an unchanged rerun passed, and
no surviving bridge processes were found. Existing test-client deprecation
warning remains. No external account calls or business writes were made.

Production preflight rejects the subminute capability requirement; the actual
profile remains in simulation. Durable coalescing, immediate first refresh,
concurrent change preservation, legacy pending refreshes, incremental/restartable
scans, conservative near-range freshness, manual endpoint protection and exact
fetched-version telemetry are covered. These tests do not measure remote import
latency. Details and source hashes: `evidence/availability-validation.json`;
JUnit: `availability-windows-tests.xml` and `availability-linux-tests.xml`.

## Ažuriranje 2026-10-22

- Naknadna lokalna dorada: svih **303 Windows testa** i **171 Linux test
  povezivača** prolaze. Docker image je izgrađen; HTTP smoke sa zasebnim radnikom
  radi sa read-only root-om, kao UID 10001 i bez mrežnog izlaza.
  Dokaz: `evidence/container-followup-validation.json` i odgovarajući JUnit fajlovi.
- Readiness sada proverava oba sveža vremenska podatka, validan zdrav izveštaj i
  trenutne incidente u istoj transakciji. Reprodukovani stari lažni 200 odgovori
  za nov incident i zastareo izveštaj su ispravljeni.
- Novi offline `preflight` proverava oba ciljna režima bez API poziva i bez
  inicijalizacije/migracije baze. Stvarna konfiguracija ostaje `simulation`;
  oba cilja pravilno izlaze kodom 2. Hash-evi zaštićene konfiguracije/mapiranja i
  DB fajla su isti pre i posle. Dokaz: `evidence/offline-preflight-check.json`.

Sledeće stavke opisuju raniji pokušaj pripreme pilota istog dana:

- MCP OAuth i `studioandjelija` potvrđeni stvarnim alatnim pozivima; početni
  pregled je šest zaposlenih i 494 usluge, Europe/Belgrade.
- REST `/admin/tariff/current`: aktivni Standard, provider limit 15, slobodno 9.
- REST POST/PUT `/admin/providers` na ovom nalogu ignorišu `services: []`.
  Kreiran skriveni test ID 8 dobio je 12 starih usluga. Izvršenje je zaustavljeno,
  ID 8 uklonjen kroz MCP, a potpuni REST pregled potvrđuje vraćen baseline.
  Tri poslovna upisa: jedno kreiranje, jedan pokušaj ispravke, jedno povlačenje.
  Nema upisa rezervacija, klijenata ili test usluga.
- Dodata je zaštićena priprema `provision_pilot` sa trajnim dnevnikom namera,
  proverom baseline-a i zabranom novog create bez dokazane izolacije. Lokalni
  simulator ne predstavlja dokaz stvarnog API ponašanja; neuspeh naloga ostaje
  eksplicitno blokiran. Sanitizovan dokaz: `evidence/pilot-provisioning-check.json`.
- Buker u otvorenom Chrome-u pokazuje login formu; prijava je potrebna za dalji
  rad. Nema konfigurisanih SrediMe ID-eva/tajni niti javnog HTTPS deploymenta.
- Svih 269 lokalnih testova prolazi, uključujući devet novih za pripremu pilota:
  zabranu upisa bez izolacije/kapaciteta/identiteta, očuvanje baseline-a,
  trajnu nejasnu nameru, idempotentan nastavak i server koji ignoriše dodele.
  JUnit: `evidence/pilot-implementation-test-results.xml`.

Istorijski nalazi ispod ostaju datirani na 2026-10-21.

Pripremljeno 2026-10-21. Lokalni izvor SrediMe je pročitan u celosti:
`C:\Users\aaaaz\Downloads\SrediMe for Developers.html`, verzija **2026-09-10-1**.
HTML nije kopiran u javni izvoz, a privatni feedovi/ključevi nisu ispisivani.
Pročitani su postojeći README, import pravila/status, provider klijent i token
store, završna provera dodela i dokumenti booking/Any Employee toka. AGENTS
instrukcija dostavljena u sesiji navodi instaliran Postman CLI; dodatni lokalni
AGENTS.md nije pronađen. Novi povezivač ne pokreće stari import niti provider izmene.

## Ugovor SrediMe

Potvrđeno iz merodavnog lokalnog dokumenta: salonska konfiguracija, besplatna
webhook aktivacija kroz Buker; salon-wide created/updated/deleted događaji;
potpis HMAC-SHA256 nad raw bytes; event ID različit od booking ID-a; najmanje
jedna isporuka, duplikati i promenjen redosled. Početno stavljanje u red određuje
nepotpisano timestamp zaglavlje. Test je anonimizovan i ima `test:true`.

Potvrđeni svi navedeni statusi (1, 0, -1, -2, -101, -901, -902), otkazivanje kroz
updated i deleted kod -2. Kontakt podaci nisu standardno dostupni. external_id
je pomoć za eksplicitno mapiranje, ne osnov za slobodno pogađanje.

Originalni ICS po zaposlenom ima stabilni UID i izostavlja kontakte; prozor je
sedam dana unazad bez dokumentovanog budućeg kraja. Najviše 12 GET/h/zaposleni.
Uvoz tretira DTSTART/DTEND/SUMMARY kao blok, ignoriše STATUS, uz približno -1/+60
dana. Uspešan uvoz menja prethodni skup blokova; redovno osvežavanje oko 15 min
ili 5 min za trenutnu potvrdu. POST privatnom export URL-u samo zakazuje refresh,
najviše 60/h. Prazni/neuspeli feedovi usporavaju provere do 12 h i zaustavljaju
ih posle 100 uzastopnih slučajeva. Praktično ponašanje praznog uvoza nije testirano.

## Aktuelni zvanični SimplyBook izvori

| Izvor | Provereno | Naša upotreba |
|---|---|---|
| [Admin OpenAPI](https://simplybook.me/api/swagger-admin) | Preuzet HTTP 200; sačuvan `evidence/admin-openapi.json` | REST booking/client/calendar/schedule ugovori |
| [Admin JSON-RPC metode](https://help.simplybook.me/wiki/Company_administration_service_methods) | addClient, book, editBook, cancelBooking, getBookings, getBookingDetails postoje | Potvrda mogućnosti; ne šaljemo te parametre REST-u |
| [Autentifikacija](https://simplybook.me/en/api/developer-api/ref) | JSON-RPC admin token i javni token su različiti; objavljene granice 5.000/dan, 2 paralelna, 5/s na zajedničkom serveru | REST koristi sopstveni `/admin/auth` i deljeni konzervativni budžet |
| [REST webhookovi](https://help.simplybook.me/wiki/REST_API_webhooks) | new_booking/change_booking/cancel_booking; raw HMAC X-Signature uz API secret | Potpisani signal za REST proveru, uz limit i fallback polling |
| [Calendar Sync](https://help.simplybook.me/wiki/Calendar_Sync_custom_feature) | Google/Outlook dvosmerno, dodatna latencija | Dokumentovana alternativa, nije aktivirana |

JSON-RPC `book` koristi eventId/unitId/clientId i odvojene datum/vreme parametre;
`editBook` uzima shedulerId; `cancelBooking(id)` vraća boolean. `getBookings` ima
objekt filtera, `getBookingDetails(id)` čita pojedinačni zapis. `addClient` zahteva
ime, a kontaktna obaveznost zavisi od naloga. Ovi ugovori ne potvrđuju ponašanje
REST POST /admin/clients pri duplikatima i ne koriste se kao izgovor za automatsko
spajanje osoba.

REST koristi `/admin/bookings` POST/GET, `/admin/bookings/{id}` GET/PUT/DELETE i
`/{id}/approve` PUT; trajanja i resurse proveravamo preko servisa i detalja.
OpenAPI ne daje booking idempotency key, referencu izvornog SrediMe ID-a niti
garantovano utišavanje obaveštenja. Nisu izmišljeni takvi parametri.

## Praktično čitanje postojećeg naloga

Svi sledeći pozivi bili su read-only, osim neophodne autentifikacije/obnavljanja
tokena. Nije bilo upisa rezervacija, klijenata, usluga, zaposlenih ili pretplata.

| Dokaz | Nalaz |
|---|---|
| `evidence/account-read-check.json` | Ispravan postojeći region i pristup; 494 usluge i šest aktivnih zaposlenih |
| `evidence/calendar-week-check.json` | Week režim daje radne dane; neradna nedelja je izostavljena |
| `evidence/calendar-offday-check.json` | Ni provider dnevni prikaz ne vraća kolonu neradnog dana; service detalj ima buffer 0 i očekivane zaposlene |
| `evidence/schedule-offday-check.json` | `/admin/schedule` vraća svih sedam dana i eksplicitno `is_day_off:true` za nedelju |
| `evidence/booking-list-check.json` | Prazan raspon: `data:[]`, `items_count:0`, `pages_count:0`; prihvaćeno u adapteru |
| `mappings/services.csv` | 490 confirmed checkpoint redova → 490 jedinstvenih SB ID-eva; bez pogađanja SrediMe ID-a |

Detaljni booking podaci pravih klijenata nisu sačuvani u dokazima. Trenutno nema
rezervacija u pročitanom rasponu; stvarni non-empty REST booking rezultat ostaje
za pilot. Rasporedi su provereni čitanjem, ali nije kreirana test pauza, odsustvo
ili ručna blokada; njihove konkretne sadržaje i resursne efekte tek treba proveriti.

## Lokalno testirano

`evidence/test-results.xml` i `evidence/validation.json` beleže početni prolaz.
Naknadno odobrena dorada ima zaseban završni dokaz u
[`evidence/followup-validation.json`](evidence/followup-validation.json) i JUnit
[`evidence/followup-test-results.xml`](evidence/followup-test-results.xml): svih
260 testova prolazi (128 povezivača, 132 postojećih modula). Pronađeni scenario
sa ignorisanim novijim događajem je dodat i ispravljen; početni prolaz sam nije
pokrivao taj scenario. Poslovne odluke nisu potvrđene niti je time aktivirana produkcija.
Testovi zabranjuju pravi `requests` HTTP i koriste lokalni FastAPI TestClient,
privremeni SQLite, simulator i kontrolisane REST odgovore. Pokrivaju kreiranje,
promene, potvrde, statuse, deduplikaciju, redosled, potpise, test/allowlist,
nepoznate podatke, restart, nejasan create, privremeni pad, privatni ICS, buffer,
promenu sata, opseg, uklanjanje otkazanih događaja, prazne feedove, limite,
backoff/stop i sprečavanje povratne petlje. Ovo nije dokaz ponašanja udaljenog
servisa koje nije praktično testirano.

## Preostali uslovi i ograničenja

Zvanični MCP je istražen i postupak je u [MCP_SETUP.md](MCP_SETUP.md).
Vlasnica je odabrala originalni nalog za test zaposlene; dijagnostika potvrđuje
šest postojećih zaposlenih, 494 usluge i Europe/Belgrade. Predloženi test zapisi
još ne postoje. Pripremljen je offline manifest sa hash-om početnog pregleda, bez
udaljenih upisa. Kapacitet/cena, MCP prijava i kontakt test klijenta još nedostaju.

- Poslovne odluke, test ID-evi, SrediMe aktivacija i privatni URL-ovi čekaju vlasnicu.
- Kontakt podaci čekaju posebno odobrenje; standardni opaque ID i ICS ih ne mogu oporaviti.
- Udaljeni booking i client upisi, prava, obaveštenja, resursi/intake/naplata i
  stvarni callback payload moraju proći izolovani pilot.
- Nema dokazanog webhooka za rasporede/pauze/blokade; koristi se satni polling
  i proverena referentna usluga. Preostali prozor može biti neprihvatljiv bez
  operativnog dogovora; ne obećava se sprečavanje svakog duplog termina.
- Izmena koja preklapa sopstveni prethodni termin može tražiti ručnu intervenciju.
- Nejasan create zahteva potvrdu vlasništva; odsustvo kandidata nije dozvola za ponovni create.
- Prazan feed i uklanjanje poslednjeg Buker bloka zahtevaju test/potvrdu podrške.
- Docker/Caddy javni deployment, konkretna ponuda, kanal upozorenja i off-host
  restore nisu izvršeni. Nema plaćenog hostinga niti aktivne produkcione integracije.
- Retencija payload-ova i praktičan Linux runtime build su produkcioni uslovi;
  deduplikacioni ID-evi i tombstone veze ne smeju se izgubiti pri arhiviranju.
