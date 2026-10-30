# Priprema produkcije na postojećem VPS-u

## Aktuelno stanje — 30.10.2026

Nova priprema nakon korisnikovog zahteva da završi tri prepreke:

- [Svež held stage u 11:05:52 UTC](evidence/production-20261030-fresh-held-state-c958f6d1.json):
  23/23 očuvanja istorije/ownership-a/kvota, target 5 GET-potvrđen kao canceled,
  [privatni ACL proveren](evidence/production-20261030-fresh-held-state-c958f6d1-acl.json).
  Hold nije skinut, baza nije promovisana; ovo ne potvrđuje ceo aktivni kalendar.
  [Nova provera stanja](deploy/CUTOVER_STATE_PREPARATION.md) ima 63 prolazna testa.
- [Implementiran dormant backup/monitor paket](evidence/production-20261030-operations-preparation.json)
  ima 50 ciljanih Windows provera, stvarni pinned SDK i offline Compose proveru.
  [Linux validacija](evidence/production-20261030-operations-linux-validation.json)
  ima 48 PASS + 2 očekivana skip-a za Compose, uz oba offline host Compose PASS-a.
  Nema deployment-a, upload-a, naloga, poruka ili uključenih timera; vlasnikova
  destinacija/ključ/nezavisni monitor još nedostaju.
  [Operativno uputstvo](deploy/operations/README.md).
- [Aktuelna client-field pravila](evidence/production-20261030-client-required-fields-corrected.json)
  zahtevaju name+email+phone. SrediMe [podrazumevano izostavlja kontakte](evidence/production-20261030-source-contact-contract-provenance.json),
  a dodatni kontakt pristup za endpoint nije potvrđen. Auto-create klijenata ne
  postoji u worker-u i zahteva pouzdan odobren izvor kontakata i novu implementaciju.
  [Dokumentovani REST](evidence/production-20261030-current-client-notification-contract.json)
  ne daje per-booking notification suppression ili izmenu required-field politike.
- [50 offline kandidata za pregled](evidence/production-20261030-catalog-candidate-expansion.json)
  ne predstavljaju odobrena mapiranja ili trenutno aktivni source katalog.

Vlasnik je [izabrao 1C](evidence/production-20261030-owner-scope-decisions.json):
pune rezervacije u oba smera, odluke o svakoj razlici pojedinačno, bez čuvanja
klijenata u SimplyBook-u. Nije odobren tehnički/dummy klijent ili brisanje starih.
Booking schema ne čini client_id obaveznim, ali anonimni booking nije account-testiran
i trenutni worker ga ne podržava; [feasibility](evidence/production-20261030-clientless-appointment-feasibility.json).
Source puni write adapter nije implementiran; ICS blok nije zamena za novi opseg.
[Sveži katalozi](evidence/production-20261030-current-catalog-collection.json) imaju
678/495 usluga; dopunsko source-form prikupljanje je u toku i odgovori na
[T01–T09](evidence/production-20261030-duration-questions-batch01.json) još nedostaju.
Runtime profil, readiness i kontrole nisu promenjeni; produkcija nije uključena.
Detaljan nastavak i ograničenja su u [handoff-u](../AI_HANDOFF.md).

[Direktna VPS provera u 10:39:30 UTC](evidence/production-conditional-activation-20261030T103937Z.json)
na korisnikov uslovni zahtev za aktivaciju potvrđuje **49 provera / 29
neispunjenih**, `configuration_ready=false`, prazna produkciona mapiranja i
odsustvo produkcionih kontejnera/state volumena. Server profil/manifest
odgovaraju pregledanim lokalnim kopijama. Produkcija nije pokrenuta; dijagnostika
ostaje healthy. Nema promena servisa, rezervacija, tajni ili produkcionih kontrola.

**Produkcija je odobrena, ali i dalje nije uključena.** Korisnik je sada izričito
odobrio konkretan prenos administratorskih i webhook pristupa na VPS, a
[prenos je stvarno završen](evidence/production-20261030-credentials-installed.json)
u privatne fajlove ispod `/opt/booking-bridge-production/secrets`.
Samo worker ima REST pristup; API ima odvojene signing/admin tajne, bez REST
akreditiva. Fajlovi su UID/GID 10001, mode 0400, direktorijum 0700. Vrednosti tajni
ne ulaze u javne dokaze. Ranija odbijanja transfera opisuju ranije pokušaje;
**ne tražiti ponovo već dobijeno konkretno odobrenje ili iste akreditive**.

