# Operacije, pristupi i struktura koda

## Najnovije operativno stanje — 28.10.2026

Aktivacija produkcije i potreban administrativni transfer worker-u sada su
odobreni, ali **nisu izvršeni**. Ne tražiti ponovo ta opšta odobrenja. Novi
preduslov je rezidentni Qwen3.5 4B za prijavu bugova/dvostrukih termina vlasniku
email-om; model nema pravo popravki, booking upisa ili upravljanja servisima.

Deployment je na zasebnoj putanji `/opt/booking-bridge-diagnostics`.

[Stvarna završna provera modela](../evidence/diagnostics-20261028-model-eval-final.json)
ima **7/7 PASS za 817.221 s, bez novog OOM-a**, na V3 slici
`sha256:1ad9a4fa512e969cb193f50dab25e6f4ff2a1588b605554cc6544c64be250608`.
Isti sintetički scenariji i očekivanja zadržani su; model ima 8 GiB,
num_batch=64, kontekst 4096 i jedan paralelni zahtev.

V4 runtime slika je `sha256:7b11e4fbc5c7335e763677909243553f38f050ead7101271aec723c06c7210b9`.
[Offline dokaz ekvivalencije](../evidence/diagnostics-20261028-v3-v4-protocol-equivalence.json)
potvrđuje byte-identičan SYSTEM, schema i svih sedam request body-ja, uz ponovnu
validaciju svih stvarnih V3 odgovora. **Sedam stvarnih modelskih poziva nije
ponovljeno na V4.** V4 dodaje proveru da završen AI kandidat pripada sadašnjem
validnom opažaju i ograničenja čekanja; ne menja testirani modelski protokol.

[Analyzer je pokrenut](../evidence/diagnostics-20261028-python-rollout.json), samo nad
postojećom pilot bazom: kontejner od 17:21:37 UTC, prvi heartbeat 17:21:52 UTC.
[Runtime pregled u 17:25:14 UTC](../evidence/diagnostics-20261028-runtime-status.json)
potvrđuje **prvi uspešan live AI pregled**, bez restarta ili novog OOM-a.
Početni dnevni sedmočlani self-test započet je u 17:24:53 UTC i još je pending.
Keeper/collector ostaju healthy na slici 07e13d, Qwen i pilot procesi nepromenjeni.
Analyzer je running, ali `healthy=false`, `email_configured=false` i
`smtp_not_configured`; outbox ima jednu pending poruku i **0 SMTP pokušaja**.
Model/analyzer nemaju bridge bazu, booking/SSH tajne ili pravo popravke.
Nema booking upisa, prenosa REST administratorskih pristupa, SMTP autentikacije,
poslatih dijagnostičkih email-ova ili inbox dokaza.

SMTP password ostaje [prazan uz privatni ACL](../evidence/diagnostics-20261028-smtp-private-acl.json).
[Završni pregled pripreme](../evidence/diagnostics-20261028-preparation.json) razlikuje
izvedenu dijagnostiku od produkcionih preduslova koji još nedostaju.

V4 softverska validacija: [Windows 756 PASS](../evidence/diagnostics-20261028-windows-tests.xml),
[Linux 746 PASS + 10 skip](../evidence/diagnostics-20261028-linux-tests.xml)
i [HTTP smoke PASS](../evidence/diagnostics-20261028-linux-smoke.json).
To su odvojeni dokazi od stvarne V3 modelske provere.

Raniji OOM/semantički rezultati ostaju istorija u
[glavnoj primopredaji](../../AI_HANDOFF.md). Healthy collector ne čini zastareli
booking/buffer keš svežim. [Runbook](../deploy/DIAGNOSTICS_RUNBOOK.md).

Produkcioni gate i dalje blokira dokaze starije od sedam dana i zahteva
`soak_72h`. Predlog izmene automatski je odbijen i čeka posebno korisničko
odobrenje; nije primenjen. [Aktuelna politika](../PRODUCTION_READINESS.md).

