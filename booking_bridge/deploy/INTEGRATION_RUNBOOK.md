# Kontrolisani pilot — završen ciklus i operativna referenca

Konačni presek **27.10.2026,14:45 UTC**. Odobreni ciklus je završen:
source **9VPLV6E** → target **5**, create iz stvarnog updated resync-a,
move14:00→15:00, cancel oba sistema i sva tri host ACK-a.
**Ovo uputstvo nije nalog za ponavljanje završenih upisa.**

[Potpun ciklus](../evidence/integration-20261027-booking-cycle.json) potvrđuje
controlled_cycle_verified=true i cleanup_verified_by_independent_native_readback=true.
[Završni source](../evidence/integration-20261027-source-final.json):
status-101, zapis sačuvan, callback 6false, employee 11772bookablefalse/svi dani off,
service 233160 inactive; klijenti873710 i1 ostaju. Callback zatvoren 14:44:10.807 UTC,
nezavisni GET 14:45:13.702 UTC. [Završni host](../evidence/integration-20261027-live-final-after-cleanup.json)
ima liveness/readiness200,0 incidenata,3 done+1 stariignored,hostlinks/intents 0.

## Odobrenje, runtime i granice

„Uradi to” odobrio je minimalnu zauzetost i SB HMAC na postojećem VPS-u.
„Potvrdjujem onda sve” odobrio je pretplate 1/2/3, sopstveni source kontakt i
jedan ciklus oba sistema sa porukama samo korisniku. Sve je izvedeno;
iste dozvole ne tražiti ponovo. Podršci ne slati, prevodi prihvaćeni za sada.
**Produkcija i administratorski pristupi na VPS-u nisu odobreni.**

Slika `andjelija-bridge:pilot-20261027-integration1`, image ID
`sha256:8a8440d7e6ab72d6a388deb5bf2594e5ae174bfd166075d939d81c8d08987cc0`.
API+pilot_receiver su simulation/reads off, bez administratorskih akreditiva.
[Compose](compose.pilot.yaml) nema stari snapshot profil.
[Rollout](../evidence/integration-20261027-rollout.json),
[Windows](../evidence/integration-20261027-windows-tests.xml) /
[Linux](../evidence/integration-20261027-linux-tests.xml): **382/382** na obe
platforme i HTTP smoke. Privatni collector/ACK114, native operator36 offline
testova; privatne izmene nisu promenile deploy sliku.

| Uloga | Šta radi | Šta ne dokazuje |
|---|---|---|
| Lokalni snapshot/publisher | REST snimak, minimalni atomski paket preko pinned SSH | Sam native import ili 24/7 |
| VPS receiver | Trajni provereni prijem i nadzor | Booking upis ili pozadinsko čitanje naloga |
| Privatni collector | Jedan stvarni host event, potvrđen scope/binding | Opšti resolver identiteta |
| Lokalni pilot_execute | Jedan stvarni pregledani pilot upis | Automatsku obradu celog reda |
| REST readback i host ACK | Tačan target rezultat i done samo tog eventa | Inbox dostavu korisniku |

## Finite publisher — i dalje odobreno isti obuhvat

```powershell
.\.venv\Scripts\python.exe -m booking_bridge.pilot_publish --read-only --config booking_bridge/state/controlled-pilot-config.json --state booking_bridge/state/controlled-pilot --env-file booking_bridge/secrets/pilot.env --cycles 1
```

To je jedan svež read-only capture i minimalni transfer na isti VPS, bez
booking promene. Nije daemon; računar mora biti uključen. Paket ima 15 blokova,
izvorna vremena i minimalni raspored, bez kontakata/client_id/beleški/tajni.
Identičan stari paket ne podmlađuje keš; greška ne objavljuje delimično stanje.
Lokalno posedovani target 5 nije povratno izvezen kao dodatni occupancy blok.

Capture profil ostaje simulation/reads off. Zasebni execution profil je
state/integration-20261027/pilot-execution-config.json, pilot/reads on,
31/31 preflight, samo 11772/233160/873710→9/496/1. REST pristupi ostaju lokalno
u service_importer/.env i provider_assignment/.env. Privatni state/secrets
ne ulaze u release.

Native uvoz **12/12 budućih intervala** već je dokazan;3od 15 bila su prošla.
[Dokaz](../evidence/integration-20261027-source-import.json). Po isteku svežine
readiness/feed mogu dati503; to ne uklanja automatski već uvezene source blokade.
Eventualni podržani source refresh ima trajnu kvotu pre POST-a; acceptance/fetch
nisu završetak native uvoza.

## Referenca već izvedenih faza — ne pokretati ponovo

Originalni created bio je cancelled/attempts 0/HTTP —. Podržani save iste source
rezervacije/termina uz internu belešku stvorio je pravi booking.updated resync.
Nije izmišljen payload niti ponovljen source create.

