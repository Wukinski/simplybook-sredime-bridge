# Archived documentation before the live-trial reconciliation

Historical text only, captured on 2026-10-27. These documents contain superseded current-state claims and permissions that were later granted. Use AI_HANDOFF.md and the current handoff documents for actions. Original prose is quoted below; relative links inside the quoted text retain their original locations. No source evidence or private state was changed.

## Original: AI_HANDOFF.md

````markdown
# Primopredaja sledećem AI modelu — počni ovde

Pripremljeno 27.10.2026; dopunjeno posle živog nastavka istog dana.
**Najnovija odluka korisnika:** ne slati podršci; postojeći prevodi su dovoljni
za sada. Nastaviti izgradnju i integraciju, bez zadržavanja na preostalom jeziku.
Ta odluka ne uključuje produkciju niti prenos administratorskih akreditiva.

**Najnovije odobrenje:** korisnik je posle objašnjenja webhook pretplata odgovorio
„potvrdjujem onda sve” na konkretno pitanje za tri SimplyBook booking pretplate,
unos samo svog probnog kontakta u SrediMe ako nedostaje i jedan create/move/cancel
test u oba sistema sa porukama samo njemu. Sve te radnje su sada odobrene;
prethodna odbijanja i čekanja ispod su istorijska. Ne tražiti ponovo istu dozvolu.
Produkcija i prenos administratorskih akreditiva ostaju izvan odobrenja.

**Novije izričito odobrenje:** korisnik je odgovorio „uradi to” na pitanje za
prenos probne zauzetosti bez imena/kontakata i čuvanje SimplyBook HMAC ključa na
postojećem VPS-u 169.58.118.33. Oba konkretna prenosa su odobrena; ranija
auto-review odbijanja ispod su istorija pre ovog odgovora. Administratorski
akreditivi i produkcija nisu obuhvaćeni. Izvršenje i dokaze još treba dopuniti.

**Prenosi su zaista završeni:** [dokaz od 10:08 UTC](booking_bridge/evidence/integration-20261027-approved-transfers.json).
VPS čuva 15 svežih blokova, originalni timestamp-ovi su isti kao lokalno;
liveness/readiness su 200 i nema otvorenih incidenata u tom trenutku. HMAC ključ
je postavljen uz mod 0600 i runtime readback; [poseban dokaz](booking_bridge/evidence/integration-20261027-signing-install.json).
Administratorski akreditivi nisu preneti. Svežina traje ograničeno, publisher nije daemon.

**Nova zasebna prepreka:** automatska kontrola odbila je komandu za kreiranje
tri SimplyBook webhook pretplate (`new_booking`, `change_booking`, `cancel_booking`)
ka postojećem prijemniku, kao posebnu izmenu naloga koju prethodno odobrenje
prenosa ne pokriva. Komanda nije izvršena, pretplate nisu kreirane. Korisniku je
postavljeno jedno precizno async pitanje za te pretplate; odgovor još nije stigao.
Ne pokušavati drugi transport. Skripta `state/setup_sb_webhooks.py --execute`
je pripremljena sa per-POST namerom/readback-om i zaštitom od deaktiviranja drugih pretplata.

**Stvarni uvoz probne zauzetosti je potvrđen:** [dokaz](booking_bridge/evidence/integration-20261027-source-import.json).
Posle jednog podržanog, kvótovanog refresh-a, native SrediMe kalendar prikazuje
svih **12/12 budućih intervala** te verzije, bez viškova/duplikata; ranije 5/12.
Tri od ukupno 15 feed intervala već su bila prošla i nisu uvezena u buduće stanje.
Fetch je viđen 38.063 s posle refresh acceptance-a, puna buduća native slika prvi
put 67.911 s posle acceptance-a; actual commit vreme ostaje unknown. Nije dokazano
booking-change E2E vreme ni <60 s. Zaposleni je ostao zatvoren; nema novih source
bookinga/kupaca iz tog import testa.

**Priprema rezervacionog testa je završena, živi upis dodatno blokiran:**
native trial skripta sada ima inspect/status/customer/prepare/create/move/cancel/restore,
17 privatnih offline testova prolazi; read-only pregled je poslao 0 POST-ova.
Pravi customer modal/submit/readback i guard protiv dodatnog realnog zaposlenog
implementirani su. Međutim, auto-review je i customer-only komandu odbio **pre
pokretanja procesa**, jer odobrenje VPS transfera nije prepoznao kao zasebno
slanje kontakta i kreiranje SrediMe klijenta. Nema novih klijenata/rezervacija,
source customer ID ostaje nepotvrđen, booking create gate ostaje zatvoren.
[Dokaz pripreme/prepreka](booking_bridge/evidence/integration-20261027-next-trial-prepared.json).
Privatni plan je `state/integration-20261027/NATIVE_TRIAL_PLAN_PRIVATE.md`.
Draft `state/collect_source_pilot_event.py` nikad nije pokrenut i programski je
blokiran posle pregleda; pre korišćenja treba tačan customer binding, jedan
izričit queued event bez kontakata i scoped ACK. Nalaz je u privatnom
`state/integration-20261027/COLLECTOR_REVIEW_PRIVATE.md`. Ne bulk-kopirati kasnije
source faze pre izvršenja create-a, jer booking_heads tada stale-uje stariji create.
Ne zaobilaziti odbijanje. Sledeće precizno pitanje obuhvata tri SB pretplate,
unos samo odobrenog korisnikovog kontakta u SrediMe ako nedostaje, i jedan
kontrolisani create/move/cancel ciklus na probnim zapisima oba sistema, poruke
samo tom kontaktu. Ovo ne odobrava produkciju niti administratorske kredencijale.

## Najnoviji nastavak izgradnje — 27.10.2026, 09:48 UTC

- Nova slika `andjelija-bridge:pilot-20261027-integration1` zaista radi na VPS-u
  u oba kontejnera. Worker je sada `booking_bridge.pilot_receiver`: prati zdravlje
  i trajni prijem, ali ne obrađuje rezervacije i ne pravi simulirane veze.
  Ostaju `simulation`, `reads_enabled=false`, scope 11772 → 9.
- **382/382 testa prolaze na Windowsu i 382/382 na Linuxu.** Potvrđeni su i
  HTTP smoke testovi. [Aktuelni rollout](booking_bridge/evidence/integration-20261027-rollout.json)
  beleži image ID, komande procesa i zaštitu kontejnera; ne ponavljati build bez razloga.
- Implementirani su atomski minimalni snapshot paket, ograničen lokalni SSH
  publisher i pojedinačni lokalni pilot izvršilac. Administratorski pristupi
  ostaju lokalno; ništa od toga ne znači da radi automatska sinhronizacija.
- Lokalni read-only snimak 09:46 UTC sadrži **15 blokova**, paket je validiran bez
  imena, kontakata ili tajni. [Dokaz](booking_bridge/evidence/integration-20261027-local-snapshot.json).
  **Nije prenet**: automatska kontrola sada traži izričitu dozvolu za taj sadržaj
  na VPS 169.58.118.33. Zbog starog server snimka readiness opravdano vraća 503.
- Stvarni SimplyBook webhook HMAC ključ pronađen je u nativnom API editoru i
  sačuvan **samo lokalno**. Njegov prenos na isti VPS takođe je odbijen automatskom
  kontrolom. Server ključ je prazan, SimplyBook webhook pretplate nisu kreirane.
  Ne zaobilaziti nijedno odbijanje drugim transportom.
- Korisniku je postavljeno **jedno pitanje** za dozvolu minimalnih termina i tog
  HMAC ključa. Odgovor još nije primljen. To nije zahtev za administratorske lozinke.
- Živo potvrđeni trajanje/pauze/resursi obe test usluge:
  [ugovor usluge](booking_bridge/evidence/pilot-service-contract-20261027.json).
  Samo lokalni capture profil dobio je `timing_verified/resources_verified=true`;
  i dalje nema client mapiranja niti novih živih rezervacija u ovom nastavku.
- Podržani nativni SrediMe `calendar/json` vraća blokove zaposlenog 11772 i kada
  nije bookable. Time je omogućen budući dokaz stvarnog uvoza bez otvaranja termina.
  Svež uvoz i ceo create/move/cancel tok još nisu dokazani.
- Privatni `state/native_source_trial.py` je priprema, **nije izvršen prepare/create**.
  Read-only pregled je potvrdio pravi booking modal na punoj calendar stranici i
  zaseban vidljiv customer modal; POST/readback još nisu implementirani.
  **Prepare/create su sada programski blokirani**; ne menjati flag da bi prošli.
  [Dokaz i završni readback](booking_bridge/evidence/integration-20261027-source-ui-review.json).
  Callback 6 ostaje neaktivan,
  zaposleni 11772 nije bookable, svi dani su neradni i usluga 233160 je neaktivna.

Sledeće: pročitati [integraciono uputstvo](booking_bridge/deploy/INTEGRATION_RUNBOOK.md),
proveriti odgovor na precizno pitanje o prenosima, pa nastaviti svežim lokalnim
publisher ciklusom i dokazom uvoza. Ne slati podršci i ne ponavljati prevode.

## Prethodni jezički nastavak i istorijska primopredaja

**Najnovije:** [provera jezika i nastavak](booking_bridge/localization/LANGUAGE_AUDIT.md).
Potvrđeno je 695 promenjenih klijentskih polja, 8 oznaka trajanja,
10 zajedničkih polja podnožja/oznaka i 35 polja šablona. Rezervacija **2 je otkazana**, potvrđeno kao `canceled`
27.10.2026. u 08:17:45 UTC; klijent **1** je sačuvan. Prijem obaveštenja još
nije potvrđen. Evidencija imejla za taj test pokazala je srpski naslov/telo i
englesko podnožje; podnožje je zatim prevedeno i očitano nazad. Novi render
posle te izmene još nije dokazan. Ne ponavljati otkazivanje, prevode niti završene importe/dodele.
Ceo klijentski put još nije potvrđen kao 100% srpski; preostale provajderske
prepreke i neposlati nacrti pitanja su u novom pregledu. Produkcija je isključena.

Sledeći uvodni opis odnosi se na prvobitnu primopredaju pre ovog nastavka.
Tadašnji operativni dokazi bili su uglavnom od 23.10.2026.
Ova primopredaja je napravljena proverom lokalnih datoteka i prenošenjem konteksta
prethodnog rada. U ovom koraku nisu ponovo proveravani udaljeni nalozi/server i
nisu menjane rezervacije. „Poslednje poznato” nije tvrdnja o stanju danas.

## Zadatak i obavezni redosled čitanja

Nastavi postojeći SrediMe/Buker ↔ SimplyBook.me pilot za Studio Anđelija SG.
Ne počinji implementaciju iznova. Aktuelni prioritet je izgradnja i integracija;
korisnik je prihvatio sadašnje prevode za ovu fazu. Prethodni zahtev za ceo
klijentski put na srpskom i njegove preostale nepoznanice ostaju dokumentovani.

1. [Stanje, dokazi i tačni ID-evi](booking_bridge/handoff/STATE_AND_EVIDENCE.md).
2. [Server, pristupi, kod i bezbedno održavanje](booking_bridge/handoff/OPERATIONS_AND_ACCESS.md).
3. [Naredni koraci, srpski jezik i uklanjanje test promena](booking_bridge/handoff/NEXT_STEPS.md).
4. [Odluke korisnika jednostavnim jezikom](DECISION_CHECKLIST.md).
5. [Glavni dnevnik napretka](SREDIME_SBM_PROGRESS.md), počevši od novog vrha.

Za detalje pročitaj i `booking_bridge/MCP_SETUP.md`, `SREDIME_ACCOUNT_REVIEW.md`,
`PILOT_MAPPING_REVIEW.md`, `PILOT_SETUP_REVIEW.md`, `AVAILABILITY_LATENCY.md`,
`SREDIME_ACCESS_REQUIRED.md`, `DECISIONS.md`, `deploy/PILOT_RUNBOOK.md` i
`deploy/VPS_PILOT.md`. Stariji zahtevi u njima nisu automatski važeći.
Novije korisničke odluke imaju prednost; konkretan nalaz iz aktuelnog čitanja
ima prednost nad starim opisom stanja. Sačuvaj istorijske dokaze.

## Najvažnije pre sledeće radnje

- **Ne šalji novu poruku klijentu, uključujući poruku o otkazivanju, dok ne proveriš
  srpski jezik odgovarajuće stranice/šablona.** To ne znači da su ranije zakazani
  podsetnici isključeni; njihovo stanje je nepoznato i treba ga pročitati.
- Probna SimplyBook rezervacija **2** za **26.10.2026, 10:00–10:30**,
  zaposleni **9**, usluga **496**, klijent **1**, sada je **otkazana**.
  [Autoritativno očitavanje](booking_bridge/evidence/pilot-booking-cancelled-20261027.json)
  vraća `canceled` (izveštaj koristi filter `cancelled`). Ne ponavljati operaciju;
  dobijeni API uspeh ne potvrđuje dostavu poruke.
- Klijent **1** je postojeći korisnikov zapis. **Ne brisati ga** pri čišćenju testa.
- SrediMe test zaposleni **11772** poslednje poznato nije dostupan za zakazivanje,
  svi dani su neradni; test usluga **233160** je neaktivna. Ne otvaraj termine
  stvarnim klijentima radi merenja.
- SrediMe callback **6** postoji, stvarni potpis je preuzet, probna isporuka je
  stigla. Endpoint je poslednje potvrđeno **neaktivan**, ne praviti ga ponovo.
- Server radi u `simulation`, pozadinska čitanja naloga su isključena.
  **Produkcija nije odobrena niti aktivirana.** Živi pojedinačni testovi ne znače
  da radi automatska sinhronizacija rezervacija.
- Kopiranje SimplyBook administratorskih akreditiva na VPS odbila je automatska
  kontrola odobrenja. Nisu prebačeni. Ne zaobilazi odbijanje drugim transportom.
  Lokalno čitanje i prenos minimalnih podataka o zauzetosti već su uspešno korišćeni.

## Odluke koje ne treba ponovo tražiti

- SimplyBook trenutno nije u aktivnoj upotrebi; dozvoljeni su kontrolisani testovi.
  Potpuna izolacija probnog zaposlenog više nije uslov za pilot.
- Postojeći katalog i veze čuvati koliko je praktično; sve test promene zapisati
  sa tačnim ID-evima i predvideti njihovo uklanjanje.
- Ispod 60 sekundi je **cilj optimizacije**, ne uslov za početak pilota.
  Ne čekati garantovano vreme uvoza ili odgovor podrške da bi se nastavilo.
- Dozvoljene su test pripreme i podešavanje webhook-a. Korisnik je obezbedio VPS
  i sopstveni kontakt za test poruke. Ne pitati ponovo za host ili test kontakt.
- Nisu odobreni kupovina hostinga, produkcija, ometanje stvarne SrediMe
  raspoloživosti niti poruke stvarnim klijentima/podršci.
- Potpisi, zaštita akreditiva, sprečavanje duplikata, oporavak i zaštita ličnih
  podataka ostaju obavezni. Ne menjati kriterijume da bi preflight „prošao”.
