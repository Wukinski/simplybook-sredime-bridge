# Concrete deployment and live-test prerequisites

## Aktuelni nastavak 27.10.2026.

Za novi lokalni publisher, server bez izvršavanja inbox-a i zaseban kontrolisani
executor koristiti [INTEGRATION_RUNBOOK.md](INTEGRATION_RUNBOOK.md). Korisnik
ne želi slanje podršci i sadašnji jezik prihvata za nastavak. Postojeći host,
kontakt, test zapisi i ranije završeni poslovi se ne traže i ne prave ponovo.

Slika `pilot-20261027-integration1` je postavljena i proverena: 382/382 testa
na Windowsu i Linuxu. Minimalni prenos zauzetosti, HMAC ključ, tri SimplyBook
pretplate i kontrolisani test naknadno su izričito odobreni i izvršeni.
Ne tražiti ista odobrenja ponovo. Rezervacija SrediMe `9VPLV6E` preneta je kao
SimplyBook `5`, pomerena na 15:00–15:30 i otkazana u oba sistema. Prvobitni
created callback nije isporučen; nedostajuća kopija napravljena je iz stvarnog
updated resync događaja uz provereno povezivanje opaque/native ID-eva.
[Konačni dokaz](../evidence/integration-20261027-booking-cycle.json).

Završni native readback potvrđuje callback6=false, employee11772 bookable=false,
sve dane off, service233160 inactive i sačuvane klijente. Server ostaje
simulation/reads off, administratorski pristup lokalno, publisher nije daemon.
Stalna automatska sinhronizacija i produkcija nisu uključene. Završeni ciklus
ne ponavljati; naredni rad vodi aktuelni [handoff](../../AI_HANDOFF.md).

## Istorijski preduslovi od 23.10.2026.

Sledeći tekst čuva raniju pripremu. Tvrdnje o nedostajućem hostu/kontaktu,
starom build-u ili neizvršenom pilotu više nisu aktuelno stanje.

Reviewed 2026-10-23. See ../../DECISION_CHECKLIST.md for current decisions. This is a prepared deployment, not an activated service.
The existing Compose and Caddy configurations are the deployment inputs.

## Infrastructure findings

Docker Desktop previously worked, but on 23 October the engine reported unable
to start after launch; current code Linux validation remains outstanding. The
workspace contains Compose/Caddy templates, but no Terraform inventory or
configured public host. Caddy still names `booking-bridge.example.invalid`.
No SSH config exists in this user's profile. This does not prove the owner has
no server elsewhere; a hostname, access route and DNS control are still needed.
No hosting connector was identified among available tools. The controlled test
contact file exists but its name, email and phone fields are all empty.

The smallest technical mapping now exists: SrediMe employee 11772/service 233160
to SimplyBook provider 9/service 496. The source employee remains nonbookable
with all days off and its service inactive. New IDs and inherited target service
links are recorded in the evidence cleanup plan; complete SimplyBook isolation
is waived for this pilot. No real source staff should be changed to test it.

## Deployment inputs and startup sequence

1. Select an existing always-on Linux host with persistent local storage outside
   OneDrive, SSH access and DNS control. Agree the operator, encrypted off-host
   backup destination and alert destination. New hosting costs require separate
   authorization. Use one API and exactly one worker sharing the same SQLite disk.
2. Copy the reviewed project release to `/opt/booking-bridge`. Preserve the source
   directory layout used by `compose.yaml`. Build and record the actual image ID;
   a local Docker image ID is not necessarily a registry pull digest. Keep the
   previous release/image for rollback. Existing validated image ID is recorded
   in `../evidence/subminute-pipeline-validation.json` relative to this runbook.
3. The dedicated private pilot inputs are `state/controlled-pilot-config.json`
   and `secrets/pilot.env`. Stage those as the template's `config.local.json`
   and `secrets/production.env` only in the separate host checkout, or review
   equivalent Compose bind-mount overrides. Never overwrite the default local
   runtime to activate it accidentally. Use Linux owner UID 10001, mode 0600,
   parent directory 0700;
   grant the deployment operator/root only the needed access. Compose file-backed
   secrets are bind mounts, not an encrypted secret store. Verify readability as
   UID 10001 without printing contents. Keep private feeds and browser sessions
   out of build contexts, logs, command arguments and evidence.
