# Operativni pregled pre aktivacije — 28.10.2026.

## Najnoviji status posle operativnog pregleda

Korisnik je sada odobrio produkcionu aktivaciju i potreban administratorski
transfer worker-u. To još nije izvršeno; nema potrebe ponavljati opšte odobrenje.
Najnoviji prethodni uslov je rezidentni Qwen3.5 4B za bugove/dvostruke termine
i email vlasniku, bez popravki ili booking upisa iz modela.

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

Raniji OOM i semantički neuspeh ostaju istorija u [primopredaji](../../AI_HANDOFF.md).
[Operativno uputstvo](DIAGNOSTICS_RUNBOOK.md).

Produkcioni gate i dalje blokira dokaze starije od sedam dana i zahteva
`soak_72h`. Predlog izmene automatski je odbijen i čeka posebno korisničko
odobrenje; nije primenjen. [Aktuelna politika](../PRODUCTION_READINESS.md).

[Pregledani held stage](../evidence/activation-staging-20261028-2eb16604-reconciliation.json)
usaglasio je istorijski raw/projected provenance završenog testa i sačuvao
originalni host prijem/ownership/kvote. Hold nije skinut; aktivne baze nisu
menjane i worker start nije dozvoljen. To rešava istorijski konflikt, bez
tvrdnje da su stvarna poslovna mapiranja, pokrivenost, trajanja ili resursi dokazani.

[Stvarni encrypted off-host backup i isolated restore](../evidence/offhost-restore-drill-20261028-6e619251.json)
završeni su u 12:50 UTC sa **14/14 provera**, uz očuvane redove/hash-eve/kvote i
priložene budžete. Ciphertext je prenet van VPS-a, privremeni server ključ
obrisan, restore ostaje pod hold-om. Unattended raspored još nije aktiviran.

Brojevi i tvrdnje o neinstaliranom modelu u početnom inventaru ispod su
**istorijski presek oko 11:27–11:31 UTC**, pre odvojenog dijagnostičkog rollout-a.

[Noviji TLS dokaz](../evidence/diagnostics-20261028-tls.json) potvrđuje validan
IP/DNS chain/hostname i Let's Encrypt YE1 cert tačnog veka 160h, sa oko 122h
preostalog važenja. Namenski timer je active/enabled; poslednja provera ima
exit 0 i certificate_not_yet_due, bez pokušaja/neuspeha obnove. Za cert-ove do
10 dana prag obnove je polovina veka, ovde 80h, pa obnova još nije dospela.
Ovo nije TLS kvar ili otvorena prepreka za produkciju; ne forsirati obnovu.

Read-only provera postojećeg VPS-a oko **11:27 UTC** nije menjala servise,
konfiguraciju, ključeve, rezervacije ili poruke. Sanitizovani lokalni inventar
je `booking_bridge/state/ops-audit-20261028.json`; ne sadrži env vrednosti ili
booking payload-e.

| Oblast | Stvarni nalaz |
|---|---|
| Procesi | Pilot API + receiver, slika `pilot-20261027-integration1`, oba running, bez restartova |
| Zaštita procesa | UID 10001, read-only root, ALL capabilities dropped, no-new-privileges |
| Pripremljena slika | `production-preparation-20261028`, image ID počinje `a3f938816314` |
| Disk | 200.80 GB slobodno od 206.90 GB |
| Liveness / readiness | 200 / 503 |
| Uzrok readiness | `booking_snapshot_stale`; occupancy snimci oko 74.590 s stari, heartbeat oko 1 s |
| Red | 3 done + 1 ignored, host owned links 0, neizvesne host namere 0 |
| Minutni check | Timer active/enabled, poslednji service failed / exit 1, bez spoljnog alarma |
| Satni backup | Timer active/enabled, poslednji service success / exit 0 |
| Postojeće kopije | 120 SQLite fajlova, ukupno 14.9 MB; najnoviji oko 27 min star, najstariji oko 4.96 dana |
| Dozvole kopija | Direktorijum 0700, fajlovi 0600, root vlasnik |
| TLS | I IP i DNS prolaze normalnu proveru lanca i hostname-a; cert do 02.11.2026. 14:34:01 UTC |
| Obnova TLS | `booking-bridge-certbot.timer` active/enabled; poslednji service success / exit 0 |