- Srpski jezik je izričito odlučen. Latinica je saopštena radna pretpostavka,
  ne zasebna eksplicitna korisnikova odluka o pismu.

## Kako raditi sa korisnikom

Piši kratko, razumljivo i na srpskom. Korisnik nije razumeo tehničku listu odluka.
Ne šalji seriju pitanja i ne staj samo radi preferencija: odradi nezavisan posao.
Ako je zaista potrebna odluka, postavi jedno jasno pitanje u razgovoru, sa
konkretnim posledicama i jednostavnim izborom. Prethodni iskačući upit korisnik
nije video. Ćutanje nije odobrenje. Ne ponavljaj lozinke, telefon ili imejl u izveštajima.

Podagente koristiti prema važećim uputstvima sesije; trenutno je uključeno
proaktivno delegiranje nezavisnih zadataka.
Lokalni AGENTS zahtev samo beleži da je Postman CLI instaliran.

## Kratko uputstvo koje korisnik može dati sledećem modelu

> Pročitaj AI_HANDOFF.md i sva tri dokumenta na koja upućuje, pa nastavi od
> postojećeg stanja. Prati najnoviji integracioni nastavak i INTEGRATION_RUNBOOK.md;
> jezik je za sada prihvaćen, podršci ne slati. Proveri odgovor na pitanje o
> prenosu minimalnih termina i webhook HMAC ključa pre tih radnji. Rezervacija 2
> je već otkazana; ne ponavljati import, dodele, prevode ili postojeće test zapise.
> Ne aktiviraj produkciju.


````

## Original: DECISION_CHECKLIST.md

````markdown
# Odluke za povezivanje SrediMe i SimplyBook

## Aktuelno — 27.10.2026.

**Najnoviji odgovor „potvrdjujem onda sve”:** odobrene su i tri SimplyBook booking
webhook pretplate, unos samo korisnikovog probnog kontakta u SrediMe ako ga nema,
i jedan ciklus create/move/cancel na probnim zapisima oba sistema, poruke samo
tom kontaktu. Prethodna čekanja za stavke16/17 su rešena; ne tražiti ih ponovo.
Produkcija i administratorski kredencijali nisu obuhvaćeni.

**Poslednja odluka:** podršci se ne šalje ništa. Postojeći prevodi su dovoljno
dobri za sada; prioritet su izgradnja i integracioni testovi. Preostale jezičke
nepoznanice su evidentirane i ne zaustavljaju kontrolisani pilot. Produkcija
i prenos SimplyBook administratorskih akreditiva ostaju zasebne odluke.

**Novo precizno pitanje posle build-a:** automatska kontrola traži izričito
odobrenje da se na postojeći VPS 169.58.118.33 prenesu (a) samo termini zauzetosti
test zaposlenog 9 bez imena/kontakata i (b) SimplyBook ključ za proveru webhook
potpisa. Ni jedno nije preneto u ovom nastavku. Pitanje je postavljeno u razgovoru;
odgovor još nije primljen. To ne uključuje administratorske lozinke niti produkciju.

**Odgovor korisnika „uradi to”: oba navedena prenosa su sada izričito odobrena**
na isti postojeći VPS. Gornji opis čekanja odnosi se na trenutak pre tog odgovora;
prenos administratorskih pristupa i produkcija ostaju neodobreni.

Oba odobrena prenosa su potom završena i proverena. Novo zasebno pitanje je
uključivanje tri booking webhook pretplate. Automatska kontrola je tu komandu
odbila kao posebnu izmenu naloga; ona nije izvršena i čeka odgovor korisnika.

Odgovori u razgovoru, na primer: **„Odobravam 12”**, **„Ne odobravam 12”** ili
**„Za 6 želim drugo rešenje…”**. Ne moraš da menjaš ovaj fajl. Kada odluka postane
neophodna, dobićeš jedno konkretno pitanje; ne treba sada odgovoriti na sve.
Odobrenje jedne stavke ne odobrava kupovinu ili puštanje svega u rad.

„Odlučeno” znači da si već dao odgovor. „Za probu” je privremeno rešenje.
„Kasnije” ne zaustavlja sadašnji rad. „Čeka odobrenje” važi samo za navedenu radnju.

| Broj / odluka | Izabrano ili preporučeno rešenje | Status | Kada je potrebno |
|---|---|---|---|
| 1. Gde radi veza? | Na VPS-u koji si dao; probna aplikacija je postavljena. | Odlučeno | Već urađeno; proveravati rad |
| 2. Kome idu probne poruke? | Tebi, na kontakt koji si dao. Privatno je potvrđen tvoj postojeći SimplyBook zapis. | Odlučeno | Svaki test koji šalje poruku |
| 3. Na čemu testiramo? | Jedan označen probni zaposleni i usluga od 30 minuta u oba sistema. SrediMe test ostaje zatvoren za stvarne klijente. | Za probu | Test zapisi već postoje |
| 4. Nepotvrđen termin i poruke | Čuvamo zauzeće dok čeka potvrdu; nedolazak ostaje u istoriji. Probne poruke samo tebi, na srpskom. | Za probu | Obrada probnih rezervacija |
| 5. Kako saznajemo za kvar? | Server se proverava svakog minuta. Greške se beleže; kasnije biramo kome stiže upozorenje. | Za probu; primalac kasnije | Pre stvarnog rada treba spoljno upozorenje |
| 6. Kako vraćamo podatke? | Kopija svakog sata na istom serveru. Pre stvarne upotrebe treba i zaštićena kopija van servera. | Za probu; drugo mesto kasnije | Pre svakodnevnog oslanjanja na vezu |
| 7. Podaci klijenata | Koristimo samo neophodno; ne kopiramo celu listu niti spajamo ljude po sličnom imenu. | Za probu | Svaki rad sa podacima |
| 8. Uklanjanje testa | Vodimo tačne ID-eve i uklanjamo samo test promene. Tvoj postojeći profil se ne briše. | Za probu | Po završetku testa |
| 9. Stvarni zaposleni/usluge | Kasnije potvrđujemo identitet, trajanje i opremu. Sara i Sanja se ne smatraju istom osobom. | Kasnije | Pre proširenja izvan testa |
| 10. Rad za sve klijente | Posle uspešnih testova, provere poruka, kašnjenja i oporavka tražimo tvoje posebno odobrenje. | Kasnije; nije odobreno | Pre produkcije, odnosno stvarnog rada |
| 11. Poruka podršci | Pripremamo nacrt ako zatreba; šaljemo samo na tvoj nalog. | Kasnije | Ako njihov odgovor postane neophodan |
| 12. SimplyBook administratorski pristup na serveru | Ako automatski test zahteva taj pristup, prvo tražimo tvoje izričito odobrenje. Čitamo lokalno; i minimalni prenos zauzetosti sada čeka zasebno odobrenje ispod. | Čeka odobrenje za prenos; drugi rad se nastavlja | Pre postavljanja tih akreditiva na VPS |
| 13. Jezik za klijente | Sve na srpskom: stranice, potvrde, podsetnici, izmene i otkazivanja. Latinica je radna pretpostavka. Sačuvani su prevodi stranice i 35 polja poruka. | Delimično podešeno; provajderovi tekstovi i prijem poruke još nisu potvrđeni | Pre javne upotrebe; kontrolisana provera je nastavljena |
| 14. Minimalna test zauzetost na VPS | Samo termini probnog zaposlenog 9, bez imena, kontakata i kredencijala; postojeći VPS 169.58.118.33. | Odobreno i izvršeno: 15 blokova, originalni timestamp-ovi potvrđeni | Naredni ograničeni publisher ciklusi unutar istog scope-a |
| 15. Provera SimplyBook potpisa na VPS | Samo stvarni HMAC ključ, u zaštićenoj konfiguraciji postojećeg VPS-a; bez administratorskog pristupa nalogu. | Odobreno i izvršeno: 0600 i runtime readback | Ključ spreman za prijem stvarnih provider poruka |
| 16. Tri SimplyBook booking webhook pretplate | new_booking/change_booking/cancel_booking ka postojećem VPS prijemniku; obaveštenja rezervacija naloga. | Novo pitanje posle zasebnog auto-review odbijanja; čeka odgovor | Pre stvarne automatske isporuke SimplyBook događaja |
| 17. Probni kontakt u SrediMe i povezani test ciklus | Ponoviti tri tačne pretrage; ako kontakt nedostaje, upisati samo korisnikov probni kontakt i potvrditi oba kanala/ID; jedan create/move/cancel test na probnim zapisima oba sistema, poruke samo korisniku. | Customer-only komanda odbijena pre procesa; neizvršena, obuhvaćena sledećim preciznim pitanjem | Pre source customer mapiranja i živog rezervacionog testa |

Već si odobrio kontrolisane SimplyBook testove bez potpune izolacije zaposlenog,
uz čuvanje kataloga i dnevnik promena. Ispod jednog minuta je cilj za poboljšavanje,
a ne uslov početka testa. Ne čekamo garancije podrške. Nisu odobreni ometanje
stvarnih SrediMe termina, kupovina hostinga ili puštanje veze u stvarni rad.

Za stavku 12 automatska kontrola je odbila kopiranje administratorskih akreditiva:
dozvola za korišćenje servera nije izričito obuhvatala prenos tih osetljivih podataka.
Oni mogu omogućiti upravljanje SimplyBook nalogom, ne samo čitanje slobodnih
termina. Nisu preneti. Ovo ne blokira pripremu dokumentacije i lokalne provere.

Detalji za sledeći model: [AI_HANDOFF.md](AI_HANDOFF.md).

## Istorijska verzija od 23.10.2026. — nije aktuelna lista

Tekst ispod je sačuvan kao istorija. Njegove tvrdnje da kontakt nedostaje više
ne važe; gornja tabela je jedina aktuelna lista odluka.

### Choices for the booking integration - historical

Updated 23 October 2026.

We are connecting SrediMe and SimplyBook so bookings and blocked times can be
shared. We have created test records, but the connection is not yet running for
real customers. We have not measured how long a change takes to appear in the
other system.

## How to approve, reject or change something

Reply in this chat using the item number. There is no approval button or form.
For example:

- "Approve 3, 4 and 5 for testing."
- "Reject 6. I want daily backups instead of hourly."
- "Leave 9 for later."
- "Change 4: I want to check every test message before it is sent."

You do not need to edit this file. I will record your answer and make the
corresponding changes. A question or silence does not count as approval.
Approval applies to the item you name: approving tests does not approve spending
money or switching the connection on for real customers.

Some items need information, not approval. For example, saying "approve the
server" does not provide an actual server or access to it.

## What the status words mean

- **Already agreed:** you have decided this. No need to approve it again.
- **Temporary choice for testing:** I chose a practical starting point. It applies
  only to tests; you can change it.
- **Waiting for information:** a specific missing detail prevents that step.
- **Can wait:** we can continue other work without deciding this now.

## What you have already agreed

- We may use your currently unused SimplyBook account for integration tests.
  Test records should be clearly named, logged and easy to remove. They do not
  need to be completely separate from the existing SimplyBook setup.
- We should build the connection using the tools already available, measure its
  speed, then improve it. Updates under one minute are a goal, not a condition
  for starting tests. We do not need to wait for a provider guarantee.
- Tests must protect real SrediMe appointments, customer availability and messages.
- This instruction does not approve buying hosting or turning on the connection
  for real customers.

## What matters next

### 1. A place to run the connection

**Meaning:** an internet-accessible computer that stays on, even when your laptop
is off.

**Your decision:** use the VPS you supplied. Access worked. A secure test service
is running at https://169.58.118.33/health/live. No new server or domain was bought.
The service is in test mode and is not synchronizing real customer bookings.

**Status:** Already agreed; server setup and secure connection completed.
The server password was not saved in project files. A separate private access key
was prepared for ongoing setup.

### 2. A person/contact to use for test bookings

**Meaning:** test bookings might send confirmations or reminders. They need to go
to you or someone who has agreed to help, rather than an actual customer.

**Recommendation:** use your own contact details. Store them privately in
`booking_bridge/secrets/pilot-contact.json`; the file is currently empty. I can
help you enter them without putting them in project reports.

**Status:** Waiting for information.
**Needed:** before creating test customers or bookings that might send messages.

Approving this approach alone does not supply the missing contact details.

## Temporary choices I have made for testing

| Item | Choice in everyday language | Status | When it matters |
|---|---|---|---|
| 3. Test employee and service | Use one clearly named test employee and one 30-minute test service in each system. Keep the SrediMe employee unavailable to customers and the service inactive until a controlled test needs them. Real employee/service matches can wait. | Temporary choice for testing | Prepared already; before booking tests |
| 4. Unconfirmed bookings and messages | An appointment waiting for confirmation should still keep its time occupied in the other system. A no-show stays in history. Send test messages only to the agreed test contact; leave real salon message settings alone. Unexpected booking states stop for review. | Temporary choice for testing | First booking test; real-customer rules will need review later |
| 5. Detecting problems | Check that the connection is running and flag failed or delayed work. For now, keep a local record. The hosted connection is checked every minute. Choose an alert recipient later. | Temporary choice for testing | Hosted tests; alert recipient still unspecified |
| 6. Recovery copies | During hosted testing, save an hourly recovery copy, protected and stored separately from the running connection. An hourly recovery copy now runs on the server and passed its integrity check. A separate, protected backup location is still needed; this is not yet an off-server backup. | Temporary choice for testing | Before hosted tests start making booking changes |
| 7. Customer information | Use only the customer information needed for the test. Do not copy the whole customer list or guess that two people with similar names are the same person. | Temporary choice for testing | Every test involving customer information |
| 8. Removing test changes | Keep a list of exactly what we created. Check for test bookings before removing those records. Preserve the log and leave existing salon records alone. | Temporary choice for testing | After testing or if we need to undo changes |

You may approve or change these choices, but they do not all need answers now.
The server is available now. Work that needs a test customer still waits for
your controlled contact.

## Choices that can wait

| Item | Recommendation | Status | When it matters |
|---|---|---|---|
| 9. Connecting real employees/services | Confirm who matches whom, service lengths and required equipment before using real salon records. Sara versus Sanja remains unresolved. | Can wait | Before expanding beyond the test records |
| 10. Switching on for real customers | Review actual test results, messages, delays and recovery behavior first. Then request your separate approval to launch. Decide the acceptable real-use delay from those results. | Can wait | After a working test connection |
| 11. Contacting provider support | Ask for help if testing reveals a problem we cannot resolve. Draft requests exist but have not been sent; I need your instruction before sending them. | Can wait | If provider help becomes necessary |

Technical details and evidence are in [SREDIME_SBM_PROGRESS.md](SREDIME_SBM_PROGRESS.md).
This file records decisions only; it does not itself switch anything on.

````

## Original: SREDIME_SBM_PROGRESS.md

````markdown
# SrediMe / Buker <-> SimplyBook.me progress

## Izričito odobreni prenosi i dokazan uvoz — 27. oktobar 2026.

