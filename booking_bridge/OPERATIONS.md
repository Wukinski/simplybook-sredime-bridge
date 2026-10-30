# Nadzor i oporavak

## Dnevni pregled

API sluša lokalno. Administracija zahteva `X-API-Key` iz privatnog `.env`;
pristupati preko lokalnog računara, SSH tunela ili VPN-a. Primer u PowerShell-u
čita ključ bez unošenja u istoriju komandi:

```powershell
@'
from dotenv import dotenv_values
import requests
key = dotenv_values('booking_bridge/.env')['BRIDGE_ADMIN_KEY']
r = requests.get('http://127.0.0.1:8010/ops/issues', headers={'X-API-Key':key}, timeout=10)
print(r.status_code)
print(r.json())
'@ | .\.venv\Scripts\python.exe -
```

| Provera | Značenje |
|---|---|
| `GET /health/live` | API proces radi; ne potvrđuje svežinu podataka |
| `GET /health/ready` sa ključem | Heartbeat i ispravan zdrav izveštaj nisu stariji od 120 s; u istoj DB transakciji nema otvorenih incidenata |
| `GET /ops/events` | Poslednjih 200 događaja, stanje, pokušaji i razlog; bez payload-a |
| `GET /ops/issues` | Otvoreni incidenti i zastareli izvori |
| `GET /ops/intents` | Nejasni udaljeni upisi; bez kontakata klijenata |
| `python -m booking_bridge status` | Lokalni zbir stanja i starost heartbeat-a |
| `python -m booking_bridge preflight --target pilot` | Offline provera lokalne konfiguracije i postojećih nejasnih namera; bez API poziva i kreiranja/migracije baze |

Preflight podrazumeva `--target pilot`; `--target production` dodatno zahteva
potvrđene udaljene probne scenarije. Izlaz je JSON sa `target`, `current_mode`,
`configuration_ready`, listom `checks` (`code`/`ok`) i
`external_validation_performed:false`. Izlazni kod 0 znači samo da lokalni
preduslovi prolaze; kod 2 znači da postoji blokada ili konfiguracija nije čitljiva.
Izveštaj ne ispisuje ID-eve, privatne URL-ove, kontakte ili kredencijale.
Postojeća baza se otvara samo za čitanje; ako je nema, preflight je ne pravi.

Preflight ne menja režim ili approval zastavice i ne potvrđuje stanje udaljenih
naloga, DNS/TLS ili isporuku poruka. Nedostajuća zastavica označava stanje
konfiguracije, ne novo traženje već datog odobrenja; ne uključivati zastavice
za praktične scenarije koji još nisu izvršeni. `/health/ready` dodatno proverava
stvarno stanje pokrenutog radnika. Nov incident se vidi odmah, bez čekanja
sledećeg scheduler izveštaja; neispravan ili zastareo izveštaj vraća 503.

Događaji: `queued`, `working`, `done`, `test`, `ignored`, `stale`, `review`, `dead`.
`ignored` znači da izvorni zaposleni nije dozvoljen; poznato pomeranje izvan
allowlist-e dodatno pravi incident i zaustavlja objavljivanje nesigurnih feedova.

Red stariji od 10 minuta, zastareli snimci, greške izvora, promene porekla i
nejasni upisi otvaraju incidente. Konfigurisani `BRIDGE_ALERTS_URL` prima generičan
HTTPS JSON najviše jednom u 15 minuta dok problem traje. Sadrži broj incidenata,
bez rezervacija, kontakata i URL tajni. Kanal još nije izabran niti aktiviran.

Ako se radnik ili host potpuno ugasi, on ne može poslati sopstveno upozorenje.
Nezavisna uptime provera mora pratiti privatni readiness kroz odobren VPN/tunel
ili namenski sistem nadzora; javni liveness sam nije dovoljan. Potrebna je i
provera diska, rezervnih kopija i dnevnog API budžeta.

## Ponovni pokušaj

Posle dorade baze `booking_heads` trajno čuva najnoviji poznati snimak uključujući
ignorisanog zaposlenog. Stara baza se migrira bez brisanja inbox-a/linkova;
`PRAGMA user_version=1` označava ovu aditivnu migraciju. Ne vraćati staru verziju
aplikacije koja ne održava tu evidenciju nad istom bazom. Posle restore-a ponovo
usaglasiti nove događaje i udaljene upise pre otvaranja create operacija.

