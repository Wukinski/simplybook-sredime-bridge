# Provera jezika i nastavak pilota — 27.10.2026.

Ovo je nastavak [primopredaje](../../AI_HANDOFF.md), zasnovan na živim UI
očitanjima i privatnim dnevnicima ove sesije. **Nije potvrđeno da je ceo
klijentski put 100% na srpskom. Produkcija nije uključena.**

## Sačuvano i ponovo pročitano

- SimplyBook klijentski tekstovi: prva grupa **382**, druga **315** izmena;
  ukupno **695 različitih polja**. Dve kasnije izmene popravljaju ranije
  promenjena polja, pa zbir upisa nije broj različitih prevoda.
- Prevedeno je **18 zajedničkih sistemskih polja**: 8 oznaka trajanja i
  10 polja podnožja imejla/pratećih oznaka. Readback svih
  **12.583 polja** potvrdio je da su ostale vrednosti očuvane.
- Potvrđeno je **35 polja šablona**: 22 osnovna klijentska imejl/SMS polja,
  9 polja obaveštenja o plaćanju i 4 SBPay imejl polja za račun i knjižno
  odobrenje. Poslednji SBPay dnevnik ima status `confirmed`.
- Pravila uključivanja obaveštenja, vreme slanja i podsetnika i postavke
  plaćanja očuvani su. Klijentski iCal prilog ostaje isključen.
- Početna stranica i koraci izbora usluge, datuma i podataka klijenta pregledani
  su bez potvrđivanja rezervacije. Oznaka minuta sada je `min`.

Prevodi su sačuvani za ponovnu upotrebu u [osnovnom rečniku](sr-Latn.json),
[dodatnim tekstovima](sr-Latn-additional.json),
[sistemskim oznakama](sr-Latn-system.json),
[obaveštenjima o plaćanju](sr-Latn-payments.json) i
[SBPay šablonima](sr-Latn-sbpay.json).
Tačna prethodna stanja, namere i readback ostaju u privatnim dnevnicima
`booking_bridge/state/language-audit-20261027/`; ne kopirati njihove sadržaje
u javne dokaze.

Posle provere srpskih šablona pokrenuto je jedno kontrolisano otkazivanje stare
probne rezervacije, uz uključeno imejl obaveštenje samo korisnikovom kontaktu.
**Prijem obaveštenja i njegov konačan izgled posle poslednje izmene nisu potvrđeni.** Sačuvan šablon nije dokaz
isporuke. Aplikacioni Python testovi nisu
ponavljani; ova provera obuhvata nativne UI readback-e i JSON validaciju.

## Preostale jezičke prepreke

- Deo klijentskih tekstova je još na engleskom, uključujući mnoge tekstove
  isključenih dodataka. Broj vrednosti jednakih engleskom izvorniku nije mera
  pokrivenosti aktivnog toka niti dokaz da su sve takve vrednosti pogrešne.
- HTML `lang` je i dalje `en`; srpski nije ponuđen u trenutnom meniju od 22
  sistemska jezika. Ne resetovati osnovni jezik: time se mogu izgubiti postojeći
  prilagođeni prevodi i šabloni.
- Zvanični klijentski uslovi vode na englesku stranicu:
  <https://simplybook.me/en/terms-and-conditions#tab-for-clients>.
- WhatsApp je uključen, uz 0 kredita. Šabloni nemaju pregledani editor;
  njihov stvarni jezik nije potvrđen. Nula kredita nije potvrda prevoda.
- [Postojeći zapis imejla](../evidence/pilot-cancellation-message-log-20261027.json)
  za rezervaciju 2 i odobreni kontakt pokazuje srpski naslov/telo, uz englesko
  podnožje. Potom je svih 10 odgovarajućih sistemskih polja podnožja/oznaka
  prevedeno i očitano nazad. Novi render posle ispravke i inbox dostava ostaju
  neprovereni; stari zapis se time ne menja. Datum loga je doslovno
  `27-10-2026 01:54`, zona nije navedena i nije pretvaran u UTC ili kašnjenje.
