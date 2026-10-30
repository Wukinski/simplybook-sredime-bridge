# Read-only pregled dva stanja

## Završeno usklađivanje u novom staging-u — 28.10.2026, 12:08 UTC

Stvarni sveži lokalni i host snapshot-i provereni su zajedno sa privatnim
per-booking binding-om, native journal-om, sva tri collector receipt-a, host
ACK-a i stvarnim target readback-ima. [Javni dokaz](evidence/activation-staging-20261028-2eb16604-reconciliation.json)
potvrđuje **8/8 provera** i novo held staging stanje. Read-only REST GET u
12:08:42.359 UTC ponovo je potvrdio da je target booking **5 canceled**,
`is_confirmed=false`, uz provider/service/client 9/496/1.

Dokazana je istorijska veza tri različita raw/projektovana hash para. Novi
`reconcile_trial` polazi od host snapshot-a i čuva originalne host događaje,
hash-eve, heads, receipts i vremena. Dodaje samo potvrđeni canceled owned link
9VPLV6E→5 sa raw opaque identitetima, opaque klijentsku vezu, završeni cancel
intent i applied baseline. Lokalni native projektovani zapisi i njihovi hash-evi
ostaju u provenance evidenciji za audit. Jedan lokalni quota red dodat je sa
originalnim vremenom, bez deduplikacije.

Staging ima sva tri događaja `done`, nerešene namere 0 i prazan red. Postojeći
stale incident i izvorna vremena sačuvani su. Nema lažnog osvežavanja snimka,
promene originalnih event hash-eva, globalnog alias resolver-a ili preseljenja
staging baze preko žive. Unutrašnji recovery hold i bočni marker ostaju.

Privatni ulazi i rezultat su u
`state/activation-staging-20261028-2eb16604328e4084a36158eb08c6c90c/`, a nova
baza je `held-stage/bridge.sqlite`. Javni dokaz posebno čuva hash-eve fizičkih
arhiva i normalizovanih memorijskih image-a koje alat ponovo proverava.
[Precizan opseg alata](RECONCILE_TRIAL.md) ostaje ograničen na ovaj završeni tok.

U 12:50 UTC izvedeni su i [stvarni šifrovani off-host backup i izolovani restore](evidence/offhost-restore-drill-20261028-6e619251.json),
sa **14/14 provera** očuvanja redova, hash-eva, heads, namera, kvota i priloženih
REST budget dokaza. Taj backup snima živu host bazu; ne menja njen ownership
staging rezultatom. [Detalji i granice](RECOVERY.md) uključuju trajni hold i
nedovršen automatizovani off-host raspored.

Noviji korisnikov nalog odobrava pripremu i aktivaciju. Završeni provenance
pregled uklanja istorijsku nepoznanicu ova tri hash para; aktuelna realna
mapiranja, budžeti, promene posle snapshot-a i konačan produkcioni profil i dalje
moraju biti usaglašeni pre oslobađanja hold-a. Zatvoreni booking ciklus nije ponavljan.

## Istorijski generički pregled i pravila alata `state_review`

Raniji [nalaz dva snapshot-a](evidence/production-20261028-state-review.json)
ostaje sačuvan kao prvobitni `blocked` rezultat bez naknadne izmene. Generički
alat tada nije imao pregledan dokaz privatne projekcije. Njegova detekcija
različitih payload-a sama po sebi nije potvrda novog booking kvara; konkretan
istorijski tok sada ima zaseban gore naveden dokaz usklađivanja.

`state_review` poredi zasebne lokalne i host SQLite backup snimke i priprema
sanitizovan plan ručnog usklađivanja. Ne inicijalizuje `Store` ili `Settings`, ne
kontaktira API/VPS, ne menja baze, ne pravi merge/SQL i ne uključuje izvršavanje.
Ne prepisivati host bazu lokalnom: host poseduje originalni prijem i svoj red.

Iz korena projekta, sa već pripremljenim privatnim backup fajlovima:

```powershell
.\.venv\Scripts\python.exe -m booking_bridge.state_review --local-snapshot C:\private\local-backup.sqlite --host-snapshot C:\private\host-backup.sqlite
```

