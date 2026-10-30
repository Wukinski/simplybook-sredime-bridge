# Dijagnostičke email poruke

`watchdog_alerts` prijavljuje nalaze samo na jednu izričito odobrenu adresu.
Ne popravlja rezervacije, ne poziva booking API i ne menja bridge bazu. Model
ne bira primaoca, zaglavlja, SMTP server, tajne ili proizvoljan tekst poruke.

Privatna SMTP konfiguracija koristi:

```text
BRIDGE_DIAGNOSTIC_SMTP_HOST
BRIDGE_DIAGNOSTIC_SMTP_PORT
BRIDGE_DIAGNOSTIC_SMTP_USER
BRIDGE_DIAGNOSTIC_SMTP_PASSWORD_FILE
BRIDGE_DIAGNOSTIC_SMTP_FROM_ADDRESS
BRIDGE_DIAGNOSTIC_SMTP_RECIPIENT
```

`RECIPIENT` je opcion i mora tačno odgovarati adresi dozvoljenoj u modulu.
Port mora biti **465 sa SSL-om** ili **587 sa STARTTLS-om**. Provera sertifikata
i hosta je obavezna, najmanje TLS 1.2; nema prelaska na nezaštićenu autentikaciju.
Lozinka se čita samo iz privatnog fajla i ne čuva se u konfiguracionom objektu,
outbox-u, poruci ili logu. Na POSIX-u fajl mora biti čitljiv samo vlasniku.
Nedostajuća, prazna ili neispravna lozinka sprečava rezervaciju SMTP pokušaja
i otvaranje socketa. Konfiguracija nije dokaz da je email prihvaćen ili isporučen.

`DiagnosticOutbox` koristi zaseban SQLite fajl i odbija postojeću bridge bazu.
`reserve()` prima isključivo fiksne poznate kodove, nivo `info/warning/critical`
i hash reference. Podržani AI sažetak ima samo `assessment`, `confidence` i
`recommendation_codes` sa dozvoljenim enum vrednostima. Nema slobodnog AI teksta.
Poruka je lokalni srpski plain UTF-8 šablon, bez kontakata ili provider payload-a.

Potpis nalaza zanemaruje promene modelskog stila i sam nivo ozbiljnosti.
Neizmenjen nalaz ima sat vremena cooldown-a; viši nivo može odmah rezervisati
novu poruku i potisnuti niži neslati nalaz. Isti nalaz koji već čeka SMTP ne
stvara satni backlog. Dnevno se može rezervisati najviše deset poruka, a i
stvarni SMTP pokušaji imaju zasebno ograničenje od deset dnevno. Viši nivo ne
zaobilazi dnevni limit. Privremena greška ima najviše tri pokušaja, sa čekanjem
60 pa 120 sekundi. Sve rezervacije, pokušaji i limiti opstaju kroz restart.

`send_one()` trajno upisuje pokušaj pre SMTP poziva. Jedan OS lock sprečava
istovremene sendere. Pozitivan završni `DATA` odgovor **250** daje stanje
`accepted`, `smtp_accepted=true`, uz `inbox_delivery_verified=false`.
To znači da je SMTP server prihvatio poruku, ne da je stigla u korisnikov inbox.

Prekid ili nepoznata greška tokom `DATA`, nepoznat odgovor sender-a ili prekid
procesa ostavljaju `uncertain`. Takva poruka se automatski ne ponavlja, ni posle
cooldown-a; potreban je pregled. Tačno-jednom isporuka kroz SMTP nije obećana.
Eksplicitni privremeni SMTP negativni odgovor može se ograničeno ponoviti;
trajni negativni odgovor i odbijena autentikacija zahtevaju pregled konfiguracije.

U testovima se koriste isključivo ubrizgani senderi i sintetički SMTP objekti.
Pravi prijem može se dokazati tek posebno pokrenutom probnom porukom uz stvarne
privatne akreditive i korisnikovu potvrdu prijema. Ovaj modul sam ne pokreće
daemon, ne kreira lažne akreditive i ne šalje probnu poruku.