| Faza | Event | Stvarni target 5 readback |
|---|---|---|
| resync | ce3fa625c5a6e6bf73f2f3dfd01c1026 |14:35:03.570 UTC,28.10.14:00–14:30 confirmed |
| move |6f4151881513c9fb71c1028931ca19dd |14:39:05.584 UTC,15:00–15:30 confirmed |
| cancel |ac284a7be11ee144ca7937e486f1f439 |14:43:07.866 UTC,canceled/is_confirmed=false |

Sva tri eventa su local done/attempts 1, host done sa razlogom
applied_by_local_pilot_executor, unresolved 0 i owned link canceled.
Tok je bio native potvrda → collector → pilot_execute → REST readback → ACK,
tek zatim sledeća native faza. Nije bilo batch kopiranja ili automatskog retry-a.

Webhook opaque IDs 39VLN1/V2N8N4/7E9514 dokazano pripadaju native
11772/233160/873710 na istoj rezervaciji; raw hash/IDs/type/eventID sačuvani su.
Korišćen je izričiti --binding
booking_bridge/state/integration-20261027/verified-source-identity-binding-private.json.
Ovo važi samo za taj booking. Runtime već prihvata string IDs; budući profil
treba opaque ključeve ili pregledano mapiranje, uz odvojene native UI brojeve.

Sledeće su **šabloni istorijski korišćenih komandi**, ne sledeći zadatak.
Placeholder-i zahtevaju novi konkretno pregledani događaj ako buduća izmena
opravda novi test; ne popunjavati ih završene faze radi ponovnog izvršenja.

```powershell
$env:BRIDGE_ENV_FILE = 'booking_bridge/secrets/pilot.env'
$env:PYTHONPATH = '.'
$pilotConfig = 'booking_bridge/state/integration-20261027/pilot-execution-config.json'
$pilotState = 'booking_bridge/state/controlled-pilot'
$pilotBinding = 'booking_bridge/state/integration-20261027/verified-source-identity-binding-private.json'
# Reference only: BOOKING_ID, EVENT_ID, PHASE and RECEIPT are reviewed inputs.
.\.venv\Scripts\python.exe booking_bridge/state/collect_source_pilot_event.py --config $pilotConfig --state $pilotState --booking-id BOOKING_ID --event-id EVENT_ID --step PHASE --binding $pilotBinding
.\.venv\Scripts\python.exe -m booking_bridge.pilot_execute --execute --config $pilotConfig --state $pilotState --event-id EVENT_ID
.\.venv\Scripts\python.exe booking_bridge/state/read_executed_target.py --config $pilotConfig --state $pilotState --booking-id BOOKING_ID --event-id EVENT_ID --step PHASE
.\.venv\Scripts\python.exe booking_bridge/state/ack_source_pilot_event.py --config $pilotConfig --state $pilotState --booking-id BOOKING_ID --event-id EVENT_ID --step PHASE --binding $pilotBinding --readback RECEIPT --execute
```

Collector je tražio queued/attempts 0, current head,native journal/binding/interval;
host pre SSH-a uklanja kontakte/nazive/slobodni tekst. Poverenje je postojeći
HMAC-proveren ingress i pinned SSH, ne ponovna originalna HMAC provera.
Readback mora doći iz stvarnog REST GET-a posle local done, biti svež do 300 s i
odgovarati targetu9/496/1. ACK proverava hash/scope/prior phases i menja samo
tačan host event; ne pravi host linkove/fiktivne targete. Neizvesan upis prvo
zahteva readback; nikada slepi retry ili globalni worker.

Callback je držan aktivnim kroz prijem/obradu/ACK, sa vlasnikom i bounded lease,
pa zatvoren i nezavisno očitan. Native cancel je -101, ne delete-2.
Sada nema aktivne lease niti naredne native faze.

## Dokazi, preostalo i rollback

Potpisani SB receipt count 3 dokazuje HMAC-proveren prijem. Event_type=null i
nema bookingID: stvarne izmene5 dokazuju REST readback-i. Inbox dostava nepoznata.
Signed source created→receipt 4.756/26.981/55.155 s nisu E2E. Raniji import
fetch 38.063 s/native observation 67.911 s nisu actual commit ili booking E2E.

Sledeći posao je pregledan trajni/nadzirani rad i pravilni opaque profili,
bez tihog uključivanja produkcije/admin transfera.
[Naredni koraci](../handoff/NEXT_STEPS.md). Ne ponavljati završen ciklus bez nove
izmene/proverljivog razloga. Postojeći klijent 1 i korisni test zapisi ostaju.

Za pauzu docker compose stop worker ili stop; nikad down-v, brisanje baze ili
prazan ICS. Stara slika nema receiver; rollback zahteva proveru komande/profila
i usklađivanje kasnijih upisa. Dnevnici/kvote/baze ne brišu se.

[Arhivirani runbook](../handoff/archive/20261027-before-trial-reconciliation.md)
je istorija; njegovi stari pending/draft/permission opisi nisu aktuelni.
