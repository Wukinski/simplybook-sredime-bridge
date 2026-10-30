# Predlog hostinga i deployment

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


## Current deployment review ? 2026-10-22

See [concrete pilot runbook](deploy/PILOT_RUNBOOK.md) for current prerequisites,
HTTPS configuration, secret permissions, monitoring, backup/restore and rollback.
Local Docker is available; no running containers or configured public host were
found. Compose configuration validates. Caddy hostname is still a placeholder;
TLS issuance and public callbacks have not been tested. Latest recorded tests:
373 Windows / 241 final-image Linux, both simulation smokes passed; see
[evidence](evidence/subminute-pipeline-validation.json). Earlier counts below
are historical. Test preparation/webhook configuration are already authorized;
the engineer can perform them once gates pass. Production activation is separate.

The consistently-under-60-second requirement remains unchanged. The earlier
five-minute/hourly operational compromise below is superseded and must not be
accepted as satisfying that requirement.

## Historical deployment proposal


**Nije deploy-ovano. Nema naručenog hostinga, DNS promena niti aktivnih javnih
webhookova.** Ovaj dokument i šabloni predstavljaju konkretan predlog za odobrenje.

## Predlog

Ako postoji pouzdan stalno uključen host salona, prvo proveriti njega. U suprotnom
predlažem jednu malu Linux VM u EU: najmanje 1 vCPU, 1–2 GB RAM, trajni šifrovani
disk, automatizovan šifrovan backup i HTTPS reverse proxy. API i jedan radnik dele
SQLite volume; nema Redis-a, posebne baze niti više replika. Početni predlog
budžeta za odobrenje je **do 10 EUR mesečno**, uz proveru konkretne ponude i
poreza/backup-a/domena pre kupovine. To je budžetski limit, ne potvrđena cena
dobavljača. Ponuda još nije odabrana.

Serverless instance bez trajnog diska, mrežni SQLite disk, OneDrive sinhronizacija
i više worker replika nisu odgovarajući deployment ovog rešenja. Lokalni projektni
state je samo za razvoj; produkcioni disk mora biti van OneDrive-a.

Očekivani operativni kompromis: rezervacije 5 min ili ranije po potpisanom SB
signalu, rasporedi/pauze/blokade na sat. Za šest zaposlenih satni ciklus drži
API budžet malim; promene smena koje moraju važiti odmah zahtevaju upis u oba
kalendara ili dodatnu potvrđenu mogućnost SB-a. Ovaj kompromis mora biti prihvaćen
pre produkcije. ICS uvoz dodatno kasni; ne predstavlja zaključavanje termina.

## Pripremljeni šabloni

- `deploy/Dockerfile`: Python 3.12, aplikacija kao korisnik 10001, bez ugrađenih tajni.
- `deploy/compose.yaml`: API + singleton radnik, trajni odvojeni volumes za DB i
  deljeni SimplyBook budžet, read-only filesystem, Compose secret fajl.
- `deploy/Caddyfile`: javni HTTPS samo za webhook/ICS/liveness; administratorski
  putevi preko SSH/VPN-a. Nema access loga koji bi sačuvao ICS tokene.
- `.dockerignore`: tajne, lokalni state, lokalna mapiranja i workbooks ne ulaze u image.