Korisnik je odgovorio **„uradi to”** na konkretno pitanje za minimalnu probnu
zauzetost i SimplyBook HMAC ključ na postojećem VPS-u. Oba prenosa su izvršena.

- `pilot_publish` je prihvaćen sa 15 blokova; originalni timestamp-ovi na VPS-u
  podudaraju se sa lokalnim snimkom. Ponovljen je još jedan svež ciklus istog
  obuhvata, bez promena rezervacija ili prenosa kredencijala.
- Samo SimplyBook signing ključ je instaliran u postojeći `pilot.env`, mod 0600.
  Kontejneri su ponovo kreirani radi secret bind mount-a, runtime učitavanje je
  provereno. Administratorski pristupi nisu preneti. Javni pogrešan potpis daje 401.
- Readiness posle prenosa vraća 200, sa 0 otvorenih incidenata u trenutku provere.
  To nije trajni publisher/automatski booking worker: keš ponovo zastareva ako
  lokalni proces ne pravi nove snimke.
- Jedan podržan SrediMe refresh POST, uz prethodno trajno rezervisanu kvotu,
  prihvaćen je u 10:08:55.988 UTC. Host je poslužio istu verziju/15 događaja u
  10:09:34.051 UTC. Native calendar readback u 10:10:03.900 UTC pokazuje **12/12
  budućih blokova**, bez viškova i duplikata. Tri druga intervala iz feed-a već
  su bila u prošlosti pre refresh-a; nije tvrđen puni istorijski 15/15 import.
  Baseline je imao samo 5/12 očekivanih budućih intervala.
- Izmereno je 38.063 s od refresh acceptance-a do fetch-a i 67.911 s do prvog
  potpunog native budućeg stanja. Stvarni commit timestamp nije poznat; ovo
  **nije** booking-change E2E merenje niti tvrdnja o kašnjenju ispod 60 sekundi.
- Novo kreiranje tri SimplyBook webhook pretplate odbila je automatska kontrola
  kao zasebnu izmenu naloga. Komanda nije izvršena, nema novih pretplata.
  Postavljeno je jedno pitanje za te tri pretplate; odgovor još nije primljen.

Dokazi: [odobreni prenosi](booking_bridge/evidence/integration-20261027-approved-transfers.json),
[instalacija ključa](booking_bridge/evidence/integration-20261027-signing-install.json),
[stvarni budući uvoz](booking_bridge/evidence/integration-20261027-source-import.json).
Podršci ništa nije poslato. Produkcija i globalna booking obrada ostaju isključene.

Native rezervacioni tok je potom pripremljen (17 privatnih offline testova,
read-only review bez POST-a). Customer-only komandu automatska kontrola odbila
je pre pokretanja, zbog zasebnog slanja ličnih podataka/kreiranja zapisa u SrediMe.
Nema novih source klijenata, rezervacija ili promena callback/bookable zastavica.
Booking create guard ostaje zatvoren; customer ID i `clients` mapiranje nepotvrđeni.
[Dokaz pripreme i prepreka](booking_bridge/evidence/integration-20261027-next-trial-prepared.json).
Sledeće jedno precizno odobrenje treba da pokrije pretplate i kompletan kontrolisani
test sa korisnikovim kontaktom, kako se dozvola ne bi tražila za svaki pojedinačni upis.

## Nastavak izgradnje — 27. oktobar 2026, 09:48 UTC

Korisnik je prihvatio postojeće prevode za sada i tražio nastavak izgradnje i
integracije. Podršci nije ništa poslato. Završeni importi i test otkazivanje nisu
ponavljani. Produkcija ostaje isključena.

- Implementiran je validiran minimalni paket zauzetosti: koherentna generacija
  bookings/buffers/schedule, atomski uvoz sa izvornim vremenima, zaštita od
  zastarevanja/replay-a i povratnog preslikavanja sopstvenih rezervacija. Paket
  isključuje kontakte, imena i slobodan tekst; nepoznate usluge na istom probnom
  zaposlenom izazivaju pregled umesto tihog izostavljanja zauzeća.
- Ograničeni `pilot_publish` čita nalog lokalno i pripremljen je da šalje samo
  taj paket preko proverenog SSH hosta. Nije instaliran trajni proces na računaru;
  zatvaranje konačnog broja ciklusa zaustavlja osvežavanje. To nije autonomna
  sinhronizacija rezervacija niti rešenje koje radi bez ovog računara.
- Dodati su `pilot_receiver`, koji čuva red bez simuliranih upisa, i
  `pilot_execute`, koji lokalno obrađuje samo jedan pregledan događaj uz eksplicitni
  pilot profil, client mapiranje, lock i bez automatskog retry-a.
- Ispravljeno je pakovanje javnih CSV kataloga, uz regresioni test. Build paket
  isključuje privatna stanja, tajne, lokalne konfiguracije i lokalna CSV mapiranja.
- **382 testa prolaze na Windowsu i 382 na Linuxu**, bez preskakanja; oba HTTP
  smoke testa prolaze. Prvi Linux pokušaj je otkrio nedostajući javni CSV i ostao
  sačuvan kao neuspešna istorija; završni dokaz je novi uspešan XML.
- Na VPS su postavljeni nova slika `pilot-20261027-integration1` i receiver komanda,
  posle backup-a i provere Compose konfiguracije. API i receiver rade kao 10001,
  sa read-only root filesystem-om i bez capabilities. `simulation` i reads off ostaju.
- Lokalni snimak 09:46 UTC ima **15 blokova**; **nije prenet**. Automatska kontrola
  odbila je komandu za prenos minimalne zauzetosti na 169.58.118.33, jer traži
  specifično odobrenje za taj sadržaj i odredište. Nije pokušan drugi transport.
  Server liveness je 200, privatni readiness je 503 zbog `booking_snapshot_stale`.
- Nativni API editor dao je stvarni SimplyBook HMAC ključ, sačuvan samo lokalno.
  Njegov prenos na VPS takođe je odbijen automatskom kontrolom. Server ključ je
  prazan, a webhook pretplate nisu kreirane. Administratorski pristupi nisu preneti.
- Postavljeno je jedno precizno pitanje za oba prenosa; odgovor još nije stigao.
  Lokalne provere i dokumentacija nastavljene su nezavisno od te prepreke.
- Živo su provereni trajanje 30 min, nulte pauze i resursi obe probne usluge.
  Nativni SrediMe calendar/json omogućava čitanje uvezenih blokova zatvorenog
  zaposlenog 11772. Svež udaljeni uvoz i create/move/cancel tok još nisu dokazani;
  nisu napravljeni novi kupci ili rezervacije niti aktiviran callback 6.

Završni [read-only pregled source UI-ja](booking_bridge/evidence/integration-20261027-source-ui-review.json)
potvrdio je zaseban native customer modal umesto skrivenih inline polja. Draft
prepare/create su programski blokirani do implementacije POST-a i nezavisnog
readback-a. Poslednji native status potvrđuje callback off, employee bookable off,
svih 7 dana neradnih i 0 probnih rezervacija u pregledanom prozoru 27–31.10.

Dokazi: [rollout](booking_bridge/evidence/integration-20261027-rollout.json),
[lokalni snimak](booking_bridge/evidence/integration-20261027-local-snapshot.json),
[ugovor usluge](booking_bridge/evidence/pilot-service-contract-20261027.json),
[Windows](booking_bridge/evidence/integration-20261027-windows-tests.xml),
[Linux](booking_bridge/evidence/integration-20261027-linux-tests.xml).
Nastavak: [integraciono uputstvo](booking_bridge/deploy/INTEGRATION_RUNBOOK.md).

## Nastavak — 27. oktobar 2026: srpski jezik i zaključenje stare rezervacije

Pročitana je primopredaja i povezani dokumenti. Završeni uvoz, kategorije,
dodele i kreiranje test zapisa nisu ponavljani. Najnoviji detalji su u
[jezičkom pregledu](booking_bridge/localization/LANGUAGE_AUDIT.md).

- Kroz postojeći administratorski UI sačuvano je **695 različitih klijentskih
  polja** i **18 zajedničkih sistemskih polja** (8 za trajanje, 10 za podnožje
  imejla/prateće oznake). Javno su provereni početna
  stranica, izbor usluge i datuma i formular klijenta; `mins.` sada piše `min`.
- Sačuvano i očitano nazad **35 polja šablona**: 22 osnovna klijentska
  imejl/SMS polja, 9 polja obaveštenja o plaćanju i 4 SBPay polja za račun i
  knjižno odobrenje. Očuvani su uključeni kanali, podsetnici i postavke plaćanja.
  Nisu uključene ili kupljene nove funkcije i nije resetovan sistemski jezik.
- Editor je odbio jednu grupu zbog PO sintakse u HTML ključu sa navodnicima.
  Potpuno očuvano udaljeno stanje potvrđeno je pre ispravljenog pokušaja;
  ostatak je uspešno sačuvan bez problematičnog unosa. Privatni backup,
  namere i puna poređenja ostaju u ignorisanom audit direktorijumu.
- Postojeća rezervacija **2** otkazana je posle ponovne provere oba odobrena
  kontakta i srpskih šablona otkazivanja. Izveštaj `cancelled` potvrđuje stvarni
  status **`canceled`**, 27.10. u 08:17:45 UTC. **Klijent 1 ostaje.** Nije
  napravljena nova rezervacija. Prijem i konačan izgled poruke još nisu potvrđeni.
- [Zapis imejla za test](booking_bridge/evidence/pilot-cancellation-message-log-20261027.json)
  poklopljen je sa rezervacijom 2 i odobrenim kontaktom: naslov/telo srpski,
  podnožje englesko. Podnožje je zatim prevedeno i readback potvrđen; novi render
  posle ispravke još nije viđen. Datum loga `27-10-2026 01:54` nema navedenu zonu;
  nije korišćen kao UTC vreme slanja ili mera kašnjenja. Log nije dokaz inbox dostave.
- Nije potvrđeno „100% srpski”: ostali su provajderovi tekstovi i jezičke
  nepoznanice, među njima HTML `lang=en`, zvanični engleski uslovi, WhatsApp
  šabloni i SrediMe `Previous`/`Next` oznake galerije. [Nacrti pitanja](booking_bridge/localization/PROVIDER_LANGUAGE_REQUESTS.md)
  su spremni za pregled, **nisu poslati**.
- Živo očitavanje VPS-a potvrđuje `simulation`, `reads_enabled=false`, aktivne
  tajmere i sertifikat obnovljen do 02.11.2026. u 14:34:01 UTC. Readiness i
  privatni feed vraćali su 503 zbog starog snimka. Nije prenet novi snimak,
  administratorski akreditivi ni nova konfiguracija; automatska sinhronizacija
  i produkcija nisu uključene.
- SrediMe test zaposleni 11772 ostaje nedostupan/svi dani neradni, usluga
  233160 neaktivna, callback 6 deaktiviran. Postojeći webhook događaj je ponovo
  pročitan iz baze: `booking.updated`, `test:false`, ignorisan zbog zaposlenog
  van allowlist-a; bez bridge veza ili namera upisa.

Novi javni dokazi: [jezik](booking_bridge/evidence/client-language-audit-20261027.json),
[otkazivanje](booking_bridge/evidence/pilot-booking-cancelled-20261027.json),
[operacije](booking_bridge/evidence/pilot-operations-check-20261027.json),
[trajni prijem](booking_bridge/evidence/live-source-webhook-receipt-20261027.json).
Validirani su JSON datoteke i stvarni UI readback-i; aplikacioni i Linux testovi
nisu ponavljani jer runtime kod nije menjan. Stari rezultati testova ostaju istorija.

Sledeće: pregledati postojeće obaveštenje za otkazivanje pre novog slanja,
razjasniti preostale provajderske prevode uz izričit nalog za kontakt podršci,
pa nastaviti ograničeni pilot. Ne ponavljati otkazivanje rezervacije 2.

## Aktuelna primopredaja — 27. oktobar 2026.

**Počni od [AI_HANDOFF.md](AI_HANDOFF.md).** Potpuni nastavak konteksta je u
[stanju i dokazima](booking_bridge/handoff/STATE_AND_EVIDENCE.md),
[operativnim uputstvima](booking_bridge/handoff/OPERATIONS_AND_ACCESS.md) i
[narednim koracima](booking_bridge/handoff/NEXT_STEPS.md).
Ovaj unos zasniva se na proveri lokalnih dokumenata i prethodnim operativnim
nalazima od 23.10; udaljeno stanje nije ponovo provereno pri primopredaji.
Ostatak dnevnika ispod je **istorija** sa zastarelim tvrdnjama koje ovaj unos ispravlja.

- Novi obavezni zahtev: sve stranice i poruke namenjene klijentima moraju biti
  na srpskom. Latinica je radna pretpostavka. Podešavanje/provera nisu završeni;
  pre sledeće radnje koja šalje poruku proveriti njen jezik, uključujući otkazivanje.
- Host i kontakt za testiranje više ne nedostaju. Korisnikov kontakt je privatno
  potvrđen kao postojeći SimplyBook klijent **1**; ne brisati ga pri čišćenju.
- SimplyBook rezervacija **2** kreirana je za test zaposlenog **9**, uslugu **496**,
  26.10.2026. u 09:00–09:30, zatim pomerena na 10:00–10:30 Europe/Belgrade.
  Nema zabeleženog otkazivanja. Datum je prošao: prvo pročitati današnji status.
- DNS HTTPS `https://vmi3688215.contaboserver.net/health/live` dodat je uz IP HTTPS.
  SrediMe callback **6** uspešno je kreiran, potpis sačuvan privatno i instaliran;
  posle readback-a endpoint je deaktiviran. Buker Test je stigao sa HTTP 202;
  događaj je ignorisan zbog zaposlenog van allowlist-a, bez poslovnog upisa.
- Samo test zaposlenom **11772** upisan je privatni import URL. Zaposleni je
  poslednje potvrđeno nedostupan za zakazivanje/svi dani neradni, usluga **233160**
  neaktivna. Refresh POST je prihvaćen za 0,422 s. Zabeležen fetch nije potvrda
  završetka udaljenog uvoza ili promene raspoloživosti klijentima.
- [Snimak posle kreiranja](booking_bridge/evidence/pilot-booking-created-feed.json)
  nastao je za 4,761 s i prenet kao minimalni paket zauzetosti na host.
  [Snimak posle pomeranja](booking_bridge/evidence/pilot-booking-moved-feed.json)
  nastao je za 4,003 s; njegov prenos na host nije potvrđen.
  [Podešavanje import-a](booking_bridge/evidence/pilot-import-setup.json) potvrđuje
  URL/readback i refresh acceptance, ne remote completion.
- Produkcija nije aktivirana; host je `simulation`, bez pozadinskih čitanja naloga.
  Ručni prenos snimka nije automatska sinhronizacija.
- Automatska kontrola odobrenja odbila je prenos SimplyBook administratorskih
  akreditiva na VPS jer odobrenje korišćenja hosta ne pokriva izričito taj prenos.
  Tajne nisu prenete. Lokalni Compose snapshot profil je nedovršen predlog,
  nije postavljen i referencira nepostojeći `snapshot.env`.