[Izolovani reconciliation stage](../evidence/activation-staging-20261028-2eb16604-reconciliation.json)
usaglasio je istorijski raw/projected provenance završenog testa uz očuvanje
originalnog host prijema/head-ova/hash-eva, ownership-a, završene namere i kvota.
Stage ostaje pod hold-om; aktivne baze nisu promenjene, worker start je blokiran.
Ne vraćati isti istorijski konflikt kao novu nerešenu prepreku i ne ponavljati
završeni booking ciklus. Stvarna poslovna mapiranja/resursi/trajanja ostaju
nedokazani; ne izjednačavati opšte odobrenje sa potvrđenim identitetom.

[Šifrovani off-host backup i izolovani restore](../evidence/offhost-restore-drill-20261028-6e619251.json)
stvarno su završeni sa 14/14 provera. Ciphertext je van VPS-a, privremeni server
ključ je obrisan, svi redovi/hash-evi i priloženi budžeti očuvani, restore pod
hold-om. Privatni paket/restore su u `state/offhost-restore-drill-20261028-6e61925100ec4bbd956d9e67c8708724/`,
a ključ u zasebnom privatnom `secrets/offhost-drill-20261028-6e61925100ec4bbd956d9e67c8708724/backup-key.bin`.
Ne kopirati ključ u javne dokaze ili zajedno sa arhivom u release. Unattended
off-host raspored, trajno skladište i key custody ostaju operativni posao.

Odeljci ispod čuvaju istorijski booking presek; najnoviji dijagnostički status je iznad.

[Aktuelni TLS dokaz](../evidence/diagnostics-20261028-tls.json): IP/DNS validni,
160h short-lived cert sa oko 122h preostalog veka, timer active/enabled i
certificate_not_yet_due/exit 0. Obnova još nije dospela. Deployment monitor
koristi `--tls-min-days 2`; ne forsirati obnovu zbog generičkog default-a 7.

Konačni presek **27.10.2026,14:45 UTC**: kontrolisani ciklus i zatvaranje testa
potvrđeni su. [Primopredaja](../../AI_HANDOFF.md),
[ciklus](../evidence/integration-20261027-booking-cycle.json),
[završni source](../evidence/integration-20261027-source-final.json),
[završni host](../evidence/integration-20261027-live-final-after-cleanup.json).

## Postavljen VPS i stanje testa

VPS **169.58.118.33**, DNS **vmi3688215.contaboserver.net**,
IPv6 **2a02:c207:2368:8215::1**, deploy `/opt/booking-bridge-pilot`.
Slika `andjelija-bridge:pilot-20261027-integration1`, image ID
`sha256:8a8440d7e6ab72d6a388deb5bf2594e5ae174bfd166075d939d81c8d08987cc0`.

API i worker rade kao UID 10001, read-only root, bez capabilities,
no-new-privileges, postojeći trajni volumeni. Worker je
`python -m booking_bridge.pilot_receiver`; **simulation/reads off**, ne izvršava
booking upise. API je na 127.0.0.1:8000. Host env 0600/owner 10001 ima oba signing
ključa, **nema SimplyBook administratorskih akreditiva**. Compose nema stari
nedovršeni snapshot profil ili potrebu za snapshot.env.

Source **9VPLV6E** i target **5** su otkazani; sva tri local/host eventa done,
local unresolved 0, owned link canceled. **Nema aktivne callback lease**:
callback 6 zatvoren 14:44:10.807 UTC i nezavisno potvrđen false14:45:13.702 UTC.
Employee 11772 bookable=false/svih sedam dana off; service 233160 inactive.
Source 873710 i postojeći target klijent 1 ostaju. **Ne ponavljati ciklus.**