Svih šest credential provera prolazi. [Preflight neposredno posle prenosa](evidence/production-20261030-credentials-preflight.json)
imao je 49 provera i 31 neuspešnu. Zatim su stvarno pregledani dokazi za
`server_credentials_review` i `diagnostic_qwen_readonly`, a TLS dokaz zamenjen
novom obnovom: [aktuelni pregled](evidence/production-20261030-reviewed-gates.json)
ima **6 reviewed / 10 pending**, odnosno **49 preflight provera / 29 neuspešnih**,
`configuration_ready=false`. Produkcioni API/worker nisu pokrenuti, produkcioni
DB volumen nije napravljen, mapiranja/allowlist su prazni, nema export URL-ova
ili feed tokena. Nema DB promocije, promene proxy ruta ili skidanja recovery hold-a.

[SMTP je stvarno podešen i testiran](evidence/production-20261030-smtp-setup.json)
preko `smtp.gmail.com:465` uz verifikovani TLS, sa korisnikovog izabranog
pošiljaoca `wukinski021@gmail.com` na jedini odobreni
`aaaazzzz.5226@gmail.com`. Jedan kontrolisani test je SMTP-prihvaćen u jednom
pokušaju; posle starta analyzer-a prihvaćena je i jedna čekajuća dijagnostička
poruka. Postojeći outbox/lock i limiti su očuvani, bez ponovljenog testa.
[Kasniji read-only presek u 10:11:16 UTC](evidence/production-20261030-post-smtp-runtime.json)
potvrđuje **4 SMTP accepted / 4 pokušaja**, bez pending poruka,
`email_configured=true`, `healthy=true`, `last_model_ok=true` i
`last_model_self_test_ok=true`. **Prijem u vlasnikov inbox još nije potvrđen**;
SMTP prihvatanje nije dokaz inbox dostave. App lozinka ostaje samo u privatnim
fajlovima; ne prepisivati njenu vrednost ili hash u dokumentaciju.

Rezidentni Qwen3.5 4B i analyzer rade samo dijagnostiku postojeće **pilot baze**:
`diagnostics_only=true`, `repairs_enabled=false`. Nisu dokaz uključene produkcione
sinhronizacije i nemaju pravo popravke ili booking upisa. Analyzer je jedini
zaustavljen/pokrenut tokom SMTP podešavanja; pilot, Qwen, keeper i collector
sačuvali su isti procesni identitet. Početni SMTP setup presek `health=starting`
i resetovani model self-test već su razrešeni kasnijim healthy presekom.

[TLS obnova je stvarno uspela](evidence/production-20261030-tls-renewal.json)
kroz postojeći normalni Certbot servis, bez force opcije ili promene ruta.
Novi IP/DNS sertifikat ima validan chain/hostname i važi do **05.11.2026.
23:55:03 UTC**. Stariji dokaz sertifikata do 02.11. ostaje istorija.

[Pregled porekla mapiranja](evidence/production-20261030-mapping-provenance.json)
povezuje workbook i potvrđeni import/assignment trag sa jedinstvenim sačuvanim
inventory kandidatima za Tamaru i dve usluge. **Ne tražiti ponovnu potvrdu već
podudarnih imena.** Nedostajući autoritativni native→opaque webhook crosswalk je
tehnički dokaz, ne dodatna vlasnikova saglasnost. Provider-specific timing,
fizički resursi i notification/client pravila ostaju nepotvrđeni; stvarne poslovne
nejasnoće su devet konflikata trajanja i Sanja/Sara identitet. Runtime mapiranja
nisu promenjena.

[Fresh source GET pregled](evidence/production-20261030-source-scope-readonly.json)
potvrđuje da je postojeći callback isključen, a test zaposleni nije bookable;
native callback filtriranje zaposlenih nije dokazano. [Pregled pipeline-a](evidence/production-20261030-pipeline-review.json)
razdvaja read-only posmatranje od booking automatizacije. Prazni export URL-ovi,
allowlist i mapiranja ne postaju funkcionalan source pipeline samim startom procesa.

