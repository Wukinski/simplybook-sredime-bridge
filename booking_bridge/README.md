# SrediMe/Buker ↔ SimplyBook.me — Studio Anđelija SG

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


**2026-10-22 — SrediMe authentication completed.** The Studio Anđelija SG account
and integration controls were inspected. Nine private export URLs are saved;
the new offline `prepare-source-review` command prepares mapping candidates
without applying them. Nine of 18 unique service-name candidates have duration
conflicts. Live polling and production remain disabled. See
[SREDIME_ACCOUNT_REVIEW.md](SREDIME_ACCOUNT_REVIEW.md) for findings and commands.

Implementiran je lokalni povezivač. Podrazumevani `simulation` režim ne poziva
spoljne sisteme. Produkcija nije aktivirana; odluke, mapiranje i izolovani pilot
još nisu potvrđeni. Import 490 usluga nije ponavljan.

Nastavak odobrenog plana dodaje trajno najnovije poznato stanje i za ignorisane
događaje, migraciju stare baze, dijagnostiku bez upisa i izolaciju ICS kvarova.
MCP prijava i identitet naloga su potvrđeni 2026-10-22; paket ima devet slobodnih
mesta za zaposlene. Odobreni pokušaj test pripreme je povučen: REST kreiranje i
ažuriranje zaposlenog ignorišu `services: []` i dodeljuju postojeće usluge.
Samo novokreirani test ID 8 je uklonjen i početni pregled je potpuno vraćen.
Trenutno nema test zaposlenih/usluga. Zaštićeni `provision_pilot` čuva namere i
blokira nova kreiranja dok izolacija nije dokazana. Prijava u Buker sada je potvrđena;
test kontakti, javni HTTPS host i praktični pilot još nedostaju. Dokaz i naredni
koraci su u [PILOT_SETUP_REVIEW.md](PILOT_SETUP_REVIEW.md).

```powershell
.\.venv\Scripts\python.exe -m booking_bridge diagnose --read-only
.\.venv\Scripts\python.exe -m booking_bridge prepare-pilot
```

`diagnose` koristi zaseban klijent koji odbija poslovne upise čak i uz produkcionu
konfiguraciju. Autentifikacija/obnavljanje tokena i lokalni brojač ostaju postojeći.
`prepare-pilot` radi bez mreže i pravi pregled novih test zapisa vezan hash-om za
provereni početni pregled. Nijedna komanda ne uključuje produkciona pravila.

## Arhitektura

Jedan host, FastAPI prijemnik, jedan radnik i SQLite na trajnom lokalnom disku.
Webhook proverava potpis nad originalnim bajtovima, u jednoj transakciji upisuje
događaj i posao, pa vraća 202. Radnik serijalizuje promene, koristi postojeći
`provider_assignment.client.Client` za REST autentifikaciju, ograničenje poziva
i obnavljanje tokena. Poseban JSON-RPC klijent nije potreban.

```
SrediMe webhook → raw-body HMAC → SQLite inbox → singleton radnik → SimplyBook REST
                                             ↕ trajne veze / namere / incidenti
SimplyBook webhook → potpisani signal → REST provera rezervacija → lokalni snimak
SimplyBook kalendar + raspored + trajanja → privatni ICS zaposlenog → SrediMe uvoz
Promenjen ICS → objedinjeni POST privatnom SrediMe export URL-u → zakazan refresh
SrediMe originalni ICS → zasebna periodična provera, bez ponovnog objavljivanja
```

SQLite `WAL` i `synchronous=FULL`, jedinstveni event ID, OS zaključavanje radnika
i zapis namere pre udaljenog upisa omogućavaju oporavak nakon prekida. Događaj i
rezervacija imaju različite ID-eve. Zastareli snimci ne prepisuju novije, a
različiti snimci sa istim vremenom zahtevaju proveru. Ne koristimo nepotpisano
timestamp zaglavlje za odbacivanje višesatnih ponovljenih isporuka.

## Lokalno pokretanje

Iz korena projekta, u PowerShell-u:

```powershell
.\.venv\Scripts\python.exe -m pip install -r booking_bridge\requirements.txt
.\.venv\Scripts\python.exe -m booking_bridge init
.\.venv\Scripts\python.exe -m pytest booking_bridge\tests -q
.\.venv\Scripts\python.exe -m booking_bridge.tests.smoke_local
.\.venv\Scripts\python.exe -m booking_bridge preflight --target pilot
.\.venv\Scripts\python.exe -m uvicorn booking_bridge.api:app --host 127.0.0.1 --port 8010 --no-access-log --workers 1
```