Za bezbedan pregled naloga bez potvrde poslovnih pravila koristiti
`python -m booking_bridge diagnose --read-only`; za offline predlog test zapisa
`python -m booking_bridge prepare-pilot`. Obe komande odbijaju/izbegavaju
poslovne upise, a rezultati su privatni u ignorisanom `state/` direktorijumu.

Prvo ispraviti uzrok: mapiranje, poslovnu odluku, nedostajuće odobrenje ili
privremeni kvar. Zatim `POST /ops/events/{event_id}/retry` sa administratorskim
ključem. Događaj se ponovo stavlja u trajni red; endpoint ne zove SimplyBook.
Novi snimci i dalje imaju prvenstvo nad starim po vremenu nastanka. Nema
automatskog ponavljanja trajnih/poslovnih grešaka.

Čitanja koja privremeno ne uspeju ponavljaju se sa rastućim razmakom, do
`max_attempts` (podrazumevano 8), zatim prelaze u `dead`. Udaljeni upisi se nikada
ne ponavljaju u transportu povezivača. Započeta namera preživljava prekid procesa.

### Timeout nakon kreiranja

1. Zaustaviti samo radnika; API može i dalje trajno prihvatati webhookove.
2. Pregledati `/ops/intents`, originalni termin u Bukeru i SB kalendar.
3. Povezivač periodično traži kandidate kroz REST, ali jedan isti klijent/termin
   nije dokaz vlasništva. Kandidati ostaju u privatnoj DB cache tabeli
   `candidates:{booking_id}`; njihove podatke ne objavljujemo.
4. Ako je konkretan SB booking ID pouzdano potvrđen kao rezultat tog prenosa:

```powershell
.\.venv\Scripts\python.exe -m booking_bridge resolve-create --booking "SREDIME_BOOKING_ID" --target 123 --verified-ownership
```

Komanda ponovo čita detalje, zahteva potpuno slaganje osobe/usluge/zaposlenog/
termina sa namerom i upisuje vezu. Ne kreira rezervaciju. Zatim pokrenuti radnika.
Pre ove radnje svi approval podaci i identitet naloga moraju biti podešeni za
odobreni pilot/produkciju; komanda ne radi sa memorijskim simulatorom.

Ako nema kandidata, odsustvo na jednom čitanju ne dokazuje neuspeh. Potrebna je
provera na nalogu/podrška. Namere se ne brišu da bi se zaobišla zaštita. Ako je
rezultat snimljen pre pada procesa, radnik ga sam proverava i nastavlja. Izmene,
otkazivanja i potvrde takođe se prvo proveravaju čitanjem; neslaganje ostaje
za ručno rešavanje, bez slepog ponavljanja.

## Klijenti

Uz odobrenje `client_mapping`, nakon provere iste osobe u oba sistema:

```powershell
.\.venv\Scripts\python.exe -m booking_bridge map-client --source "SREDIME_CUSTOMER_ID" --target 123 --verified-person
```

Komanda zahteva zaustavljenog radnika i čita samo ciljnog klijenta. Odbija
promenu postojeće veze i zajednički ciljni ID za različite izvorne osobe.
Za novog klijenta, tek uz posebno odobrene kontakt podatke u potpisanom događaju:

```powershell
.\.venv\Scripts\python.exe -m booking_bridge create-client --event "EVENT_ID_32_HEX" --verified-new-person
```

Pre toga operator proverava da osoba već nije u SB. Potrebna su stvarna ime,
imejl i telefon iz odobrenog payload-a; nepotpuni podaci zaustavljaju postupak.
Na timeout posle kreiranja ne pokretati ponovo; ručno proveriti i koristiti
`map-client` za potvrđeni rezultat. Ne deliti kontakte ili DB kroz chat.

## Periodična ICS provera

Originalni SrediMe feedovi ostaju privatni i ne objavljuju se ponovo. UID,
LAST-MODIFIED, SEQUENCE, vremena i STATUS služe za detekciju promena.
Prethodni događaji se zadržavaju ako nestanu iz feeda: feed ima klizni prozor
od sedam dana unazad, a nestanak može značiti pomeranje zaposlenog.