4. Prepare config and mappings read-only. Begin in simulation with reads disabled.
   The prepared pilot profile has `require_subminute_availability=false`: the
   target is measured rather than a pilot gate. Pilot preflight requires
   `pilot_scope_reviewed`, explicit test IDs, reviewed semantics and controlled contacts;
   it must not turn on production or copy production approval flags.
5. From `booking_bridge/deploy`, run `docker compose config --quiet
   --no-env-resolution`, build the reviewed release, and start the simulation API
   and worker only on the approved host. Port 8000 is bound to host loopback.
   Restart policy stops after five failures: monitoring must detect exhausted
   restart attempts and a dead worker, not only a live API.
6. Replace only the placeholder Caddy hostname with the selected public name.
   Validate with `caddy validate --config Caddyfile --adapter caddyfile` before
   reload. Point A/AAAA records to reachable addresses; provision 80/443 for TLS.
   Preserve raw webhook bodies, use direct URLs (no redirects), and keep `/ops`
   and readiness accessible only by SSH/VPN. Public routes are only the two
   webhooks, private ICS paths and `/health/live`. No access logging is enabled;
   verify host/proxy error logs also do not retain tokens or payloads.
7. Verify public TLS/liveness and denial of `/ops` before configuring providers.
   Use private monitoring for `/health/ready`, worker heartbeat, unresolved issues,
   queue age, quota exhaustion and availability history. Poll these local endpoints
   every 10 seconds; independent external liveness can run every 30 seconds. These
   intervals are proposed operational settings, not a remote availability guarantee.
   Send a synthetic alert only once an actual destination is authorized/configured.
8. Once controlled source scope, mappings and contacts pass their gates, the engineer can use
   the already-authorized callback configuration: inspect existing subscriptions,
   configure only the scoped pilot, verify signing secrets and send the Buker Test.
   SimplyBook permits five active subscriptions per event and creating a sixth
   deactivates the oldest: inspect before adding. No blanket salon-wide processing.
   A signed 202 proves durable acceptance only.

## Backup and restore drill

Use the existing online backup command, never copy an active SQLite file alone.
On the approved host, from the deployment directory:

```sh
docker compose exec -T worker python -m booking_bridge backup --destination /state/bridge-backup.sqlite
```

Export that completed file to a protected directory, encrypt it and transfer it
off-host. Also retain the matching image/config/mappings and protected secrets;
retain shared provider transport-budget state so restart/restore cannot reset
quotas. A bridge DB backup alone does not include that separate volume. Schedule
hourly backups for pilot, then agree production retention and recovery objectives
before activation. Verify each backup with SQLite `PRAGMA integrity_check` on an
isolated copy. Never log its rows or copy it into public evidence.

Restore rehearsal: with network disabled and a fresh temporary volume, restore a
synthetic backup, run integrity check, and verify queue, links/tombstones, intents,
refresh generations, rate counters and observations survive. Do not attach the
restored copy to live providers. For a real restore, stop both API and worker
before swapping storage; reconcile deliveries missed during downtime and all
remote changes after the backup before enabling writes. Uncertain writes remain
blocked. An old DB can forget a completed remote create and cause duplicates.

## Rollback and live measurement

Stop the worker first; keep the API accepting durably when the DB is intact.
Reconcile uncertain remote results by reads, then use the previous compatible
image/config with the current DB. Do not erase the DB or feed history. A DB restore
uses the stricter procedure above. Do not remove imported blocks or publish an
empty calendar as rollback. Provider-side closing/reopening behavior remains a
separate unsolved dependency; our readiness failure does not close remote slots.

For each isolated trial record UTC source commit, webhook receipt, bridge apply,
feed version readiness, refresh acceptance, remote import completion/version and
customer-visible availability. Missing completion evidence is unknown; every
delay >=60 seconds misses the optimization target and is recorded for analysis. Include last-block removal, reassignment, schedules,
manual blocks, retries, burst/quota failure and recovery in both directions.
No test pass or pilot approval activates production.

References: [Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/),
[Caddy proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy),
[SimplyBook subscriptions](https://help.simplybook.me/wiki/REST_API_webhooks),
[mapping review](../PILOT_MAPPING_REVIEW.md), [provider questions](../PROVIDER_SUPPORT_REQUESTS.md).