Readiness 503 je očekivana posledica završenog konačnog publisher procesa;
zdrav receiver ne osvežava podatke samostalno. Postojeće importovane blokade se
time automatski ne uklanjaju. Host tada nije imao istorijsku lokalnu ownership
vezu. Naknadni gore navedeni stage usaglasio je njen provenance; živa baza
ostaje nepromenjena, a pregledano stanje/profil prethode booking startu.

## Praktičan redosled prelaska

1. Sačuvati postojeći image, Compose, env i baze; ne brisati volumene ili stare
   kopije. Napraviti nov konzistentan SQLite snapshot i proveriti integritet.
2. Završiti pregled raw/projected događaja i vlasništva nad target rezervacijama.
   Ne zameniti originalne host hash-eve istorijskim lokalnim projekcijama.
3. Pripremiti novu zasebnu deployment putanju i pregledani release image.
   Popunjene secret fajlove držati pod `secrets/`, 0600/vlasnik 10001;
   administratorski pristup dobija samo worker. Kopiranje i aktivacija su zasebni
   konkretni koraci nakon završenih preduslova.
4. Popuniti tačan produkcioni profil i readiness manifest stvarnim pregledanim
   dokazima. Prazan simulation template ostaje blokiran. Nepoznata mapiranja,
   neizvesni upisi, neproverene poruke i latencija ne dobijaju fiktivne potvrde.
5. Pre starta pregledati config, private file dozvole, singleton lock, backup,
   restore karantin i plan povratka. Posle starta proveriti isti image/config,
   signed ingress, konačni target readback, trajne kvote i stvarnu native primenu.
6. Održavati obnavljanje TLS-a i postojeće kopije kroz prelazak. Preraspodelu
   proxy-ja, gašenje starog receiver-a ili promenu state volumena izvršiti tek uz
   tačno pregledanu migraciju; dva booking izvršioca ne smeju istovremeno raditi.

## TLS prag za ovaj server

