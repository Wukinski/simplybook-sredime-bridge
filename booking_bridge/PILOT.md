# Podešavanja i izolovani pilot

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


## Preduslovi i granice odobrenja

Nijedan produkcioni webhook nije kreiran niti aktiviran ovim radom. Nisu
napravljeni zaposleni, usluge, klijenti ili rezervacije. Vlasnica treba da odabere
izolaciju, pravila i odobri konkretan hosting i spoljne test upise.

Potvrđen izbor vlasnice je **test zaposleni/usluge/test klijent na originalnom
nalogu**. Zaposleni tek treba da se naprave. Test zaposleni ne sme biti dostupan
stvarnim klijentima i svi kontakti test klijenta moraju biti pod kontrolom vlasnice.
Kapacitet paketa proveriti pre kreiranja; nema neodobrene doplate.

Pilot `allowed_employees` sadrži samo SrediMe test ID-eve. `pilot_client_ids`
i `pilot_service_ids` sadrže isključivo SB test ID-eve. Promena zaposlenog iz
testa u stvarnog zaposlenog ostaje neobrađena za udaljene upise i otvara incident.
Za test promene zaposlenog potrebna su **dva** dozvoljena test zaposlenog u oba sistema.

## Buker

1. Vlasnica otvara **Buker → Webhooks** i traži besplatnu aktivaciju.
2. Kreira test zaposlenog, a za test pomeranja između zaposlenih i drugog test
   zaposlenog. Dostavlja samo neosetljive ID-eve kroz dogovoreni lokalni postupak.
3. U **Employees → zaposleni → integration fields** prepisuje privatni export
   URL u lokalni `SREDIME_EXPORT_URLS` JSON. URL ne slati kroz razgovor/tiket.
4. U `.local.csv` unosi proverene SrediMe employee/service ID-eve i external_id.
   U `allowed_employees` omogućava samo test zaposlenog/zaposlene.
5. Tek posle odobrenog javnog HTTPS hosta dodaje endpoint:
   `https://ODOBRENI_HOST/sredime/webhook`, port 443, javni DNS i ispravni A/AAAA
   zapisi. Ne uključuje stvarne zaposlene u allowlist-u. Endpoint može ostati neaktivan.
6. Odmah kopira jednom prikazanu 64-znakovnu heksadecimalnu tajnu u privatni
   `booking_bridge/.env`, restartuje API i koristi Buker **Test**.
7. Potvrditi brz 202, proveru potpisa i `state=test`. **Nijedna rezervacija ne nastaje.**
8. Posle odobrenja pilota, aktivira endpoint i pravi stvarne, ali izolovane test
   rezervacije samo kod test zaposlenog. Endpoint i dalje prima događaje celog salona;
   naš filter sprečava upise ostalih zaposlenih.

Za pristup imenima/telefonima/imejlovima posebno kontaktirati SrediMe i dogovoriti
uslove zaštite podataka. Bez toga pilot koristi potvrđenu vezu sa test klijentom;
ne može demonstrirati automatski prenos stvarnih kontakata.

## SimplyBook

1. Proveriti **Custom Features → API → Settings**, korisnička ovlašćenja za
   čitanje kalendara, klijenata i izmene rezervacija. Ne menjati pretplatu automatski.
2. Postojeći nalog koristi potvrđeni REST origin
   `https://user-api-v2.simplybook.me` i company `studioandjelija`.
   REST autentifikacija je `/admin/auth`, zatim `X-Company-Login` + `X-Token`.
   JSON-RPC `getUserToken`, `X-User-Token` i `/admin` na starom hostu su drugi ugovor.
3. Za odvojeni nalog uneti njegove podatke u zaštićeni lokalni profil, podesiti
   `salon`, `expected_rest_base`, potvrditi region i `account_identity_verified`.
   Ne koristiti produkcionu tabelu usluga za drugi nalog. Potrebna su njegova
   eksplicitna mapiranja test ID-eva.
4. Proveriti da je vremenska zona naloga **Europe/Belgrade**. Testirati trajanje,
   buffer, resurse, ograničenja usluga, naplatu/članstvo/intake i prava korisnika.
   Usluga mora eksplicitno dozvoljavati već dodeljenog zaposlenog. Any Employee
   Selector se ne koristi u ovom povezivaču.
5. U `schedule_service_ids` podesiti proverenu referentnu uslugu po test
   zaposlenom, bez posebnih servisnih smena/odsustava. Potvrditi da prikazani
   neradni dan odgovara zaposlenom, a ne samo toj usluzi.
6. API secret za potpisane REST webhookove uneti u `SIMPLYBOOK_WEBHOOK_SECRET`.
   Posle odobrenja javnog endpointa kreirati tri REST pretplate:
   `POST /admin/webhooks` sa JSON telom `{"url":"https://ODOBRENI_HOST/simplybook/webhook","event":"new_booking"}`;
   isto za `change_booking` i `cancel_booking`. Prvo pregledati postojeće pretplate:
   limit je pet aktivnih po događaju; nova šesta deaktivira najstariju.
   Ne kreirati ih automatski u lokalnom razvoju.
