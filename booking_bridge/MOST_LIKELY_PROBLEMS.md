# Najverovatniji problemi i potvrđeni nedostaci

Ovaj registar razlikuje dokazani nedostatak, poznato ograničenje i neprovereno
ponašanje udaljenog sistema. Procene prioriteta nisu izmišljeni procenti
verovatnoće. Lokalni test ne potvrđuje ponašanje udaljenog naloga.

| ID / prioritet | Nalaz i dokaz | Posledica / prepoznavanje | Postupak i uslov zatvaranja |
|---|---|---|---|
| R01 / P0 | **Potvrđen nedostatak:** noviji događaj van pilot opsega nije sprečavao kasniji stariji događaj. Reprodukovano isključivo simulatorom. | Moguće kreiranje zastarele kopije kod ranijeg zaposlenog. | Trajno najnovije poznato stanje uključuje ignorisane događaje; testirati oba redosleda, restart, retry i `test:true`. Nema udaljenog pilota pre ispravke. |
| R02 / P1 | **Poznato ograničenje:** standardni SrediMe webhook nema kontakte. | Novi opaque customer ID završava na proveri. | Ručno potvrđena veza ili odobreni kontakti. Ne izmišljati podatke niti spajati različite osobe. Za produkciju je potrebna poslovna odluka. |
| R03 / P1 | **Neprovereno:** kopija rezervacije može izazvati SB poruke. | Duple potvrde, podsetnici ili poruke o otkazivanju. | Test sa kontaktima vlasnice; zabeležiti stvarne poruke pre produkcione potvrde. Nema izmišljenog `skip_notifications` parametra. |
| R04 / P1 | **Poznato ograničenje:** dostupnost pri izmeni može uključivati sopstveni stari termin. | Legitimno pomeranje/promena usluge prijavljeni kao konflikt. | Proveriti podržan način sa test rezervacijom/podrškom; ne otkazivati i ponovo kreirati automatski. |
| R05 / P1 | **Poznato ograničenje:** create timeout ne dokazuje neuspeh. | Moguć duplikat pri slepom ponavljanju. | Sačuvana namera, čitanje ishoda i ručna potvrda vlasništva ako rezultat nije poznat; bez ponovnog create na osnovu praznog čitanja. |
| R06 / P1 | **Poznato ograničenje:** rezervacije i rasporedi imaju polling, a SrediMe uvoz dodatno kasni. | Privremeno slobodan termin koji je zauzet u drugom sistemu. | Meriti latenciju u pilotu; dogovoriti operativni postupak. Trenutni satni pregled rasporeda nije potvrđen kao prihvatljiv za poslovanje. |
| R07 / P1 | **Neprovereno:** uklanjanje poslednjeg bloka i prazan feed. Dokumentovan je backoff do 12 h i stop posle 100 praznih/neuspelih provera. | Stara blokada ili dug zastoj uvoza. | Izolovani test i potvrda SrediMe podrške o uklanjanju/resetu. Bez lažnih rezervacija za održavanje feeda. |
| R08 / P1 | **Potvrđeno dosadašnje ponašanje:** jedna nejasna namera/izmena porekla zaustavljala je sve izlazne feedove. | Kvar jednog zaposlenog utiče na ostale. | Pronaći prethodnog, ciljnog i stvarnog zaposlenog; pauzirati njihove feedove. Ako opseg ne može da se utvrdi, zadržati globalnu zaštitu. |
| R09 / P1 | **Neprovereno:** referentna usluga može imati poseban raspored; trajanja/buffer/resursi mogu imati drugačiju semantiku. | Previše blokiranog ili nedovoljno blokiranog vremena. | Proveriti isti tretman, dodatno vreme, raspored i resurse. Posebno testirati pauzu, odsustvo i ručnu blokadu na nalogu. |
| R10 / P1 | **Rešeno 2026-10-22:** zvanični MCP radi; identitet `studioandjelija`, šest zaposlenih i 494 usluge potvrđeni. | MCP potrošnja ostaje izvan lokalnog REST brojača. | Katalog pregledan u `evidence/mcp-tool-review.json`; izvršavati samo odobrene radnje. |
| R16 / P1 | **Potvrđen neuspeh izolacije:** REST POST/PUT zaposlenog ignorišu `services: []` i novom zaposlenom dodeljuju 12 starih usluga. | Skrivenost sama ne dokazuje isključenje iz Any Employee toka. | Pokušaj ID 8 povučen; baseline potpuno vraćen. Nova kreiranja blokirana do proverenog metoda izolacije. Dokaz: `evidence/pilot-provisioning-check.json`. |
| R11 / P1 | **Rizik pri opterećenju:** čekanje na SQLite lock može ugroziti webhook rok. | Spor odgovor / ponovljene isporuke. | Kratko ograničeno čekanje, obrada DB rada van async petlje i 503 bez potvrde prijema ako upis nije uspeo. Testirati stvarno zaključavanje i paralelni HTTP. |
| R12 / P1 | **Neprovereno:** Linux image, trajni disk, TLS i restore na hostingu još nisu izvršeni. | Nemoguć start, gubitak DB ili ponovno pravljenje rezervacija posle starog backup-a. | Build na odabranom hostu, jedan worker, šifrovan backup i kontrolisan restore; bez otvaranja produkcije pre provere. |
| R13 / P2 | **Poznato ograničenje:** lokalni API brojač ne vidi MCP i druge aplikacije. | Dnevno ograničenje ili throttling. | Izveštavati potrošnju direktnog klijenta i izdvojeno MCP aktivnosti; ne tvrditi da vidimo ukupan broj serverskih zahteva. |
| R14 / P2 | **Konfiguracioni rizik:** lokalni CSV može zameniti JSON mapiranje. | Neočekivano prazne ili drugačije veze. | Dijagnostika prikazuje izvor i broj mapiranja; suprotstavljeni izvori se odbijaju umesto tihog prepisivanja. |
| R15 / P1 | **Poznato ograničenje:** SQLite fajl sam nije šifrovan. | Izlaganje ID-eva ili odobrenih kontakata pri pristupu disku/backup-u. | Servisni korisnik, šifrovan disk/backup, bez tajni u image-u, logovima i javnim dokazima. |

