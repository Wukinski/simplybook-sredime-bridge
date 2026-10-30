# Priprema trajnog lokalnog publisher-a

**28.10.2026: lokalna implementacija, nije uključena.** Završeni source
9VPLV6E → target 5 ciklus se ne ponavlja. Postojeći VPS i njegov
`pilot_receiver` nisu menjani. Produkcija, automatska obrada rezervacija i prenos
administratorskih akreditiva nisu deo ovog koraka.

## Predloženi raspored odgovornosti

Lokalni `python -m booking_bridge.pilot_supervisor` koristi postojeći
`capture_packet` i `publish_packet`. Administratorski pristup ostaje u lokalnom
REST klijentu sa GET-only fasadom; autentikacija ostaje posao tog klijenta.
Publisher šalje samo validiran minimalni occupancy paket preko postojećeg
pinned SSH pristupa. Host potvrđuje prihvatanje paketa, ne izvršeni SrediMe uvoz.

Postojeći udaljeni API i receiver čuvaju događaje i prijavljuju zdravlje.
Publisher ne konstruiše booking worker, ne preuzima niti potvrđuje source red,
ne aktivira callback i ne poziva native refresh. Automatski booking executor
ostaje poseban naredni posao sa sopstvenim pravilima i odobrenim opsegom.

Koristiti postojeću lokalnu bazu sa owned linkovima, namerama i incidentima.
Nova prazna baza nije zamena za tu istoriju. `CaptureView` zadržava te zaštite;
owned target rezervacije ostaju izostavljene iz povratnog feed-a. Ne kopirati
native brojeve kao webhook ključeve: [format mapiranja](../mappings/README.md).
Ovaj korak nije aktivirao nove identitete ili proširio privatni booking binding.
Istorijski capture profil i postojeći feed URL zadržavaju raniji namespace:
publisher ne obrađuje webhook događaje, pa ovom pripremom nisu migrirani.
Budući webhook execution profil mora zasebno koristiti proverene opaque ključeve,
uz usklađene feed tokene/putanje i pregled njihovih zavisnosti.

## Pokušaji, prekid i zdravlje

Podrazumevani početak ciklusa je na približno 300 s. Profil mora ostati
`simulation`, `reads_enabled=false`, sa ranije eksplicitno pregledanim jednim
probnim zaposlenim/uslugama i `pilot_read_snapshots`/`pilot_scope_reviewed`.
CLI traži `--run --read-only` i konkretan izolovani profil. Zajednički
`pilot-read-snapshot.lock` sprečava istovremeni finite publisher/capture.

Pre svakog čitanja generacije trajno se rezervišu pokušaj i naredno dozvoljeno
vreme u `publisher-status.json`. Restart ne briše broj neuspeha ili čekanje.
Posle najviše tri uzastopna neuspeha proces staje sa kodom 2. Samo privremeno
čitanje, prekoračenje capture roka i tačno prepoznat transportni prekid imaju
ograničen retry; novi pokušaj uvek ponovo čita podatke. Nepoznat SSH odgovor,
odbijen paket, neusklađen receipt, Review ili neočekivana greška blokiraju rad.

Status se zapisuje atomskim zamenjivanjem, uz fiksne razloge bez provider
payload-a, kontakata ili tajni. Heartbeat se osvežava tokom čekanja i na granicama
REST čitanja; konzola beleži promene faze/broja pokušaja. Capture rok je 180 s,
proveren pre GET-a i nakon kompletiranja; tekući HTTP/auth poziv završi u okviru
sopstvenog timeout-a. Lokalni GET transport ima jedan pokušaj i timeout (3,5 s).
SSH ima timeout 60 s. To nije tvrdi prekid svakog mogućeg internog čekanja
lokalnog klijenta. Zaustavljanje signalom prekida čekanje, a tekući poziv mora
da se završi; prisilan prekid ostavlja rezervaciju pokušaja za restart.

Obavezno važi `interval + capture_timeout + 60 < min(snapshot_max_age,
schedule_max_age)`. Ova margina ne predstavlja obećanje dostupnosti ili uvoza.
Za puni 60-dnevni opseg jedan ciklus može zahtevati oko 13 GET-ova: na 300 s to
je okvirno 3.744 GET-a/dan, pre paginacije, autentikacije, retry-a i drugih
procesa. Zajednički trajni budžet 4.500 ostaje obavezan. Pre uključivanja
izabrati horizont/interval prema stvarnom budžetu; ne zaobilaziti limit radi
održavanja zelenog statusa.

