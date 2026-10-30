# Naredni posao posle završenog probnog ciklusa

## Najnoviji nalog i redosled — 28.10.2026

Korisnik je sada tražio završetak svih preduslova i **uključivanje produkcije**
na postojećem VPS-u, uključujući potreban pregledani prenos administrativnog
pristupa worker-u. Ne tražiti ponovo ta opšta odobrenja. Naknadni obavezni
preduslov je rezidentni Qwen3.5 4B koji prijavljuje bugove/dvostruke termine
vlasniku email-om, bez popravki, booking upisa ili upravljanja servisima.

1. Stvarna završna V3 modelska provera ima [7/7 PASS](../evidence/diagnostics-20261028-model-eval-final.json),
   817.221 s i zero OOM delta uz 8 GiB/num_batch=64.
   [V4 analyzer je pokrenut](../evidence/diagnostics-20261028-python-rollout.json),
   kontejner od 17:21:37 UTC, prvi heartbeat 17:21:52 UTC; keeper/collector healthy.
   [Pregled u 17:25:14 UTC](../evidence/diagnostics-20261028-runtime-status.json)
   potvrđuje prvi uspešan live AI pregled i 0 SMTP pokušaja; health je false zbog
   praznog SMTP-a i početni dnevni self-test ostaje pending. Pratiti taj posao
   bez ponavljanja završenog ručnog sedmočlanog testa.
   [V3/V4 ekvivalencija](../evidence/diagnostics-20261028-v3-v4-protocol-equivalence.json)
   dokazuje isti SYSTEM/schema/sedam request body-ja i revalidirane stvarne V3
   odgovore; sedam inference poziva nije ponovljeno na V4.
   Raniji neuspešni rezultati ostaju istorija u [primopredaji](../../AI_HANDOFF.md).

2. Završiti pregledani SMTP pristup i dokaz stvarne inbox dostave vlasniku.
   SMTP password je [prazan uz privatni ACL](../evidence/diagnostics-20261028-smtp-private-acl.json);
   nema autentikacije ili poslatih dijagnostičkih email-ova.
   [Postupci](../deploy/DIAGNOSTICS_RUNBOOK.md). Model ne bira primaoca ili komande
   i ne dobija pristup bazi/booking akreditivima.
3. [Held stage usaglašavanja](../evidence/activation-staging-20261028-2eb16604-reconciliation.json)
   završio je pregled istorijskog raw/projected provenance za tačan završeni
   booking uz očuvan originalni host prijem, ownership, završenu nameru i kvote.
   **Istorijski hash diff više nije nerešen identitetski konflikt tog testa.**
   Hold ostaje aktivan, aktivne baze nisu menjane i worker start nije dozvoljen.
4. Dokazati stvarna mapiranja i pokrivenost zaposlenih/usluga, ispravna trajanja
   i resurse, produkcioni opseg i postupak za nepoznate klijente. Dokazati
   notification/original-created/native-removal ponašanje i meriti transport.
   Ne prenositi testni binding na stvarno osoblje. To su činjenice
   koje nedostaju, odvojene od već datog odobrenja za aktivaciju.
5. Sačuvati [stvarni off-host backup/restore dokaz](../evidence/offhost-restore-drill-20261028-6e619251.json):
   14/14 provera, originalni redovi/hash-evi/budžetski dokazi očuvani, privremeni
   server ključ obrisan i restore pod hold-om. Sledeći backup posao je trajni
   raspored/skladište/key custody; jednokratna proba već je završena.

V4 runtime slika je `sha256:7b11e4fbc5c7335e763677909243553f38f050ead7101271aec723c06c7210b9`.
Stvarni sedmočlani modelski test pripada V3 slici `sha256:1ad9a4fa512e969cb193f50dab25e6f4ff2a1588b605554cc6544c64be250608`.

V4 softverska validacija: [Windows 756 PASS](../evidence/diagnostics-20261028-windows-tests.xml),
[Linux 746 PASS + 10 skip](../evidence/diagnostics-20261028-linux-tests.xml)
i [HTTP smoke PASS](../evidence/diagnostics-20261028-linux-smoke.json).
To su odvojeni dokazi od stvarne V3 modelske provere.