## Rezultat odobrene dorade

Završno prošlo **260 testova**: 128 testova povezivača i 132 testa postojećih
modula; nula grešaka, padova ili preskočenih provera. Lokalni HTTP test sa
odvojenim procesima takođe prolazi. Rezultati su u
[`evidence/followup-validation.json`](evidence/followup-validation.json) i
[`evidence/followup-test-results.xml`](evidence/followup-test-results.xml).

- **R01 — ispravljeno i lokalno provereno:** najnovije poznato stanje se trajno
  upisuje i za ignorisane događaje, migrira iz stare baze i ponovo proverava pred
  slanje upisa. Pokriveni su restart, retry, oba redosleda i zasebni `test:true`.
  Poslednja lokalna provera ne može atomski zaključati udaljeni SrediMe/SB sistem;
  promena koja nastane tokom već poslatog zahteva i dalje zahteva usklađivanje.
- **R08 — izmenjeno i lokalno provereno:** poznati opseg zaustavlja prethodnog,
  ciljnog i poznatog stvarnog zaposlenog. Stari/nepoznati opseg zadržava globalnu
  zaštitu. Nejasan create se i dalje ne ponavlja naslepo.
- **R11 — ublaženo i lokalno provereno:** SQLite čeka najviše 2 sekunde; upis ide
  izvan async petlje, a neuspeo trajni upis vraća 503. Konkurentni prijem ne blokira
  liveness i duplikati ostaju jedan zapis. Stvarni proxy/hosting još treba testirati.
- **R14 — ublaženo:** konflikt JSON/CSV izvora se odbija, a dijagnostika prikazuje
  izvor i broj aktivnih mapiranja. Poslovni upisi dijagnostičkog klijenta su zabranjeni.
- **Ažurirano 2026-10-22:** R10 je zatvoren stvarnim MCP čitanjem. Kapacitet
  paketa je potvrđen. Za R12 lokalni Docker build, 171 Linux test i read-only
  HTTP smoke prolaze; javni hosting, TLS i off-host restore još nisu izvršeni.
  R16 i udaljeni pilot ostaju otvoreni: bez potvrđene izolacije nema novih
  test zaposlenih. Stvarni resursi, obaveštenja i prazan SrediMe feed još čekaju
  praktičnu proveru. Nema aktivacije produkcije.

## Potvrđene granice rada

- Test zaposleni se pripremaju na postojećem nalogu; još nisu napravljeni.
- Poslovna pravila ostaju nepotvrđena. Odobrenje plana nije odobrenje tih pravila.
- Import 490 usluga se ne ponavlja; postojeće usluge/zaposleni se ne prepravljaju radi pilota.
- MCP služi interaktivnom radu, a trajni API servis izvršava sinhronizaciju bez otvorenog razgovora.

## Izvori

- Lokalni `SrediMe for Developers.html`, verzija 2026-09-10-1.
- [Zvanični SimplyBook MCP Connector](https://help.simplybook.me/wiki/Special:MyLanguage/MCP_Connector_custom_feature).
- [OpenAI Docs — MCP povezivanje i dozvole](https://developers.openai.com/codex/mcp).
- Lokalni kod i dokazi u `evidence/`; konačni rezultati ove implementacije beleže se zasebno.