[Ograničena pasivna provera](evidence/production-20261030-passive-capture.json)
završena je u 10:19:16 UTC: callback je bio aktivan 138.049 s, zatim GET-provereno
isključen; zaseban Rootwatch potvrdio je zatvoren lease i završio bez dodatnog
restore zahteva. Nije stigao nijedan novi događaj. Originalni events/heads i svi
owned zapisi ostali su nepromenjeni, bez obrade/replay-a ili promene termina.
Ovo **ne potvrđuje source isporuku ili original-created gate**.

[Tačan lookup ranijeg ignorisanog događaja](evidence/production-20261030-ignored-booking-identity-read.json)
potvrđuje postojeći native booking za employee 5571 i service 208138; sačuvani
employee export identity segment takođe se podudara. Događaj nije dokazani vendor
dummy. [Drugi i poslednji GET](evidence/production-20261030-ignored-booking-snapshot-comparison.json)
potvrdio je iste hid/status/start/end/duration vrednosti i identičan hash odgovora,
ali nema revision/modified dokaza. Usluga 208138 nema exact-normalized target
kandidata. Ovi završeni lookup-i ne daju opaque ID-eve za 128275/128316; runtime
mapiranje, obrada i replay starog događaja nisu omogućeni.
Nepostojanje revision polja opisuje ograničenje ovog dokaza; nije dodatni gate.

Redovan backup i spoljni nadzor moraju raditi **nezavisno od Windows računara**,
bez kupovine novog hostinga. Potrebni su postojeća, vlasnikova stalno dostupna
off-host destinacija za šifrovane kopije i spoljašnji servis za proveru dostupnosti
koji radi i kad je VPS nedostupan. Nijedan takav unattended tok još nije potvrđen;
lokalni disabled publisher task ne ispunjava ovaj zahtev. Novi nalozi ili dodatne
Google veze nisu napravljeni. Vlasniku su poslata dva aktuelna poslovna
pitanja: autoritativna trajanja i Sanja/Sara identitet.

Preostaju stvarni tehnički/poslovni dokazi, inbox potvrda, nezavisan spoljni
nadzor, ponovljivi unattended off-host backup i pregledana promocija stanja.
Jednokratni šifrovani off-host restore drill nije dokaz redovnog backupa.
Raniji odbijeni predlog promene sedmodnevne blokade/`soak_72h` nije primenjen;
**nijedan gate nije ublažen ili fiktivno označen kao verified**. Odeljci ispod
čuvaju starije preseke; tadašnje tvrdnje da prenos ili SMTP još nisu izvršeni
nisu aktuelni zahtevi korisniku.

## Prethodni presek — 29.10.2026

Korisnik je rekao **„pali produkciju i guraj”**: opšte odobrenje aktivacije na
postojećem VPS-u već postoji i ne traži se ponovo. **Produkcija još nije uključena.**

[Lokalni privatni launch paket](evidence/production-launch-package-20261028-34e5a346.json)
sada postoji: `booking_bridge/deploy/secrets/production-config.json` i profilom vezan readiness
manifest imaju **4 pregledane i 12 pending stavki**. Mode je production, reads
uključen, subminute=false; samo live_writes/hosting odobrenja su true. Stvarna
mapiranja i allowlist su prazni, činjenična odobrenja false, poruke unapproved.

[Staging na VPS-u u 12:27:21 UTC](evidence/production-20261029-server-staging.json)
stvarno je završen u `/opt/booking-bridge-production`, **bez ikakvih akreditiva**.
Privatni Compose je validan, koristi pregledanu sliku `7b11e4fb…`, kandidat port
`127.0.0.1:8001` i zaštićene fajlove vlasnika UID 10001. Produkcioni API/worker
kontejneri nisu napravljeni ili pokrenuti; nema novog DB volumena, izmene žive
baze/proxy-ja ili skidanja recovery hold-a. [Config-only preflight](evidence/production-20261029-server-preflight.json)
u izolovanom network=none/read-only-root/UID10001 kontejneru proverio je **49
stavki: 37 ne prolazi, configuration_ready=false**. To je pripremljen pending paket,
ne aktivan booking servis; dostupni su samo prazni javni secret šabloni.