Za proverenu vezu između ICS UID-a i webhook booking ID-a:

```powershell
.\.venv\Scripts\python.exe -m booking_bridge bind-source-uid --employee "SREDIME_EMPLOYEE_ID" --uid "VERIFIED_ICS_UID" --booking "SREDIME_BOOKING_ID" --verified-reference
```

Ne dekodirati/pretpostavljati format ID-a. Ako test pokaže da je UID jednak
booking ID-u, i dalje treba zabeležiti potvrđenu vezu. Sledeća provera poredi
poznati webhook snimak i feed. Neusklađenost/nepoznati UID otvara incident.

Automatski se oporavljaju: trajno primljeni poslovi posle restarta, prolazne
greške čitanja, duplikati, stariji događaji i poznat rezultat upisa koji je
moguće potvrditi čitanjem. Ručna provera je potrebna za propušten webhook bez
snapshot-a, nejasno vlasništvo SB termina, nepoznatu vezu UID-a, promenu
usluge bez dovoljnog mapiranja ili kontakte koje ICS nikada nije sadržao.
ICS CANCELLED nije dovoljan za izbor SrediMe razloga otkazivanja: i interno/
no-show stanje se tako izvozi.

Prazan/neispravan/nedostupan izvorni feed usporava lokalna čitanja do 12 h i
zaustavlja ih posle 100 neuspeha. Posle ispravke koristiti
`POST /ops/source-feeds/{employee_id}/reset`. Ovo resetuje **naš** brojač;
SrediMe-ov zaustavljeni uvoz zasebno resetuje vlasnica/podrška. Ne dodavati
lažne rezervacije za održavanje feeda.

## Tajne i privatnost

- Webhook tajna je heksadecimalni tekst; HMAC koristi njene tekstualne bajtove,
  bez `bytes.fromhex`. Potpis SrediMe ima prefiks `sha256=`, SB X-Signature nema.
- Ugasiti access log za ICS putanje u svim proxy/hosting slojevima. Token u
  putanji je kredencijal. Uvicorn primeri imaju `--no-access-log`.
- Interna i obična beleška se ne čuvaju u inbox-u niti šalju klijentima. Kontakti
  se odbacuju osim kada je posebno odobren `customer_contacts`.
- `.env`, stanje i backup dozvoliti samo servisnom korisniku. SQLite sam nema
  enkripciju: produkcija zahteva šifrovan disk/backup i HTTPS. Opaque ID-evi su
  i dalje podaci koji zahtevaju kontrolu pristupa.
- Windows klijent koristi postojeći DPAPI token cache. Na Linux-u token ostaje
  u memoriji dugotrajnog radnika; nema plaintext token cache-a. Restart ne treba
  pretvoriti u beskonačnu petlju prijavljivanja.

Rotacija privatnog izlaznog ICS tokena:

```powershell
.\.venv\Scripts\python.exe -m booking_bridge rotate-feed --employee "SREDIME_EMPLOYEE_ID"
```

Nova vrednost se sačuva u lokalni `.env`, bez ispisa. Restartovati API, zatim
odmah ažurirati privatnu Buker import adresu u lokalnom editoru/UI-ju. Stari
token daje 404. Ako proces koristi secret-manager/`BRIDGE_ENV_FILE`, rotirati
isti ključ u tom izvoru umesto samo u lokalnom `.env`, pa restartovati servise.

SrediMe webhook rotacija: po potrebi deaktivirati endpoint, sačekati tekuće
isporuke, rotirati u Bukeru, odmah uneti novu tajnu lokalno, restartovati API,
poslati Test i ponovo aktivirati. Nova tajna važi i za ponovljene stare isporuke;
Buker ne nudi dve istovremeno aktivne tajne. Privatni originalni SrediMe feed
URL rotira se preko vlasnice/podrške; promena lozinke zaposlenog menja izvedeni token.
SB webhook secret rotirati u API Settings uz koordinisani restart prijemnika.

## Backup i bezbedno isključivanje

```powershell
.\.venv\Scripts\python.exe -m booking_bridge backup --destination "PRIVATE_BACKUP_DIRECTORY\bridge-backup.sqlite"
```