SB pretplate 1/2/3 ostaju aktivne. Host 14:45:42 UTC ima liveness/readiness200,
0 incidenata,3 done+1 stariignored,hostlinks/intents 0. Potpisani SB receipt count 3,
event_type=null; ne izvoditi bookingID/tip iz tog minimalnog receipt-a.

Finite publisher prenosi 15 minimalnih occupancy blokova sa izvornim vremenima,
bez kontakata/kredencijala; owned booking 5 nije dodat kao povratni blok. Nije
daemon/24x7; readiness može ponovo dati503 kada keš zastari.

## Lokalno okruženje i privatni ulazi

Produkcioni nastavak 28.10.2026 bira postojeći VPS i rad bez ovog računara.
[Pregled](../PRODUCTION_READINESS.md) i [server/monitor](../deploy/PRODUCTION_PREPARATION.md)
opisuju dormant Compose, split secrets i hard gate. Novi alati su
`production_readiness`, `server_worker`, `state_review`, `recovery` i
`production_monitor`. Privatni snapshot-i su u ignorisanim
`state/production-preparation-20261028-*`, a source archive/manifest i privatni
Linux validation metadata u `state/production-validation-20261028`.
Ne kopirati te snapshot-e u image/javne dokaze. Restore ne skida hold automatski.

Lokalni nastavak **28.10.2026**: novi `pilot_supervisor` i
`deploy/prepare_publisher_task.ps1` pripremaju nadzirano lokalno osvežavanje.
`deploy/publisher-task.local.xml` postoji sa isključenim task-om i trigger-om;
nije registrovan. Nema pokrenutog supervisor-a ili novog deploy-a.
`--check --state PATH` čita samo `PATH/publisher-status.json`; status nastaje
tek eksplicitnim pokretanjem/resetom, pa trenutno nije dokaz rada servisa.
[Detalji, budžet i oporavak](../deploy/PERSISTENT_PUBLISHER.md).
Novi format mapiranja je u [mappings/README.md](../mappings/README.md), bez
promene stvarnih lokalnih profila. Live stanje iznad ostaje istorijski readback.

Windows/PowerShell; koren
`C:\Users\aaaaz\OneDrive\Documents\andjelijasg\simplybook-API`.
Python `.venv\Scripts\python.exe`, Chrome Playwright, Postman CLI instaliran.
Git nije na PATH-u. Udaljeni Docker radi; lokalni Docker ranije nije startovao.

Putanje ispod relativne su na booking_bridge i privatne:

| Putanja | Namena |
|---|---|
| secrets/pilot-contact.json | Odobreni kontakt; ne ispisivati |
| secrets/pilot.env | Signing/feed/bridge admin tajne |
| secrets/vps_pilot_ed25519, vps_known_hosts | Namenski SSH ključ i pinned host |
| state/sredime-session.json | Native browser sesija |
| state/controlled-pilot-config.json | Capture simulation/reads off profil |
| state/controlled-pilot/bridge.sqlite | Trajne lokalne kvote/snimci/linkovi/namere |
| state/integration-20261027/pilot-execution-config.json | Zaseban pilot profil,31/31 preflight |
| state/integration-20261027/native-source-trial-private.json | Potvrđeni create/resync/move/cancel i tačni ID-evi |
| state/integration-20261027/verified-source-identity-binding-private.json | Stvarno korišćen binding samo za 9VPLV6E |
| state/integration-20261027/target-readback-resync.json | Stvarni REST create readback target 5 |
| state/integration-20261027/target-readback-move.json | Stvarni move readback |
| state/integration-20261027/target-readback-cancel.json | Stvarni canceled readback |
| state/integration-20261027/COLLECTOR_REVIEW_PRIVATE.md | Collector/ACK ugovor |
| state/native_source_trial.py | Ograničeni native operator;36 offline testova |
| state/pilot_event_operator.py | Collector/ACK sa per-booking aliasima;114 offline testova |
| state/read_executed_target.py | Stvarni REST readback posle local done |
| state/read_pilot_live_state.py | Bezbedni host metapodaci/HTTP zdravlje |
| state/pilot-source-integration-private.json | Privatni import/export/refresh URL-ovi |
| state/language-audit-20261027/ | Jezički backup/readback-i |