Ovaj server koristi kratkotrajni IP sertifikat. Let's Encrypt shortlived
sertifikati važe oko 160 sati; monitorov opšti prag od 7 dana bio bi trajno
neuspešan i neposredno nakon obnove. Za ovaj konkretan server koristiti eksplicitno
`--tls-min-days 2`, uz postojeći timer obnove dvaput dnevno i spoljnu kontrolu.
To ne menja opštu CLI podrazumevanu vrednost i nije naredba za forsiranu obnovu.
[Let's Encrypt shortlived/IP ugovor](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability).

## Kopija van VPS-a i spoljni alarm

Postojeći `pilot_host_maintenance.py` pravi nešifrovane kopije na istom VPS-u i
nema automatsko proređivanje. Trenutni disk ne zahteva hitno brisanje tih kopija.
Novi `recovery` alat stvarno je napravio AES-256-GCM arhivu na serveru i proverio
je na obe strane prenosa, zatim vratio u novi izolovani fajl sa recovery hold-om.
Izvedena proba koristi zaseban privatni key direktorijum; dugoročna politika
treba da razdvoji decryption ključ od sinhronizovanog ciphertext stabla.

Vlasnikov privatni lokalni workspace sada ima stvarno prenetu šifrovanu arhivu
i held restore, sa [14/14 dokaza](../evidence/offhost-restore-drill-20261028-6e619251.json).
To ne potvrđuje cloud sinhronizaciju ili kontinuiran backup dok je računar
ugašen. Bezbedna dnevna/periodična politika, trajna destinacija, nezavisno
čuvanje ključa i potvrda cloud sinhronizacije ostaju naredni operativni posao.

Dropbox i Google Drive upload alati postoje u ovoj sesiji. Njihova dostupnost
ne daje VPS-u trajni OAuth token ili background uploader i ne dokazuje postojanje
neprekinutog backup posla. Za rad nezavisan od Windows-a treba izabrati postojeće
vlasnikovo skladište sa ograničenim serverskim write pristupom ili drugo već
postojeće odredište dostupno SFTP/S3/API-jem. Takav pristup u pregledanim pilot
env fajlovima nije konfigurisan.

Isto važi za spoljni alarm: nema konfigurisanog `BRIDGE_ALERTS_URL` ili
`BRIDGE_MONITOR_ALERT_URL`. Monitor može proveravati HTTPS/TLS izvan VPS-a i
slati samo fiksne šifre kvara na posebno izabran HTTPS sink uz `--send-alert`.
Pokretanje monitora na samom VPS-u ne otkriva potpuni pad tog VPS-a. Windows
scheduled task može biti privremeni spoljni posmatrač samo dok računar radi;
trajni spoljni nadzor zahteva postojeći stalno dostupan servis ili drugi host.
Nije poslat test alarm, niti su izmišljeni primalac ili pristupni podaci.

Contabo ima opcioni Auto Backup dodatak sa dnevnim off-server kopijama, ali
status tog dodatka za ovaj nalog nije poznat i nije dokazano šifrovanje/restore
ovog booking stanja. Ne kupovati ili uključivati dodatak na osnovu ovog pregleda.
[Contabo Auto Backup dokumentacija](https://docs.contabo.com/docs/servers-hosting/vps-auto-backup/).

## Šta može da se automatizuje kada su ulazi određeni

- Host timer: read-only worker health, disk, backup age i izlaz sa fiksnim šiframa.
- Šifrovani konzistentni backup sa trajnim kvotama i lokalnim manifestom.
- Upload samo ciphertext-a na odobreno off-host odredište, sa ograničenim
  write pristupom i nezavisnom kontrolom poslednje uspešne kopije.
- Spoljni HTTPS/TLS monitor, bounded alarm politika i provereni izabrani sink.
- Periodičan izolovani restore sa recovery hold-om, bez pokretanja booking upisa.

Prvobitni inventar bio je read-only. Naknadni dijagnostički rollout, pregledani
held stage i jednokratna off-host restore proba imaju zasebne dokaze iznad.
Produkcija ostaje isključena. V4 analyzer radi samo dijagnostiku postojeće pilot
baze; prvi live AI pregled je uspešan, dnevni self-test pending, SMTP nedostaje
i health ostaje false. Nema prenosa administratorskih pristupa, email-ova,
popravki iz modela ili ponavljanja završenog booking ciklusa.

## Resursi za rezidentnu dijagnostiku — oko 11:31 UTC

Novi zahtev je lokalni Qwen3.5 4B kao dijagnostičar koji prijavljuje vlasniku,
bez ovlašćenja za popravke. Read-only inventar potvrđuje x86_64 AMD EPYC,
6 logičkih CPU-a i 11.68 GiB RAM-a; dostupno oko 10.92 GiB. Nema swap-a,
`nvidia-smi` ili `/dev/dri`. Pilot receiver koristi oko 60 MiB, API oko 37 MiB.
U tom trenutku Ollama još nije bila instalirana. Naknadni dokaz instalacije,
rezidentnosti i CPU merenja naveden je iznad; ne koristiti ovaj početni inventar
kao aktuelni status. Semantički kvalitet se proverava odvojeno od instalacije.

Nema instaliranog sendmail/postfix/msmtp/mail/exim programa ili odgovarajućeg
servisa, niti SMTP konfiguracije na pregledanim standardnim putanjama. TCP
veze ka Gmail portovima 25, 587 i 465 uspevaju; nije poslata nijedna SMTP
komanda, autentikacija ili poruka. Dostupan port ne dokazuje mogućnost slanja,
dozvoljenog pošiljaoca ili inbox isporuke. Potrebni su stvarni pregledani SMTP
submission/OAuth pristup ili izabrani postojeći relay.

Zabranu popravki sprovesti i pravima procesa: model/diagnostic service ne dobija
Docker socket, root SSH ključ, REST administrativne tajne, bridge bazu ili
systemctl interfejs. Ulaz su sanitizovane fiksne šifre i ograničeni metapodaci;
slanje ide kroz statičan SMTP kod samo odobrenom primaocu. Sam prompt nije
zamena za ovaj procesni i pristupni razmak.
