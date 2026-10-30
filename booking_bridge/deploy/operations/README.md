# Off-host backup and independent monitoring

These are prepared tools, not activated services. No storage account, upload,
email, timer, production database, or external monitor was created by this work.
The booking worker and its readiness policy are unchanged.

The hourly backup runs on the VPS without the Windows PC. It takes the existing
SQLite online snapshot, preserves the explicitly supplied request budgets/floors,
encrypts it with the existing AES-256-GCM recovery format, uploads only ciphertext,
downloads the exact object, and verifies its hash, authentication, database
integrity, schema, and budget metadata. Upload uses conditional create, so an
existing key is never replaced. The daily job additionally restores that download
into a private isolated temporary directory and verifies its worker-start hold.
The temporary plaintext and its budget copies are then removed.

The host monitor reads the bridge database and backup spool read-only. It checks
worker readiness, free space, hourly remote-verified backup freshness, and daily
held-restore freshness. It sends static Serbian alerts only to
`aaaazzzz.5226@gmail.com` through the existing verified-TLS SMTP sender. Nothing
in these tools restarts services, repairs data, or invokes a model.

The independent monitor must run outside the booking VPS. It checks public HTTPS
liveness and the actual verified TLS expiry. The default explicitly reports
`readiness_checked=false`; it does not pretend that public liveness proves worker
readiness. Optional authenticated readiness needs a separately approved GET-only
access route and private key file. A managed external HTTP monitor can replace
this custom external runner; its notification sender may differ from Gmail.

## Owner inputs still needed

- Existing independent storage, or a selected S3-compatible provider/account.
  Need HTTPS endpoint, region, private bucket and dedicated prefix, plus restricted
  credentials in a private JSON file. Do not paste secret values into chat.
- Independent recovery-key custody, such as the owner's existing password vault.
  A reviewed 32-byte production key must remain recoverable outside the VPS and
  outside the ciphertext bucket. This tool never uploads it. Do not silently
  reuse the prior one-off drill key or claim that two files on one server are
  independent custody.
- Existing always-on independent executor for the custom monitor, or a selected
  managed monitoring service. A logged-on Windows task and an on-VPS email sender
  cannot detect and report a complete VPS outage.

