# Konkretan predlog pripreme testa — originalni nalog

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


## Rezultat izvršenja 2026-10-22

MCP i identitet naloga su potvrđeni. Standard paket ima devet slobodnih mesta.
Vlasnica je odobrila izvršenje ovog predloga. Prvi skriveni zaposleni (ID 8)
je kreiran sa `services: []`, ali je server ipak dodelio 12 postojećih usluga.
Isti parametar na PUT nije uklonio veze. Naredna kreiranja su zaustavljena;
uklonjen je samo novokreirani ID 8. Read-back potvrđuje potpuno vraćen baseline.
Nijedna test usluga, klijent ili rezervacija nije kreirana.

`python -m booking_bridge.provision_pilot --execute` čuva nameru pre svakog
POST-a, ne ponavlja nejasan create i proverava stare zapise posle svakog koraka.
Trenutno je blokiran: nedovršeni/povučeni dnevnik traži pregled, a dijagnostika
ne izdaje potvrdu `pilot_provider_isolation_verified`. Ne postavljati tu potvrdu
ručno radi zaobilaženja neuspelog ugovora. Potrebno je prvo dokazati bezbedan
način kreiranja/dodela preko podržanog interfejsa, pa uskladiti implementaciju.
Prazan `services` na zaposlenom trenutno nije pouzdana zaštita na ovom nalogu.

Buker login je otvoren u Chrome-u; pristup zaposlenima i webhook podešavanjima
čeka prijavu. Nema aktivnog javnog endpointa; webhookovi nisu registrovani.
Privatni dnevnik je `state/pilot-provisioning.json`, sanitizovani dokaz je
`evidence/pilot-provisioning-check.json`.

## Prvobitni predlog

Vlasnica je odobrila korišćenje test zaposlenih na originalnom nalogu. Još nisu
napravljeni. Predlog ne uključuje produkcione rezervacije ili potvrdu poslovnih pravila.

| Novi zapis | Predlog | Izolacija |
|---|---|---|
| Zaposleni A | TEST integracija A; jedan klijent istovremeno | Skriven od javnog zakazivanja; bez menjanja postojećih zaposlenih |
| Zaposleni B | TEST integracija B; jedan klijent istovremeno | Ista zaštita; služi proveri promene zaposlenog |
| Usluga A | TEST integracija 30 min; test cena 0; buffer 0 | Skrivena; samo novi test zaposleni |
| Usluga B | TEST integracija 45 min; test cena 0; buffer 0 | Skrivena; samo novi test zaposleni |
| Test klijent | Postojeća pouzdano potvrđena test osoba, ili jedna nova ako je potrebno | Stvarni kontakti vlasnice, uneseni lokalno; bez izmišljenih adresa |

Ovi su predlozi samo priprema; nisu poslati nalogu. Prva dva uslova pre kreiranja
su potvrđena dva slobodna mesta u paketu i potvrđena izolacija od javnog Any Employee
zakazivanja. Skrivenost i prazne veze ne tumače se proizvoljno: API ovde dokumentuje
prazan service.providers kao ANY. Ne menjamo postojeće servise da bismo otvorili test.

Pre svake udaljene promene proveriti stvarnu MCP/REST šemu i mogućnosti naloga.
Za postojeće zapise istog naziva stati radi pregleda tačnih ID-eva, umesto
automatskog povezivanja ili pravljenja novih sufiksa.

## Priprema bez upisa

```powershell
.\.venv\Scripts\python.exe -m booking_bridge diagnose --read-only
.\.venv\Scripts\python.exe -m booking_bridge prepare-pilot
```

Prva komanda beleži sanitizovan read-only pregled i baseline postojećih usluga/
zaposlenih u ignorisanom `state/diagnostics.json`. Druga ne poziva mrežu: pravi
`state/pilot-setup.json` sa hash-om, tačnim predlogom novih zapisa i listom uslova
koji još nisu potvrđeni. Poslovni upisi su u obe komande zabranjeni.

Kontakt se može privatno pripremiti u `secrets/pilot-contact.json`; prazne
vrednosti znače da nedostaje podatak. Ne popunjavati ga podacima drugog klijenta
ili izmišljenim kontaktima. Fajl se ne šalje u chat i ne ulazi u image.

## Izvršenje tek kad su uslovi ispunjeni

1. Proveriti kapacitet/cenu, javnu izolaciju, read-back i stvarne dozvole upisa.
2. Sačuvati početni pregled; kreirati samo dogovorene nove zapise podržanim alatom.
3. Posle svakog upisa proveriti rezultat i upisati novi ID u privatni dnevnik.
   Na nejasan odgovor stati i proveriti ishod, bez ponovnog create.
4. Uporediti sve postojeće ID-eve i njihove postavke sa baseline-om. Imena/cene/
   trajanja/dodele postojećih usluga i zaposlenih moraju ostati ista.
5. Tek zatim pripremiti zaseban pregled test rezervacija. Produkciona pravila se
   ne označavaju potvrđenim radi zaobilaženja zaštite za pilot.
6. Čišćenje posle testa predložiti po stvarno kreiranim ID-evima; nema automatskog
   brisanja zaposlenih, klijenata ili istorije rezervacija.

Nijedan javni endpoint, hosting ili plaćena funkcija nije aktiviran ovom pripremom.