Smoke test koristi sistemski privremeni direktorijum i ispisuje rezultat na
stdout. Za JSON dokaz dodati `--report booking_bridge/evidence/local-http-smoke.json`.
Preflight radi offline, ne menja konfiguraciju/bazu i izlazi kodom 2 dok
preduslovi pilota nedostaju. Njegov `configuration_ready` nije potvrda udaljenog
pilota. Detalji su u [OPERATIONS.md](OPERATIONS.md).

U drugom terminalu:

```powershell
.\.venv\Scripts\python.exe -m booking_bridge worker
```

`init` je već izvršen: sačuvao je nasumičan administratorski ključ u ignorisani
`booking_bridge/.env`, bez ispisa vrednosti. Nije uneo niti kopirao postojeće
SimplyBook tajne. Menjanje lokalnih datoteka:

```powershell
notepad booking_bridge\.env
notepad booking_bridge\config.local.json
```

Radnik u `simulation` režimu koristi memorijski simulator; njegova udaljena
stanja ne preživljavaju restart. Trajnost reda i oporavak stvarnog udaljenog
sistema testirani su odvojeno. Za ponovljiv lokalni scenario koristi testove i
`fixtures/booking.created.json`, čiji su svi ID-evi sintetički. Ne slati fixture
na produkcioni webhook. Samo `test:true` iz Buker Test nikada ne pravi rezervaciju
ni u pilotu ni u produkciji.

## Konfiguracija i mapiranje

`config.example.json` i `.env.example` sadrže samo primere bez tajni. Radne
konfiguracije, SQLite, lokalne CSV tabele i tajne su ignorisani. SimplyBook
akreditivi ostaju u postojećem `service_importer/.env`. Za izdvojeni nalog
dozvoljen je poseban profil kroz promenljive u `booking_bridge/.env`, sa
`salon`, `expected_rest_base` i potvrdom `account_identity_verified`.

| Tabela | Šta je pripremljeno | Šta nedostaje |
|---|---|---|
| `mappings/employees.csv` | Šest potvrđenih SimplyBook ID-eva | SrediMe ID i očekivani external_id |
| `mappings/services.csv` | Tačno 490 ID-eva iz završenog importa, Excel red, trajanje, naziv | SrediMe ID, external_id, potvrda trajanja i resursa |
| `clients` / lokalna DB tabela | Veza preko neprozirnog SrediMe customer ID-a | Ručna potvrda osobe i saglasnost za povezivanje |

`init` pravi `.local.csv` kopije za uređivanje. Novi katalog koristi
`sredime_webhook_id` kao autoritativni ključ, a `sredime_native_id` samo kao
odvojenu UI metadata. Prazan webhook ključ ostaje nepovezan; stari CSV fajlovi
sa `sredime_id` ostaju podržani. [Tačan format](mappings/README.md).
Nazivi su za ljudsku proveru; nema približnog
uparivanja. Ako webhook ima external_id, on mora odgovarati eksplicitnom redu.
Usluge van importa dodaju se ručno posle provere ID-a; četiri postojeće usluge
nisu proglašene uvezenim uslugama. `prepare_mappings` čita samo postojeći checkpoint
i dokaze; ne menja nalog. Ponovno pokretanje tog pomoćnog alata prepisuje javni
katalog, ali ne lokalne tabele.

Zaposleni: Vanja **2**, Sara **3**, Jelena **4**, Tamara **5**, Olja **6**, Ljilja
**7**. Ovo su ID-evi postojećeg naloga, ne predlog da se oni koriste za pilot.

Za svaku omogućenu uslugu proveriti isti tretman, dodeljenog zaposlenog,
trajanje i `cleanup_duration` naspram `buffer_time_after`, pa uneti
`timing_verified=yes` i `resources_verified=yes`. Razdvojena početna/završna
faza tretmana ide na proveru; ne aproksimira se običnim terminom. Dodatni resursi,
intake forme, članstva i naplata moraju proći pilot. Ne šaljemo parametre za
zaobilaženje članstava ili naplate. Beleške se ne kopiraju.

`schedule_service_ids` zahteva jednu proverenu referentnu uslugu po zaposlenom
koja prati njegov raspored bez sopstvenih izuzetaka. Potvrda
`schedule_reference_verified` je obavezna za izvoz rasporeda: API `/admin/schedule`
je vezan i za uslugu. Izbor proizvoljne usluge može pogrešno protumačiti neradan dan.

## Statusi i tok rada