REST akreditivi ostaju u lokalnim service_importer/.env i provider_assignment/.env.
Root VPS lozinka nije sačuvana u projektu. HTML/SQLite/storage state/URL mogu
sadržati lične podatke/tajne. Release izuzima state,secrets,.env*,config.local.json
i*.local.*. Ne kopirati ih u javne dokaze ili argumente procesa.

## Bezbedna čitanja i održavanje

```powershell
ssh -i booking_bridge/secrets/vps_pilot_ed25519 -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=booking_bridge/secrets/vps_known_hosts -o BatchMode=yes root@169.58.118.33 "docker ps --format '{{.Names}} {{.Status}}'"
.\.venv\Scripts\python.exe booking_bridge/state/read_pilot_live_state.py --phase operator-readback
```

Ne ispisivati docker env, pilot.env, sirove payload-e, razrešene tajne ili ICS
tokene. Udaljene skripte slati kao bytes, bez Windows text-mode CRLF konverzije.

nginx fajl je /etc/nginx/sites-available/booking-bridge-pilot; IPv4/IPv6, IP+DNS.
Izloženi su webhook-i,ICS,liveness; ops/readiness privatni. Access log off,
error critical. Sertifikat /etc/letsencrypt/live/booking-bridge-ip/ poslednje
proveren ističe 02.11.2026,14:34:01 UTC; `booking-bridge-certbot.timer` radi dvaput
dnevno sa reload. Read-only provera 28.10. potvrđuje active/enabled i poslednji
service success/exit 0, uz validan javni TLS chain/hostname.
booking-bridge-pilot-check.timer radi minutno, backup.timer satno. Kopije su
privatne na istom serveru i nešifrovane; nova jednokratna šifrovana kopija van
VPS-a i restore imaju 14/14 provera. Trajni off-host raspored i nezavisan spoljni
alarm još nisu konfigurisan posao; SMTP primalac je već izabran, tajna nedostaje.

Za pauzu docker compose stop worker ili docker compose stop. Nikad down-v,
brisanje baze ili prazan ICS. Restore stare baze zahteva usklađivanje kasnijih
udaljenih upisa; stara slika nema receiver pa worker ne vraćati naslepo.

## Pouke iz završenog testa

Originalni created otkazan je pre dispatch-a. Isti booking resync uspeo je kada
je callback ostao aktivan kroz prijem/obradu/ACK. Konačno gašenje je potvrđeno.
Novi native Test nije bio izvršen; nema potrebe ponavljati tu dijagnostiku.

Webhook IDs39VLN1/V2N8N4/7E9514 su stringovi. Privatni binding na native
11772/233160/873710 ima dokaz samo za 9VPLV6E i čuva raw hash/IDs/type.
Za širi profil koristiti stvarne opaque ključeve ili pregledano eksplicitno
mapiranje, uz zasebne native UI ID-eve; ne izmišljati globalno dekodiranje.

Native create/edit imaju različita array/scalar polja; status -101 automatski
submit-uje Salon otkazao, -2 je brisanje. Calendar/json vraća sve zaposlene:
odmah filtrirati 11772 i odbaciti ostale bez čuvanja. Source refresh zahteva
trajnu kvotu store.rate('sredime-post:11772',60); fetch nije native import.

Runtime 382/382 Windows i 382/382 Linux provere ostaju važeće za postavljenu sliku;
privatni alati nisu deploy. Stare audit skripte imaju hardkodirana zastarela
permission stanja; ne prepisivati njima konačne dokaze.

[Runbook](../deploy/INTEGRATION_RUNBOOK.md) je referenca izvedenog toka.
[Arhiva](archive/20261027-before-trial-reconciliation.md) čuva stare operativne opise.