- Poslednji puni dokazi: **385 Windows** i **249 Linux** testova, oba smoke testa
  u simulaciji. Novi `pilot_snapshot.py` ima 4 fokusirana Windows prolaza iz
  prethodne sesije; puna regresija/Linux za taj dodatak nisu ponovljeni.
- Ispod 60 s ostaje optimizacioni cilj. Stvarno end-to-end vreme do efektivne
  udaljene raspoloživosti je **nepoznato**. Support garancije i potpuna izolacija
  zaposlenog nisu uslovi za pilot.

Pri ovoj primopredaji napisani su dokumenti i proverene lokalne reference/dokazi.
Nisu slati novi zahtevi provajderima ni poruke klijentima.

## Istorijski zapisi počinju ovde

## Current VPS checkpoint - 23 October 2026

The owner supplied an existing VPS and authorized its use for this project.
Access succeeded. The test application is now hosted at
https://169.58.118.33/health/live with a publicly trusted IP certificate; no domain
or hosting purchase was needed. Production synchronization remains disabled,
mode is simulation and live account background reads remain off.

- Installed Docker/Compose/nginx and prepared a separate root-private release
  under `/opt/booking-bridge-pilot`. Existing applications were absent. The root
  password was not saved in project files; ongoing access uses a separate private
  key with a pinned host fingerprint.
- Current image passed **249 Linux tests** and Linux HTTP smoke. The prior local
  Docker Desktop problem no longer prevents Linux validation on this VPS. Runtime
  source hashes match the workspace. Previous **385 Windows tests** remain the
  latest Windows result; no runtime business logic changed in this hosting step.
- External checks: trusted HTTPS/liveness 200; admin/readiness and invalid feed
  URL 404; unsigned source and SimplyBook webhooks 401. One API/worker run as
  non-root containers; port 8000 binds only to loopback.
- Certificate renewal timer is active; renewal dry run passed. Local private
  readiness checks run every minute. Hourly on-server SQLite recovery copies are
  configured; the first integrity check passed. Off-host/encrypted disaster
  backup and an external alert destination are still outstanding.
- One inactive SrediMe callback creation was attempted, but the endpoint name did
  not appear in subsequent list reads. The exact remote outcome is unresolved;
  the private journal prevents automatic retry. Callback registration, real
  signing secrets and a source Test receipt have **not** been verified.
- Existing test IDs remain SrediMe employee 11772/service 233160 and SimplyBook
  provider 9/service 496. Source employee remains nonbookable/service inactive.
  No new client, booking or import URL changes were made in this hosting step.
  Actual cross-system availability delay remains unknown.

Current evidence: [VPS validation](booking_bridge/evidence/vps-pilot-deployment-validation.json),
[Linux tests](booking_bridge/evidence/vps-pilot-linux-tests.xml),
[Linux smoke](booking_bridge/evidence/vps-pilot-linux-smoke.json),
[actual deployment/operations](booking_bridge/deploy/VPS_PILOT.md),
[plain-language decisions](DECISION_CHECKLIST.md).

Next dependencies: controlled test contact; reconcile the source callback attempt
and obtain real signing secrets; then run scoped callback/booking/import trials.
Public hosting is now available and must not be listed as missing. No renewed
permission for already-authorized test preparation is needed.

## Earlier test-record checkpoint (historical hosting/Linux status below)


Updated 23 October 2026. Current decisions: [DECISION_CHECKLIST.md](DECISION_CHECKLIST.md).

## Current direction and runtime

The owner has approved integration testing on the currently unused SimplyBook
account. Complete provider isolation is no longer a pilot blocker. Use the
supported SrediMe webhooks/ICS now and measure behavior; consistently under 60
seconds is a pilot optimization target, not an entry requirement. Provider support
commitments and guaranteed import-completion APIs are not prerequisites.

Production remains disabled. Default runtime remains simulation, with live
background reads disabled. A separate ignored seven-day pilot draft is prepared;
it is also simulation and has no client mappings. Credentials, signatures,
deduplication, unknown-write recovery, explicit test scopes and customer privacy
remain protected. No hosting was purchased and no public service activated.

## Completed existing work (not repeated)

Service import: 490 imported / 494 original total. All 467 eligible imports were
category-sorted; 23 are reserved for manual review. Exclusive provider assignment
work for 481 categorized services is complete. See [import](service_importer/IMPORT_STATUS.md),
[categories](category_sorter/BULK_CATEGORY_RESULTS.md) and
[assignments](provider_assignment/reports/verified-exclusive-final.md).
Both account identities and Buker authentication were verified previously; the
existing authenticated Buker session worked again for this checkpoint.

## What changed and actually worked

- Updated runtime/preflight pilot approval from complete provider isolation to
  `pilot_scope_reviewed`, protecting source scope and controlled contacts.
  Production approval/trial checks remain separate. The pilot draft explicitly
  sets `require_subminute_availability=false`; production was not activated.
- Added [controlled provisioning](booking_bridge/controlled_pilot.py) and routed
  the main provisioning CLI to it. It creates one hidden provider and one hidden
  service, writes durable intent before each create, verifies actual assignments,
  rejects unrelated catalog changes and never automatically retries ambiguous
  creates. The prior strict helper remains for historical tests.
- Reconciled the old provider ID 8 rollback against live account inventory, then
  preserved that attempt in the private journal history before new setup.
- Created SimplyBook **provider 9**, `TEST integracija A`, and **service 496**,
  `TEST integracija 30 min`, duration 30, zero price, hidden, assigned only to 9.
  Provider 9 also inherited the 12 existing services listed in the change log.
  Their new links to 9 were recorded; settings and assignments between existing
  records stayed intact. No existing catalog PUT was sent. Repeating setup reused
  the same IDs without further creates.
- Created SrediMe **employee 11772**, `TEST integracija A`, and **service 233160**,
  `TEST integracija 30 min`, duration 30, zero price, inactive, external ID 496.
  Employee external ID is 9; it is nonbookable, has all working days off and no
  access to other calendars/client contacts. Its own service list verifies 233160.
  The service form omits nonbookable employees from its selector; its displayed
  empty selection is not treated as proof of no relationship.
- Buker initially retained default booking/day toggles on employee creation;
  readback caught that and the test employee alone was corrected through its UI.
  Creating the inactive service required temporarily making this all-days-off
  test employee selectable, then restoring nonbookable. Exact changes are in the
  private journals. All 12 pre-existing employees' settings/service assignments
  were checked again after setup and matched the baseline.
- Ran a live schedule trial only on SimplyBook provider 9 for 26 October: 22 slots
  became zero on day-off, then all 22 returned after restoring 09:00-20:00.
  A dated override remains on that test provider; it is in the cleanup plan.
- Five live SimplyBook GETs produced a complete seven-day private local ICS with
  15 occupancy events. The local feed route returned 200. One quota-counted GET
  of the new SrediMe export parsed successfully and contained zero events.
- Prepared a dedicated private pilot config/secret file and exact-ID cleanup
  plan. Real signing-secret fields remain empty until provider configuration;
  no substitute secrets or customer contacts were invented.

No clients, bookings, webhook subscriptions or import URLs were created. Existing
real SrediMe employee availability was not changed. Technical test mapping avoids
all unresolved real-person/service business matches.

## Measured stages and limits

| Observation | Result | What it establishes |
|---|---:|---|
| SimplyBook close request -> first slot API readback | 5.215 s | 22 -> 0 slots for test provider/service; includes MCP roundtrips |
| SimplyBook restore request -> first slot API readback | 5.097 s | 0 -> 22 slots; includes MCP roundtrips |
| Live SimplyBook reads -> local feed ready | 4.000 s | Current schedule snapshots can render a local feed |
| Local TestClient feed request | 0.078 s / 200 | Local application route works; caller was not SrediMe |
| New SrediMe export GET | 0.375 s / parseable, empty | Supported export endpoint works for the test employee |
| Simulation HTTP webhook acknowledgement | 31 ms / 202 | Local durable acceptance only; no provider event |
| Actual source commit, real webhook receipt, local processing of real booking | unknown | No controlled booking/contact trial yet |
| Real refresh acceptance / SrediMe HTTP fetch / completed import | unknown | No public host or test import URL configured |
| Source change -> effective remote/customer-visible availability | unknown | No cross-system end-to-end latency claim |

The next useful optimization must follow an actual connected trial. These local
and single-system measurements do not identify SrediMe import delay and do not
justify another polling/optimization pass yet.

## Validation and evidence

- [Current validation](booking_bridge/evidence/controlled-pilot-validation.json):
  **385 Windows tests passed**, 40 focused tests passed (overlapping suites),
  simulation HTTP smoke passed, live write counts, source hashes and limitations.
- [Full Windows XML](booking_bridge/evidence/controlled-pilot-windows-tests.xml),
  [focused XML](booking_bridge/evidence/controlled-pilot-focused-tests.xml),
  [HTTP smoke](booking_bridge/evidence/controlled-pilot-windows-smoke.json).
- [SimplyBook provisioning / inherited assignments](booking_bridge/evidence/controlled-pilot-provisioning.json),
  [source employee setup](booking_bridge/evidence/controlled-pilot-source-setup.json),
  [source service and toggle journal](booking_bridge/evidence/controlled-pilot-source-service.json),
  [source baseline preservation](booking_bridge/evidence/controlled-pilot-source-preservation.json).
- [Live schedule measurements](booking_bridge/evidence/controlled-pilot-schedule-trial.json),
  [live reads/local feed](booking_bridge/evidence/controlled-pilot-live-read-check.json),
  [exact cleanup plan](booking_bridge/evidence/controlled-pilot-cleanup-plan.json).
- [Pilot preflight](booking_bridge/evidence/controlled-pilot-pilot-preflight.json) /
  [production preflight](booking_bridge/evidence/controlled-pilot-production-preflight.json)
  remain blocked; test-record provisioning is separate from activating the worker.
- The previous final Linux image passed 241 tests. Current changed code was **not**
  tested on Linux: Docker Desktop reported unable to start after launch attempt.
  The old image result is historical, not verification of this revision.

Private journal/config paths: `booking_bridge/state/pilot-provisioning.json`,
`pilot-source-provisioning.json`, `pilot-source-service-provisioning.json`,
`pilot-schedule-trial.json`, `controlled-pilot-config.json`, dedicated state
`state/controlled-pilot/`, and `booking_bridge/secrets/pilot.env`. No secrets,
private URLs or customer records are included in public reports.

## Next executable steps and exact dependencies

1. **Public HTTPS:** no hostname, host access or DNS route is configured. A provider
   cannot call this local workspace. Use the [deployment runbook](booking_bridge/deploy/PILOT_RUNBOOK.md)
   once an existing host is available; no purchase or unapproved tunnel is assumed.
2. **Real callback verification:** configure the already-authorized pilot callbacks,
   obtain actual signing secrets, send Buker Test, validate signatures/durable
   receipt and real event schema. No renewed test-preparation authorization needed.
3. **Controlled contact:** the private contact file is empty. Needed before booking
   or client operations that could send real notifications; never reuse another
   customer's contact or fabricate one.
4. **Pilot booking trial:** finish timing/resource checks, use explicit technical
   test IDs, enable only the required internal test schedule/service, then exercise
   create/update/cancel. Keep real SrediMe staff untouched. Pending=hold and
   no-show=retain are pilot defaults; unknown statuses go to review.
5. **Availability trial:** configure only test employee 11772's import URL, then
   measure source request/commit where observable, event receipt, local apply,
   feed ready, refresh acceptance, fetch and actual remote effect separately.
   Unknown stages remain unknown. Add reassignment with a second test provider
   only after the first small flow works.
6. **Later production:** real mappings, notifications/status decisions, outage
   behavior, monitoring/backup destinations and separate rollout approval follow
   actual pilot results. Old support questions are optional follow-up, not gates.

No batch of preferences is required now. The current short decision register is
[DECISION_CHECKLIST.md](DECISION_CHECKLIST.md); unresolved identities and production
choices remain deferred instead of blocking technical test preparation.

````

## Original: booking_bridge/handoff/STATE_AND_EVIDENCE.md

````markdown
# Stanje projekta i dokazi

## Posle odobrenja korisnika — 27.10.2026, 10:18 UTC

„Uradi to” je odobrio oba konkretna prenosa. [Zaista izvršeni prenosi](../evidence/integration-20261027-approved-transfers.json)
potvrđuju 15 blokova na VPS-u sa izvornim timestamp-ovima, pravi HMAC ključ u
runtime-u, liveness/readiness 200, 0 incidenata i odbijanje pogrešnog potpisa 401
u trenutku provere. Ključ je 0600; admin kredencijali nisu preneti.

[Stvarni native uvoz](../evidence/integration-20261027-source-import.json) je
potvrdio **12/12 budućih intervala**, bez dodatnih/dupliranih blokova; tri od
ukupno 15 već su prošla. Jedan kvótovani refresh; fetch38.063s, prvo puno buduće
native stanje67.911s posle acceptance-a. Nema actual commit/E2E/<60s dokaza.

[Sledeći probni tok](../evidence/integration-20261027-next-trial-prepared.json)
je pripremljen uz 17 privatnih offline testova i 0 read-only POST-ova. Auto-review
je posebno odbio tri SB pretplate i customer-only SrediMe unos pre pokretanja.
Oba ostaju neizvršena; source customer mapiranje i rezervacioni ciklus nepotvrđeni.
Callback6 ostaje off, employee11772 nije bookable/svi dani off, booking count0.
Minimalni publisher jeste odobren; raniji status blokade ispod je istorijski.

## Najnovije — izgradnja i integracija 27.10.2026, 09:48 UTC

Korisnik je prihvatio postojeći jezik za sada, ne želi slanje podršci i traži
nastavak integracije. Novi [rollout dokaz](../evidence/integration-20261027-rollout.json)
potvrđuje stvarno postavljenu sliku `andjelija-bridge:pilot-20261027-integration1`
i `pilot_receiver` umesto simulation obrade događaja. Server je i dalje
`simulation`/reads off, liveness 200, readiness 503 zbog zastarelog feed-a.
Nema novih veza ni živih rezervacija. **382/382 Windows i 382/382 Linux testa prolaze.**

Lokalni read-only [snimak od 09:46 UTC](../evidence/integration-20261027-local-snapshot.json)
ima 15 blokova. Prenos nije izvršen: automatska kontrola posebno je odbila i minimalnu
zauzetost i SimplyBook HMAC ključ na postojeći VPS. Jedno pitanje za izričito
odobrenje oba prenosa je postavljeno, bez odgovora za sada. Ne menjati transport
da bi se zaobišlo odbijanje. HMAC je samo lokalno; SimplyBook pretplata nema.

[Ugovor usluge](../evidence/pilot-service-contract-20261027.json) je živim čitanjima
potvrdio tajming/resurse test para 233160 → 496. Lokalni capture profil je ažuriran;
`clients` ostaje prazan. Nativni source calendar/json vraća blokove 11772 i kada
nije bookable; to priprema dokaz uvoza, ali svež uvoz još nije dokazan.
Dalje u [integracionom uputstvu](../deploy/INTEGRATION_RUNBOOK.md).

