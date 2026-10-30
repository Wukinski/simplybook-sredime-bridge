# Stanje projekta i dokazi

## Najnovije stanje — 28.10.2026

Korisnik je odobrio završetak preduslova, uključivanje produkcije i potreban
administratorski transfer worker-u. Dodatni prethodni uslov je rezidentni
Qwen3.5 4B za bugove/dvostruke termine i email vlasniku, **bez popravki ili
booking upisa iz modela**. Produkcija još nije uključena; transfer nije izvršen.

| Dokaz | Potvrđeno stanje |
|---|---|
| [Model](../evidence/diagnostics-20261028-model-install.json) | Qwen3.5 4B je instaliran i učitan rezidentno |
| [Keeper/collector](../evidence/diagnostics-20261028-final-collector-rollout.json) | Oba running/healthy; sveža sanitizovana projekcija, bez booking upisa ili email-ova |
| [Istorijski prvi test](../evidence/diagnostics-20261028-model-eval.json) / [3 ciljana PASS](../evidence/diagnostics-20261028-prompt-probe.json) | Ranijih 6 klasifikacionih grešaka razrešeno je SYSTEM poverenjem u trusted collector; stari svih-insufficient rezultat čuva se kao istorija |
| [Pregledana ponovljena serija](../evidence/diagnostics-20261028-model-eval-reviewed-memory-failure.json) | 6 semantičkih PASS + 1 model_unavailable; prekid je dokazani OOM, ne nova pogrešna klasifikacija |
| [OOM dokaz](../evidence/diagnostics-20261028-memory-before-fix.json) / [live korekcija](../evidence/diagnostics-20261028-memory-fix.json) | Limit 6 GiB, oom_kill=1, HTTP 500/ubijen runner; sada 8 GiB uz isti kontejner/server proces, sledeći request num_batch=64/kontekst 4096/jedan paralelni zahtev |
| [Renderer audit](../evidence/diagnostics-20261028-model-renderer-audit.json) | Stvarni renderer/parser qwen3.5; placeholder template sam nije dokaz ignorisanih poruka |
| [Izolovani held stage](../evidence/activation-staging-20261028-2eb16604-reconciliation.json) | Istorijski raw/projected provenance završenog testa usaglašen uz originalne host hash-eve/head-ove; hold aktivan, worker start blokiran, aktivne baze nepromenjene |
| [Noviji TLS dokaz](../evidence/diagnostics-20261028-tls.json) | IP/DNS chain/hostname validni; normalan 160h cert sa oko 122h preostalog veka; timer active/enabled, certificate_not_yet_due, bez neuspeha obnove |
| [Stvarni off-host restore](../evidence/offhost-restore-drill-20261028-6e619251.json) | 14/14 provera, ciphertext prenet van VPS-a, privremeni server ključ obrisan; hold ostaje, unattended backup nije uključen |
| [Windows](../evidence/diagnostics-20261028-windows-tests.xml) / [Linux](../evidence/diagnostics-20261028-linux-tests.xml) / [HTTP](../evidence/diagnostics-20261028-linux-smoke.json) | 756 Windows PASS; 746 Linux PASS + 10 skip; HTTP smoke PASS |

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

Healthy collector nije dokaz svežeg target keša: rollout prijavljuje zastarele
booking/buffer snimke i nedovoljne booking dokaze. [Runbook](../deploy/DIAGNOSTICS_RUNBOOK.md).

Nedostaju stvarni identiteti/mapiranja, pokrivenost usluga, ispravna trajanja i
resursi, produkcioni opseg i postupak za nepoznate klijente, notification/original-created/
native-removal dokazi, merenje transporta, SMTP dostava i nezavisan spoljni nadzor.
Istorijski hash konflikt završenog testa nije nova nerešena blokada.
Capture/execution profili imaju require_subminute_availability=false; cilj
<60 s nije potvrđen vlasnikov SLA. Raniji 72h/7-dnevni gate je naša softverska
politika, ne novi korisnikov uslov. Predložena korekcija je automatski odbijena
i nije primenjena; root čeka zatraženo konkretno korisničko odobrenje. Aktuelni
kod i dalje zadržava sedmodnevnu blokadu i `soak_72h`.
Za ovaj short-lived TLS deployment koristiti `--tls-min-days 2`; generički
default 7 nije primeren i nije razlog za forsiranu obnovu.

Sledeći odeljci čuvaju ranije dokaze i njihove tadašnje granice. Ne koristiti
stare tvrdnje o neodobrenoj produkciji umesto najnovije korisničke odluke.

