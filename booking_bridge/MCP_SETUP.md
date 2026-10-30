# Zvanični SimplyBook MCP — povezivanje i granice

## Trenutno potvrđeno stanje

**Ažuriranje 2026-10-22:** OAuth je uspešno završen i stvarni SimplyBook MCP
alati su dostupni u Codex sesiji. `get_company_info` je potvrdio login
`studioandjelija`, naziv Studio Andjelija i zonu Europe/Belgrade. MCP pregled
šest zaposlenih i 494 usluge odgovara početnom REST pregledu. Ponovna prijava
nije sledeći korak dok stvarni alatni pozivi uspevaju.

Aktivni Standard paket ima limit 15 zaposlenih, od kojih je devet slobodno.
Pokušaj izolovane pripreme otkrio je da REST kreiranje i ažuriranje zaposlenog
ignorišu `services: []` i povezuju ga sa 12 postojećih usluga. Napravljen je samo
skriveni test zaposleni ID 8, zatim je uklonjen kao povlačenje neuspelog testa.
REST je potvrdio potpuno vraćen početni pregled: šest zaposlenih i 494 usluge,
bez promena postojećih postavki/dodela. Nema novih klijenata ili rezervacija.
Detalji: `evidence/pilot-provisioning-check.json`.

## Istorija povezivanja (2026-10-21)

Vlasnica je 2026-10-21 potvrdila da je **MCP Connector uključen i aktivan** i da
koristi **Zed**. Lokalna provera Zed podešavanja potvrdila je unos `codex-acp`.
Posle dostavljenog Admin URL-a dodat je `simplybook-admin` u `context_servers`,
uz rezervnu kopiju globalnog settings fajla i proveru da su ostala podešavanja
očuvana. URL je sačuvan i u ignorisanom lokalnom secrets fajlu.
MCP `initialize` bez kredencijala vraća HTTP 401 sa Bearer OAuth izazovom;
običan GET vraća 404 i zato nije valjana provera MCP dostupnosti.
OAuth prijava i saglasnost vlasnice tek slede. U ovoj sesiji još nema SimplyBook
MCP alata; nije potvrđen identitet naloga niti izvršen poslovni upis.

Poslovna pravila i produkcija ostaju nepotvrđeni. Kapacitet za dva dodatna
zaposlena još treba proveriti u postojećem paketu. Nema neodobrene doplate.

## Koraci vlasnice

**Ako je potrebna ponovna prijava:** unos je već dodat. U Zedu otvoriti **MCP Servers**,
pronaći `simplybook-admin` i završiti prijavu/odobrenje pristupa. Koraci 1–4
ispod služe za ponovnu instalaciju; sada nije potrebno ponovo dodavati server.

1. U SimplyBook **Custom Features → MCP Connector** otvoriti već aktivnu funkciju.
2. Otvoriti **Admin AI Assistant**. Public agent integration ima druga prava i
   ne koristi se za administraciju ovog naloga.
3. Tačan connector URL prepisati u lokalni
   `booking_bridge/secrets/simplybook-mcp-url.txt`. Ne unositi URL iz pretpostavke,
   ne slati ga kroz razgovor i ne kopirati lozinku/API ključ u taj fajl.
4. U Zedu otvoriti Command Palette (`Ctrl+Shift+P`), pokrenuti `agent: open settings`,
   pa **MCP Servers → Add Server → Add Remote Server**. Naziv: `simplybook-admin`.
   U URL polje nalepiti tačan URL iz **Admin AI Assistant**. Za ovaj OAuth tok ne
   dodavati izmišljeni Bearer token niti REST lozinku u headers. Ako opcije nema,
   zabeležiti verziju Zeda i proveriti ažuriranje pre menjanja formata konfiguracije.
5. Prijaviti se u otvorenom SimplyBook prozoru i pregledati saglasnost. Izabrati
   korisnika sa najmanjim dovoljnim pravima. Nikada ne davati opšte „always allow“
   odobrenje za sve upise na originalnom nalogu.