[Read-only live pregled u 12:19:04 UTC](evidence/production-20261029-live-check.json),
pre server staging-a, potvrđuje uspešan live model review **i dnevni sintetički
self-test**. Qwen/keeper/collector su healthy, Qwen i analyzer imaju 0 restartova.
Analyzer i dalje prati samo pilot bazu, nema booking prava/popravke i ostaje
unhealthy zbog SMTP-a: password prazan, **2 pending poruke, 0 pokušaja slanja**,
bez SMTP prihvatanja ili inbox dokaza. Nema aktivne produkcije.

Automatska approval kontrola **odbila je** predlog čitanja/prenosa lokalnih
SimplyBook REST admin login/token podataka i kopiranja webhook signing tajni na
VPS. Navedeni razlog: opšta namera uključivanja produkcije nije eksplicitno
odobrenje konkretnog credential sadržaja i destinacije. **Radnja nije izvršena;
helper fajl nije napravljen, credential izvori nisu čitani i tajne nisu prenete.**
Root je zasebno zatražio eksplicitnu dozvolu za taj prenos na `169.58.118.33`,
u `/opt/booking-bridge-production/secrets/worker.env`; odgovor je pending.
Izvedena je dozvoljena alternativa: staging bez tajni. Ovo ne poništava već dato
opšte odobrenje produkcije.

Sledeći potrebni vlasnikovi ulazi:

- Konkretno odobrenje navedenog prenosa akreditiva; ne slati njihove vrednosti u razgovor.
- Stvarni početni opseg: Tamara i dve predložene usluge ili svi zaposleni/usluge;
  identitet, trajanje/resursi i postupak za nepoznate klijente još nisu potvrđeni.
- SMTP app lozinka u privatnom fajlu, pa kontrolisan test stvarne dostave vlasniku.

Raniji predlog izmene sedmodnevne blokade i `soak_72h` **zasebno je automatski
odbijen**, nije primenjen i čeka posebno eksplicitno odobrenje. Trenutne kontrole
ostaju iste; nijedna od ovih dozvola nije zamenjena fiktivnim dokazima. Preostali
notification/original-created/native-removal dokazi, spoljni nadzor, unattended
backup i pregledana promocija held stanja i dalje nisu završeni. Stariji odeljci
ispod čuvaju tadašnji presek; pending dnevni self-test iz 28.10. je sada razrešen.

## Prethodni presek — 28.10.2026

Korisnik je odobrio završetak svih preduslova, uključivanje produkcije i
potreban administrativni transfer worker-u na postojećem VPS-u, nezavisno od
Windows računara. Poslednji dodatni uslov je
rezidentni Qwen3.5 4B koji bugove/dvostruke termine prijavljuje vlasniku email-om;
model **nema pravo popravke ili booking upisa**. Ne tražiti ponovo opšte odobrenje.

[Stvarna završna provera modela](evidence/diagnostics-20261028-model-eval-final.json)
ima **7/7 PASS za 817.221 s, bez novog OOM-a**, na V3 slici
`sha256:1ad9a4fa512e969cb193f50dab25e6f4ff2a1588b605554cc6544c64be250608`.
Isti sintetički scenariji i očekivanja zadržani su; model ima 8 GiB,
num_batch=64, kontekst 4096 i jedan paralelni zahtev.

V4 runtime slika je `sha256:7b11e4fbc5c7335e763677909243553f38f050ead7101271aec723c06c7210b9`.
[Offline dokaz ekvivalencije](evidence/diagnostics-20261028-v3-v4-protocol-equivalence.json)
potvrđuje byte-identičan SYSTEM, schema i svih sedam request body-ja, uz ponovnu
validaciju svih stvarnih V3 odgovora. **Sedam stvarnih modelskih poziva nije
ponovljeno na V4.** V4 dodaje proveru da završen AI kandidat pripada sadašnjem
validnom opažaju i ograničenja čekanja; ne menja testirani modelski protokol.

[Analyzer je pokrenut](evidence/diagnostics-20261028-python-rollout.json), samo nad
postojećom pilot bazom: kontejner od 17:21:37 UTC, prvi heartbeat 17:21:52 UTC.
[Runtime pregled u 17:25:14 UTC](evidence/diagnostics-20261028-runtime-status.json)
potvrđuje **prvi uspešan live AI pregled**, bez restarta ili novog OOM-a.
Početni dnevni sedmočlani self-test započet je u 17:24:53 UTC i još je pending.
Keeper/collector ostaju healthy na slici 07e13d, Qwen i pilot procesi nepromenjeni.
Analyzer je running, ali `healthy=false`, `email_configured=false` i
`smtp_not_configured`; outbox ima jednu pending poruku i **0 SMTP pokušaja**.
Model/analyzer nemaju bridge bazu, booking/SSH tajne ili pravo popravke.
Nema booking upisa, prenosa REST administratorskih pristupa, SMTP autentikacije,
poslatih dijagnostičkih email-ova ili inbox dokaza.