## Dopuna posle nastavka 27.10.2026.

Najnoviji [pregled jezika](../localization/LANGUAGE_AUDIT.md) i
[dokaz promena](../evidence/client-language-audit-20261027.json) potvrđuju 695
klijentskih polja, 18 zajedničkih oznaka/polja podnožja i 35 polja šablona na srpskom.
Potpuni zahtev 100% još nije dokazan. Rezervacija **2 je otkazana** i očitana
kao `canceled`; [dokaz](../evidence/pilot-booking-cancelled-20261027.json).
Klijent **1** ostaje. Pre otkazivanja oba kontakta ponovo su privatno poklopljena
sa odobrenim kontaktom i pročitani su srpski šabloni otkazivanja; prijem poruke
nije potvrđen. Ne ponavljati otkazivanje kao retry.

[Zapis imejla](../evidence/pilot-cancellation-message-log-20261027.json) je
povezan sa rezervacijom 2 i odobrenim kontaktom: naslov/telo srpski, podnožje
englesko. Podnožje je potom prevedeno i očitano nazad; novi render posle izmene
i inbox dostava nisu potvrđeni. Vreme prikazano u logu nema navedenu zonu.

[Operativno čitanje](../evidence/pilot-operations-check-20261027.json) potvrđuje
zatvoren izvorni test scope, deaktiviran callback 6, `simulation`/reads off,
aktivne tajmere i obnovljen TLS do 02.11.2026. Readiness i feed vraćali su 503
zbog zastarelog snimka; nova verzija nije preneta. [Trajni prijem događaja](../evidence/live-source-webhook-receipt-20261027.json)
ponovo je dokumentovan: `booking.updated`, `test:false`, ignorisan van allowlist-a.

## Prethodna primopredaja i istorijski dokazi

Primopredaja 27.10.2026; operativno stanje ispod je poslednje poznato 23.10.2026,
osim gde je navedena lokalna provera datoteka pri primopredaji. Udaljeno stanje
mora ponovo da se pročita pre novih izmena.

## Završeno — ne ponavljati

- Uvezeno 490 usluga; pre pilot dodatka nalog je imao ukupno 494 usluge.
- Sortirano 467 podobnih usluga; 23 su ostavljene za ručni pregled.
- Završene isključive dodele zaposlenima za 481 kategorizovanu uslugu.
- Potvrđeni nalozi i prijava: SimplyBook `studioandjelija`; SrediMe Studio
  Anđelija SG, vendor **1404**, slug `studio-andjelija-sg`; Buker Olja, uloga 90.
- Implementirani konektor, trajni red, deduplikacija, provera potpisa, oporavak,
  periodično usklađivanje, ICS izvoz, rasporedi i evidencija faza kašnjenja.
- Prvobitni neuspešni pokušaj potpune izolacije sa SimplyBook zaposlenim **8**
  je povučen; taj zaposleni je obrisan, početno stanje provereno i istorija sačuvana.
  `services: []` nije sprečio automatske dodele; PUT ih nije uklonio.

Dokazi: [import](../../service_importer/IMPORT_STATUS.md),
[kategorije](../../category_sorter/BULK_CATEGORY_RESULTS.md),
[dodele](../../provider_assignment/reports/verified-exclusive-final.md).

## Tačni test zapisi i promene

| Sistem | Zapis | Poslednje potvrđeno stanje |
|---|---|---|
| SimplyBook | Zaposleni **9**, `TEST integracija A` | Skriven, kapacitet 1 |
| SimplyBook | Usluga **496**, `TEST integracija 30 min` | Skrivena, 30 min, cena 0, buffer posle 0; dodeljena samo 9 |
| SimplyBook | Klijent **1** | Postojeći korisnikov zapis; oba dostavljena kontakta poklopljena; nije blokiran; nije kreiran niti preimenovan |
| SimplyBook | Rezervacija **2** | Kreirana za 26.10. u 09:00–09:30, pomerena na 10:00–10:30; otkazana 27.10, readback `canceled` |
| SimplyBook | Poseban raspored zaposlenog **9** za 26.10. | Posle testa neradnog dana vraćeno 09:00–20:00; datumski override je ostao |
| SrediMe | Zaposleni **11772**, `TEST integracija A` | external_id `9`; nije dostupan za zakazivanje, svi dani neradni; bez pristupa tuđim kalendarima/kontaktima |
| SrediMe | Usluga **233160**, `TEST integracija 30 min` | external_id `496`; 30 min, cena 0, neaktivna; jedan zaposleni, bez izabranih sredstava i dodatnih trajanja |
| SrediMe | Callback **6**, `TEST bridge VPS 20261023` | Postoji, potpis preuzet; nakon kreiranja deaktiviran i provereno neaktivan |
| SrediMe | Uvoz kalendara za **11772** | Privatni HTTPS ICS URL upisan i pročitan nazad; ranije je bio prazan |

Zaposleni 9 automatski je dobio i postojeće usluge
**2, 3, 5, 13, 29, 47, 312, 444, 452, 462, 472, 474**.
To su evidentirane dodatne veze; nisu menjane veze među originalnim zapisima.
Ne menjati postojeće dodele da bi se test „izolovao”.

Veza izvorne usluge 233160 sa zaposlenim 11772 potvrđena je na zaposlenikovom
izboru usluga. Editor usluge izostavlja zaposlene koji nisu dostupni za zakazivanje;
prazan izbor u tom editoru nije dokaz da veza ne postoji. Za izbor pri kreiranju
test zaposleni je privremeno učinjen dostupnim, uz sve dane neradne, pa vraćen.
Svih 12 prethodnih izvornih zaposlenih naknadno je upoređeno sa početnim stanjem.

## Šta je stvarno prošlo u živim sistemima

1. Host dostupan preko pouzdanog HTTPS-a; provere javnih granica endpoint-a prošle.
2. Kontrolisana promena rasporeda zaposlenog 9: 22 termina → 0 → 22 nakon vraćanja.
3. SimplyBook rezervacija 2: kreiranje je zauzelo 09:00; pomeranje je oslobodilo
   09:00 i zauzelo 10:00. To su API očitavanja raspoloživosti u jednom sistemu.
4. Lokalni autorizovani GET pozivi napravili su pravi snimak zauzetosti i ICS.
   Preneti su minimalni podaci o zauzetosti, bez administratorskih akreditiva.
5. Buker Test poslat na callback 6 dobio je HTTP 202, u jednom pokušaju.
   Obrada događaja završila je kao `ignored / employee_outside_allowlist`.
   Nije potvrđena obrada kao `test:true`; ne pretpostavljati da se stvarni paket
   ponaša identično opisu iz uputstva. Nije napravljen SimplyBook upis tim događajem.
6. Upisan je izvorni test import URL; podržani POST za osvežavanje prihvaćen je
   sa `success:true, refresh_scheduled:true`.
7. Host je zabeležio HTTP preuzimanje odgovarajuće verzije feed-a. SrediMe je
   verovatan pozivalac jer mu je URL upravo predat, ali identitet pozivaoca nije
   kriptografski potvrđen. Nije potvrđen završetak udaljenog uvoza.

Nije napravljen SrediMe test klijent/rezervacija. Nije potvrđena SimplyBook
webhook pretplata/potpis. Nije pokrenuta automatska živa sinhronizacija.
Stvarni prijem imejla/SMS-a i jezik dostavljenih poruka nisu provereni.

## Merenja — ne sabirati ih u izmišljeno end-to-end vreme

| Faza | Rezultat | Ograničenje |
|---|---:|---|
| SimplyBook zahtev za neradni dan → prvo očitavanje | 5,215 s | MCP i očitavanje uključeni |
| Vraćanje rasporeda → prvo očitavanje | 5,097 s | Jedan sistem |
| Kreiranje rezervacije 2 → prvo očitavanje | 25,521 s | Uključuje pauzu između poziva i zapisivanje dnevnika |
| Pomeranje rezervacije 2 → prvo očitavanje | 5,188 s | Nije vreme prenosa u SrediMe |
| Čitanje živog stanja → lokalni feed, posle kreiranja | 4,761 s | 16 događaja zauzetosti, 15 iz rasporeda + rezervacija |
| Čitanje živog stanja → lokalni feed, posle pomeranja | 4,003 s | Lokalni dokaz postoji; prenos ove verzije na VPS nije potvrđen |
| Zahtev za osvežavanje → HTTP odgovor | 0,422 s | Samo prihvatanje zahteva |
| Verzija feed-a spremna na hostu → zabeležen fetch | oko 90,03 s | Uključuje ručnu pripremu pre zahteva za refresh |
| Prihvatanje refresh zahteva → zabeležen fetch | oko 8,7 s | Fetch nije dokaz uvoza ili promene slobodnih termina |
| Izvorna promena → efektivna raspoloživost drugog sistema | **nepoznato** | Nije dokazana ciljna brzina ni završetak uvoza |

Poslednje dve približne vrednosti prenete su iz prethodne sesije: host
`feed-ready` 1792764298.374925; `feed-last-served` 1792764388.4070325.
Ponovo pročitati bezbedne metapodatke i sačuvati dokaz pre korišćenja u zaključku.
Izvorni test zaposleni je zatvoren sve vreme, pa njegove javne slobodne termine
nije moguće koristiti kao dokaz promene raspoloživosti zbog ove rezervacije.

## Testovi i javni dokazi

- [Windows XML](../evidence/controlled-pilot-windows-tests.xml): **385** testova,
  bez grešaka/padova; broj ponovo pročitan iz XML-a pri primopredaji.
- [Linux XML](../evidence/vps-pilot-linux-tests.xml): **249** testova, bez grešaka/
  padova, u poslednjoj postavljenoj slici; ponovo pročitan XML. Linux testovi su
  bez mreže, sa read-only root i non-root izvršavanjem.
- [Windows smoke](../evidence/controlled-pilot-windows-smoke.json) i
  [Linux smoke](../evidence/vps-pilot-linux-smoke.json) prošli su u simulaciji.
  Linux HTTP prijem oko 22 ms nije živo kašnjenje provajdera.
- Novi `pilot_snapshot.py`: prethodna sesija prijavila je **4** fokusirana
  prolazna Windows testa. Ceo skup nakon tog dodatka nije ponovljen; ne tvrditi
  „389 full suite” niti da je taj dodatak testiran u postavljenoj Linux slici.
- Stariji brojevi 373 Windows / 241 Linux su istorija.
- [Validacija VPS-a](../evidence/vps-pilot-deployment-validation.json) je raniji
  snimak: njene tvrdnje o nedostajućem callback-u/kontaktu su sada zastarele.
- [Kreiranje → feed](../evidence/pilot-booking-created-feed.json),
  [pomeranje → feed](../evidence/pilot-booking-moved-feed.json),
  [podešavanje uvoza](../evidence/pilot-import-setup.json) provereni su lokalno.
- [Test provisioning](../evidence/controlled-pilot-provisioning.json),
  [izvorni zaposleni](../evidence/controlled-pilot-source-setup.json),
  [izvorna usluga](../evidence/controlled-pilot-source-service.json),
  [očuvanje izvora](../evidence/controlled-pilot-source-preservation.json).

Prethodni pokušaj čuvanja `live-source-webhook-receipt.json` završio je lokalnim
`NameError: Path`; taj javni dokaz ne postoji. Živi prijem je bio očitan, ali ga
treba iznova dokumentovati iz baze bez kopiranja korisničkog payload-a.

## Nerešeno poslovno povezivanje

Realni kandidati nisu odobreni. Sara SimplyBook **3** i Sanja SrediMe **6873**
ne smeju se poistovetiti. Devet od 18 jedinstvenih kandidata usluga ima različito
trajanje; tri izvorne usluge su neaktivne. Detaljna tabela sa ID-evima je u
[PILOT_MAPPING_REVIEW.md](../PILOT_MAPPING_REVIEW.md).

Najmanji kandidat za kasniji poslovni pregled je Tamara **10142 → 5**, sa
Probiotskim tretmanom lica **128316 → 36**, 30 min; dodatni kandidat
Mikrodermoabrazija **128275 → 31**, 15 min. To nisu odobrena povezivanja i nisu
dozvola za testiranje stvarnog osoblja. Trenutni tehnički testovi koriste samo
11772 → 9 i 233160 → 496.

````

## Original: booking_bridge/handoff/OPERATIONS_AND_ACCESS.md

````markdown
# Operacije, pristupi i struktura koda

## Odobreni prenosi izvršeni — 27.10.2026, 10:18 UTC

Korisnik je odobrio minimalnu test zauzetost i HMAC na isti VPS. Oba su preneta;
`pilot.env` ima mod0600 i pravi SB ključ, kontejneri su ponovo kreirani da vide
novi secret inode. Runtime/snapshot timestamp readback i javni401 provereni su;
[dokaz](../evidence/integration-20261027-approved-transfers.json). Nisu preneti
admin pristupi. Readiness200 je vremenski ograničen svežinom lokalnog publisher-a.

Podržani refresh i native blokade dali su [dokaz12/12 budućih intervala](../evidence/integration-20261027-source-import.json).
Nove SB pretplate i source customer-only unos su zasebno odbijeni pre procesa;
ne koristiti drugi transport. Native operator skripta je pripremljena uz17offline
testova, create gate ostaje false bez stvarnog customer binding-a. Privatni plan
je `state/integration-20261027/NATIVE_TRIAL_PLAN_PRIVATE.md`.
Ne koristiti draft `collect_source_pilot_event.py`: posle pregleda je programski
blokiran, nikad pokrenut; hardening/ACK plan je u `COLLECTOR_REVIEW_PRIVATE.md`
u istom privatnom direktorijumu. Mora primati jedan događaj, bez kontakata, uz
tačan client binding i hash; ne bulk-ingestovati create/move/cancel unapred.

## Nova postavljena verzija — 27.10.2026, 09:48 UTC

VPS sada koristi `andjelija-bridge:pilot-20261027-integration1`, image ID
`sha256:8a8440d7e6ab72d6a388deb5bf2594e5ae174bfd166075d939d81c8d08987cc0`.
Worker komanda je `python -m booking_bridge.pilot_receiver`; ne troši inbox,
ne pravi simulirane target ID-eve i ne poziva naloge. Oba procesa ostaju non-root,
read-only/caps ALL dropped, sa postojećim trajnim volumenima. Backup pre rollout-a
ima uspešan SQLite integrity_check. [Dokaz](../evidence/integration-20261027-rollout.json).

Novi CLI-jevi i tačne granice su u [integracionom uputstvu](../deploy/INTEGRATION_RUNBOOK.md).
Finite lokalni publisher još nije uspešno prenet: automatska kontrola blokirala
je occupancy payload i zasebno SimplyBook HMAC ključ, čeka se izričito odobrenje.
Administratorski kredencijali ostaju lokalno. Server SimplyBook HMAC i dalje prazan;
potpis se ne sme isključiti da bi callback radio. Readiness 503 zbog starog snimka
je očekivan do odobrenog svežeg prenosa.

