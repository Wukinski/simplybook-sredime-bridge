# Šifrovana kopija i izolovani oporavak

## Potvrđena proba — 28.10.2026, 12:50 UTC

Izvedeni su stvarna šifrovana kopija žive host baze, prenos van VPS-a u korisnikov
privatni lokalni workspace i vraćanje u novu izolovanu bazu. [Javni dokaz](evidence/offhost-restore-drill-20261028-6e619251.json)
ima **14/14 uspešnih provera**, `off_host_export_performed=true` i
`unattended_backup_complete=false`.

Korišćena je neizmenjena pregledana slika
`sha256:ac942940d496a7c84c5b29a357e7625044a4b54ef00d372e13068ef8abc7cde3`,
UID 10001, bez mreže, sa read-only root filesystem-om i read-only mount-om
izvorne baze. Nov lokalni ključ ima pregledan privatni Windows ACL; prenet je
samo sigurnim SSH stdin kanalom u privremeni tmpfs fajl sa dozvolama 0600.
Njegovo brisanje, uklanjanje privremenih fajlova i gašenje jednokratnog
kontejnera potvrđeni su. Ključ nije u argumentima, logovima ili javnom dokazu.

Remote i lokalni AES-GCM verify prolaze. Vraćeni su svi originalni poslovni
redovi, raw događaji/hash-evi, booking heads, namere i kvote sa originalnim
vremenima. Dodata je obavezna recovery blokada. Sačuvani su stvarni lokalni
`budget.json`, `last-request.json` i jedan importer budget floor; category
checkpoint nema top-level `budget` polje za prilaganje. Drugi API klijenti i
udaljeni provider budžeti nisu obuhvaćeni ovom potvrdom.

Privatni paket i held restore nalaze se u
`state/offhost-restore-drill-20261028-6e61925100ec4bbd956d9e67c8708724/`.
Živa baza, servisi i rezervacije nisu menjani, administratorski pristupi nisu
prenošeni i nema slanja poruka ili oslobađanja hold-a. [Usklađeni staging](STATE_RECONCILIATION.md)
ostaje zaseban rezultat; backup snima tadašnju živu host bazu.

Korisnikov noviji nalog odobrava pripremu i aktivaciju. Ovaj izvedeni korak
ostavlja obe obnovljene/staging baze blokirane do usaglašavanja aktuelnog
udaljenog stanja, budžeta i konačnog profila. Raspored kopiranja, dugoročno
skladište, rok čuvanja, alarm i čuvanje/rotacija ključa ostaju operativni posao.

## Ponašanje alata

`python -m booking_bridge.recovery` koristi SQLite online backup, uključujući
potvrđene zapise u WAL-u. Snimak se pravi i proverava u memoriji; nema privremene
nešifrovane kopije na disku. AES-256-GCM iz biblioteke `cryptography` autentikuje
i šifruje ceo paket nasumičnim nonce-om. Pogrešan ključ, promenjen ili skraćen
paket se odbijaju pre kreiranja restore fajlova. Količina podataka je ograničena
na 128 MiB baze i 192 MiB paketa. To nije postupak za proizvoljno velike baze.

## Ključ i izlazi

Ulaz je postojeći privatni fajl sa tačno **32 nasumična binarna bajta**, bez
tekstualnog kodiranja ili novog reda. Ključ ne ulazi u komandne argumente,
manifest, backup ili log. Putanja se zadaje kroz `--key-file` ili promenljivu
`BRIDGE_RECOVERY_KEY_FILE`; ne stavljati sadržaj ključa u promenljivu.
Na POSIX-u ključ mora imati dozvole samo za vlasnika. Na Windows-u koristiti
privatni direktorijum sa pregledanim ACL-om; `0600` sam ne uređuje Windows ACL.
Čuvanje, rezervna kopija i rotacija ključa ostaju deo produkcionog postupka.

Sve izlazne putanje moraju biti nove, a njihov privatni roditeljski direktorijum
već mora postojati. Postojeći fajlovi, marker-i i budget direktorijumi se nikada
ne prepisuju. Šifrovani izlaz dobija sanitizovan `.manifest.json` sa hash-evima,
vremenom i brojevima zapisa; ne sadrži putanje, kontakte, ključeve ili payload-e.
`off_host_export_prepared=true` znači lokalno pripremljen paket, ne udaljenu kopiju.
Manifest je informativan; `verify` proverava autentikovani sadržaj samog paketa.