Provera koja **samo čita lokalni status**, bez .env, baze ili mreže:

```powershell
.\.venv\Scripts\python.exe -m booking_bridge.pilot_supervisor --check --state booking_bridge/state/controlled-pilot
```

Kod 0 znači svež proces i nedavno potvrđen paket sa svežim izvornim vremenima;
kod 2 znači da provera nije zdrava. Zdravlje zahteva heartbeat do 120 s,
poslednji potvrđeni paket i najstariji snapshot unutar limita iz profila.
Backoff, stop, blokada, neispravan/nedostajući status ili vraćen sat nisu zdravi.
Lokalni capture ili heartbeat bez potvrđenog SSH receipt-a ne obnavlja uspeh.
Ni ova provera ne dokazuje native uvoz, booking E2E ili dostavu poruka.

## Pripremljen Windows zadatak

`prepare_publisher_task.ps1` samo pravi **nov, isključen XML fajl**. Ne registruje,
ne uvozi i ne pokreće zadatak. Ne čita sadržaj konfiguracije ili env fajla.
Action koristi apsolutni lokalni Python, ispravno citirane putanje i radni
direktorijum projekta; nema shell-a ili tajni u argumentima.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File booking_bridge/deploy/prepare_publisher_task.ps1 -Workspace . -Config booking_bridge/state/controlled-pilot-config.json -State booking_bridge/state/controlled-pilot -EnvFile booking_bridge/secrets/pilot.env -Output booking_bridge/deploy/publisher-task.local.xml
```

Process-scoped Bypass služi samo izvršenju ovog pregledanog lokalnog helper-a;
ne menja sistemsku execution policy. Postojeći output se ne prepisuje.
Task i njegov logon trigger su oba disabled. Predviđeni su isti korisnik,
InteractiveToken, LeastPrivilege, IgnoreNew, najviše tri task restarta na pet
minuta i bez roka za normalno trajanje procesa. XML ne sadrži lozinku.
Helper je lokalni Windows alat i namerno nije deo VPS release arhive.

Ovaj izbor zahteva uključen računar i prijavljenog korisnika. Sleep, gubitak
mreže, odjava ili gašenje prekidaju osvežavanje; zato priprema nije dokaz 24/7.
XML treba pregledati uz konkretan profil, vlasnika nadzora, budžet i način rada
računara pre buduće registracije/uključivanja. U ovoj fazi ništa nije registrovano.

## Oporavak i povratak

Pregledati sanitizovan status, lokalne incidente/owned namere i host readiness.
Otkloniti uzrok pre eksplicitnog lokalnog resetovanja failure budžeta. Reset
koristi isti lock, ne čita nalog, ne briše SQLite/journals i ne pokreće proces:

```powershell
.\.venv\Scripts\python.exe -m booking_bridge.pilot_supervisor --reset-failures --read-only --config booking_bridge/state/controlled-pilot-config.json --state booking_bridge/state/controlled-pilot --env-file booking_bridge/secrets/pilot.env
```

Reset briše samo tekuću agregatnu evidenciju supervisor-a, uključujući prethodnu
oznaku uspeha; operativni booking dokazi ostaju. Promena opsega/destinacije traži
novi pregled i reset, bez prenošenja starog zelenog statusa na novi profil.
Pre incidentnog resetovanja sačuvati status u privatnoj evidenciji po potrebi.

Za povratak zaustaviti lokalni proces/zadatak, sačuvati status i bazu, pa po
potrebi koristiti raniji finite publisher sa istim pregledanim profilom/bazom.
Host će prijaviti zastarelost kad isteknu izvorna vremena. Ne prazniti ICS,
brisati bazu/linkove, koristiti `down -v` ili vraćati staru bazu preko kasnijih
upisa. Zatvoreni callback 6 i završene rezervacije ostaju u potvrđenom stanju.

Spoljni alarmi i zaštićena kopija van VPS-a ostaju naredni pregled. Trenutna
implementacija ne šalje poruke. Za budući callback/executor potreban je jasan
vlasnik lease-a, prijem i završetak queued događaja pre gašenja, stvarni target
readback pre ACK-a i postupak za neizvestan upis bez slepog ponavljanja.
