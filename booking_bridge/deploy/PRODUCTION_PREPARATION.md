# Priprema servera za trajni rad

Ovo su lokalno pripremljeni fajlovi za pregled; nisu postavljeni ili aktivirani.
Postojeći pilot Compose i završeni probni ciklus ostaju istorijski dokaz.
`compose.production.yaml` koristi novu sliku `andjelija-bridge:production-reviewed`
i zasebne trajne volumene. Prelazak sa postojećeg pilot stanja zahteva pregledanu
migraciju i proveru neizvesnih udaljenih upisa; prazna nova baza nije zamena za
istoriju vlasništva nad rezervacijama.

Oba servisa imaju eksplicitni Compose profil `production`. Profili sprečavaju
podrazumevano pokretanje, ali eksplicitno izabrani servis može pokrenuti njegov
profil; zato worker dodatno proverava readiness dokaz pri svakom startu.
[Docker profili](https://docs.docker.com/compose/how-tos/profiles/).

Javni `production-config.example.json` ostaje simulation/reads off, sa praznim
mapiranjima i nepotvrđenim odobrenjima. Ova konfiguracija ne prolazi worker gate.
Privatne popunjene kopije pripadaju `deploy/secrets/`, koji je izuzet iz Docker
konteksta i release arhive:

| Privatni ulaz | Potrošač |
|---|---|
| `secrets/production-config.json` | API i worker, read-only |
| `secrets/production-evidence/readiness.json` i dokazi na koje upućuje | Samo worker, read-only direktorijum |
| `secrets/ingress.env` iz `ingress.env.example` | Samo API: signing/feed/ops ključevi |
| `secrets/worker.env` iz `worker.env.example` | Samo worker: potrebni zajednički ključevi, source URL i REST pristup |

Na serveru tajni fajlovi treba da imaju vlasnika 10001 i dozvole 0600; Compose
lokalne secrets bind mount-ove ne treba smatrati mehanizmom koji sam popravlja
dozvole izvornog fajla. API nema REST administratorske promenljive, source export
URL ili provider_state volumen. [Docker secrets](https://docs.docker.com/reference/compose-file/secrets/).
Oba procesa rade kao 10001, sa read-only root filesystem-om, bez capabilities;
API sluša samo na host loopback portu iza postojećeg HTTPS reverse proxy-ja.

Worker drži postojeći singleton lock i koristi trajne kvote i evidenciju upisa.
Njegov healthcheck čita postojeću bazu read-only, bez inicijalizacije ili migracija.
Docker healthcheck prikazuje unhealthy stanje; sam po sebi ne šalje upozorenje
niti restartuje proces. Potreban je zaseban nadzor sa dogovorenim primaocem.
HTTP/TLS proveru i slanje alarma za potpuni pad hosta pokretati van ovog VPS-a.
Lokalnu proveru diska i kopija pokretati na VPS-u i pratiti i njen heartbeat
spolja; putanja na mašini spoljnog monitora ne predstavlja disk VPS-a. Ovaj
paket priprema obe vrste provere, ne instalira spoljnog nadzornika ili primaoca.

## Jednokratni nadzor

`python -m booking_bridge.production_monitor` vraća JSON sa fiksnim šiframa i
exit 0 za zdravo stanje, odnosno 2 kada je potrebna pažnja. URL-ovi, ključevi,
putanje, sadržaj HTTP odgovora i izuzeci ne ulaze u izveštaj. Privatni monitor env:

```dotenv
BRIDGE_MONITOR_LIVE_URL=
BRIDGE_MONITOR_READY_URL=
BRIDGE_MONITOR_ADMIN_KEY=
BRIDGE_MONITOR_TLS_HOST=
BRIDGE_MONITOR_ALERT_URL=
```

Liveness/readiness URL moraju biti HTTPS, bez korisničkih podataka, query-ja ili
fragmenta. Readiness dobija samo `X-API-Key`; redirekcije su isključene i TLS
provera ostaje uključena. Endpoint za readiness treba da bude dostupan samo
odobrenom operatoru/nadzoru, uz postojeću privatnu proxy politiku.

Primer buduće lokalne/serverske kontrole, sa stvarnim privatnim putanjama koje
operator prethodno pripremi:

```text
python -m booking_bridge.production_monitor --env-file /private/monitor.env --disk-path /opt/booking-bridge --backup-path /private/backups/latest.sqlite --backup-max-age 7200 --tls --tls-min-days 2
```

Podrazumevani timeout je 5 s; disk zahteva najmanje 1 GiB i 10% slobodnog prostora.
Backup kontrola proverava postojeći neprazan fajl i vreme poslednje izmene, ne
potvrđuje integritet, šifrovanje ili uspešan restore. TLS kontrola proverava
lanac i hostname na portu 443, pa preostalo vreme sertifikata. Za ovaj VPS važi
kratkotrajni Let's Encrypt sertifikat od oko 160 sati, pa eksplicitni prag od
2 dana daje alarm pre isteka uz timer obnove dvaput dnevno. Opšti CLI default
od 7 dana nije prikladan za ovaj kratak sertifikat i ostaje namenjen drugim
instalacijama. Certbot sertifikate kraće od 10 dana standardno obnavlja kada
ostane manje od polovine njihovog trajanja, ovde oko 80 sati.
[Stvarna TLS provera](../evidence/diagnostics-20261028-tls.json) potvrđuje validan
IP/DNS lanac do 02.11.2026. 14:34:01 UTC i uspešan obnovni check bez pokušaja
izdavanja, jer sertifikat još nije dospeo za obnovu. To nije greška obnove.
[Certbot pravilo obnove](https://eff-certbot.readthedocs.io/en/stable/using.html#renewing-certificates).

Bez `--send-alert` nema POST-a ili poruke. Taj eksplicitni argument koristi
`BRIDGE_MONITOR_ALERT_URL` samo pri neuspešnoj kontroli, sa fiksnim razlogom kvara.
Nema deduplikacije između pokretanja; budući timer/alarm sistem treba da odredi
učestalost, usporavanje ponovljenih poruka i primaoca. Ovaj nastavak ne instalira
timer i ne šalje probno upozorenje.

Za container healthcheck, bez mreže i bez administratorskih pristupa:

```text
python -m booking_bridge.production_monitor --local-state /state/bridge.sqlite
```

Nedostajuća baza se ne kreira. Zastareo heartbeat/health ili nov otvoreni incident
daju neuspeh po istim pravilima kao API readiness. Karantin vraćene baze se
proverava dodatno: svež kopirani heartbeat ne može preskočiti recovery hold.
Uspešan healthcheck ne dokazuje
end-to-end rok ispod 60 s, prijem poruke u inbox ili spremnost svih poslovnih
pravila za produkciju.
