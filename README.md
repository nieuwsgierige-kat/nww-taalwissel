# NWW taalwissel

Bookmarklet voor redacteuren: één klik op een pagina van nederlandwereldwijd.nl opent de Engelse versie op netherlandsworldwide.nl.

## Hoe het werkt

1. `build_map.py` leest de sitemaps (NL: `paginas`, `contact/ambassades-consulaten-generaal`, `reisadvies`; EN: `paginas`, `contact/embassies-consulates-general`; plus de hoofdsitemap als vangnet), haalt de Engelse pagina's op en leest uit de paginadata (`translations`) welke Nederlandse pagina erbij hoort. ES/FR/DE-pagina's (`…/pagina.es` en `…/pagina/es`) tellen niet mee als Engels.
   Engelse pagina's zonder NL-link worden alsnog gekoppeld via `data/handmatig.json` of *afgeleid*: het Engelse pad wordt vertaald met de woorden uit bestaande koppelingen (bijv. `consular-fees/italy` → `consulaire-tarieven/italie`). Dat gebeurt alleen als die NL-pagina in de sitemap staat, nog niet gekoppeld is en er precies één Engelse pagina op uitkomt.
2. Het resultaat staat in `docs/map.json` (Nederlandse URL → en/es/fr/de).
3. `docs/index.html` (GitHub Pages) zoekt de Nederlandse URL op en stuurt door.
4. De workflow draait elke maandag en haalt alleen pagina's op die volgens de sitemap gewijzigd zijn.

Veiligheidsgrenzen: de lijst wordt **niet** overschreven als meer dan 20% van de fetches mislukt, als bij vrijwel geen enkele pagina vertaaldata gevonden wordt (paginastructuur veranderd), of als de nieuwe lijst meer dan 20% kleiner is dan de oude. De run faalt dan zichtbaar in Actions.

## Eenmalige installatie

1. Maak een nieuwe **public** repo, bijv. `nww-taalwissel`, en upload alle bestanden uit deze map (inclusief `.github/` en `docs/.nojekyll`).
2. **Settings → Pages**: Source = *GitHub Actions*. De workflow publiceert de lookup-pagina zelf na elke run.
3. **Actions → Koppellijst bijwerken → Run workflow**, vink *Alle pagina's opnieuw ophalen* aan. De eerste run haalt alle Engelse pagina's op (1 per seconde), dus reken op een uur of langer.
4. Controleer in het log de regel `Klaar: … Nederlandse pagina's gekoppeld`.

## Bookmarklet

Maak een bladwijzer en plak één van deze regels als URL (precies zo, op één regel). De code bevat bewust geen `%`, `#` of regeleinden: Firefox kan die bij opslaan of bewerken omzetten, waarna de bladwijzer zonder foutmelding niet meer werkt.

Engels, zelfde tabblad:

```
javascript:(()=>{location.href='https://nieuwsgierige-kat.github.io/nww-taalwissel/?u='+encodeURIComponent(location.href)})()
```

Engels, nieuw tabblad:

```
javascript:(()=>{window.open('https://nieuwsgierige-kat.github.io/nww-taalwissel/?u='+encodeURIComponent(location.href))})()
```

Spaans, Frans of Duits (zelfde tabblad; vervang `es` door `fr` of `de`):

```
javascript:(()=>{location.href='https://nieuwsgierige-kat.github.io/nww-taalwissel/?u='+encodeURIComponent(location.href)+'&lang=es'})()
```

Controle na opslaan: ga naar https://www.nederlandwereldwijd.nl/bsn en klik op de bladwijzer. Je moet uitkomen op https://www.netherlandsworldwide.nl/bsn (of de Spaanse/Franse/Duitse versie). Gebeurt er niets, verwijder de bladwijzer en plak de regel opnieuw.

De bladwijzer zelf verandert nooit: alle logica zit in de lookup-pagina en de koppellijst. Een nieuwe versie van het script vraagt dus niet om een nieuwe bladwijzer. Welke versie actief is, staat onderaan de lookup-pagina en op het tabblad Info.

## Koppellijst als spreadsheet

Na elke geslaagde run staat de nieuwste versie op
`https://nieuwsgierige-kat.github.io/nww-taalwissel/koppellijst.xlsx`
(ook te vinden via de lookup-pagina zonder `?u=`). Tabbladen:

- **Gekoppeld**: NL-pagina met EN/ES/FR/DE, de NL sub-sitemap en hoe de koppeling gevonden is (*CMS*, *afgeleid* of *handmatig*).
- **Geen EN-versie**: Nederlandse pagina's uit de sitemap waar geen Engelse pagina naar linkt (ook niet afgeleid).
- **EN zonder NL-link**: Engelse pagina's waar het CMS geen NL-link geeft, met de vermoedelijke NL-pagina. Werklijst om de koppeling in het CMS te herstellen.
- **Doorverwijzingen in sitemap**: Engelse URL's die in de sitemap staan maar doorsturen naar een andere pagina. Die worden niet gekoppeld (anders lijkt het alsof twee Engelse pagina's naar dezelfde NL-pagina linken). Opruimlijst voor de sitemap. Wordt alleen bijgewerkt voor pagina's die opgehaald worden: draai daarom maandelijks een volledige run.
- **Meerdere EN naar 1 NL**: Nederlandse pagina's waar meer dan één Engelse pagina naar linkt (vaak dubbele of verkeerde koppeling in het CMS).
- **Te controleren**: Engelse pagina's die linken naar een NL-URL die niet in de NL-sitemap staat, met status:
  - *verplaatst*: de oude URL stuurt door; de nieuwe URL staat erbij en werkt ook in de bookmarklet.
  - *niet gevonden*: de Engelse pagina linkt naar een verwijderde Nederlandse pagina (fout in het CMS).
  - *niet in sitemap*: de pagina bestaat, maar ontbreekt in de sitemap.
  - *onduidelijk*: niet automatisch vast te stellen; handmatig bekijken.
- **Niet opgehaald**: sitemaps of Engelse pagina's die deze run niet opgehaald konden worden, met de reden. Leeg = alles gelukt.
- **Info**: datum van de run, scriptversie, aantallen en de uitslag van de controlepagina's.

**Controlepagina's** (`data/controle.json`): een vaste set koppelingen die elke run gecontroleerd wordt. Een afwijking staat in het log (`CONTROLE AFWIJKING`) en op het tabblad Info. Oorzaak is meestal een wijziging op de site of in het script; is die bewust, pas dan de verwachting in het bestand aan.

Het log van elke run begint met een zelftest: hoe de site een niet-bestaande pagina afhandelt. Als daar niet `-> niet gevonden` staat, klopt de detectie van verwijderde pagina's niet en moet het script aangepast worden.

## Bekende beperkingen

- Een Nederlandse pagina zonder Engelse versie geeft "Geen EN-versie gevonden". Datzelfde zie je als de Engelse pagina ontbreekt in de sitemap.
- Pagina's met alleen ES/FR/DE en geen Engelse versie worden niet gevonden.
- *Afgeleide* en *handmatige* koppelingen zijn vermoedens, geen CMS-gegevens. Een foute handmatige koppeling pas je aan in `data/handmatig.json`.
- Nieuwe of verplaatste pagina's verschijnen pas na de volgende run (maandag, of handmatig starten).
- De koppeling komt uit interne paginadata van de site, geen standaardtag. Bij een redesign kan die verdwijnen; de run faalt dan in plaats van de lijst te wissen.