Privatna priprema ovog nastavka: `state/integration-20261027/` (uključuje stvarni
SB API config/ključ, ne izvoziti), `state/native_source_trial.py` i audit skripte
u `state/`. Release builder izričito isključuje `state/`, `secrets/`, `.env*`,
`config.local.json`, `*.local.*`; uključuje javna CSV mapiranja potrebna aplikaciji.

## Dopuna 27.10.2026.

Živa podešavanja jezika, privatni backup/readback i dnevnici su u
`state/language-audit-20261027/`; to nije sadržaj za release. Javni pregled je
[LANGUAGE_AUDIT.md](../localization/LANGUAGE_AUDIT.md). SBPay je otvoren preko
postojećeg SimplyBook UI dugmeta za račune; direktan GET bez UI CSRF konteksta
odbijen je. Njegova sesija ostaje privatna u istom audit direktorijumu.
Četiri polja računa/knjižnog odobrenja sačuvana su nativnim submit-om i očitana
nazad, uz očuvanje svih ostalih polja formulara.

Stvarni TLS pri ovoj proveri ističe 02.11.2026. u 14:34:01 UTC. Prava imena
kontrolnih tajmera su `booking-bridge-pilot-check.timer` i
`booking-bridge-pilot-backup.timer`; oba su aktivna. Kontrola prijavljuje
zastareo snapshot / 503, a poslednja rezervna kopija je uspela. Ovo ne uključuje
pozadinska čitanja ili produkciju. Administratorski akreditivi nisu preneti.

Otkazivanje postojeće rezervacije 2 ima poseban privatni dnevnik
`state/pilot-booking-cancellation-20261027.json`, status `confirmed`;
SimplyBook vraća `canceled`, dok njegov izveštaj koristi filter `cancelled`.
Ne ponavljati operaciju zbog razlike u pisanju statusa. Dnevnik prvog testa je
dopunjen; klijent 1 nije obrisan. Dostava poruke ostaje nepoznata.

## Lokalno okruženje i privatne datoteke

Windows, PowerShell; koren projekta:
`C:\Users\aaaaz\OneDrive\Documents\andjelijasg\simplybook-API`.
Python: `.venv\Scripts\python.exe`; Playwright sa Chrome kanalom je ranije radio.
Postman CLI je instaliran. Lokalni Docker Desktop prethodno nije uspeo da se
pokrene; udaljeni Docker je radio. Git nije bio na PATH-u; nije napravljen commit.

Sledeće su **lokalne privatne putanje**, ne sadržaj za javni izveštaj ili release:

| Putanja, relativno na `booking_bridge/` | Namena |
|---|---|
| `secrets/pilot-contact.json` | Korisnikov odobren test kontakt, telefon normalizovan na +381; ime u datoteci je test oznaka |
| `state/pilot-contact-link.json` | Potvrda da oba kontakta pripadaju postojećem SimplyBook klijentu 1 |
| `secrets/pilot.env` | Privatni feed token, administratorski ključ bridge-a, izvorne tajne; ne ispisivati |
| `secrets/vps_pilot_ed25519` | Namenski SSH privatni ključ |
| `secrets/vps_known_hosts` | Pinned identitet SSH hosta; ne isključivati proveru |
| `state/sredime-session.json` | Autentifikovani browser storage state; možda istekao |
| `state/source-webhook-signing-private.json` | Stvarni SrediMe secret za endpoint 6 |
| `state/vps-source-webhook-provisioning.json` | Istorija pokušaja kreiranja, potvrda ID-a 6 i deaktivacije |
| `state/source-webhook-test.json` | Zapis namere i zahteva za Buker Test |
| `state/pilot-booking-trial.json` | Tačan dnevnik kreiranja i pomeranja rezervacije 2 |
| `state/pilot-provisioning.json` | SimplyBook test provisioning, uključujući prethodni pokušaj/oporavak |
| `state/pilot-source-provisioning.json`, `state/pilot-source-service-provisioning.json` | Izvorni zapisi i UI ispravke |
| `state/pilot-schedule-trial.json` | Probni datumski raspored |
| `state/pilot-source-integration-private.json` | Privatni SrediMe export/refresh URL |
| `state/pilot-import-setup.json` | Dnevnik upisivanja import URL-a |
| `state/controlled-pilot-config.json` | Namenska pilot konfiguracija; razlikuje se od host konfiguracije |
| `state/controlled-pilot/bridge.sqlite` | Lokalna pilot baza, kvote i snimci |
| `state/pilot-availability-packet.json` | Minimalni paket zauzetosti; proveriti verziju pre prenosa |
| `state/source-review/`, `state/sredime-service-details-private.json` | Privatni izvori pregleda povezivanja |

SimplyBook REST akreditivi ostaju lokalno u postojećim
`service_importer/.env` / `provider_assignment/.env`. Root VPS lozinka iz razgovora
nije sačuvana u projektne datoteke; ne praviti novu kopiju. Browser HTML odgovori,
SQLite, storage state i privatni URL-ovi takođe mogu sadržati lične podatke/tajne.
Datoteke `state/`, `secrets/`, `.env`, lokalne konfiguracije i lokalni CSV su
ignorisan sadržaj. Pri prenosu projekta sledećem modelu ovaj Markdown ne zamenjuje
te privatne datoteke: ako ih nema, prijaviti tačno šta nedostaje, ne izmišljati.

## Stvarno postavljen VPS — poslednji potvrđeni raspored

- IP **169.58.118.33**; DNS **vmi3688215.contaboserver.net**; IPv6
  **2a02:c207:2368:8215::1**. Host je korisnikov postojeći Contabo VPS.
- Ubuntu 24.04.5 LTS, Docker 29.9.2, Compose 5.6.1, nginx, Certbot 5.8.0 u
  `/opt/booking-bridge-certbot`. Nije urađen reboot, OS upgrade ili promena
  politike SSH prijavljivanja. Postojao je zahtev sistema za restart.
- Direktorijum `/opt/booking-bridge-pilot`, root-private 0700;
  release `releases/20261023-pilot1`.
- Slika `andjelija-bridge:pilot-20261023`, stvarni image ID
  `sha256:c03d960d9a2b0c86640d6d74ee668f5c7f9380644662a7e7c242eafc6dcba566`.
  Ne mešati image ID i Compose config digest.
- API i worker su `simulation`, `reads_enabled=false`, sa trajnim SQLite volume-om.
  UID 10001, read-only root, uklonjene capabilities, no-new-privileges.
  API vezan samo na `127.0.0.1:8000`.
- Host `pilot.env` mode 0600, vlasnik 10001: stvarni SrediMe potpis je instaliran,
  SimplyBook potpis je prazan, **nema SimplyBook administratorskih akreditiva**.
- Host konfiguracija je starija od lokalne: nema novog test kontakta/klijenta ni
  potpuno ažurnih lokalnih approval vrednosti. Ne kopirati je naslepo i ne
  smatrati lokalnu `approvals` vrednost dokazom proverenog udaljenog ponašanja.

Bezbedan obrazac čitanja, iz korena projekta:

```powershell
ssh -i booking_bridge/secrets/vps_pilot_ed25519 -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=booking_bridge/secrets/vps_known_hosts root@169.58.118.33 "docker ps --format '{{.Names}} {{.Status}}'"
```

Ne ispisivati `docker inspect` env, `docker compose config` sa razrešenim tajnama,
ceo `pilot.env`, payload-e ili privatne feed URL-ove. Mrežne privilegije i pravila
trenutnog okruženja važe i kada je poslovna radnja već odobrena.

## HTTPS, zdravlje, kopije i rollback

- Provereni javni endpoint-i: `https://169.58.118.33/health/live` i
  `https://vmi3688215.contaboserver.net/health/live`, 200 sa standardnom TLS proverom.
- nginx stvarni fajl `/etc/nginx/sites-available/booking-bridge-pilot`; oba
  server bloka imaju IP+DNS i IPv4/IPv6 listen za 80/443. Template u repozitorijumu
  nije potpun odraz naknadnih DNS/IPv6 izmena na serveru.
- Javno su izloženi samo predviđeni webhook-i, `/ics/*`, `/health/live`.
  Admin/readiness i loš feed token vraćali su 404; webhook bez potpisa 401.
  Access log isključen, error log na critical.
- Zajednički Let's Encrypt IP+DNS sertifikat u
  `/etc/letsencrypt/live/booking-bridge-ip/`. Poslednji zapis ističe **30.10.2026**;
  proveriti stvarni novi datum/obnovu, ne zaključiti da je danas već istekao.
- `booking-bridge-certbot.timer` dva puta dnevno, nginx reload hook.
  Dry-run za prvobitni IP sertifikat prošao; nakon proširenja IP+DNS nije ponovljen.
  Za ručni dry-run koristiti `--no-random-sleep-on-renew`, inače može dugo čekati.
- `/opt/booking-bridge-pilot/pilot_host_maintenance.py`: `check` jednom u minutu,
  `backup` jednom na sat; početna provera integriteta kopije prošla.
  Kopije su privatne, **na istom serveru i nešifrovane**. To nije oporavak nakon
  gubitka VPS-a. Nisu odabrani spoljašnji alarmni kontakt ni mesto rezervne kopije.
- Za pauzu: u deploy direktorijumu `docker compose stop worker`; po potrebi
  `docker compose stop`. Nikada `down -v` ili brisanje baze kao rollback.
  Povratak starije baze zahteva usklađivanje kasnijih udaljenih upisa i neizvesnih
  namera pre ponovnog kreiranja rezervacija. Prazan ICS nije bezbedna zamena za rollback.

## Odbijeni prenos akreditiva i nedovršeni snapshot deploy

Automatska kontrola je odbila kopiranje SimplyBook administratorskih akreditiva
na VPS, uz obrazloženje da odobrenje hostinga ne obuhvata izričito izvoz tih
osetljivih akreditiva na taj server. Cela odbijena izvršna komanda nije izvršena.
Nije nastao `snapshot.env` i nije postavljena snapshot usluga.

**Lokalni** `deploy/compose.pilot.yaml` ipak ima nov `snapshot` profil
`read-snapshot` koji referencira `./snapshot.env` i bind `./pilot_snapshot.py`.
To je pripremljen, nedovršen predlog — **nije host Compose**. Proveriti ponašanje
Compose validacije sa nedostajućim secret fajlom pre bilo kakvog korišćenja.
Bez izričitog odobrenja transfera ne slati iste tajne drugim putem. Ako transfer
ostane neophodan, jednostavno objasniti korisniku širok pristup koji akreditivi
daju, navesti automatsko odbijanje i tražiti samo tu konkretnu odluku.

Bezbedna alternativa koja je radila: lokalni read-only API snimak, pa ručni
prenos minimalnog availability paketa. To **nije automatizovana sinhronizacija**.

## Kod i praktične zamke

- `api.py`: verifikovan prijem događaja i privatni ICS/ops; `worker.py`: obrada i
  upisi; `store.py`: SQLite namere, red, istorija, oporavak; `scheduler.py`:
  čitanje kalendara, osvežavanje i periodično usklađivanje; `calendar.py`: ICS;
  `latency.py`: opažanja faza; `model.py` / `preflight.py`: konfiguracija i provere.
- `controlled_pilot.py`: nov kontrolisani provisioning; istorijski stroži
  provisioning nije razlog za povratak napuštenog uslova potpune izolacije.
- Novi `pilot_snapshot.py` odbija rad osim `simulation`, `reads_enabled=false`,
  approvals `pilot_read_snapshots=true` i `pilot_scope_reviewed=true`, tačno jednog
  zaposlenog i samo pilot usluga. Koristi `ReadOnlyGateway`, ne obrađuje inbox i
  ne šalje source refresh. `NoWorker.once` namerno baca grešku.
- `Settings.load(read_only=True)` može učitati lokalne CSV koji se sukobe sa JSON
  profilom. Prethodni uspešan lokalni snimak koristio je `dataclasses.replace`
  nad podrazumevano učitanim settings sa namenskim profilom, state i privatnim
  tokenima. Ne startovati CLI naslepo sa pogrešnom konfiguracijom.
- `provider_assignment/client.py`: postojeća autentifikacija, trajna kvota
  4500/dan, pacing 0,5 s; ne ponavljati automatski neizvesne POST/PUT upise.
- Windows `subprocess.run(input=script, text=True)` promenio je LF u CRLF i
  pokvario udaljeni Bash. Slati `input=script.encode()` i dekodirati izlaz.
  Ne ubacivati tajne u argumente procesa ili dinamičke shell komande.
- `Store.connect()` već počinje `BEGIN IMMEDIATE`: ne slati novi `BEGIN` u njemu.
- Minimalni paket ima samo `bookings`, `buffers`, `schedule:11772`; rezervacije
  filtrirati na zaposlenog 9/uslugu 496 i bez imena/kontakata; schedule samo
  vremenska polja/ID-evi, nikakav slobodni tekst beleški. U jednoj transakciji
  zameniti tri cache ključa, zatim `queue_if_feed_changed`, izračunati feed hash
  i proveriti očekivanu verziju. To je prethodni postupak, ne nalog da se danas
  prenese stari paket. Verzija posle pomeranja postoji lokalno; na hostu je poslednje
  potvrđena verzija posle kreiranja sa 09:00 zauzećem.
- SrediMe POST refresh ide na isti privatni export URL, uz trajno
  `store.rate('sredime-post:11772', 60)` pre pokušaja, uključujući neuspehe.
- SrediMe UI: bootstrap toggles menjati preko
  `jQuery(el).bootstrapToggle('off')`, zatim save i readback. Native uncheck nije
  pouzdano menjao stvarnu vrednost. Skriveni select zahteva `force=True`.
  Create je ignorisao pojedine početne false vrednosti; zato je callback 6
  nakratko nastao aktivan, odmah je deaktiviran i potvrđen.
- SrediMe odbija literal-IP callback URL; podržani DNS URL na 443 je uspeo.
  Svi A/AAAA moraju stići na isti ispravan HTTPS server. Prvo DNS izdavanje TLS-a
  palo je jer IPv6 nije bio podešen; dodavanje IPv6 listen je rešilo problem.
- SimplyBook MCP otkrivati preko dostupnih alata, ne pretpostaviti da su svi
  konektori dostupni novom modelu. Postoje `get_booking(s)`, `get_timeline`,
  `book`, `edit_booking`, `cancel_booking`, company/client/plugin čitanja;
  proveriti stvarna imena i šeme. Browser helper-i su u `category_sorter/`.
  Ne ponavljati završenu kategorizaciju radi uspostavljanja browser sesije.

Za lokalnu regresiju, kada promena koda to zahteva:

```powershell
.\.venv\Scripts\python.exe -m pytest booking_bridge/tests/test_pilot_snapshot.py -q
.\.venv\Scripts\python.exe -m pytest booking_bridge/tests -q
```

Ne prikazivati izmišljene nove rezultate: pri ovoj primopredaji provereni su
postojeći dokazi, a aplikacioni testovi nisu ponovo izvršavani.

````

## Original: booking_bridge/handoff/NEXT_STEPS.md

````markdown
# Redosled nastavka, srpski jezik i čišćenje

## Stvarno sledeće posle izvršenih prenosa — 27.10.2026, 10:18 UTC