**Produkcija još nije aktivirana; REST administratorski pristupi nisu preneti.**
Healthy collector ne osvežava zastareli booking/buffer keš. Stvarni capture i
execution profili imaju require_subminute_availability=false; cilj <60 s iz
pilota nije potvrđen vlasnikov SLA. Postojeći 72h/7-dnevni softverski gate je
naša ranije uvedena politika, ne novi korisnikov uslov. Predložena izmena
automatski je odbijena, nije primenjena i čeka konkretno korisničko odobrenje
koje je root već zatražio. Trenutni kod zadržava blokadu isteka i `soak_72h`.
Ne izmišljati dokaze ili workaround. Završeni ciklus ispod se ne ponavlja.

[TLS je uredan](../evidence/diagnostics-20261028-tls.json): 160h short-lived cert
ima oko 122h preostalog važenja, timer radi i obnova još nije dospela. Za taj
deployment koristiti `--tls-min-days 2`, ne generički 7; ne uvoditi forsiranu
obnovu kao novi posao/blokadu.

## Sačuvani istorijski probni rezultat

Poslednje potvrđeno živo stanje **27.10.2026,14:45 UTC**. Kontrolisani test je završen:
source **9VPLV6E** → target **5**, create kroz stvarni updated resync, move,
cancel i sva tri ACK-a potvrđeni. Source je **-101**, target **canceled**.
Callback 6 je zatvoren, employee 11772 bookable=false/svi dani off, service 233160
inactive; nezavisan readback potvrđen. [Dokaz ciklusa](../evidence/integration-20261027-booking-cycle.json),
[source završetak](../evidence/integration-20261027-source-final.json),
[host završetak](../evidence/integration-20261027-live-final-after-cleanup.json).

**Ne ponavljati create/resync/move/cancel ovog testa.** Nema otvorene dozvole
za taj ciklus: korisnik ga je odobrio i on je izveden. Ne kontaktirati podršku;
postojeći prevodi su prihvaćeni za ovu fazu.

## Lokalno pripremljeno 28.10.2026

`pilot_supervisor` dodaje trajne rezervacije pokušaja/cooldown, GET-only capture,
minimalni pinned SSH publish i lokalnu proveru stvarne svežine potvrđenog paketa.
Staged capture sada proverava owned target drift pre objave. Windows helper i
konkretan `.local.xml` su pripremljeni, task i trigger isključeni, ništa nije
registrovano. [Postupci i ograničenja](../deploy/PERSISTENT_PUBLISHER.md).

Mapiranja imaju odvojene webhook/native kolone i strogu validaciju;
native metadata ne rutira događaje. [Format](../mappings/README.md).
Stvarni privatni profili nisu migrirani. Nov kod nije postavljen na VPS,
ne obrađuje source red i nije korišćen za nove žive probe.
[Offline Windows provere](../evidence/development-20261028-windows-tests.xml):
**446/446 prolaza**, bez novih Linux/deploy tvrdnji.

## Sledeći posao

Korisnik je najpre izabrao trajni rad na postojećem VPS-u nezavisno od računara
i odobrio pripremu, zatim i aktivaciju uz preduslove iznad. [Produkcioni pregled](../PRODUCTION_READINESS.md)
opisuje implementirani wrapper/gate/Compose/monitor/backup i stvarno poređenje
stanja. Lokalni supervisor ostaje neuključen fallback. **562 Windows testa**,
**558 Linux prolaza + 4 platformske provere preskočene** i HTTP smoke na obe
platforme prolaze; zasebna validation slika nije deploy. Produkcioni ledger
ima sve odluke pending, a prenos administratorskih pristupa nije izvršen.

1. Sačuvati [izvorni state diff](../evidence/production-20261028-state-review.json):
   raw/projektovani hash konflikti tri događaja, head/guard razlike i lokalna owned
   veza koja nedostaje hostu. Sačuvati oba izvora i tačan per-booking provenance;
   nema automatskog merge-a, prepisivanja hash-eva ili zamene host baze lokalnom.
   Naknadni pregledani stage naveden je iznad; isti istorijski konflikt ne
   prijavljivati ponovo kao nerešenu prepreku.
2. Koristiti **stvarne opaque webhook ID-eve kao autoritativne ključeve**
   budućeg profila ili pregledano eksplicitno mapiranje. Runtime već tretira
   ID-eve kao stringove. Native UI brojeve držati odvojeno; ne pokušavati
   globalno dekodiranje ili povezivanje po sličnom imenu/kontaktu.