Cloudflare R2 is one compatible example: its official API supports the atomic
conditional `PutObject` used here. Its Standard free allowance is currently
10 GB-month, 1 million Class A operations and 10 million Class B operations per
month, with free internet egress. Account setup, eligibility and charges above
the allowance still need the owner's selection; no account was opened.
[R2 API compatibility](https://developers.cloudflare.com/r2/api/s3/api/),
[R2 pricing](https://developers.cloudflare.com/r2/pricing/).

UptimeRobot's official FAQ lists 5-minute checks for Free and 60-second checks for
Solo. A selected managed service can cover total-host failure without exporting
the Gmail app password to a second executor. It still needs an actual configured
monitor and verified recipient; no registration was performed.
[UptimeRobot plans](https://uptimerobot.com/pricing/).

## Review and delivery

Build the separate operations image from the existing reviewed base and these
two new modules. The optional SDK dependencies are pinned separately in
`requirements.lock.txt`; the booking runtime environment is not modified.
Set `BRIDGE_OPERATIONS_IMAGE` to the resulting immutable image ID in a private
`operations.env`. Transfer/review the image for a selected external executor
separately; the example does not grant credential transfer to a new host.

```text
docker build -f booking_bridge/deploy/operations/Dockerfile -t andjelija-bridge:operations-reviewed .
```

The source-only release builder omits `.service` and `.timer` suffixes. Use
`python -m booking_bridge.deploy.build_operations_bundle` for an explicit public
operations bundle; it includes these unit templates and excludes every private
`secrets/`, `state/`, and filled configuration file.

For the VPS, prepare `/opt/booking-bridge-operations` from the host Compose file,
units and private inputs. The production bridge/provider volumes are declared
`external`: a missing production state fails instead of creating an empty
replacement database. Each container is UID 10001, has read-only root, no
capabilities, no Docker socket, no REST credentials and no listening ports.
Only the backup receives S3 credentials and the encryption key. Only the monitor
receives SMTP files; its backup/database mounts are read-only. Named operations
volumes must be initialized with the image's UID 10001 private directories.

Prepare private copies beneath `secrets/`, owner UID 10001, files mode 0400 and
directories 0700:

- `backup.json` from the example, with real independent storage and exact source
  paths. Set `destination_independent_of_source=true` only for the chosen
  independent destination.
- `s3-credentials.json` with exactly `access_key_id` and `secret_access_key`
  (optional `session_token` is supported). Use a dedicated bucket; restrict
  permissions to list and read/write objects in the chosen prefix. Deletion is
  needed only when retention is deliberately enabled.
- `recovery-key.bin`, exactly 32 bytes, with confirmed independent recovery copy.
- `budget-floor.json`, containing the current reviewed conservative `budget`
  object from preserved state. Resolve actual budget/timing files and floors
  during state migration; the examples supply no fictitious budget values.
- `monitor.host.json`, `diagnostic-smtp.env`, and `diagnostic-smtp-password.txt`.
  Reuse the approved sender and fixed recipient; never print the password.

First inspect Compose offline, run one backup with held restore, and verify the
sanitized receipt against the selected destination. Then check the host monitor
without SMTP; an explicit `--send-alert` enables sending. The default backup
example fails until an independent destination is supplied. Every runtime command
below is an operator action, not an action already performed by these templates.

```text
docker compose -f compose.host-operations.yaml --profile operations config --format json
docker compose -f compose.host-operations.yaml --profile operations run --rm --no-deps -T backup python -m booking_bridge.deploy.offhost_backup --config /run/config/backup.json --restore-drill
docker compose -f compose.host-operations.yaml --profile operations run --rm --no-deps -T host-monitor python -m booking_bridge.deploy.operations_monitor --config /run/config/monitor.host.json
```

After a successful real run, the four host backup/restore unit files and two host
monitor unit files provide hourly backup, daily restore and checks after each
minute of inactivity. `Persistent=true` is used on calendar backup timers to
catch a missed scheduled invocation after downtime; it does not backfill every
missed backup. The templates are not installed or enabled. Docker Compose `run`
executes a one-off process; `--no-deps` avoids starting application services.
[systemd timer semantics](https://freedesktop.org/software/systemd/man/latest/systemd.timer.html),
[Compose run](https://docs.docker.com/reference/cli/docker/compose/run/).

For a selected independent executor use its own directory,
`compose.external-monitor.yaml`, external configuration and matching timer. It
requires no bridge database, backup key, S3 credentials, model or REST access.
The default uses public liveness/TLS only, so no admin key leaves the VPS.

## Retention and alert behavior

Default proposals are 30 days and a floor of 48 verified copies. The public
example has `delete_expired=false`: deletion requires a reviewed private setting.
An object must be both old enough and outside the newest-copy floor to expire.
Only exact generated names in the exact prefix with this destination's durable
verified-upload receipts count toward that floor. Arbitrary matching names,
uncertain uploads, foreign prefixes and unverified local copies are preserved.
At most 32 remote objects are deleted per successful run, after a fresh verified
upload. Local encrypted files require matching hash/verification receipts before
pruning. Small receipts remain until corresponding remote pruning; losing the
local catalog disables automatic deletion of old remote objects rather than
guessing which were verified. Bucket versioning/object locks may retain old
versions despite a delete; provider lifecycle and storage use require review.

Each monitor keeps its own durable SQLite outbox. Two failed checks trigger an
alert; two healthy checks trigger recovery. Repeats are deduplicated for one hour,
with at most 10 attempts per UTC day and 3 attempts per message. A transport
outcome that might have completed SMTP DATA is marked uncertain and never blindly
retried. SMTP acceptance is recorded separately from inbox receipt. Queue/status
files contain fixed codes, timestamps and hashes, never response bodies, URLs,
credentials or customer contact fields.

`backup-status.json` distinguishes encrypted creation, actual off-host upload,
remote readback verification and held restore. The host monitor rejects a fresh
mtime on a failed/unverified job, and separately checks
`restore-drill-status.json`. Neither a unit template nor a local unit test is
evidence that unattended transfer or independent outage delivery is active.

The S3 adapter uses the maintained SDK, finite timeouts/retries and explicit
credentials rather than an ambient account. Local hash/AES authentication is
performed after remote download; no ETag-as-hash assumption is made.
[Boto3 object operations](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/put_object.html),
[SDK configuration](https://docs.aws.amazon.com/botocore/latest/reference/config.html).
