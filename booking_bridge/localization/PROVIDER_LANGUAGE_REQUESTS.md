# Nacrti pitanja o srpskom jeziku

Pripremljeno 27.10.2026. **NIJE POSLATO.** Ovo su predlozi za pregled;
slanje podršci zahteva izričit nalog korisnika. Nisu priloženi podaci klijenata,
akreditivi ni privatni integracioni URL-ovi.

## SimplyBook.me — nacrt, nije poslat

Poštovani,

želimo da sav sadržaj za klijente bude na srpskom, latinicom, uz očuvanje
postojećih prilagođenih prevoda i šablona. Molimo za podržan način podešavanja:

- Srpski nije među 22 jezika u trenutnom sistemskom meniju. Kako podesiti
  klijentski jezik, uključujući HTML atribut `lang` koji je sada `en`, bez
  resetovanja postojećih prilagođavanja?
- Glavni imejl/SMS šabloni već su prevedeni. U postojećem zapisu imejla podnožje
  je bilo englesko, pa smo preveli i zajedničke tekstove podnožja. Kako pregledati
  ceo ponovo renderovan imejl, uključujući dugmad i podnožje, bez novog slanja?
  Da li svi tipovi klijentskih imejlova koriste taj isti prilagođeni rečnik?
- WhatsApp obaveštenja su uključena, stanje kredita je 0, a stvarni jezik poruka
  nije proveravan. Kako se bira jezik unapred odobrenih šablona, da li postoji
  srpska verzija i može li se pregledati pre slanja?
- Kako na postojećem Standard nalogu podesiti srpski za ugrađene oznake SBPay
  računa/PDF-a? Naslove i tela četiri prateća imejl polja već smo preveli. Koje izmene su dostupne
  bez prelaska na SBPay Pro?
- Klijentski link za uslove korišćenja vodi na
  <https://simplybook.me/en/terms-and-conditions#tab-for-clients>. Postoji li
  zvanična srpska verzija ili podržan način da klijent dobije te uslove na srpskom?

Imamo i konkretan problem sa editorom prevoda. Pri prevođenju tačnog `msgid`:

```text
Don't have an account? <a class="to-sign-up__link" tabindex="0">Sign up</a>
```

čuvanje vraća grešku `lang.po.tmp:2310: keyword "to" unknown`, a prevodi se ne
sačuvaju. Ostatak grupe uspešno je sačuvan nakon izostavljanja ovog unosa.
Koji je podržan način ispravke, uključujući pravilno formatiran PO uvoz ako je
to preporučeno rešenje? Molimo bez promene osnovnog jezika koja bi obrisala
postojeće prevode i šablone.

Pročitana zvanična uputstva:
[jezici i prevodi](https://help.simplybook.me/wiki/Adjust_your_terminology/language),
[obaveštenja](https://help.simplybook.me/wiki/Adjusting_notifications),
[WhatsApp](https://simplybook.me/en/whatsapp-notifications),
[Custom Email](https://help.simplybook.me/wiki/Custom_Email_custom_feature),
[SBPay](https://help.simplybook.me/wiki/SBPay.me_integration) i
[podešavanje računa](https://help.simplybook.me/wiki/Adjusting_client_invoices).

Hvala.

## SrediMe — nacrt, nije poslat

Poštovani,

proveravamo da sav sadržaj za klijente salona bude na srpskom, latinicom.
Na [javnoj stranici salona](https://www.sredime.rs/novisad/salon-studio-andjelija-sg)
dugmad za listanje galerije imaju engleski tekst i `aria-label` vrednosti
`Previous` i `Next`. Kako ih podržanim putem prevesti na srpski, uključujući
oznake koje čitaju čitači ekrana?

Takođe, gde možemo pregledati i po potrebi ispraviti izvorne šablone poruka za
klijente — potvrdu, podsetnik, promenu i otkazivanje termina — pre slanja
kontrolisane probne poruke? Molimo da navedete ako za neki kanal tekst ili
jezik određuje isključivo SrediMe.

Hvala.
