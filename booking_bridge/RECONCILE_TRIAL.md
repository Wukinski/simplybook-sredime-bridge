# Usklađivanje završenog lokalnog pilota sa host istorijom

`reconcile_trial` priprema isključivo **novu, blokiranu staging bazu** iz
pregledanih snapshot-a. Ne menja živu bazu, ne šalje kontakte/akreditive,
ne uključuje worker i ne ponavlja završene booking upise.

Tri ista event ID-a imaju različite host/local hash-eve zato što je privatni
collector napravio dokazanu minimalnu lokalnu projekciju sa native ID-evima.
Originalni host događaji imaju opaque ID-eve. Collector receipt i host ACK
čuvaju vezu originalnog host hash-a, minimalnog source hash-a, local hash-a,
binding hash-a i stvarnog REST readback hash-a. To nisu proizvoljne kolizije
koje treba rešiti prepisivanjem događaja.

Postupak proverava tačno jedan završen resync/move/cancel tok i njegov booking:
binding i native identity proof, potvrđeni journal, sve tri neizmenjene
host/local poruke, collector receipts, host ACK-ove, originalne i projektovane
booking heads, target readback-e, završni canceled link, resolved cancel intent,
klijentsku vezu i poslednji applied baseline. Dodatna lokalna ownership istorija
zahteva zaseban pregled. Nedostajuća ili promenjena činjenica zaustavlja pripremu
pre objavljivanja staging fajla.

```powershell
.\.venv\Scripts\python.exe -m booking_bridge.reconcile_trial --host-snapshot PRIVATE_SNAPSHOTS\host-snapshot.sqlite --local-snapshot PRIVATE_SNAPSHOTS\local-snapshot.sqlite --binding PRIVATE_PROOFS\verified-source-identity-binding-private.json --journal PRIVATE_PROOFS\native-source-trial-private.json --cycle booking_bridge\evidence\integration-20261027-booking-cycle.json --readbacks-dir PRIVATE_PROOFS --output PRIVATE_NEW_STAGE\bridge.sqlite
```

Staging polazi od cele host baze. Svi originalni host event payload-i/hash-evi,
booking heads, receipts, stari ignored događaji, incidenti, feed snapshot-i i
njihova vremena ostaju neizmenjeni. Dodaju se samo:

- dokazani canceled owned link sa **raw opaque** završnim snapshot-om;
- potvrđena opaque klijentska veza, applied baseline i završeni cancel intent;
- lokalne quota stavke, konzervativno **bez deduplikacije**, sa starim vremenima;
- audit/provenance sa originalnim lokalnim projektovanim zapisima, hash-evima i
  receipt vremenima, namenjen isključivo istorijskom pregledu;
- unutrašnji `recovery-hold` i spoljašnji marker koji sprečavaju pokretanje worker-a.

Native klijentski ključ ne dodaje se u routing tabelu. Binding ne postaje
globalni resolver za druge rezervacije, zaposlene ili usluge. Postojeći stale
feed i incidenti se ne proglašavaju svežim; nema lažnog heartbeat-a ili
prepisivanja ACK istorije. Sanitizovan `.reconciliation.json` sadrži hash-eve,
brojeve i preostale zabrane, bez kontakata ili payload-a.

Staging se nikada ne prepisuje. Pre marker-a rezerviše se novi prazan DB fajl;
takav nepotpun fajl ne prolazi proveru integriteta. Validni DB bajtovi upisuju
se tek posle trajnog marker-a, a unutrašnja blokada ostaje i pri kopiranju same
baze. Za neuspelu ili ponovljenu pripremu izabrati novu izolovanu putanju.

Ovaj istorijski dokaz nema proizvoljan rok od sedam dana: dokazuje već izvršene
operacije. On ne zamenjuje **nov** pregled aktuelne udaljene rezervacije,
ownership-a, dolaznih događaja od snapshot-a, konfiguracije i spoljašnjeg REST
budžeta pre aktiviranja. Nepoznat budžet ostaje zabrana rada, a ne razlog za
izmišljanje brojača. Produkcioni rollout i oslobađanje staging blokade pripadaju
posebnom pregledanom operativnom postupku.