SMTP password ostaje [prazan uz privatni ACL](evidence/diagnostics-20261028-smtp-private-acl.json).
[Završni pregled pripreme](evidence/diagnostics-20261028-preparation.json) razlikuje
izvedenu dijagnostiku od produkcionih preduslova koji još nedostaju.

Sveža collector projekcija ne osvežava zastareli booking/buffer keš.
[Dijagnostički runbook](deploy/DIAGNOSTICS_RUNBOOK.md).

[Pregledani reconciliation stage](evidence/activation-staging-20261028-2eb16604-reconciliation.json)
zadržava originalne host događaje/head-ove/hash-eve i tačan završeni probni
ownership, uz opaque client binding, završenu nameru i konzervativne kvote.
**Hold nije skinut, worker start je blokiran i aktivne baze nisu promenjene.**
Stage je usaglasio istorijski raw/projected provenance završenog testa; isti
konflikt nije nerešena nova blokada. Ne potvrđuje produkciona mapiranja/pravila
ili opštu migraciju. Stvarno nedostaju identiteti/mapiranja, pokrivenost usluga,
ispravna trajanja i resursi, produkcioni opseg i postupak za nepoznate klijente,
SMTP pristup/dostava, notification/original-created/native-removal dokazi,
merenje transporta i nezavisan spoljni nadzor. Jednokratni [encrypted off-host backup/restore](evidence/offhost-restore-drill-20261028-6e619251.json)
ima **14/14 provera**; unattended raspored i trajno skladište ostaju nedovršeni.

V4 softverska validacija: [Windows 756 PASS](evidence/diagnostics-20261028-windows-tests.xml),
[Linux 746 PASS + 10 skip](evidence/diagnostics-20261028-linux-tests.xml)
i [HTTP smoke PASS](evidence/diagnostics-20261028-linux-smoke.json).
To su odvojeni dokazi od stvarne V3 modelske provere.

Raniji semantički/OOM rezultati ostaju istorija u
[glavnoj primopredaji](../AI_HANDOFF.md); završna V3 modelska provera je prošla.

## Serverska obrada i zaštita upisa

`server_worker` koristi isti `Worker` i `Scheduler` kao postojeći CLI. API
potvrđuje samo trajan prijem; event postaje `done` tek posle obrade i target
readback-a. Na istom serveru nema potrebe za dodatnim lokalnim SSH collector/ACK
tokom između dve baze. Privatni pilot alati ostaju istorija i alat za oporavak.

Novi Compose je odvojen, iza eksplicitnog `production` profila. API i radnik
imaju odvojene secret fajlove; samo radnik dobija REST pristup i provider_state.
[Postavljanje i monitor](deploy/PRODUCTION_PREPARATION.md). Javni config ostaje
simulation/reads off i odbijen je na serverskom worker ulazu.

Produkcioni radnik zahteva kompletan preflight pre konstrukcije gateway-a ili
oporavka reda. I stari worker ulaz i direktni Gateway upisi proveravaju novu
evidenciju: zaobilaženje wrapper-a ne otvara produkciju. Blokada vraćene baze
važi i za pilot/simulation worker, pre preuzimanja događaja.
Posle prvog potpunog integrity/schema pregleda, radnik pre svakog sledećeg
pokušaja proverava hold direktno u bazi, uključujući WAL promene; ne skenira
celu bazu na svakoj sekundi. Nerešena namera pri produkcionom startu blokira
wrapper dok operator ne proveri ishod i usaglasi stanje. Simulacioni restart
testovi dokazuju zaštitu od dupliranja, ne neograničen automatski oporavak.

## Evidencija spremnosti

`production_readiness` obrađuje operatorovu pregledanu evidenciju. Manifest
`deploy/production-readiness.example.json` počinje sa svim proverama pending.
Za konkretan pregledani privatni profil pripremiti novi manifest:

```text
python -m booking_bridge.production_readiness --template --config PRIVATE_CONFIG
python -m booking_bridge preflight --target production --readiness PRIVATE_READINESS_JSON
```