3. Sadašnji privatni binding39VLN1/V2N8N4/7E9514 →11772/233160/873710 važi
   **samo za potvrđeni booking 9VPLV6E**. Sačuvani su raw hash/IDs/type i trag
   izvršenja. Nemoj tvrditi da je implementiran opšti resolver ili širiti taj
   dokaz na stvarne zaposlene/klijente.
4. Za budući kontinuirani pilot pripremiti ownership/loop zaštitu, obnovu
   svežine, nadzor reda, ograničene retry/recovery postupke i povratak na
   prethodno stanje. Publisher deo tih zaštita sada ima offline provere;
   budući serverski readback i callback lifecycle proveravaju se odvojeno.
   API i serverski worker koriste istu bazu, bez lokalnog copy/ACK koraka.
   Originalni created izgubljen je pre dispatch-a; buduće
   callback aktiviranje treba obuhvatiti prijem i obradu queued događaja,
   sa jasnim vlasnikom i proverom gašenja.
   Serverski worker sada koristi isti Worker/Scheduler i ima produkcioni gate;
   nerešena namera pri startu zahteva prvo readback/usaglašavanje. Backup restore
   ostaje held i kad se kopira sama baza. Jednokratni off-host restore sada je
   dokazan sa 14/14 provera; naredni posao su trajni raspored/key custody i
   nezavisan alarm. `soak_72h` i dalje postoji u kodu jer je predlog promene
   automatski odbijen, iako nije novi vlasnikov uslov.
5. Novi živi test raditi tek kada postoji nova promena ili konkretan zahtev za
   proveru. Relevantne provere vezati za novu izmenu; ne ponavljati uspešan
   ciklus/puni build radi ponovnog potvrđivanja već poznatog stanja.

## Šta već radi, a šta još nije dokazano

Host ima API+pilot_receiver, simulation/reads off, bez administratorskih
akreditiva. Lokalni publisher je konačan proces; zavisi od uključenog računara,
pa sadašnji readiness200 nije trajna garancija. Posle isteka svežine može biti
503; to ne znači automatsko uklanjanje već uvezenih SrediMe blokada.

Native uvoz12/12 budućih blokova je već dokazan. Tri SB potpisane poruke stvarno
su primljene, ali njihov minimalni receipt nema bookingID/poznat event_type;
ne pripisivati mu više od HMAC-proverenog prijema. Booking5 promene imaju
nezavisne stvarne REST readback-e.

Nisu dokazani24/7 autonomni rad, E2E ispod 60 s ili inbox dostava. Signed event
created→receipt 4.756/26.981/55.155 s nisu end-to-end vremena.
Produkcija i potreban administratorski transfer su odobreni, ali još nisu
izvedeni. Stvarna staff/service mapiranja, notification pravila, prihvatljivo
kašnjenje, spoljni alarmi i trajni off-host backup raspored ostaju konkretni dokazi
za završetak; nema novog vlasnikovog strogog SLA. SMTP/inbox preduslov iznad
ostaje otvoren iako je dijagnostički proces pokrenut.

## Sačuvati završeno stanje

- Source 9VPLV6E i target 5 već su otkazani. Stara target 2 takođe je canceled.
- **Postojeći target klijent 1 se ne briše.** Source 873710 postoji i oba kontakta
  su ponovo potvrđena; ne brisati ga automatski na kraju ciklusa.
- Zadržati korisne test zaposlene/usluge9/496 i 11772/233160, callback 6inactive,
  import URL11772, aktivne SB pretplate 1/2/3 i istorijski override 26.10.
  Eventualno kasnije uklanjanje mora proveriti tačne zavisnosti i posledice.
- Sačuvati baze, kvote, journals, binding, readback-e i dokaze. Nikad down-v,
  brisanje baze ili prazan ICS kao rollback. Uklanjanje import URL-a nije dokaz
  uklanjanja ranije uvezenih blokada.

Runtime ima 382/382 Windows i 382/382 Linux prolaza; privatni collector114/native 36.
[Runbook](../deploy/INTEGRATION_RUNBOOK.md) čuva referencu već izvedenog toka,
a ne nalog da se zatvoreni test ponovo izvrši.
[Arhiva ranijih planova](archive/20261027-before-trial-reconciliation.md) nije
aktuelna lista nedovršenih radnji.