Oba VPS prenosa su odobrena i izvršena. Native budući uvoz12/12 je potvrđen;
ne ponavljati ga kao nedokazan posao. Minimalni lokalni publisher može se ponoviti
unutar istog obuhvata; ne tražiti ponovo tu dozvolu ili pravi signing ključ.

1. Proveriti odgovor na precizno pitanje za tri SB booking pretplate i unos samo
   odobrenog probnog kontakta u SrediMe ako ga nema, uz jedan create/move/cancel
   test na probnim zapisima oba sistema. Auto-review je posebno odbio pretplate
   i customer-only unos pre procesa; nisu izvršeni niti zaobiđeni.
2. Posle odobrenja, `state/setup_sb_webhooks.py --execute` kreira samo tri tačne
   pretplate, uz nameru/readback i bez gašenja postojećih. Stvarni callback dokaz
   dobija se tek živom operacijom; ne slati potpisane fixtures kao provider dokaz.
3. Privatni `native_source_trial.py customer --execute --server-ready` je najmanji
   owncontact korak. Ponovo tri tačne pretrage, jedan POST ako nema zapisa,
   nezavisan exact-contact/native-ID readback. Ne tražiti ponovo korisnikov kontakt.
4. Pre booking create-a dovršiti stvarni customer binding i scoped native selector
   proveru; ne prebaciti gate samo da prođe. Collector transport i host ACK su još
   draft: programski blokirani, nalaz u `state/integration-20261027/COLLECTOR_REVIEW_PRIVATE.md`.
5. Raditi create → collect jednog tačnog eventa → local pilot_execute → stvarni
   target readback → exact host ACK; tek zatim move i cancel istim redom. Sačuvati
   client1 i sve prethodne zapise, vratiti callback/bookable zastavice u finally.

Produkcija ostaje isključena, admin kredencijali lokalni, podršci ništa ne slati.
Stariji prvi koraci ispod o čekanju VPS prenosa više ne važe.

## Aktuelni redosled posle izgradnje 27.10.2026.

Korisnik je prihvatio postojeće prevode za sada. **Ne slati podršci, ne ponavljati
prevode; prioritet je integracija.** Novi build je postavljen i 382/382 testa
prolaze na obe platforme. Pročitati [integraciono uputstvo](../deploy/INTEGRATION_RUNBOOK.md).

1. Proveriti korisnikov odgovor na već postavljeno pitanje: prenos samo test
   zauzetosti i SimplyBook HMAC ključa na postojeći VPS. Oba prenosa je odbila
   automatska kontrola; odgovor nije primljen, ne koristiti drugi transport.
2. Ako je odobren prenos zauzetosti, pokrenuti svež finite `pilot_publish` ciklus;
   server trenutno ima stari snimak i opravdan readiness 503. Ne slati stari paket
   od 09:46 UTC kao novi. Publisher ne zahteva admin akreditive na serveru.
3. Proveriti efektivno zamenjene blokove 11772 kroz native calendar/json, uz
   zasebnu kvotu za podržani refresh POST. Fetch i refresh success nisu dokaz uvoza.
4. Ako je odobren HMAC ključ, podesiti baš taj ključ i nativne booking webhook
   pretplate, uz readback. Server trenutno odbija unsigned/SB poruke bez ključa.
5. Dovršiti pregled privatnog nativnog source customer/booking modal toka pre
   pojedinačnog create/move/cancel testa. `state/native_source_trial.py` nije
   dokaz spremnosti: prepare/create su sada blokirani u draft skripti. Pravi
   booking modal i poseban customer modal jesu otvoreni read-only; njihov POST i
   readback tek treba implementirati. [Pregled](../evidence/integration-20261027-source-ui-review.json).
   Klijenta mapirati tek posle tačnog email+phone readback-a, ne po imenu.
6. Ograničeni `pilot_execute` ostaje lokalno i obrađuje samo jedan tačno odabran
   potpisan događaj uz zaseban pilot profil. Ne uključivati globalni live worker,
   automatski retry ili produkciju da bi pojedinačni test prošao.

Callback 6 neaktivan, zaposleni 11772 nije bookable/svi dani off, usluga 233160
neaktivna; ne otvarati stvarne termine. Booking 2 otkazan, client 1 se ne briše.
Starije korake ispod čitati samo gde ne protivreče ovom vrhu.

## Ažuriranje 27.10.2026. posle živog nastavka

Prvo pročitati [novi jezički pregled](../localization/LANGUAGE_AUDIT.md).
Sačuvano je 695 klijentskih polja, 18 zajedničkih polja (trajanje/podnožje) i 35 polja
šablona. Ne ponavljati te upise. Jedan HTML ključ blokira providerov PO editor;
preostaju i provajderovi tekstovi, WhatsApp jezik, novi render posle prevedenog
podnožja imejla i dokaz dostave. Stari zapis imejla imao je englesko podnožje;
prevod je sada sačuvan, ali zapis ne dokazuje izgled buduće poruke.
Nacrti pitanja su pripremljeni, nisu poslati; kontaktiranje podrške nije odobreno.

Rezervacija **2 je već otkazana**, status `canceled` u izveštaju `cancelled`.
Odobreni kontakt i srpski šabloni provereni su pre operacije; prijem obaveštenja
ostaje nepoznat. Sačuvati klijenta 1 i korisne test zaposlene/usluge. Ne ponavljati
otkazivanje i ne praviti novu rezervaciju kao retry. Sledeći test treba da proveri
stvarni sadržaj poruke, uz uvid u već poslato obaveštenje pre novog slanja.

VPS ostaje simulacija sa isključenim čitanjima. Zastareli feed i readiness 503
su dokumentovani; ne prikazivati stari ručni snimak kao svež ili automatski.
Tekst ispod je prethodni plan, primenjiv samo gde se slaže sa ovom dopunom.

## 1. Prvo uskladiti sadržaj namenjen klijentima

Poslednji funkcionalni zahtev korisnika: **sve što dolazi do klijenta mora biti
100% na srpskom**. Prethodni odgovor je najavio latinicu; to je radna pretpostavka.
Zahtev je sada delimično implementiran; ceo put još nije potvrđen kao srpski.

Obuhvati stvarno vidljive površine: sajt/stranicu zakazivanja, dugmad, formulare,
validacije, datume/vreme, potvrdu uspeha i greške, naslov/telo imejla, SMS,
podsetnike, pomeranje/otkazivanje, potvrđivanje i linkove koje klijent otvara,
tekst kalendarskog poziva i sve aktivne dodatke/kanale. Ne prevoditi tehničke
API ključeve, potpise, JSON polja i interne logove. Stručna/robna imena u katalogu
ne menjati masovno bez razumevanja značenja i očuvanja ID-eva/dodela.

Već urađena ograničena provera:

- SimplyBook `get_company_info` pokazuje timezone Europe/Belgrade, ali ne vraća
  locale/language. `update_company_info` u dostupnoj šemi nema jezičko polje.
- Pretraga tada dostupnih MCP alata nije našla namenski editor jezika/šablona.
  To nije dokaz da podešavanje ne postoji u podržanom administratorskom UI-ju.
- SrediMe kalendar je učitavao `fullcalendar/locale/sr.js`; to ne dokazuje jezik
  svih poruka ili stranica za klijenta. ICS summary u našem kodu je `Zauzeto`.
- Nisu napravljene promene jezika/šablona i nema potvrde dostave na srpskom.

Sledeći model treba da istraži zvaničnu aktuelnu dokumentaciju SimplyBook-a,
pročita aktuelna podešavanja i postojeće šablone i primeni podržane izmene u
okviru korisnikovog zahteva. Prvo sačuvati privatni prethodni izgled/podešavanja
i log tačnih promena, bez kontakata u javnom izveštaju. Koristiti postojeći
autentifikovani UI ako MCP nema tu mogućnost; lokalni API kredencijal možda
nije lozinka za web prijavu. Ne pretpostavljati da lokalni prevod bridge-a menja
providerove poruke. Ako neku površinu provajder ne može da prevede, zabeležiti
tačnu prepreku; ne tvrditi „100%” na osnovu samo jezičkog birača.

Pre sledeće radnje koja može poslati poruku pregledati odgovarajući šablon.
Potom, u kontrolisanom testu, dokazati stvarni sadržaj dostavljene poruke samo
korisnikovom odobrenom kontaktu. Ne izmišljati da je imejl/SMS isporučen na osnovu
API uspeha. Očekivane automatske poruke iz ranijih testova možda već postoje;
ne tvrditi da su retroaktivno zaustavljene.

## 2. Pročitati aktuelno stanje pre sledećeg testa

- SimplyBook rezervacija 2 je otkazana 27.10; proveriti samo ako zavisi naredno
  čišćenje. Zaposleni 9, usluga 496 i klijent 1 ostaju. Datum 26.10. je prošao;
  ne praviti novi termin niti ponovo otkazivati kao retry.
- SrediMe endpoint 6 treba da je neaktivan; zaposlenog 11772 i uslugu 233160
  treba zateći zatvorene za klijente. Proveriti da import URL ostaje samo na
  tom zaposlenom. Uvid ne znači odobrenje otvaranja stvarnih termina.
- VPS: procesi, mode/reads flag, sertifikat/obnova, tajmeri, bezbedni feed metadata,
  svežina snimaka. Ručni snimak od 23.10. ne predstavlja trenutno stanje.
- Pre svake mutacije zapisati nameru; ako je prethodna komanda prekinuta,
  prvo proveriti rezultat. Lokalni moved-feed je stvarno završen iako je poziv
  bio prekinut, dok njegov prenos na host nije potvrđen.

## 3. Nastaviti najmanji koristan pilot

Produkcija ostaje isključena. Test scope ostaje 11772 → 9 i 233160 → 496.
Kontakt postoji; ne pitati korisnika ponovo za imejl/telefon. Izvorni customer ID
još nije utvrđen, `clients` mapiranje je prazno; ciljni client allowlist lokalno
sadrži 1. Ne automatski odobravati ceo source customer map na osnovu target ID-a.

Nastaviti podržani izvorni webhook/ICS tok, ali jasno razlikovati:

1. vreme zahteva i, ako dostupno, stvarnog izvornog upisa;
2. prijem i trajno čuvanje događaja;
3. završetak lokalne obrade;
4. novu verziju feed-a;
5. prihvatanje refresh zahteva;
6. HTTP fetch konkretne verzije;
7. efektivnu promenu udaljene raspoloživosti/importovanog zauzeća.

Nedostupno merenje ostaje `unknown`. Poslednja faza nije dokazana. Endpoint koji
vraća 202 ne potvrđuje ceo tok. Zatvoren test zaposleni nema vidljive slobodne
termine; prvo pokušati podržano čitanje importovanih blokada u internom kalendaru,
bez otvaranja stvarne prodaje. Prethodno posmatrana ruta je
`/buker/studio-andjelija-sg/calendar`; test zaposleni nije nađen u selektoru.
Nije dovoljno učitati `sr.js` ili videti refresh da bi se proglasio uspešan pilot.

Podršci se ne šalje ništa bez izričitog naloga. Nacrti pitanja već postoje u
`PROVIDER_SUPPORT_REQUESTS.md`. Odgovor podrške i garantovani SLA nisu pilot gate.

## 4. Otkloniti konkretne tehničke zavisnosti, bez novih širokih optimizacija

- Proveriti stvarni Buker Test payload samo po bezbednim poljima/šemi i razlog
  ignorisanja; ne širiti allowlist da bi prošao tuđi/test nasumični employee ID.
- Dobaviti/podesiti pravi SimplyBook webhook secret podržanim putem ako treba
  za sledeću fazu. API plugin je ranije bio enabled/configured; MCP plugin info
  nije dao secret. Ne izmišljati ili slati generičku lokalnu tajnu provajderu bez
  razumevanja protokola.
- Za automatske host snapshot-e postoji zasebna nerešena dozvola za SimplyBook
  administratorske akreditive. Do tada lokalna read-only merenja ostaju moguća.
- Ne ostavljati tvrdnju da ručni feed ostaje svež bez procesa koji ga ažurira.
  Proveriti ponašanje zastarelog feed-a (prethodno očekivan prag oko 15 minuta).
  Ako se pilot pauzira, dokumentovati ili kontrolisano pauzirati samo nov test
  import. Uklanjanje URL-a/prazan feed nisu dokaz uklanjanja već uvezenih blokada.
- Proveriti novi snapshot modul fokusiranim testovima, pa relevantnu regresiju
  kad se menja kod/deploy. Ne prisvajati stare Linux rezultate novoj verziji.

## 5. Tačan plan čišćenja — nije izvršen

Stariji `evidence/controlled-pilot-cleanup-plan.json` ostaje istorijski: njegovi
prazni booking/subscription ID-evi i tvrdnja „no import URL” su zastareli.
Aktuelni obuhvat čišćenja uključuje:

- Rezervacija **2** je otkazana i dokumentovana; ne ponavljati operaciju.
  Proveriti stvarno obaveštenje; njegov prijem nije dokazan.
- **Ne brisati klijenta 1**: preegzistirao je i pripada korisniku.
- Datumski raspored zaposlenog **9** za **26.10.2026**; sačuvati istoriju testa.
- SimplyBook uslugu **496**, zatim zaposlenog **9**, samo kada se test završava,
  posle pregleda vezanih rezervacija. Ne ručno menjati dodele originalnih usluga.
- SrediMe import URL samo zaposlenog **11772**, uz proveru uvezenih blokada i
  podržanog načina pauze/čišćenja; ne menjati URL-ove stvarnog osoblja.
- SrediMe callback **6**: potvrditi deaktivaciju; eventualno uklanjanje samo
  pri završetku testa, uz tačan dnevnik. Ne praviti novi endpoint kao zamenu.
- SrediMe uslugu **233160** i zaposlenog **11772**, posle provere zavisnosti.
- Sačuvati journals, kvote, baze i javne dokaze. Zaustavljanje worker-a ne
  podrazumeva brisanje volume-a, baze, naloga ili servera.

Ne izvršavati ceo cleanup samo zato što ova primopredaja postoji. Korisnik želi
nastavak projekta; nedovršen test zaključiti, a ponovno upotrebljive test zapise
zadržati dok su potrebni.

## Šta traži buduću odluku, a šta više ne nedostaje

**Već postoji:** host/DNS/TLS, korisnikov test kontakt, test zaposleni/usluge,
stvarni source potpis i callback. Ne vraćati te stavke kao otvorena pitanja.

**Konkretno otvoreno:** jezik svih potrošačkih površina i njegov dokaz; stvarni
status/potrebno čišćenje rezervacije 2; podržano opažanje importovanog zauzeća;
source customer map za stvarni source test; SimplyBook webhook potpis; ako se
bira automatski remote snapshot, izričita dozvola prenosa administratorskih tajni.

**Može kasnije:** spoljni alarmni kontakt i kopije van VPS-a, realne staff/service
veze i trajanja/resursi, konačna notification/status pravila, zasebna produkciona
odluka. Činjenica da neke lokalne approval vrednosti već imaju `true` ne zamenjuje
proveru ovih stvarnih preduslova.