Prva komanda ispisuje šablon; ne pravi nalog ili menja profil. Druga samo čita
lokalne preduslove. Wrapper uzima isti manifest kroz `--readiness`; postojeći
worker/Gateway kroz `BRIDGE_PRODUCTION_READINESS_FILE`.

Po sadašnjoj implementaciji svaka stavka mora imati `status=verified`, `reviewed=true`, putanju do
artefakta ispod direktorijuma manifesta, SHA-256 i aware `observed_at` ne stariji
od sedam dana. Promena profila, dokaza, politike ili isteka zatvara gate.
Ne unositi kontakte, tajne ili sirove payload-e u javni manifest ili git.
Privatni popunjeni primerak i dokazi idu u `deploy/secrets/production-evidence`.

Stavke pokrivaju usaglašavanje stanja, mapiranja, poslovna pravila, poruke,
originalni created, latenciju, poslednji uklonjeni blok/prazan feed, spoljni
nadzor, šifrovan off-host restore, TLS, Linux/HTTP, 72 sata rada, pregled prenosa
pristupa i posebno produkciono odobrenje. Operator mora pregledati sadržaj;
hash sam ne dokazuje istinitost ili poreklo tvrdnje. Izlaz zato zadržava
`external_validation_performed=false`. Podizanje zastavica nije zamena za dokaze.

Ovo je naš ranije uvedeni softverski gate: 72 sata rada i sedmodnevni rok dokaza
nisu novi vlasnikovi zahtevi. Predlog da se nepromenjeni profile/hash dokazi
posle sedam dana samo označe za pregled, a `soak_72h` zameni opažanjem stvarnog
opsega/trajanja, **odbila je automatska approval kontrola kao trajno slabljenje
sigurnosne kontrole**. Izmena nije primenjena. Root je zatražio konkretno
korisničko odobrenje predloga i odgovor je pending. Do tada aktuelni kod i dalje
blokira istek i zahteva `soak_72h`; nema workaround-a ili fiktivnih verified dokaza.

`require_subminute_availability=true` je podrazumevana vrednost javnog šablona,
a stvarni capture/execution profili imaju **false**. Pilot cilj <60 s nije
potvrđen vlasnikov SLA niti sam po sebi nova prepreka aktivaciji. Kada konkretan
pregledani profil zaista traži strict subminute, sadašnji kod ga blokira; manifest
to ne zaobilazi. HTTP fetch i dalje nije native import ili potvrda E2E trajanja.

## Mapiranja i poslovni pregled

[Matrica kandidata](mappings/production-review.csv) prenosi mali istorijski
predlog iz [ranijeg pregleda](PILOT_MAPPING_REVIEW.md): Tamara i dve usluge.
To su kandidati iz sačuvanih podataka, ne nova potvrda istog identiteta, rasporeda
ili podržanih resursa. Webhook ključevi su prazni, sve odluke pending; ova CSV
se ne učitava kao runtime mapiranje. Nema kreiranja termina za stvarno osoblje.

Pre popunjavanja novog profila potvrditi:

| Oblast | Odluka/dokaz koji nedostaje |
|---|---|
| Identitet | Stvarni opaque webhook ID, target ID i odvojeni native ID |
| Usluga | Isti tretman, stvarno trajanje, priprema/cleanup, uređaj i referentni raspored |
| Klijent | Proverena osoba ili definisan ručni postupak za nepoznat customer ID |
| Pending/no-show | Za produkciju posebno potvrditi postojeće probno hold/retain ponašanje |
| Poruke | Izabrati ko šalje potvrdu, podsetnik, pomeranje i otkazivanje; potvrditi stvarnu dostavu i odsustvo dupliranja |
| Kvar/kašnjenje | Odgovorni operator i postupak u oba kalendara; naš 503 ne zatvara automatski SrediMe termine |

## Stanje, kopije i konkretni nalazi

[Read-only pregled](STATE_RECONCILIATION.md) poredi zasebne SQLite snapshot-e,
nikad ne pravi merge ili SQL za izvršavanje. Novi alat je primenjen na lokalni i
host snapshot bez izmene aktivnih baza:
[sanitizovan nalaz](evidence/production-20261028-state-review.json).