- SrediMe javna galerija koristi engleske `Previous`/`Next` tekstove i
  `aria-label` oznake. U pregledanim podešavanjima salona nije nađen editor
  za njih. Izvorni šabloni klijentskih SrediMe poruka ostaju neprovereni.

SimplyBook editor odbio je prevod jednog HTML unosa sa navodnicima, uz grešku
`lang.po.tmp:2310: keyword "to" unknown`. Taj unos je izostavljen, a ostatak
grupe uspešno sačuvan. Tačan `msgid`, opis prepreka i dva kratka nacrta pitanja
nalaze se u [pitanjima za provajdere](PROVIDER_LANGUAGE_REQUESTS.md).
**Nacrti nisu poslati.**

## Rezervacija i operativna provera

SimplyBook rezervacija **2**, za prošli termin **26.10.2026, 10:00–10:30
Europe/Belgrade**, zaposleni **9**, usluga **496**, klijent **1**, **otkazana je**
27.10.2026. API izveštaj `cancelled` očitao je `canceled` u 08:17:45 UTC;
[dokaz](../evidence/pilot-booking-cancelled-20261027.json). Pre operacije su
oba kontakta ponovo privatno poklopljena i pročitani su srpski šabloni otkazivanja.
Prijem poruke ostaje nepoznat. Rezervacija nije obrisana i nije napravljen duplikat.
**Klijenta 1 sačuvati.** SrediMe test zaposleni **11772** ostaje nedostupan za
zakazivanje sa svim danima neradnim; usluga **233160** je neaktivna, callback
**6** deaktiviran. Ne otvarati stvarne termine radi merenja.

VPS je i dalje `simulation`, `reads_enabled=false`. TLS je obnovljen do
**02.11.2026. u 14:34:01 UTC**. Tajmeri su aktivni; pri očitavanju je postojalo
84 lokalnih rezervnih kopija. Readiness i probni feed vraćaju **503** zbog
`booking_snapshot_stale`. Ručni stari snimak nije automatska sinhronizacija.
SimplyBook administratorski akreditivi nisu preneti na VPS.

[Dokaz iz trajnog webhook reda](../evidence/live-source-webhook-receipt-20261027.json)
sada dokumentuje već postojeći `booking.updated` događaj sa `test:false`,
stanjem `ignored` i razlogom `employee_outside_allowlist`. Pročitano je postojeće
stanje, bez nove isporuke i bez širenja dozvoljenog obuhvata; broj veza i namera
upisa je **0**. To nije dokaz prenosa rezervacije ili završenog uvoza.

Dokazi ovog nastavka:
[jezik](../evidence/client-language-audit-20261027.json),
[zapis imejla pre ispravke podnožja](../evidence/pilot-cancellation-message-log-20261027.json),
[operacije pilota](../evidence/pilot-operations-check-20261027.json).
Istorijski dokazi rezervacije ostaju sačuvani:
[kreiranje](../evidence/pilot-booking-created-feed.json) i
[pomeranje](../evidence/pilot-booking-moved-feed.json).

## Sledeći koraci

1. Dovršiti podržane prevode aktivnih površina; po potrebi pregledati podržan
   PO uvoz za problematični HTML unos, uz čuvanje sadašnjeg stanja.
2. Razjasniti preostale provajderske mogućnosti. Nacrti pitanja nisu poslati;
   slanje podršci zahteva izričit nalog korisnika.
3. Proveriti postojeće obaveštenje nastalo posle otkazivanja rezervacije 2,
   pre bilo kakvog novog slanja. Tek posle provere odgovarajućih šablona testirati
   poruku isključivo na odobrenom korisnikovom kontaktu. Ne ponavljati otkazivanje.
4. Nastaviti postojeći ograničeni pilot i dokumentovati ono što je stvarno
   izmereno. **Ne uključivati produkciju.** Zadržati korisne test zapise i
   završene prevode; ne ponavljati uvoz, kategorije ili dodele usluga.