6. U **MCP Servers** proveriti zeleni indikator i opis **Server is active**.
   Posle povezivanja javiti samo da je konekcija završena. Ako klijent traži
   ponovno učitavanje alata/sesije, uraditi to; povezivanje nije potvrđeno dok
   stvarni alati nisu dostupni i read-only provera ne potvrdi identitet naloga.

Zed udaljeni OAuth unos ima oblik ispod; ovo je samo primer, ne gotova konfiguracija.
Ne zamenjivati ceo postojeći `settings.json` ovim fragmentom.

```json
{
  "context_servers": {
    "simplybook-admin": {
      "url": "<tačan Admin AI Assistant URL iz SimplyBook panela>"
    }
  }
}
```

Zed može proslediti MCP servere spoljnim agentima preko ACP-a, ali podrška zavisi
od konkretnog agenta. Ako je server zelen, a alati nisu dostupni u Codex razgovoru,
prvo otvoriti novi Codex thread u istom projektu. Ako i dalje nedostaju, proveriti
`dev: open acp logs` i verziju `codex-acp`; ne slati sirove logove kroz razgovor jer
mogu sadržati privatne URL-ove/tokene. Odvojeno proveriti da li server radi u
ugrađenom Zed Agent-u. Uspeh u njemu ne dokazuje pristup u Codex sesiji.

## Provera inženjera posle povezivanja

- Pregledati stvarni katalog alata, argumente i dozvole, bez pozivanja poslovnih upisa.
- Potvrditi company identitet `studioandjelija` i uporediti pregled zaposlenih/
  usluga sa direktnom read-only dijagnostikom.
- U klijentu omogućiti samo pregledane alate za čitanje. Imena alata se ne
  izmišljaju iz naziva REST metoda. Read-only oznaku potvrditi ugovorom alata.
- Za svaki budući upis ograničiti rad na pregledani pilot manifest i nove test
  ID-eve; ne kreirati kopiju SrediMe rezervacije direktnim MCP pozivom mimo
  trajnog povezivača. Za samostalni SB test zauzetosti koristiti isključivo test opseg.
- Ako MCP ne nudi potrebnu operaciju ili prijava nije kompatibilna, ostaviti ga
  ograničenog i nastaviti podržanim REST klijentom. Ne instalirati nezvaničan
  server niti prenositi lozinke trećoj strani kao automatski fallback.

Ako se naknadno koristi Codex CLI, zvanična dokumentacija podržava udaljene MCP
konekcije, OAuth prijavu i `enabled_tools`/`disabled_tools` pravila. Konfiguraciju
praviti tek sa stvarnim URL-om i imenima pregledanih alata. CLI trenutno nije
instaliran/dostupan na PATH-u, pa komande za prijavu nisu pokretane.

## Evidencija i povlačenje pristupa

Voditi zasebnu evidenciju MCP čitanja/upisa i porediti je sa lokalnim REST brojačem.
Broj MCP alatnih poziva nije dokaz tačnog broja osnovnih API zahteva. Način obračuna
MCP potrošnje mora se potvrditi na nalogu ili sa SimplyBook podrškom.

Prekid konekcije, promena dozvola ili lozinke i gašenje MCP funkcije mogu zahtevati
ponovno povezivanje. Sinhronizacija salona ostaje nezavisan dugotrajan API servis;
ne zavisi od otvorenog razgovora ili prijavljenog MCP asistenta.

## Izvori

- [SimplyBook MCP Connector](https://help.simplybook.me/wiki/Special:MyLanguage/MCP_Connector_custom_feature)
- [OpenAI Docs: MCP konfiguracija, OAuth i izbor alata](https://developers.openai.com/codex/mcp)
- [Zed: MCP, udaljeni serveri i OAuth](https://zed.dev/docs/ai/mcp)
- [Zed: spoljni agenti i ACP granice](https://zed.dev/docs/ai/external-agents)