Pregled je **blocked**: tri ista event ID-a imaju različite hash-eve u izvornom
host prijemu i istorijskoj lokalnoj projekciji; host nema lokalnu owned vezu,
a razlikuju se i zaštitna evidencija i stari snimci. To je očekivana granica
ranijeg per-booking binding-a. Nije dozvoljeno automatski prepisati originalne
hash-eve ili zameniti host bazu lokalnom. Naknadni pregled provenance i izolovani
held stage navedeni su iznad; izvorni read-only diff ostaje istorijski nalaz nad
nepromenjenim snapshot-ima, bez tvrdnje da je aktivna migracija izvršena.

[Backup/restore alat](RECOVERY.md) koristi SQLite online snapshot i
AES-256-GCM, bez privremenog plaintext backup-a. Vraća samo u novi fajl i ugrađuje
recovery hold u samu bazu plus bočni marker; kopiranje same vraćene baze ne
uklanja zaštitu. Priloženi REST budžeti ostaju u posebnom direktorijumu za pregled,
ne prepisuju aktivne brojače. Nema automatskog skidanja hold-a ili pokretanja.
Stvarna šifrovana kopija tadašnje žive host baze preneta je van VPS-a i vraćena
u novu held bazu: [14/14 provera](evidence/offhost-restore-drill-20261028-6e619251.json).
Privremeni server ključ je obrisan, redovi/hash-evi/kvote i priloženi budžeti
očuvani. Trajni off-host raspored, skladište, retention i key custody ostaju
operativni posao. [Dokumentacija biblioteke](https://cryptography.io/en/latest/hazmat/primitives/aead/).

[Noviji read-only TLS pregled](evidence/diagnostics-20261028-tls.json) potvrđuje
validan chain/hostname za IP i DNS. Let's Encrypt YE1 kratkotrajni cert važi
160h, do 02.11.2026 14:34:01 UTC; preostalo je oko 122h. Namenski timer je
active/enabled, poslednja provera success/exit 0 i certificate_not_yet_due;
obnova još nije dospela i nema neuspešne obnove. Ne tražiti forsiranu obnovu
kao uslov aktivacije. Za ovaj deployment monitor koristi `--tls-min-days 2`,
dok generički CLI default 7 nije primeren ovom normalnom veku cert-a.

## Pre buduće aktivacije

Novi paket je proveren source-only bez akreditiva u izolovanom Linux kontejneru,
sa isključenom spoljašnjom mrežom i read-only root filesystem-om. Lokalni Docker
engine nije radio; korišćen je zaseban validation image na postojećem VPS-u,
bez zamene/zaustavljanja pilot servisa. SQLite backup sada eksplicitno zatvara
veze; testovi ne zavise od naknadnog oslobađanja WAL/SHM kroz GC.

| Provera | Rezultat |
|---|---|
| [Windows](evidence/production-20261028-windows-tests.xml) | 562 prolaza |
| [Linux](evidence/production-20261028-linux-tests.xml) | 558 prolaza, 4 platformske provere preskočene |
| [Windows HTTP](evidence/production-20261028-windows-smoke.json) / [Linux HTTP](evidence/production-20261028-linux-smoke.json) | Odvojen API/worker, signed ingress, dedupe, 401 i readiness200 u simulaciji |
| [Preflight](evidence/production-20261028-preflight.json) | Očekivano blocked; šablon ne uključuje produkciju |

Preskočene Linux provere su Windows task helper i Compose parser bez Docker CLI-ja
u izolovanom kontejneru; ove provere prolaze na Windows-u. Postoji jedno poznato
upozorenje biblioteke Starlette o budućoj promeni TestClient zavisnosti.
[Sažetak i source/image identitet](evidence/production-20261028-preparation.json).

Novi kontrolisani živi scenario opravdan je promenjenim serverskim tokom, ali
završeni 9VPLV6E → 5 ciklus ne ponavljati. Originalni booking.created, stvarna
inbox dostava, native primena blokada/uklanjanje poslednjeg bloka i izmerena E2E
latencija zahtevaju zasebne stvarne dokaze. Ranije implementirani gate traži
72 sata nadziranog rada; to je naša softverska politika, ne vlasnikov dodatni
zahtev. Za sada nema novog callback lease-a,
rezervacionih upisa ili slanja poruka. Produkciono puštanje je odobreno, ali
nije izvršeno dok konkretni preduslovi ostaju nedokazani.
