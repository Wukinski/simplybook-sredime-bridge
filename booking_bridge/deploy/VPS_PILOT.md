# Current VPS pilot - 23 October 2026

## Dopuna 27.10.2026: ograničena integracija, bez produkcije

Aktuelno praktično uputstvo je [INTEGRATION_RUNBOOK.md](INTEGRATION_RUNBOOK.md).
API i worker su postavljeni sa slikom `andjelija-bridge:pilot-20261027-integration1`,
ID `sha256:8a8440d7e6ab72d6a388deb5bf2594e5ae174bfd166075d939d81c8d08987cc0`.
Worker sada pokreće `booking_bridge.pilot_receiver`: nadzire keš i čuva inbox,
bez obrade događaja i bez pozivanja naloga. Režim ostaje `simulation`, reads off.

Korisnik je naknadno izričito odobrio minimalni prenos zauzetosti, HMAC ključ,
tri SimplyBook pretplate i kontrolisani booking ciklus; sve je izvršeno.
`pilot_publish` prenosi 15 blokova bez kontakata/admin akreditiva; native uvoz
12/12 tada budućih intervala već je potvrđen. Pretplate 1/2/3 su aktivne.
Lokalni `pilot_execute` obradio je tri stvarna događaja za source `9VPLV6E`:
resync je napravio target `5`, zatim su pomeranje i otkazivanje potvrđeni REST-om.
Sva tri host ACK-a su završena; source je -101, target canceled, klijenti ostaju.
[Konačni ciklus](../evidence/integration-20261027-booking-cycle.json).

Callback6 je vraćen na false, employee11772 ostao nonbookable/svi dani off,
service233160 inactive. U završnoj proveri 14:45:42 UTC live/ready su 200,
nema otvorenih incidenata, host ima tri done događaja, jedan stari ignored,
bez links/intents. Administratorski pristup ostaje lokalno. Nije uključena
stalna automatska sinhronizacija; publisher je ograničen i snapshot ponovo ističe.

Priloženi novi [Linux XML](../evidence/integration-20261027-linux-tests.xml) i
[Linux smoke](../evidence/integration-20261027-linux-smoke.json) pripadaju novom
checkpoint-u. Aktuelni javni hostname je `vmi3688215.contaboserver.net`.

## Istorijska postavka od 23.10.2026.

Tekst ispod čuva raniji checkpoint; njegove verzije, sertifikat, IP URL i
tvrdnje o neizvršenim prenosima/testovima ne zamenjuju aktuelni runbook.

Public liveness: https://169.58.118.33/health/live . This is a test application,
not production booking synchronization. The owner supplied this existing VPS;
no hosting/domain purchase was made. Root password was used interactively for
initial access only and was not saved to project files or command arguments.

## Actual deployment

- Ubuntu 24.04.5 LTS; existing `/opt` and `/srv` had no applications, no prior
  web server or Docker installation was found, and ports 80/443 were free.
- Installed Docker Engine 29.9.2 / Compose 5.6.1 from Docker's official repository,
  Ubuntu nginx/python3-venv, and Certbot 5.8.0 in a separate certificate-only venv.
  No OS upgrade/reboot or global SSH-authentication change was performed.
- Added a dedicated pilot SSH public key to root's existing authorized keys,
  preserving them. Private key and pinned host key remain under ignored local
  `booking_bridge/secrets/`; never include those in releases/evidence.
- Root-private deployment directory: `/opt/booking-bridge-pilot`. Source release:
  `releases/20261023-pilot1`. Uploaded archive excluded private state, secrets,
  `.env`, local mappings, workbooks and customer data. Uploaded only the dedicated
  simulation config and pilot env separately; the env file is mode 0600 and owned
  by container UID 10001. Original development credentials were not copied.
- Image: `andjelija-bridge:pilot-20261023`, actual image ID
  `sha256:c03d960d9a2b0c86640d6d74ee668f5c7f9380644662a7e7c242eafc6dcba566`.
  Runtime source hashes match the workspace checkpoint.
- [Compose](compose.pilot.yaml) runs one API and one worker with read-only root,
  no added capabilities and no-new-privileges, as UID 10001. State and provider
  transport state use named persistent volumes. API publishes only host loopback
  `127.0.0.1:8000`; nginx exposes the four approved route families.
- Mode remains **simulation**, background account reads disabled. Production is
  disabled. No real booking/client writes, test contacts or real provider signing
  secrets were supplied to the hosted worker. No SrediMe import URL was changed.

## HTTPS and operations

The actual proxy is [nginx-ip.conf](nginx-ip.conf), replacing the example IP with
the owner-supplied address. The earlier Caddy template remains an alternative.
Access logs are off; proxy errors are restricted to critical severity. Public
admin/readiness paths and invalid private feed tokens return 404; unsigned
webhooks return 401. Liveness returns 200 from an external client using normal
certificate verification.

Let's Encrypt supports public IP certificates with its shortlived profile.
Certbot >=5.4 supports webroot issuance for these certificates. Both staging and
trusted issuance succeeded; the current trusted certificate expires
2026-10-30 03:16:29 UTC. References:
[Let's Encrypt instructions](https://letsencrypt.org/2026/03/11/shorter-certs-certbot),
[Certbot renewal guide](https://eff-certbot.readthedocs.io/en/stable/using.html#automated-renewals).

`booking-bridge-certbot.timer` checks twice daily, with a deploy hook to reload
nginx after actual renewal. A renewal dry run passed. For interactive verification
use `--no-random-sleep-on-renew`; otherwise Certbot may sleep several minutes
before starting, which can exceed a remote command timeout.

[pilot_host_maintenance.py](pilot_host_maintenance.py) is installed under the
deployment directory. The `check` timer runs every minute against private
readiness using the key read from the protected env file; it never prints the key.
Failures are recorded in systemd; no external alert recipient is configured.
The `backup` timer makes an hourly SQLite online backup and verifies integrity.
The first copy passed. These copies are root-private **on-server, unencrypted**
recovery copies, not off-host disaster backups. A separate protected destination,
retention and restore acceptance are still needed before real use.

## Validation and pending callback work

249 Linux tests and the isolated Linux HTTP smoke passed on this image with
network disabled, read-only root and non-root execution. These supersede the
previous inability to run current code on the local Windows Docker engine.
See [deployment evidence](../evidence/vps-pilot-deployment-validation.json),
[Linux tests](../evidence/vps-pilot-linux-tests.xml) and
[Linux smoke](../evidence/vps-pilot-linux-smoke.json).

An inactive SrediMe webhook creation was attempted once through Buker. Subsequent
list reads did not show the requested name. The outcome is not proven; do not
retry create automatically or claim the callback is registered. Private journal:
`state/vps-source-webhook-provisioning.json`. Reconcile that outcome and obtain
the actual provider signing secret before sending the source Test. No actual
source Test receipt, refresh/import or end-to-end availability timing is claimed.

## Pause and rollback

From `/opt/booking-bridge-pilot`, use `docker compose stop worker` to stop
processing while retaining API intake, or `docker compose stop` to pause both.
Do not run `down -v` or delete volumes. Keep current DB and journals with a
compatible image; restoring an older DB requires reconciling later remote writes
before re-enabling creates. Restore nginx only to its saved matching configuration
and validate before reloading. Disable project timers if the project is paused
long term. Keep certificate renewal enabled for as long as HTTPS is used.

Next user information is the controlled test contact. Other pilot setup work can
continue independently; production remains a separate later decision.