Compose montira tajnu kao fajl u `/run/secrets`; aplikacija podržava
`BRIDGE_ENV_FILE`. Pristup dobija samo servis kome je secret izričito dodeljen.
Host fajl i dalje mora biti zaštićen i disk šifrovan.
Izvor: [Docker Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/).
Izostavljena Caddy `log` direktiva sprečava uključivanje request access loga;
runtime/proxy greške i hosting sloj takođe moraju biti provereni na testu privatnosti.
Izvor: [Caddy log](https://caddyserver.com/docs/caddyfile/directives/log).

Docker Desktop 4.96.2, Docker CLI 29.9.2, Compose 5.6.1 i WSL 2.7.13 su
instalirani 2026-10-22. Posle ručnog restarta Windows-a Linux engine i hypervisor
rade. Image `andjelija-bridge:validation` je praktično izgrađen. Dokaz instalacije
i provere: `evidence/docker-installation-check.json`.

Compose konfiguracija prolazi `docker compose config --quiet --no-env-resolution`.
Za svih 37 zaključanih paketa uspešno su preuzeti Python 3.12 Linux x86_64
wheel-ovi; hash-evi su u `evidence/linux-dependency-check.json`. Ovo potvrđuje
dostupnost zavisnosti. Linux runtime je zatim proveren: 171 test povezivača i
HTTP smoke sa zasebnim radnikom prolaze kao UID 10001, uz read-only root,
privremene writable direktorijume, bez mrežnog izlaza, uz uklonjene capabilities
i `no-new-privileges`. Na Windows-u prolaze sva 303 testa. Image digest i
rezultati su u `evidence/container-followup-validation.json`.

Reprodukcija iz korena projekta (lokalna simulacija; bez tajni ili javnih portova):

```powershell
docker build -f booking_bridge/deploy/Dockerfile -t andjelija-bridge:validation .
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges --tmpfs '/tmp:mode=1777' --tmpfs '/state:uid=10001,gid=10001,mode=0700' -e BRIDGE_STATE=/state andjelija-bridge:validation python -m pytest booking_bridge/tests -q -p no:cacheprovider --basetemp=/tmp/pytest
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges --tmpfs '/tmp:mode=1777' --tmpfs '/state:uid=10001,gid=10001,mode=0700' -e BRIDGE_STATE=/state andjelija-bridge:validation python -m booking_bridge.tests.smoke_local
```

Smoke koristi sistemski privremeni prostor i bez `--report` ne piše u `/app`.
Po potrebi zadati `--report /tmp/smoke.json`; putanja mora biti upisiva servisnom
korisniku. Testirani image ne uključuje lokalne konfiguracije, tajne ili mapiranja.
Caddy još nije instaliran; Compose start sa produkcionim tajnama i izdavanje
javnog sertifikata nisu izvršeni. Nema javnog servisa niti aktivacije produkcije.

## Posle odobrenja hosta i pilota

1. `requirements.lock.txt` zaključava instalirane runtime/test pakete iz proverenog
   Python 3.12 okruženja; Dockerfile ga koristi. Proveriti build i testove u istom
   Linux image-u, pa sačuvati i odobren image digest za odabrani host.
2. Kreirati servisnog korisnika, šifrovan lokalni disk, backup destinaciju i
   privatni pristup. UID 10001 mora imati pristup samo svojim volumes/tajnama.
3. Bez tajni u command line argumentima ili image-u, lokalno napraviti
   `booking_bridge/secrets/production.env` (dozvole 0600, čitljivo servisnom UID-u).
   Uneti bridge tajne i `SIMPLYBOOK_REST_BASE_URL`, `SIMPLYBOOK_COMPANY_LOGIN`,
   `SIMPLYBOOK_ADMIN_LOGIN`, `SIMPLYBOOK_ADMIN_SECRET`. Ne koristiti `.env` ispise
   ili `docker inspect` izlaz kao dokaz uspeha.
4. Kopirati provereni `config.local.json` i `.local.csv` tabele. Za pilot odobriti
   samo test ID-eve; ne postavljati produkcione potvrde pre praktičnih provera.
   Prvo pokretanje sa praznim mapiranjem neće praviti upise.
5. Iz `booking_bridge/deploy` proveriti `docker compose config --quiet`, zatim
   `docker compose build`. Nakon odobrenja aktivacije: `docker compose up -d`.
   API sluša samo host loopback port 8000. Ne skalirati worker.
6. Zameniti primer hosta u Caddyfile-u, podesiti javni DNS sa ispravnim A/AAAA,
   standardni HTTPS port 443 i proslediti samo navedene putanje. Postaviti limite
   konekcija/HTTP timeout na odabranom hostu; aplikacija ograničava telo na 128 KiB.
7. Proveriti TLS, raw-body potpis kroz proxy i da nijedan access/error/analytics
   sloj ne zadržava privatnu ICS putanju ili payload. Ne koristiti javni tunnel
   za ceo localhost/admin API.
8. Proveriti heartbeat, fresh ICS i nezavisnu uptime proveru; povezati odobren
   operativni kanal upozorenja. Simulirati pad API-ja/radnika/feed-a i restore.
9. Vlasnica kreira test webhookove i import pretplate prema PILOT.md. Zapisati
   izmerenu latenciju i rezultate; tek zatim tražiti odobrenje produkcije.

## Povratak na prethodno stanje

Zadržati prethodni image/config i DB backup. Prvo zaustaviti novog radnika,
proveriti nejasne upise čitanjem, pa vratiti usklađeni image i isti DB. Vraćanje
stare kopije DB bez novijih linkova može izazvati duplikate; takav restore zahteva
ručnu rekonstrukciju/usklađivanje pre dozvole novih create operacija. Endpoint može
nastaviti da prima događaje dok je radnik zaustavljen. Produkcioni restore test
je obavezna provera pre otvaranja stvarnih upisa.
## Required availability deadline (2026-10-22)

The required end-to-end delay is consistently less than 60 seconds. The current
ICS transport cannot establish this, so the default
`require_subminute_availability: true` blocks production startup/preflight. Keep
simulation until a supported provider contract and tested adapter can satisfy
the requirement. See [AVAILABILITY_LATENCY.md](AVAILABILITY_LATENCY.md) and
[SREDIME_ACCESS_REQUIRED.md](SREDIME_ACCESS_REQUIRED.md). Earlier test counts below
are historical; the latest code passes 316 Windows and 184 Linux tests plus HTTP
smoke on both platforms. Evidence: `evidence/availability-validation.json`.