Produkcioni nastavak 28.10.2026: korisnik je izabrao postojeći VPS i rad bez
Windows računara. Implementirana je [priprema](../PRODUCTION_READINESS.md),
uz 562 Windows prolaza, 558 Linux prolaza (+4 platformske provere preskočene)
i HTTP smoke na obe platforme. [Sažetak](../evidence/production-20261028-preparation.json).
Prvobitni read-only state diff je
[blocked](../evidence/production-20261028-state-review.json), bez merge-a ili
booking upisa. Postoji nova zasebna Linux validation slika, nije deploy pilota.
[TLS/host read-only](../evidence/production-20261028-live-readonly.json) potvrđuje
cert do 02.11. i stvarni active renewal timer; host snapshot ima jedan
booking_snapshot_stale. Produkciona aktivacija i admin transfer nisu izvedeni.

Lokalni razvoj **28.10.2026**: pripremljen neuključen supervisor, ispravljena
owned target drift provera capture-a, odvojeni webhook/native konfiguracioni
ID-evi i napravljen isključen Windows task XML bez registracije. Novi kod ima
**446/446 offline Windows prolaza**. [JUnit](../evidence/development-20261028-windows-tests.xml),
[sažetak](../evidence/development-20261028-preparation.json),
[postupci](../deploy/PERSISTENT_PUBLISHER.md). Nema novog Linux/deploy dokaza
ili živih izmena; slika i readback-i ispod ostaju poslednje potvrđeno živo stanje.

Konačni presek **27.10.2026, 14:45 UTC**: kontrolisani ciklus i nezavisna provera
zatvaranja source testa uspešno su završeni. Ne ponavljati ovaj ciklus.

## Tačni zapisi

| Sistem | Zapis | Potvrđeno stanje |
|---|---|---|
| SimplyBook | Zaposleni9 / usluga496 | Skriveni, aktivni; kapacitet 1,30 min,cena 0, buffer 0; usluga samo 9 |
| SimplyBook | Klijent 1 | Postojeći korisnikov zapis, oba kontakta potvrđena; nije brisan |
| SimplyBook | Stara rezervacija 2 | Već canceled; ne ponavljati |
| SimplyBook | Rezervacija **5** | Kreirana iz resync-a14:00–14:30, pomerena 15:00–15:30, zatim **canceled/is_confirmed=false** |
| SimplyBook | Pretplate1/2/3 | Aktivne new_booking/change_booking/cancel_booking |
| SrediMe | Zaposleni 11772 | external_id 9, bookable=false, svih sedam dana off |
| SrediMe | Usluga233160 | external_id 496, inactive,30 min,cena 0, cleanup/split 0, bez resursa |
| SrediMe | Klijent 873710 | Kreiran jednom, postoji; email/telefon/native parent ID potvrđeni |
| SrediMe | Rezervacija **9VPLV6E** | 28.10.15:00–15:30 Belgrade, status **-101 / Salon otkazao**; sačuvana, nije obrisana |
| SrediMe | Callback 6 | **Inactive**, lease zatvoren 14:44:10.807 UTC; nezavisni readback 14:45:13.702 UTC |
| SrediMe | Import11772 | Privatni URL ostaje;12/12 budućih blokova potvrđeno ranije istog dana |

Zaposleni9 zadržava evidentirane veze sa uslugama2,3,5,13,29,47,312,444,452,462,
472,474. Ne menjati originalni katalog/dodele radi nove izolacije. Datumski
override 26.10. i svi dnevnici ostaju istorija.

## Dokazan rezervacioni tok

[Potpun javni dokaz](../evidence/integration-20261027-booking-cycle.json) ima
controlled_cycle_verified=true i cleanup_verified_by_independent_native_readback=true.
Svaka faza ima stvarni native zapis, potpisan host event, local done/attempts 1,
stvarni REST target readback i tačan host ACK. Sve tri faze su done; unresolved
local intents 0, owned link 9VPLV6E→5 je canceled.

| Faza | Stvarni event ID | Target readback UTC | Signed created→host receipt |
|---|---|---|---:|
| Resync → create target 5 | ce3fa625c5a6e6bf73f2f3dfd01c1026 | 14:35:03.570;14:00–14:30 confirmed | 4.756 s |
| Move | 6f4151881513c9fb71c1028931ca19dd | 14:39:05.584;15:00–15:30 confirmed | 26.981 s |
| Cancel | ac284a7be11ee144ca7937e486f1f439 | 14:43:07.866;15:00–15:30 canceled | 55.155 s |

Sva tri stvarna source eventa bila su booking.updated. Originalni booking.created
je native delivery tabela označila cancelled/attempts 0/HTTP —: nije pokušana
isporuka. Brzo deaktiviranje queued callback-a je verovatan uzrok, ne potvrđeno
backend pravilo. Zato je ista rezervacija/termin sačuvana uz internu belešku
„Proba integracije” i legitimni updated snapshot napravio je nedostajući target.
Originalni source create nije ponavljan, a njegov callback nije retroaktivno uspeo.