Na kraju svakog nastavka ažurirati glavni progress sa linkovima ka novim dokazima,
razlikovati simulaciju od živog rezultata i reći tačno šta ostaje nepoznato.

````

## Original: booking_bridge/deploy/INTEGRATION_RUNBOOK.md

````markdown
# Kontrolisani pilot: lokalni publisher i server koji samo prima — 27.10.2026.

Korisnik je prihvatio sadašnji jezik kao dovoljan za nastavak i rekao da se
podršci ništa ne šalje. Nastavlja se izgradnja postojeće veze; produkcija nije
odobrena. Završeni uvoz, kategorije, dodele, test zaposleni/usluge i otkazivanje
rezervacije 2 ne ponavljaju se. Klijent 1 ostaje sačuvan.

## Trenutno postavljeno i šta još nije potvrđeno

API i worker koriste sliku `andjelija-bridge:pilot-20261027-integration1`, ID
`sha256:8a8440d7e6ab72d6a388deb5bf2594e5ae174bfd166075d939d81c8d08987cc0`.
Worker komanda je `python -m booking_bridge.pilot_receiver`.
Postavka je `simulation`, `reads_enabled=false`; server nema SimplyBook
administratorske akreditive. [Compose](compose.pilot.yaml) više nema nedovršeni
`snapshot` profil koji je zahtevao `snapshot.env`.

Priloženi [Windows XML](../evidence/integration-20261027-windows-tests.xml) i
[Linux XML](../evidence/integration-20261027-linux-tests.xml) pri ovom pregledu
beleže po **382 testa**, bez padova i grešaka. [Windows smoke](../evidence/integration-20261027-windows-smoke.json)
i [Linux smoke](../evidence/integration-20261027-linux-smoke.json) su simulacioni
dokazi; ne potvrđuju udaljeni uvoz ili stvarnu sinhronizaciju rezervacija.

**Korisnik je potom izričito odobrio oba prenosa odgovorom „uradi to”.**
Minimalni snapshot je uspešno prenet: 15 blokova i originalni cache timestamp-ovi
podudarni lokalno/na serveru. Pravi SimplyBook HMAC ključ instaliran je u postojeći
zaštićeni env (0600); oba kontejnera su ponovo kreirana da vide zamenjeni Docker
secret bind mount. Runtime i javno odbijanje nevažećeg potpisa (401) provereni su.
[Dokaz od 10:08 UTC](../evidence/integration-20261027-approved-transfers.json)
beleži readiness 200 bez incidenata; to važi u trenutku dok je snimak svež.

**Nova prepreka je zasebno kreiranje tri SimplyBook pretplate.** Automatska kontrola
odbila je tu komandu kao posebnu izmenu naloga koja nije uključena u odobrenje
prenosa. Nije izvršena niti zaobiđena drugim transportom. Postavljeno je jedno
precizno pitanje za new_booking/change_booking/cancel_booking; odgovor još nije stigao.

Customer-only izvorni korak je potom takođe odbijen pre pokretanja procesa, kao
zasebno slanje ličnih podataka i kreiranje klijenta u SrediMe. Nema novih source
klijenata ili rezervacija. Native tok je pripremljen uz17privatnih offline testova;
[dokaz](../evidence/integration-20261027-next-trial-prepared.json). Sledeće precizno
pitanje objedinjuje pretplate, samo odobreni owncontact unos ako nedostaje i jedan
kontrolisani rezervacioni ciklus na test zapisima oba sistema, poruke samo korisniku.

[Native import dokaz](../evidence/integration-20261027-source-import.json) potvrđuje
12/12 budućih intervala, bez viškova/duplikata; tri feed intervala već su prošla.
Fetch38.063s i prvo puno native buduće stanje67.911s posle refresh acceptance-a
nisu actual commit vreme, booking-change E2E ili dokaz ispod60s.

[Rollout dokaz](../evidence/integration-20261027-rollout.json) od 09:48 UTC
potvrđuje tačan image ID, receiver komandu, liveness 200 i privatni readiness 503
zbog `booking_snapshot_stale`. [Lokalni snimak](../evidence/integration-20261027-local-snapshot.json)
od 09:46 UTC ima 15 blokova, bez kontakata ili kredencijala u minimalnom paketu.
Vremenom zastareva; naredni odobreni publisher mora napraviti nov snimak.

Ranije odbijeni prenos SimplyBook administratorskih akreditiva ostaje zasebna
zabrana. Odobrenje vremena zauzetosti ili HMAC potpisa ne bi odobrilo prenos
administratorskog pristupa. **SimplyBook webhook pretplate još nisu napravljene.**
Kreiranje pretplate pre usaglašenog potpisa i prijemnika nije sledeći korak.

## Četiri odvojene uloge

| Modul | Gde radi i šta radi | Šta njegov uspeh potvrđuje |
|---|---|---|
| `pilot_snapshot` | Lokalno čita nalog preko postojećeg `ReadOnlyGateway` i zajedničke kvote; završava punu generaciju u privremenoj bazi | Potpun lokalni snimak i lokalni feed, bez poslovnih API upisa |
| `pilot_publish` | Lokalno pravi minimalni paket, proverava ga, pa ga šalje preko SSH-a sa proverenim host ključem | Ograničeni paket je prihvaćen i atomski sačuvan na serveru; ne potvrđuje SrediMe uvoz |
| `pilot_receiver` | Na VPS-u proverava lokalno zdravlje i svežinu keša | Server je živ i lokalno spreman; ne obrađuje inbox niti poziva naloge |
| `pilot_execute` | Lokalno izvršava najviše jedan već primljen i pregledan pravi pilot događaj | Ishod tog događaja u durable redu; nije automatsko pokretanje celog reda |

`--read-only` kod publisher-a znači da se ne upisuje na SimplyBook nalog.
Prenos ipak šalje podatke na VPS i menja njegov ograničeni keš; zato postojeće
odobrenje lokalnog čitanja ne zamenjuje otvorenu dozvolu za prenos.

Tačan obuhvat je SrediMe zaposleni **11772 → SimplyBook 9**, usluga
**233160 → 496**. [Aktuelni ugovor usluge](../evidence/pilot-service-contract-20261027.json)
potvrđuje 30 minuta, bez buffer-a, podeljenog rada ili izabranih deljenih
resursa. SrediMe zaposleni ostaje nedostupan/svi dani neradni, usluga neaktivna,
callback 6 deaktiviran. Test ostaje zatvoren za stvarne klijente.

## Lokalna priprema bez prenosa

Komande se izvršavaju iz korena projekta, u novom PowerShell prozoru bez
nasleđenog drugog `BRIDGE_*` profila. Lokalni privatni ulazi ostaju:

- `booking_bridge/state/controlled-pilot-config.json` — namenski simulacioni profil;
- `booking_bridge/secrets/pilot.env` — privatni bridge/feed podaci;
- `service_importer/.env` i `provider_assignment/.env` — postojeći lokalni REST pristup;
- `booking_bridge/state/controlled-pilot/` — trajno lokalno stanje;
- `booking_bridge/secrets/vps_pilot_ed25519` i `vps_known_hosts` — SSH pristup i proveren host.

Sadržaj tih datoteka ne stavlja se u argumente, javne dokaze, build kontekst
ili release arhivu. Eksplicitni izolovani JSON profil preskače podrazumevana
lokalna CSV mapiranja; običan `Settings.load` zadržava postojeću proveru konflikta.

Lokalni snimak, bez SSH prenosa i bez izvornih refresh POST-ova:

```powershell
$env:BRIDGE_ENV_FILE = [IO.Path]::GetFullPath('booking_bridge/secrets/pilot.env')
.\.venv\Scripts\python.exe -m booking_bridge.pilot_snapshot --read-only --config booking_bridge/state/controlled-pilot-config.json --state booking_bridge/state/controlled-pilot
```

Profil mora ostati `simulation`/reads off, sa pregledanim pilot scope-om,
`pilot_read_snapshots=true`, `schedule_reference_verified=true`, tačno jednim
zaposlenim i izričitim pilot uslugama. Ne postavljati approval vrednosti samo
da bi provera prošla. Stvarni postojeći kontakt i potvrđeni ugovor se čuvaju.

Neuspešno čitanje ne osvežava raniji objavljeni snimak. Postojeće neizvesne
namere ili drift/scope incidenti ostaju prepreka. Izvorne kopije koje lokalni
`links` već poseduje izostavljaju se iz izlaznog paketa radi sprečavanja petlje.
Ako zaposleni 9 ima aktivnu, nepovezanu rezervaciju za nasleđenu uslugu izvan
pilota, izvoz se zaustavlja umesto da objavi lažno slobodan termin ili sam proširi obuhvat.

## Ograničeni publisher — konkretan prenos je sada odobren

Sledeća komanda je uspešno izvršena posle izričitog odobrenja. Dozvola važi za
isti probni obuhvat i postojeći VPS; ne uključuje administrativne akreditive,
proširenje na druge zaposlene ili produkciju.

```powershell
.\.venv\Scripts\python.exe -m booking_bridge.pilot_publish --read-only --config booking_bridge/state/controlled-pilot-config.json --state booking_bridge/state/controlled-pilot --env-file booking_bridge/secrets/pilot.env --host 169.58.118.33 --cycles 1
```

Za kasnije odobren kratak ogled može se koristiti `--cycles 3 --interval 300`.
Podrazumevano je jedan ciklus; CLI prihvata 1–120 ciklusa i razmak 10–3600 s.
Razmak od 300 s je podrazumevana probna vrednost, ne obećanje ažuriranja ispod
minuta. Svaki snimak troši postojeću trajnu REST kvotu i pacing; neuspeh
zaustavlja seriju. Ne uvoditi neograničenu petlju ili Windows zadatak po rasporedu.

Publisher radi samo dok je **ovaj računar uključen, budan i povezan**. Završetak
ciklusa, zatvaranje procesa ili `Ctrl+C` prekidaju dalja osvežavanja. Ovo nije
samostalan servis 24/7. Stari cache zadržava izvorne timestamp-ove; po isteku
važenja feed/readiness mogu vratiti 503. To ne potvrđuje da je SrediMe uklonio
već uvezene blokade ili sam zatvorio raspoloživost.

Paket sadrži samo pregledani obuhvat, vremena/status zauzetosti, minimalne
rasporede, originalne timestamp-ove i hash verzije feed-a. Ne sadrži `client_id`,
imena, kontakte, slobodne beleške, izvorne odgovore, sesije, privatne URL-ove
niti ključeve. Lokalna provera prethodi SSH-u, a server proverava isti ugovor.
Tri cache stavke, feed metapodaci i refresh generation upisuju se u jednoj
transakciji. Pogrešan obuhvat/hash, stale/future podaci, rollback/replay konflikt
ili neispravan raspored ne menjaju objavljeno stanje. Identičan paket ne
podmlađuje podatke. SSH receipt ostaje `remote_import_confirmed=false`.

## Server samo prima i nadzire

Postojeći servis `worker` pokreće `pilot_receiver`, koji ne pravi SimplyBook
klijenta, ne čita provajdere, ne šalje refresh, ne menja rezervacije i ne
obrađuje/oporavlja inbox. Čuva red i neizvesne namere za poseban pregled.
Kašnjenje reda i zastareli keš vidljivi su kao incidenti; zelen HTTP liveness
sam po sebi ne znači uspešnu sinhronizaciju.

Čitanje poslednjeg loga aktivnog receiver-a:

```powershell
ssh -i booking_bridge/secrets/vps_pilot_ed25519 -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=booking_bridge/secrets/vps_known_hosts -o BatchMode=yes root@169.58.118.33 "docker logs --tail 3 booking-bridge-pilot-worker-1"
```

`pilot_receiver --once` koristi isti `worker.lock` kao aktivni proces; paralelni
poziv zato očekivano staje sa `Another local job holds the lock`. Taj rezultat
je potvrđen posle rollout-a i ne zahteva restart ili drugi worker.

Receiver paketa `python -m booking_bridge.pilot_exchange --read-only --stdin`
koristi publisher. Ne kopirati paket u shell argumente ili logove. Granica je
1.000.000 bajtova; duplirani JSON ključevi i dodatna privatna polja se odbijaju.
Stari `snapshot.env`/remote snapshot profil nije alternativni put za akreditive.

## Jedan lokalni događaj sa upisom — zaseban korak

`pilot_execute` je pripremljen modul, ne dokaz završenog živog transfera.
Zahteva postojeću lokalnu `bridge.sqlite`, poseban eksplicitan JSON profil
`mode=pilot`/`reads_enabled=true`, pregledane usluge i provereno client mapiranje
na odobreni kontakt. Izvorni customer ID još nije utvrđen; SimplyBook ID 1 sam
po sebi ne potvrđuje to mapiranje. [Ograničena izvorna pretraga](../evidence/pilot-service-contract-20261027.json)
nije našla odgovarajući SrediMe zapis i nije napravila klijenta.

Provera raspoloživih argumenata bez čitanja tajni ili upisa:

```powershell
.\.venv\Scripts\python.exe -m booking_bridge.pilot_execute --help
```

Stvarno izvršenje mora imati `--execute`, `--config`, `--state` i preporučeni
`--event-id` tačno pregledanog najstarijeg queued događaja. Primer profila za
izvršavanje ovde nije izmišljen niti aktiviran. Lokalni durable zapis mora
poticati od stvarnog proverenog prijema; payload se ne pravi ručno da bi gate
prošao. Postojeći Buker Test, `test:false` ali sa zaposlenim van allowlist-a,
nije odgovarajući rezervacioni događaj.

Pre konstruisanja gateway-a proveravaju se preflight, integritet/hash događaja,
tačan zaposleni/usluga/klijent i odsustvo neizvesnih namera. Obrađuje se najviše
jedan događaj; tuđi, ponovljen ili nejasan pokušaj staje radi pregleda. Povratak
`already_processed` ne ponavlja poslovni upis. Ovo ne uključuje produkciju niti
menja server u automatskog izvršioca. Pre svakog upisa koji može poslati poruku
koristi se samo odobreni kontakt i već pregledani srpski šablon.

## Šta zabeležiti posle svakog budućeg odobrenog testa

Odvojiti lokalni REST snimak, prihvatanje/verziju na hostu, prihvatanje refresh
zahteva, stvarni fetch te verzije i potvrdu importovanog zauzeća. Nedostupna
poslednja faza ostaje `unknown`. Nije dovoljno videti 202, uspešan SSH receipt
ili `refresh_scheduled:true`. Skriveni, neradni zaposleni nema vidljive slobodne
termine za takvo merenje; ne otvarati stvarnu prodaju radi dokaza.

Za zaustavljanje koristiti `docker compose stop worker` ili `docker compose stop`,
uz očuvanje baze i volume-a. Nikad `down -v`, brisanje baze ili prazan ICS kao
rollback. Stara slika iz 23.10. nema novi receiver: pri njenom vraćanju worker
ostaje pauziran dok se ne proveri usaglašena komanda/profil. Ne vraćati obični
worker koji bi trošio durable inbox kao prečicu do zelenog statusa.

````