7. Webhook ovde služi samo kao potpisani signal za REST čitanje; ne pretpostavlja
   se tačan booking payload bez pilotskog uzorka. Promene rasporeda nisu pokrivene
   tim događajima; radi periodična provera kalendara/rasporeda.

Calendar Sync sa Google/Outlook je zasebna mogućnost. Nije aktiviran i nije
preduslov ovog rešenja. Uvođenje dodatnog kalendara povećava latenciju i rizik
petlji; ne uključivati ga da bi se zaobišla neproverena integracija.

## Povratni ICS

1. Za test zaposlenog generisati privatni token komandom `rotate-feed`.
2. Proveriti privatno da feed ima stvarne SB blokade i nema klijentskih podataka.
3. U Buker polje **URL of external calendar to import** uneti
   `https://ODOBRENI_HOST/ics/SREDIME_TEST_EMPLOYEE_ID/PRIVATNI_TOKEN.ics`.
4. Uz odobren `sredime_refresh`, radnik posle promene šalje objedinjeni POST
   originalnom privatnom export URL-u. Sačuvati dokaz odgovora `refresh_scheduled`;
   kasnije proveriti stvarni blok u Bukeru. HTTP 200 nije potvrda završenog uvoza.

## Obavezni praktični scenariji

Lokalno su automatizovani svi navedeni slučajevi koji mogu da se simuliraju;
sledeća tabela predstavlja **još neizvršen** udaljeni pilot.

| Korak | Očekivanje i dokaz |
|---|---|
| Buker Test, duplikat, pogrešan potpis | 202/test bez upisa; duplikat jedan posao; pogrešan potpis 401 |
| Nova potvrđena rezervacija | Jedna SB rezervacija kod tačno dodeljenog test zaposlenog; trajna veza |
| Čekanje pa potvrda | Dogovoreno zauzeće/status, bez duplih poruka i bez druge rezervacije |
| Termin/usluga/zaposleni | Isti SB booking ID, ispravni resursi/trajanje; drugi test zaposleni samo ako dozvoljen |
| Otkazivanje/brisanje/no-show | Dogovoreno stanje, sačuvana veza i istorija; bez lažnog drugog bloka |
| Istovremeni konflikt | Nema automatske zamene/otkazivanja; incident i operativni postupak |
| SB izvorna rezervacija + izmena/otkazivanje | Povratni ICS dodaje/ažurira/uklanja blok u Bukeru |
| SB pauza, odsustvo, ručna blokada, smena | Dokaz u REST odgovorima i povratnom ICS-u; merena latencija |
| SrediMe → SB kopija, pa pomeranje/nov zaposleni/otkazivanje | Nikada nije dodatni povratni blok; osvežena oba zaposlenog |
| Gubitak odgovora, restart, privremeni pad | Nema ponovnog create bez potvrde ishoda; veza oporavljena ili bezbedan review |
| Poslednja SB blokada uklonjena | Prazan validan ICS; proveriti da Buker uklanja staru blokadu i nastavlja čitanje |
| Europe/Belgrade, granica 60 dana | Ispravan termin i opseg; dalje rezervacije ručno razrešene |
| Prekinuta dostupnost feeda i povratak | Upozorenje i provera oporavka; bez izmišljenih rezervacija |
| Drugi, stvarni zaposleni šalje webhook | Sačuvan kao ignored, nula udaljenih upisa |

## Precizna pitanja podršci

**SrediMe**: „Za naš izolovani test zaposleni, kako uvoz obrađuje uspešan validan
ICS sa nula VEVENT događaja posle brisanja poslednje spoljne blokade: da li odmah
uklanja prethodne blokove? Kako resetujemo proveravanje koje se usporilo ili
stalo posle 100 praznih/neuspelih provera? Da li POST export URL-u ponovo pokreće
zaustavljen uvoz ili je potrebna izmena konfiguracije? Molimo potvrdu veze
ICS UID-a sa webhook data.id i mogućnosti ponovne dostave propuštenih događaja.“

**SimplyBook**, ako pilot to ne razreši: „Za naš potvrđeni regionalni Admin REST
API, može li PUT /admin/bookings/{id} proveriti dostupnost izuzimajući sopstveni
stari termin? Da li admin POST/PUT sprečava istovremeno preklapanje i kako tretira
buffer/resurse? Postoji li podržan način da se za integracionu kopiju ne šalju
potvrde/podsetnici, bez menjanja obaveštenja drugih rezervacija? Da li postoji
webhook za rasporede, pauze, odsustva ili time-blocked note promene?“

Ne slati tajne, cele privatne URL-ove ili klijentske podatke u podršku.

Produkcija se otvara tek po uspešnom pilotu, potvrđenim poslovnim pravilima,
rešenim pitanjima praznog feeda/poruka, eksplicitnim mapiranjima i odobrenom
hostingu. Udaljeni testovi ne mogu biti potvrđeni samo lokalnim zelenim testovima.