Opaque webhook IDs39VLN1/V2N8N4/7E9514 vezani su za native 11772/233160/873710
preko istog tačnog booking-a, parent readback-a, vremena i external_id 9/496;
employee identitet potvrđen je i native export segmentom. Privatni --binding
čuva raw ID/hash/tip i važi samo za booking 9VPLV6E. Nema globalnog resolver-a.

## Završni readback

[Nezavisni native GET](../evidence/integration-20261027-source-final.json) u
14:45:13.702 UTC potvrđuje source cancel, postojeći odobreni kontakt, callback=false,
bookable=false, svih sedam dana off, service=inactive. Taj readback poslao je0 POST.

[Host 14:45:42 UTC](../evidence/integration-20261027-live-final-after-cleanup.json):
liveness200/readiness200, otvoreni incidenti0;3 done i1 stariignored, hostlinks0,
hostintents 0. Primljene su3HMAC-proverene SB poruke. Sačuvani event_type=null;
receipt ne dokazuje pojedinačni bookingID/tip. Izmene booking 5 dokazuju REST
readback-i, ne pretpostavljena payload korelacija.

## Runtime, testovi i ostali dokazi

Slika `andjelija-bridge:pilot-20261027-integration1`, image ID
`sha256:8a8440d7e6ab72d6a388deb5bf2594e5ae174bfd166075d939d81c8d08987cc0`.
API i pilot_receiver ostaju simulation/reads off. Receiver ne obrađuje naloge;
administratorski pristupi ostaju lokalno. Finite publisher prenosi 15 minimalnih
blokova sa izvornim timestamp-ovima, bez kontakata/kredencijala. Owned booking 5
nije dodao povratni occupancy blok. To nije daemon ili 24/7 servis.

| Dokaz | Rezultat |
|---|---|
| [Rollout](../evidence/integration-20261027-rollout.json) | Postavljena slika i receiver |
| [Windows](../evidence/integration-20261027-windows-tests.xml), [Linux](../evidence/integration-20261027-linux-tests.xml) | **382/382** na obe platforme |
| [Windows smoke](../evidence/integration-20261027-windows-smoke.json), [Linux smoke](../evidence/integration-20261027-linux-smoke.json) | HTTP simulacione provere |
| [Prenosi](../evidence/integration-20261027-approved-transfers.json) | Minimalni paket i originalna vremena |
| [HMAC](../evidence/integration-20261027-signing-install.json) | Pravi SB ključ,0600, runtime readback i 401 za loš potpis |
| [Pretplate](../evidence/integration-20261027-sb-subscriptions.json) | Stvarno aktivne1/2/3 |
| [Ugovor usluge](../evidence/pilot-service-contract-20261027.json) | Tajming/resursi test para |
| [Preflight](../evidence/integration-20261027-execution-preflight.json) |31/31 za zaseban lokalni execution profil |
| [Native uvoz](../evidence/integration-20261027-source-import.json) |12/12 budućih blokova,bez viškova/duplikata |

Privatni collector/ACK ima **114** offline prolaza, native operator **36**.
Ove privatne izmene ne menjaju postavljeni runtime. Privatni journal/binding/
readback-i su u state/integration-20261027; ne izvoziti kontakte ili sirove HTML.

## Granice rezultata

Source created→receipt vremena u tabeli nisu E2E. Jedan raniji occupancy refresh
dao je fetch 38.063 s i prvu punu native sliku12/12 budućih intervala67.911 s posle
acceptance-a;3od 15 intervala već su prošla. Actual commit nepoznat.
**Nisu dokazani <60 s E2E,24/7 automatizacija ili inbox dostava korisniku.**
Produkcija nije uključena; callback 6 je isključen.

Ranije završeno: import 490, sortiranje 467 i dodele 481; ne ponavljati.
[Import](../../service_importer/IMPORT_STATUS.md),
[kategorije](../../category_sorter/BULK_CATEGORY_RESULTS.md),
[dodele](../../provider_assignment/reports/verified-exclusive-final.md).
Prevodi695/18/35 prihvaćeni su za sada; [jezički pregled](../localization/LANGUAGE_AUDIT.md).
Realna povezivanja ostaju budući [poslovni pregled](../PILOT_MAPPING_REVIEW.md);
Sara3 i Sanja6873 nisu potvrđeni isti identitet.

[Arhiva](archive/20261027-before-trial-reconciliation.md) čuva stare tekstove,
bez vraćanja njihovih zastarelih dozvola ili prepreka.