Oba ulaza moraju biti potpuni SQLite online backup snimci, uključujući stanje
koje je u aktivnoj bazi bilo u WAL-u. Kopija samo aktivnog `bridge.sqlite` fajla
nije odgovarajući backup. Ulazi sa `-wal`, `-shm` ili `-journal` fajlom odbijaju
se. Alat čita snimak uz `mode=ro` i `immutable=1`, proverava njegov hash pre i
posle čitanja i ne pravi sidecar fajlove. Ne koristiti ga nad aktivnom bazom.
Pravljenje/prenos stvarnih privatnih backup-a je zasebna operacija.

JSON izlaz sadrži brojeve zapisa, fiksne reason kodove i hash reference, bez
kontakata, payload-a, sirovih booking/employee/client ID-eva ili putanja. Iako
nema tih vrednosti, izveštaj čuvati uz ostale operativne dokaze. Izlaz je
determinističan za ista dva snimka. Statusi su:

| Status | Značenje | Exit code |
|---|---|---:|
| `snapshots_consistent` | Oba snimka prošla su provere i nema utvrđenih razlika | 0 |
| `manual_reconciliation_required` | Oba su čitljiva, postoje razlike za pregled | 2 |
| `blocked` | Neispravan ulaz, konflikt identiteta ili nerešena zaštita | 2 |

`automatic_migration_allowed` i `activation_ready` uvek su `false`. Jednakost
snimaka nije provera stvarne udaljene rezervacije, potpisa originalnog HTTP
tela, ovlašćenja niti produkcione spremnosti.

## Šta se proverava i čuva

- Event ID/booking identitet, sačuvani payload hash, timestamp i validno stanje;
  jednak event ID uz različit validan payload blokira usklađivanje. Promenjen
  lokalni projection sa native ID-evima nije implicitni alias originalnog
  opaque event-a.
- Autoritativni `booking_heads`, jednaka vremena sa konfliktnim snapshot-ima,
  ignorisani događaji i otkazani/obrisani tombstone zapisi. Stariji zapis ne
  sme ponovo postati najnoviji zbog kopiranja baze.
- Owned linkovi, `applied:` baseline-i, client veze, ICS `source_bindings` i
  namere upisa. Nedostajući ownership/baseline ili konflikt tačnih identiteta
  blokira; nepoznat ishod upisa traži stvarni readback pre eventualnog retry-a.
- Lokalni terminalni event uz host `queued`/`working` je poseban razlog za ACK
  pregled. Lokalno `done` samo po sebi ne zatvara host prijem. Host queued
  događaji i host receipt zapisi se čuvaju.
- Incidenti, cache zaštite, refresh/polling vremena i kvote. Konflikt zaštitnih
  vrednosti blokira; vremena pokušaja zadržavaju se uz originalne zapise.
  Svežina se ponovo dokazuje novim čitanjem, ne vremenom prenosa stare baze.
- Obe rate evidencije zadržavaju se konzervativno, sa originalnim vremenima;
  čak i jednaki redovi broje se dva puta dok poreklo ne bude pregledano. Alat
  ne deduplikuje kvote, ne briše ih i ne predstavlja prazan ledger kao nov
  budžet. Zaseban REST dnevni brojač, supervisor JSON i kvote drugih aplikacija
  nisu u ovom SQLite poređenju.

U neispravne ulaze spadaju nedostajući/oštećen fajl, nepodržan `user_version`,
nepotpuna šema, nepoznata event stanja, neispravan hash i promena fajla tokom
čitanja. Alat ne pokušava migraciju ili popravku takvih ulaza.

Sam `state_review` pravi samo plan i ne potvrđuje preseljenje izvršioca na host.
Zasebni `reconcile_trial` sada je napravio dokazani held staging opisan iznad.
Produkcioni nastavak koristi potvrđene identity/profile veze, aktuelni
readback/ACK oporavak i konzervativne originalne kvote; ne prepisuje živu bazu
ili podiže approval zastavice na osnovu generičke jednakosti snapshot-a.