Koristi se SQLite online backup, uključujući WAL; ne kopirati samo otvoreni
`.sqlite` fajl. Šifrovati backup, čuvati van hosta i periodično testirati restore.
Sačuvati i zaštićene konfiguracije/mapiranja odvojeno od tajni. Retenciju
kontaktnih podataka dogovoriti pre produkcije; automatsko brisanje inbox-a
trenutno nije uključeno da ne bi izgubilo deduplikaciju i dokaz oporavka.
Tombstone veze moraju ostati i posle arhiviranja starih payload-ova.

Za privremeno zaustavljanje upisa ugasiti radnika (Ctrl+C/stop servisa), zadržati
API i red. Dug prekid izaziva zastarevanje ICS-a i traži ručno praćenje oba
kalendara. Za potpuno isključivanje prvo rešiti buduće prenete termine, zatim
deaktivirati oba webhook pretplatnika i usaglasiti uklanjanje Buker ICS import
URL-ova/blokada. Sačuvati backup i veze; ne brisati DB niti slati prazan feed
kao prečicu. Posle eventualnog restarta obnoviti isti disk, tajne i identitet
naloga. Druga instanca radnika ne može preuzeti isti OS lock.
## Availability deadline and diagnostics (2026-10-22)

The required outcome is consistently below 60 seconds end to end. The current
ICS adapter cannot establish that outcome. Production validation rejects it when
`require_subminute_availability` is true (the default). Do not disable this flag
to claim the deadline has been met. See [AVAILABILITY_LATENCY.md](AVAILABILITY_LATENCY.md)
and [SREDIME_ACCESS_REQUIRED.md](SREDIME_ACCESS_REQUIRED.md).

On the protected admin interface, `GET /ops/availability` reports the latest
feed-ready, refresh-scheduled and feed-fetched stages for allowed employees.
`current_version_fetched` compares actual ICS occupancy versions. Feed-ready age
is the age of the last content change, not measured remote propagation latency.
Feed fetch is not import confirmation; both `import_confirmed` and
`subminute_verified` remain false until a supported external receipt exists.
This report does not replace `/health/ready` or diagnose all stale snapshots.

The latest update adds durable `latency` observations and seven-day stage counts.
`GET /ops/availability/{employee}/history?limit=50` returns up to 200 records for
an allowed employee, with admin authentication. It measures **feed ready to HTTP
fetch**, not source commit to effective availability. Baselines are excluded from
change counts. Superseded versions without a fetch are listed separately, exactly
60 seconds counts as a miss, and clock anomalies are flagged. Any caller with a
valid private feed URL can generate the observed fetch; it is not authenticated
evidence that SrediMe imported the version.

`refresh_coalesce_seconds` defaults to 5 (range 1–30). There is no mandatory
60-second gap; all attempts still share the rolling 60/employee/hour allowance.
On exhaustion, inspect `refresh-quota:<employee>` and pending due time. Do not
reset counters to force traffic. Transient HTTP failures retry after 5, 10, 20,
40, 80, then at most 120 seconds by default; stale-feed validation waits five
seconds without making a POST. Unchanged outbound occupancy consumes no refresh.
Publication metadata, history and its queued notification share one transaction.
Failed background inventory/snapshot tasks recover after ten seconds, limited
to 12 accelerated attempts/task/hour plus the normal fallback. Booking recovery
also shares the 60/hour accelerated snapshot allowance. Recovery counters survive
restart; persistent errors may therefore wait for allowance to reopen.

`queue-age` now detects source work waiting over ten seconds.
`availability-fetch:<employee>` indicates no fetch of the latest version within
60 seconds. A subsequent fetch clears the current incident, but its historical
miss remains. Readiness/503 alone does not close availability on SrediMe. Keep
the existing remote outage-response requirement before production activation.

`POST /ops/availability/{employee}/refresh` requires `X-API-Key`, permits one
request per employee per minute and returns 202 for queued local work. The
singleton worker prioritizes the employee's full schedule scan and a booking
reread. This is not synchronous import, does not bypass limits, and can take
longer than a minute under load, failures or quota exhaustion. With live reads
disabled it remains queued. Keep `/ops` behind SSH/VPN; do not expose admin keys
in shell history or public requests.
