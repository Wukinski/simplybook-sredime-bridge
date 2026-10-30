# Odluke koje čekaju vlasnicu

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


## Current checkpoint ? 2026-10-22 (supersedes historical status below)

Buker authentication succeeded; salon vendor 1404 and SimplyBook studioandjelija
were verified. Login and basic account discovery are complete. Test preparation
and webhook configuration remain authorized; no repeat authorization is needed.
Public hosting, controlled contacts and verified isolation/mappings are still
missing. Runtime is simulation with live reads disabled; production is blocked.
The requirement is consistently below 60 seconds, not a five-minute or hourly
compromise. Earlier schedule-policy proposals are not accepted substitutes.

The fresh REST schema still documents `services: []` as clearing connections,
contrary to the rolled-back provider ID 8 trial. No safe retry method is proven.
See [provider requests](PROVIDER_SUPPORT_REQUESTS.md), [exact mapping review](PILOT_MAPPING_REVIEW.md)
and [deployment runbook](deploy/PILOT_RUNBOOK.md). Latest recorded validation is
373 Windows and 241 final-image Linux tests plus both simulation HTTP smokes;
see [pipeline evidence](evidence/subminute-pipeline-validation.json).

## Historical record (retained; current checkpoint above takes precedence)


**Stanje 2026-10-22:** MCP je povezan; identitet `studioandjelija` je potvrđen
stvarnim pozivom. Standard paket ima devet slobodnih mesta za zaposlene.
Izolovani REST pokušaj je povučen jer server ignoriše prazne dodele zaposlenog;
početnih šest zaposlenih/494 usluge i njihove postavke su potpuno vraćeni.
Potrebna je proverena metoda javne izolacije pre ponovnog kreiranja.
Vlasnica je odobrila da inženjer sam kreira test zapise i konfiguriše webhook
pristup; za iste radnje ne traži se novo odobrenje. Otvorena Buker stranica
zahteva prijavu. Privatni test kontakt i javni HTTPS host i dalje nedostaju.

Sledeći odeljci sadrže početni pregled od 2026-10-21; ažuriranje iznad ima
prednost za status MCP-a, kapaciteta i ovlašćenja za test pripremu.

Datum pripreme: 2026-10-21. Potvrđeno je da test zaposleni treba da budu na
originalnom SimplyBook nalogu i da tek treba da se naprave. Vlasnica je potvrdila
da je MCP funkcija uključena i aktivna; koristi Zed. Zed povezivanje i dostupnost
alata ovoj sesiji još nisu potvrđeni (videti MCP_SETUP.md). Poslovne odluke će
vlasnica potvrditi naknadno; ne smatraju
se prihvaćenim odobrenjem tehničkog plana. Lokalni razvoj nastavljen je nezavisno.

| Odluka | Preporuka | Zavisna radnja |
|---|---|---|
| Čekanje potvrde | `hold`: zauzeti SB termin, izvorni status 0 čuvati lokalno | Prenos pending događaja |
| No-show / interno | No-show zadržati u istoriji; interno/nepoznato pregledati | Primena tih statusa |
| Gde osoblje menja poreklo SrediMe | Buker; SB je operativni pregled celog salona | Uputstvo osoblju i produkcioni rad |
| Konflikt | Operator proverava oba sistema i kontaktira klijenta; bez automatske zamene osobe/termina | Rešavanje konflikta |
| Potvrde/podsetnici | SrediMe za svoje rezervacije; praktično proveriti SB kopiju da nema duplih poruka | Prenos stvarnih klijenata |
| Podaci klijenta | Početno samo potvrđena veza ka postojećem test klijentu; posebno tražiti kontakte | Client mapping i stvarni prenos |
| Horizont | SrediMe kanal ograničiti na 60 dana; dalje termine ručno proveravati | Usklađivanje podešavanja oba naloga |
| Rasporedi | Promene unapred; za hitnu promenu upis u oba sistema dok satni ciklus nije potvrđen | Prihvatanje preostalog prozora za konflikte |
| Hosting | Postojeći pouzdan host ako postoji; inače jedna mala VM u EU, budžet za odobrenje do 10 EUR/mesec | Javni pilot/deployment |
| Upozorenja | Postojeći zaštićeni webhook ka operativnom kanalu + nezavisna uptime provera | Slanje upozorenja |
| Izolacija pilota — potvrđeno | Test zaposleni/usluge/klijent na originalnom nalogu; pre kreiranja proveriti kapacitet i javnu izolaciju | Priprema konkretnih test zapisa |

## Šta vlasnica treba da uradi

1. Odgovoriti na poslovna pravila iz tabele i navesti željeni kanal upozorenja/postojeći hosting.
2. Prijaviti se u otvoreni Buker; inženjer zatim proverava aktivaciju webhooka i priprema test zaposlene.
   Za sada ne aktivirati salon-wide produkcioni endpoint.
3. Kapacitet originalnog paketa je potvrđen bez doplate; lokalno pripremiti
   kontakte test klijenta pod kontrolom vlasnice.
   Izbor originalnog naloga je već potvrđen i ne traži se ponovo.
4. Obezbediti tačne SrediMe ID-eve zaposlenih/usluga i external_id vrednosti.
   Uneti ih u lokalne CSV tabele; nije potrebno slati privatne URL-ove ili tajne.
5. Tajne uneti direktno u `booking_bridge/.env` pomoću lokalnog editora.
   Postojeća SimplyBook lozinka se ne šalje niti ponovo traži.
6. Odobriti konkretan javni pilot/hosting tek posle izbora ponude i konfiguracije.
7. Izvršiti pilot iz PILOT.md i potvrditi rezultate pre produkcije.

Potpun prenos imena, telefona i imejla zavisi od posebnog SrediMe odobrenja i
uslova zaštite podataka. Bez njega taj deo nije obećan niti zaobiđen.
