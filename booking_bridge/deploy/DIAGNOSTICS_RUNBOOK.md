# Rezidentni Qwen dijagnostičar

Korisnik je odobrio Qwen3.5 4B na postojećem VPS-u kao uslov pre booking
automatizacije. Njegova uloga je dijagnostika i izveštaj vlasniku; nema prava
za popravke, upravljanje servisima ili booking upise. Izabrani model je
`qwen3.5:4b`, službena Ollama Q4_K_M varijanta sa projector-om.
[Službeni model](https://ollama.com/library/qwen3.5:4b).

## Aktuelno stanje — 30.10.2026

**Produkcija je i dalje OFF.** [Konkretno odobreni credential prenos](../evidence/production-20261030-credentials-installed.json)
stvarno je završen; REST pristup ima samo worker, API ima odvojene signing tajne.
[Pregled readiness-a](../evidence/production-20261030-reviewed-gates.json) sada ima
**6 reviewed / 10 pending**, 49 preflight provera i 29 neuspešnih. Kontrole,
profil i recovery hold ostaju nepromenjeni; nema produkcionih kontejnera.

[SMTP test](../evidence/production-20261030-smtp-setup.json) prihvaćen je preko
verifikovanog TLS-a na `smtp.gmail.com:465`, od `wukinski021@gmail.com` ka
jedinom odobrenom `aaaazzzz.5226@gmail.com`; prihvaćene su i čekajuće dijagnostičke
poruke. [Presek 10:11:16 UTC](../evidence/production-20261030-post-smtp-runtime.json)
ima **4 accepted / 4 pokušaja**, `email_configured=true`, `healthy=true` i
uspešan model review i self-test. **Inbox potvrda još nedostaje.** Qwen/analyzer
prate samo postojeću pilot bazu, uz `diagnostics_only=true` i
`repairs_enabled=false`; nemaju pravo booking upisa ili popravke.

[Obnovljeni TLS](../evidence/production-20261030-tls-renewal.json) važi do
**05.11.2026. 23:55:03 UTC**. Opaque mapiranja su tehnički pending; ne tražiti
ponovno potvrđivanje već podudarnih imena Tamare i dve usluge. Vlasniku su poslata
poslovna pitanja o autoritativnim trajanjima i Sanja/Sara identitetu.

Trajni rad, spoljni nadzor i unattended off-host backup moraju biti nezavisni
od Windows računara, bez kupovine novog hostinga. Nije napravljen novi Windows
task. Potrebni su odgovarajući postojeći spoljni servis i off-host destinacija;
novi nalozi ili dodatne Google veze nisu napravljeni. Sedmodnevni i
`soak_72h` gate ostaju isti.

Aktuelni izvori su [primopredaja](../../AI_HANDOFF.md) i [produkcioni pregled](../PRODUCTION_READINESS.md).
Starije sekcije ispod su datirani istorijski preseci; njihove tvrdnje o praznim
credential/SMTP fajlovima ili neuspešnom health-u ne opisuju sadašnje stanje.

## Prethodni presek primene i blokada — 28.10.2026

Produkcijska aktivacija i potreban administratorski transfer worker-u jesu
odobreni, ali još nisu izvedeni. Qwen/email preduslov i zabrana popravki imaju
prednost nad početnim puštanjem booking automatizacije.

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

Istorijski dokazi ostaju sačuvani: početnih
[svih sedam insufficient_evidence](../evidence/diagnostics-20261028-model-eval.json),
[tri ciljana PASS](../evidence/diagnostics-20261028-prompt-probe.json), zatim
[šest semantičkih PASS + jedan model_unavailable](../evidence/diagnostics-20261028-model-eval-reviewed-memory-failure.json)
zbog [dokazanog 6 GiB OOM-a](../evidence/diagnostics-20261028-memory-before-fix.json).
[Limit je podignut na 8 GiB](../evidence/diagnostics-20261028-memory-fix.json) uz isti
Qwen kontejner/server proces. Kasniji [0dac rezultat 6/7](../evidence/diagnostics-20261028-model-eval-0dac3816734b.json)
imao je semantičku grešku, bez novog OOM-a. Ovi nalazi nisu završni rezultat V3;
klasifikacija svežine, aktivnog target-a posle source cancel-a i neizvesne namere
razjašnjena je testiranim SYSTEM uputstvom, bez promene očekivanja.

Collector pravi svež opažaj o **zastarelim** booking/buffer snimcima; healthy
collector ne potvrđuje svežu dostupnost ili dupli termin.
[Stvarni off-host backup/restore](../evidence/offhost-restore-drill-20261028-6e619251.json)
ima 14/14 provera; restore je held, unattended backup nije uključen. Produkcija
ostaje OFF: stvarna mapiranja/opseg/klijenti, SMTP dostava, notification/original-
created/native-removal dokazi, merenje transporta, spoljni monitor i pregledani
readiness artefakti još nedostaju. Predlog promene sedmodnevnog/`soak_72h` gate-a
automatski je odbijen i čeka posebno korisničko odobrenje; aktuelni kod je
nepromenjen. [Produkcioni pregled](../PRODUCTION_READINESS.md).

Ollama je iz zasebne službene Docker slike `ollama/ollama:0.40.12`, vezane za
digest u `compose.diagnostics.yaml`. Verzija je proverena prema
[službenom release-u](https://github.com/ollama/ollama/releases/tag/v0.40.12),
a način CPU rada prema [Ollama Docker dokumentaciji](https://docs.ollama.com/docker).
Model i image se ne osvežavaju automatski na drugi tag.

## Granice procesa i podataka

Deployment putanja je `/opt/booking-bridge-diagnostics`, odvojena od bridge
pilota/produkcije. Qwen radi kao UID 10002, sa read-only root filesystem-om,
bez capabilities, bez Docker socket-a, SSH ključa, REST pristupa, bridge baze
ili SMTP tajni. Jedini trajni volumen je `booking-bridge-diagnostics_ollama_state`.
Novi volumen se inicijalizuje sa vlasnikom 10002 i dozvolama 0700.

Model sada ima najviše 8 GiB RAM-a bez dodatnog swap-a, 2 CPU-a, jedan paralelni
zahtev, jedan učitan model i kontekst 4096. Pregledani request koristi `num_batch=64`.
`OLLAMA_NO_CLOUD=1` isključuje cloud funkcije.
Postavke su proverene u
[izvornom kodu izabrane verzije](https://github.com/ollama/ollama/blob/v0.40.12/envconfig/config.go).
Službeni model se preuzima posebnim privremenim `bootstrap` profilom sa izlaznom
mrežom. Taj downloader se posle preuzimanja zaustavlja i uklanja; model ostaje
u sopstvenom volumenu. Završni Qwen servis je samo na internoj Docker mreži.
Compose traži host port isključivo na `127.0.0.1:11434`, ali Docker 29 na
`internal:true` mreži ne pravi taj host listener: stvarni published port je null.
To nije javni endpoint; klijent na istoj internoj mreži koristi `http://qwen:11434`.
Host operator može proveravati privatni bridge IP bez dodavanja spoljne mreže.

`keep_alive=-1` zadržava već učitan model u memoriji. To nije zamena za
preload posle restarta procesa/hosta; dijagnostički klijent mora tada poslati
novi preload ili prvi zahtev. [Službeni keep-alive ugovor](https://docs.ollama.com/faq#how-do-i-keep-a-model-loaded-in-memory-or-make-it-unload-immediately).

Trusted keeper, collector i analyzer rade kao UID 10001; samo model je UID 10002.
Observation i diagnostic_state volumeni pripadaju 10001, pa analyzer može čitati
collector-ove privatne 0600 opažaje bez otvaranja pristupa drugim korisnicima.
Collector dobija samo read-only pristup pregledanoj bridge SQLite bazi i piše
sanitizovane opažaje u zaseban direktorijum. Analizator dobija samo te opažaje
read-only, sopstveno stanje i odobren SMTP secret. Analizator nema bridge bazu,
Docker socket, administratorske tajne ili kontrolni interfejs. SMTP slanje
obavlja statičan kod za odobrenog primaoca; model ne bira proizvoljnog primaoca.

SQLite WAL baza može ostati bez WAL/SHM fajlova između kratkih writer konekcija.
Tri stvarne izolovane RO provere pilota dale su neuspeh/uspeh/neuspeh; zato
poseban statični keeper održava read-only/query_only konekciju na trusted RW
mount-u, samo radi SQLite koordinacionih fajlova. Nema application SQL upisa,
Store/Gateway-a, mreže ili AI ulaza. Collector ostaje na RO mount-u i čeka
keeper healthcheck. Ovo je unapred konfigurisan operatorov helper; nije popravka
koju je model naložio ili izvršio.

Collector healthcheck čita samo svoj postojeći JSON: schema 1 i `collected_at`
star najviše 90 s, bez ispisa sadržaja. Analyzer start čeka i collector i Qwen
healthcheck; njegov status mora biti svež do 120 s, sa `diagnostics_only=true`,
`repairs_enabled=false` i uspešnim modelom, model self-testom i konfiguracijom
email-a. Nedostajući SMTP zato znači unhealthy servis, dok proces nastavlja
dijagnostiku i čuva status. Healthcheck ne pokreće popravku ili slanje poruke.
Logovi u pripremljenom Compose-u su json-file, najviše tri fajla po 5 MB za
svaki servis. Ove nove log opcije ne zahtevaju restart postojećeg modela u ovoj
fazi; izbegavati njegovu rekreaciju pri odvojenom uključivanju Python servisa.

## Dokaz modela i uključivanje ostatka

Posle download-a treba proveriti image digest, model digest, Q4_K_M detalje,
resurse i samo loopback port. Sintetički `/api/chat` test koristi `think=false`,
JSON schema, `stream=false`, `keep_alive=-1` i ograničenu dužinu odgovora; ne
šalje korisničke podatke. `/api/ps` nakon testa potvrđuje trenutno učitan model.
Kratak test ne dokazuje dugotrajnu stabilnost ili kvalitet svih budućih dijagnoza.

Booking servisi, njihove baze i callback pretplate se ne menjaju pri instalaciji
modela. Collector/analyzer i slanje pravih dijagnostičkih email-ova imaju zaseban
pregled konkretne slike, tajni, ulaza i testova. SMTP pristupi se ne ispisuju i ne
ulaze u source release. LLM odgovor je savet vlasniku, nikada nalog za izvršavanje.

## Istorijski početni dokaz instalacije modela — 28.10.2026.

[Sanitizovan dokaz](../evidence/diagnostics-20261028-model-install.json) potvrđuje
uspešnu nezavisnu instalaciju i dva sintetička JSON schema zahteva:

| Provera | Rezultat |
|---|---|
| Ollama | 0.40.12, pinned image digest iz Compose-a |
| Model | `qwen3.5:4b`, GGUF/Q4_K_M, 4.2B, 3.324 GB na disku |
| Model digest | `d8b0f5e9760cd1682034f292d7ef72ec46f432149be0df7574bf2d6e92e38c04` |
| Prvi zahtev | 39.902 s ukupno; 25.799 s učitavanje; validan JSON |
| Drugi zahtev | 8.270 s ukupno; 0.013 s učitavanje; validan JSON |
| Brzina generacije | Oko 2.7–3.2 tokena/s uz 2 CPU ograničenje |
| Rezidentnost | `/api/ps` potvrđuje CPU model, context 4096, keep-alive datum u 2319. |
| Proces pri prvoj instalaciji | UID 10002, read-only root, tada 6 GiB limit, bez tadašnjeg OOM-a ili restartova; naknadni OOM i korekcija 8 GiB opisani su iznad |
| Mreža | Internal bridge; stvarni host published port null, nema javnog listener-a |
| Podaci i poruke | Samo sintetički ulaz; 0 account reads/upisa i 0 email-ova |

Privremeni downloader je zaustavljen i uklonjen; model ostaje u svom trajnom
volumenu. Ovaj dokaz ne aktivira collector/analyzer ili booking izvršioca.
Na izmerenom CPU-u 500 izlaznih tokena može trajati više od 180 sekundi.
Ograničiti dijagnostički odgovor i meriti reprezentativan zahtev; deterministički
nalaz/alarm ne treba da zavisi od uspeha ili brzine LLM zaključka.

## Stalne kontrole i sintetički testovi

Collector na 30 s proverava postojeći keš i trajnu evidenciju, bez account API
poziva. Analyzer na 60 s obrađuje nalaze i red poruka; Qwen pregled dobija na
300 s u posebnoj niti. Default HTTP timeout je **240 s**, rok review/`--once`
**245 s**, a dnevni sedmočlani self-test ima ukupan rok **1720 s**. Rokovi su
ograničenja čekanja, ne obećanje izvršenja. Spor/nedostupan model ne odlaže
deterministički nalaz.
Otkrivanje i slanje nisu obećanje latencije ispod 60 s.

| Provera | Očekivan nalaz |
|---|---|
| Preklapanje istog zaposlenog, sveži podaci i potvrđen kapacitet 1 | Potvrđeno preklapanje, uključujući buffer |
| Jednaki/vrlo slični termini sa različitim target ID-evima | Kandidat za duplikat; nema automatskog brisanja |
| Pending i canceled termini, tačno susedni efektivni intervali | Pending zauzima; canceled i nepreklopljeni susedi ne daju lažni konflikt |
| Owned kopija promenjena, nestala ili pogrešno canceled | Neslaganje uz zahtev za pregled; bez ponavljanja upisa |
| Neizvesna namera, star red, review/dead događaj | Operativni nalaz i obaveštenje |
| Nedostajući, zastareli ili budući snimci | Nedovoljno dokaza; nikada tvrdnja o potvrđenom duplom terminu iz starog keša |
| Model nedostupan, neispravan odgovor, izmišljena referenca ili tool call | Fiksan dijagnostički kvar; ništa iz odgovora se ne izvršava |
| SMTP prekid, neizvestan DATA ishod, restart i ponovljeni nalaz | Trajni outbox, dedupe/ograničenje; neizvestan ishod se ne ponavlja naslepo |

`watchdog_eval` izvršava sedam sintetičkih modelskih scenarija: zdrav susedni
termin, potvrđeno preklapanje, kandidat za duplikat, izvor otkazan/target aktivan,
neizvesna namera, zastareli konfliktni podaci i zdravo preklapanje sa otkazanim
terminom. Analyzer ih ponavlja posle početnog pregleda i zatim dnevno,
u posebnom poslu; početna dnevna serija je pending u 17:25:14 UTC preseku, dok je
ručna stvarna V3 serija već završena sa 7/7 PASS. Ovi testovi
koriste samo izmišljene reference/vremena, ne kreiraju rezervacije i ne šalju email.

```text
python -m booking_bridge.watchdog_eval --model-url http://qwen:11434 --output /diagnostics/manual-model-tests.json
```

Modelski izlaz je ograničen na assessment/confidence/proverene reference i
predefinisane šifre pregleda. Nema slobodnog teksta u email header-ima/telu,
proizvoljnih URL-ova, primalaca ili izvršivih komandi. Neuspešna ili čista AI
procena nikada ne uklanja postojeći potvrđeni nalaz. Reference i recommendation
šifre su ograničene na opažene reference/podržane kategorije iz istog paketa.
Završen AI kandidat se proverava tek uz sadašnji validan paket: semantički
digest mora odgovarati; promenjeno, rešeno ili nestalo opažanje sprečava
objavu starog kandidata. Keširana procena takođe zahteva isti digest. Pregled je
ograničen uzorkom i signalima koje sistem može dokazati; ne predstavlja
garanciju otkrivanja svakog budućeg buga.

Za vlasnika koji želi da identifikuje termine iz hash reference u poruci:

```text
python -m booking_bridge.watchdog_resolve --database /private/bridge.sqlite --observation /private/latest.json --reference HASH_IZ_PORUKE
```

Resolver je samo operatorov read-only alat. Prikazuje calendar ID-eve/vremena i
fiksne šifre, bez klijentskih kontakata ili payload-a. Model nema ovaj alat ili
pristup bazi i ne može da ga pozove.

## Email podešavanje i preostali unos

SMTP koristi isključivo potvrđeni TLS na 465 ili STARTTLS na 587. Samo korisnikov
izričito zadati primalac je prihvaćen; model ne bira adresu. [Detalji outbox-a](../WATCHDOG_ALERTS.md).
Privatni `diagnostic-smtp.env` drži samo SMTP metadata i putanju do tajnog fajla;
lozinka je u posebnom secret-u, owner 10001 i mode 0400. Nema REST/SSH tajni.

Aktuelno podešavanje i uspešan kontrolisani test od 30.10. potvrđuju
[SMTP receipt](../evidence/production-20261030-smtp-setup.json) i
[healthy runtime](../evidence/production-20261030-post-smtp-runtime.json).
Sender je `wukinski021@gmail.com`, primalac `aaaazzzz.5226@gmail.com`;
4 SMTP prihvatanja nisu dokaz inbox dostave. Test ne ponavljati bez potrebe.

### Istorijski SMTP presek — 28.10.2026

Trenutno je lokalni `booking_bridge/secrets/diagnostic-smtp-password.txt` prazan.
Server ima prazan placeholder dok ne bude dostavljen pregledani SMTP pristup.
Analyzer je pokrenut; runtime u 17:25:14 UTC potvrđuje `email_configured=false`,
`smtp_not_configured` i `healthy=false`, jednu pending outbox poruku i
**0 SMTP pokušaja**. Nedostajući pristup čuva red bez pokušaja slanja; to nije
dokaz inbox dostave.
Keeper/collector/model rade nezavisno; to ne ispunjava email uslov produkcije.

### Postupak za buduću promenu pristupa ili novi pregledani test

Za Gmail koristiti app lozinku prema [Google uputstvu](https://support.google.com/accounts/answer/185833),
uz uključenu verifikaciju u dva koraka, ili zasebno odobren SMTP relay/OAuth.
Lozinku ne slati u razgovoru ili komandnom argumentu. Metadata drugog naloga
zahteva pregled host/user/from polja i restart samo analizatora. Izmena sadržaja
postojećeg mounted password fajla učitava se na sledećem poll-u; atomska zamena
host fajla menja inode i zahteva ponovni bind/restart analizatora.

`--test-email` koristi isti `/diagnostics/watchdog.lock` i trajni outbox kao
residentni daemon. Ako analyzer već radi, prvo uredno zaustaviti **samo analyzer**
i sačekati da se zaustavi, zatim pokrenuti jednokratnu komandu u istom
konfigurisanom okruženju sa postojećim `/diagnostics` volumenom i SMTP secret-om.
Posle provere ponovo pokrenuti samo analyzer; Qwen, keeper i collector ostaju
uključeni. Paralelni test uz residentni daemon završava se lock greškom.
Ne koristiti novu outbox bazu ili drugu state putanju radi zaobilaženja
deduplikacije ili dnevnih limita. Analyzer je na ovom preseku uključen, pa
jednokratni test zahteva navedeno uredno zaustavljanje i ponovni start.

```text
python -m booking_bridge.watchdog --input /observations/latest.json --state /diagnostics --model-url http://qwen:11434 --test-email
```

Test bira baš svoj alert ID, bez slanja neke stare kritične poruke umesto testa.
SMTP prihvatanje nije inbox dokaz; inbox se proverava odvojeno. Bez uspešnog
testa dostave ne uključivati produkciju. Stari interaktivni
`QWEN_CRITIQUE_AGENT.md` nije runtime prompt i nema ovlašćenje za automatske popravke.