| SrediMe stanje | Implementirano ponašanje |
|---|---|
| 1 potvrđeno | Kreiranje/izmena, ili potvrda postojećeg pending termina u SB |
| 0 čeka potvrdu | Dok se ne donese odluka: provera; opcija `hold` zauzima SB termin uz izvorni status 0 u DB; `wait` čeka potvrdu |
| -1 interno | Provera, bez automatskog otkazivanja |
| -2 / booking.deleted | Otkazivanje SB termina; veza ostaje kao tombstone |
| -101 / -901 | Otkazivanje SB termina |
| -902 no-show | Provera; uz odobren `retain` čuva istoriju i ne otkazuje termin |
| Nepoznato | Sačuvan status i snimak, slučaj za proveru |

`hold` je operativno zauzeće: u SB može biti potvrđena kopija, dok odluka o
potvrdi klijentu ostaje u SrediMe. To nije izjednačavanje statusa dva proizvoda.
Obaveštenja ne smeju biti omogućena za stvarne klijente dok pilot ne potvrdi
njihovo ponašanje. Nema dokumentovanog REST per-booking `skip_notifications`
parametra i takav parametar nije izmišljen.

Preporučen rad: SrediMe rezervacije menjati u Bukeru, ostale u SimplyBook-u.
Izmene/otkazivanja izvorne kopije u SB izazivaju incident, umesto tihog prepisivanja.
U slučaju konflikta nema zamene zaposlenog, pomeranja, otkazivanja niti prekomernog
zakazivanja po automatizmu. Osoblje proverava oba kalendara i dogovara ispravku.
REST provera dostupnosti prethodi kreiranju i izmeni. Izmena koja preklapa sopstveni
stari termin može zahtevati ručnu proveru jer REST nema dokumentovan parametar
za izuzimanje stare rezervacije; ne radimo cancel/recreate kao zaobilazno rešenje.

## Klijenti

Standardni webhook nema kontakt podatke. Bez odobrene veze ka stvarnom test/
postojećem klijentu događaj ostaje na proveri. Nema lažnih adresa, izmišljenih
klijenata ni spajanja po sličnom imenu. Različiti neprozirni customer ID-evi se
ne spajaju automatski čak ni ako dele telefon/imejl.

Posle odobrenja zaštite podataka, `map-client` povezuje ručno proverenu osobu.
`create-client` podržava posebno odobrene kontakte i zahteva operatorovu potvrdu
da je proverio postojeće klijente. Upisuje nameru pre POST-a; posle nejasnog
ishoda nema ponovnog kreiranja. Nedostajući kontakti se ne oporavljaju iz ICS-a.

## Dostupnost, osvežavanje i petlje

Svaki zaposleni ima privatni token za `/ics/{sredime_employee_id}/{token}.ics`.
Feed nastaje iz SB podataka i sadrži samo stabilan UID, vreme i `Zauzeto`.
Vremena su UTC sa pravilno izračunatim granicama u Europe/Belgrade. Ambivalentni
ili nepostojeći lokalni REST sati pri promeni sata idu na proveru.

Obuhvaćeni su prethodni dan i narednih najviše 60 dana. Otkazani SB događaji se
izostavljaju iz feeda: SrediMe uvoz ignoriše STATUS. Pauze, blokade i neradno
vreme nastaju iz kalendara; izostali neradni dan traži izričit dokaz rasporeda.
Samo beleška sa `time_blocked:true` blokira vreme; servisna ograničenja koja
nisu ograničenja zaposlenog zahtevaju proveru resursa.

Svaka povezana SB rezervacija ostaje isključena iz povratnog feeda i nakon
pomeranja, promene zaposlenog i otkazivanja. Oba zaposlena dobijaju zahtev za
refresh kad se veza promeni. Tombstone se ne briše. Dok postoje nejasne udaljene
namere ili nedozvoljena izmena porekla, pogođeni feed vraća 503 i prijavljuje incident,
umesto objavljivanja mogućeg dodatnog bloka. Obuhvata prethodnog, ciljnog i poznatog
stvarnog zaposlenog; ako opseg nije pouzdano poznat, zadržava se globalna zaštita.

Zahtev je sada dosledno manje od jednog minuta od promene do stvarne dostupnosti.
Postojeći asinhroni ICS ugovor to ne garantuje; produkcija sa podrazumevanim
`require_subminute_availability: true` ostaje blokirana dok ne postoji podržan
transport sa potrebnom potvrdom primene. Istraživanje i implementacija:
[AVAILABILITY_LATENCY.md](AVAILABILITY_LATENCY.md). Buker pristup i odgovori podrške:
[SREDIME_ACCESS_REQUIRED.md](SREDIME_ACCESS_REQUIRED.md).