```powershell
.\.venv\Scripts\python.exe -m booking_bridge.recovery backup --source PRIVATE_SOURCE\bridge.sqlite --output PRIVATE_BACKUPS\snapshot.enc --key-file PRIVATE_KEYS\recovery.bin --budget-file PRIVATE_PROVIDER_STATE\budget.json --budget-file PRIVATE_PROVIDER_STATE\last-request.json --budget-floor service_importer\progress_log.json
.\.venv\Scripts\python.exe -m booking_bridge.recovery verify --source PRIVATE_BACKUPS\snapshot.enc --key-file PRIVATE_KEYS\recovery.bin
.\.venv\Scripts\python.exe -m booking_bridge.recovery restore --source PRIVATE_BACKUPS\snapshot.enc --output PRIVATE_ISOLATED_RESTORE\bridge.sqlite --key-file PRIVATE_KEYS\recovery.bin
```

Ovo su šabloni za budući pregled, ne nalog za čitanje ili slanje stvarne baze.
`verify` radi u memoriji i ne pravi izlaze. CLI daje fiksne razloge grešaka;
ne prikazuje tekst SQLite/crypto izuzetaka ili privatne putanje.
Dodavati druge `--budget-floor` ulaze samo kada stvarno imaju proverljivo
`budget` polje; trenutni category checkpoint ga nema.

## Šta se čuva

Baza zadržava događaje, booking heads, linkove i tombstone-e, klijentske veze,
neizvesne namere, refresh stanje, kvote i ostale tabele. Proveravaju se integritet,
schema verzija, kolone i indeksi/unique ograničenja. Nepodržana šema i dodatni
trigger-i/view-i se odbijaju. Neizvesne namere se ne označavaju kao završene.

Eksterni REST brojači nisu svi u toj bazi. `--budget-file` eksplicitno prihvata
samo proverene oblike `budget.json` i `last-request.json`. `--budget-floor`
uzima samo `budget` iz navedenog importer/category checkpoint-a; kontakti,
rezultati i eventualna ostala privatna polja iz checkpoint-a ne ulaze u paket.
Čuvati redosled navedenih floor fajlova u privatnom operativnom postupku.
Restore ih izdvaja u novi `<database>.budgets` direktorijum, kao pripremu za
pregled; nikada ih ne upisuje preko živih brojača.

SQLite snapshot je transakciono dosledan. Eksterni brojači se čitaju zasebno,
pa paket ne tvrdi atomsku doslednost između procesa. Kopija bez eksplicitnih
budget ulaza takođe nije dokaz očuvanog ukupnog REST budžeta. Posle vraćanja
obavezno proveriti kasniju potrošnju i konzervativno uskladiti brojače.

## Obavezna blokada posle restore-a

Restore pravi novu izolovanu bazu sa `cache['recovery-hold']`, kao i prateći
`<database>.recovery.json`. Oba nose `remote_reconciliation_required=true`,
`budget_reconciliation_required=true`, `worker_start_allowed=false`.
Kopiranje same baze zadržava blokadu. Marker se čuva pre upisa validne baze;
prekid pre marker-a ostavlja rezervisanu praznu bazu koju provera integriteta
takođe blokira. Postupak ne prepisuje postojeći izvor niti automatski ponavlja upise.

`recovery_start_allowed(path)` samo čita stanje: bilo koji marker, unutrašnja
blokada ili neispravna postojeća baza znači `False`. Nema automatske komande
za uklanjanje blokade. Svaki ulaz u mutation worker mora proveriti ovu zabranu.
Restored `database_sha256` obuhvata dodatu blokadu; `source_database_sha256`
označava originalni snapshot. Poslovni zapisi ostaju očuvani.

Pre budućeg vraćanja u rad treba uporediti udaljene rezervacije sa linkovima,
proveriti sve neizvesne namere stvarnim readback-om, uskladiti događaje i ACK-ove
koji su nastali posle snapshot-a, sačuvati konzervativne kvote/budžet i proveriti
konkretan profil/mapiranja. Potreban je pregledan postupak oslobađanja blokade
nakon potvrđenog usaglašavanja. Novije korisničko odobrenje aktivacije važi;
uspešna proba sama ne potvrđuje da su aktuelna mapiranja, udaljeno stanje i
preostali operativni preduslovi rešeni.

Jednokratna off-host kopija i izolovani restore sada su dokazani. Izbor trajne
destinacije, automatizovan raspored, rok čuvanja, spoljašnji alarm, RPO/RTO i
proba zamene kompletnog produkcionog hosta ostaju operativni koraci.
Ne koristiti `down -v`, prazni ICS, brisanje namera ili staru bazu kao prečicu.