Rezervacije imaju petominutnu rezervnu proveru; potpisani SB signal može pokrenuti
čitanje posle 10 sekundi od prethodnog pokušaja, uz najviše 60 ubrzanih snimaka/h.
Rasporedi se čitaju u trajnim koracima, potpuno na sat, a prve dve kalendarske
nedelje dodatno na 15 minuta. Delimična provera ne obnavlja starost udaljenih
datuma. Radnik obrađuje rezervacije između koraka.

Prvi SrediMe POST je odmah moguć kada postoji kompletan svež feed. Sledeći
pokušaji objedinjavaju promene tokom 5 sekundi i ograničeni su na 60/h/zaposleni, uz
trajno objedinjavanje narednih promena. Uspeh znači samo zakazan refresh.
SrediMe izvoz proveravamo na 15 minuta, uz limit 12 GET/h/zaposleni.

Pozadinska REST čitanja imaju kraće timeout-e i jedan pokušaj; pre svake stranice
radnik obrađuje rezervacije i šalje dospela osvežavanja. Nepromenjen izlazni feed
ne troši refresh kvotu. Trajna istorija na `/ops/availability/{employee}/history`
razlikuje spreman feed, zakazan refresh i opažen HTTP fetch. Početni snimci nisu
merenja promena, a fetch nije dokaz da je SrediMe primenio blokade. Čekanje u redu
duže od 10 sekundi i izostanak fetch-a duže od 60 sekundi otvaraju incidente.

Za šest zaposlenih redovne provere sada troše okvirno 3.144–3.288 poziva/dan pre
ubrzanih provera, dodatne paginacije, upisa i retry-a. Deljeni klijent i dalje
staje na 4.500 obračunatih poziva/dan. Pri visokom prometu ubrzane provere mogu
iscrpeti budžet; to nije dokaz subminutne dostupnosti. Meriti i saobraćaj drugih
aplikacija/MCP-a koji lokalni brojač ne vidi.

Prazan feed je validan ICS bez izmišljenih događaja. Prazni/neispravni izvorni
feedovi dovode do backoff-a do 12 sati i lokalnog stopa posle 100 neuspeha.
SrediMe ima svoje zasebno usporavanje/proveravanje uvoza: to mora da se testira
sa podrškom, naročito uklanjanje poslednjeg bloka.

## Dokumenti i provere

- [Najverovatniji problemi i potvrđeni nedostaci](MOST_LIKELY_PROBLEMS.md)
- [Zvanični MCP — povezivanje i granice](MCP_SETUP.md)
- [Konkretan predlog novih test zapisa](PILOT_SETUP_REVIEW.md)
- [Odluke i konkretne preostale radnje](DECISIONS.md)
- [Podešavanje Bukera/SimplyBook-a i izolovani pilot](PILOT.md)
- [Nadzor, oporavak, tajne i isključivanje](OPERATIONS.md)
- [Predlog hostinga i deployment](DEPLOYMENT.md)
- [Potvrđene mogućnosti i stvarno testirani ugovori](EVIDENCE.md)
- [JUnit rezultati lokalnih testova](evidence/test-results.xml)
- [Završna dorada: 260 testova i read-only nalog](evidence/followup-validation.json)
- [Provera HTTP-a i odvojenog radnika na localhost-u](evidence/local-http-smoke.json)
- [Docker/Linux validacija, 303 Windows i 171 Linux test](evidence/container-followup-validation.json)
- [Offline preduslovi pilota i produkcije](evidence/offline-preflight-check.json)

Odluke bez odgovora ostaju nepotvrđene. `pilot` traži odobrenje upisa/hostinga,
pravila, zaštitu podataka i eksplicitne test klijente/usluge/zaposlene. Produkcija
dodatno zahteva praktično potvrđen booking, obaveštenja, blokade i prazan feed.
Menjanje approval zastavica je evidencija stvarnog odobrenja/provere; nije zamena
za njih. Potvrđeni pilot, pretplate i javni endpointi opisani su u aktuelnoj
[primopredaji](../AI_HANDOFF.md). Novi lokalni supervisor i isključen Windows
zadatak pripremljeni su bez uključivanja trajnog rada:
[postupci](deploy/PERSISTENT_PUBLISHER.md).

Za odobrenu pripremu trajnog rada na postojećem VPS-u pogledati
[PRODUCTION_READINESS.md](PRODUCTION_READINESS.md): server worker sa obaveznim
gate-om, odvojeni secret šabloni, read-only pregled baza, šifrovani backup i
izolovani restore sa blokadom izvršavanja, kao i nezavisan monitor. Sve je
priprema; produkcioni primeri su simulation/reads off/pending.
