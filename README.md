# NWW taalwissel

Bookmarklet voor redacteuren: één klik op een pagina van nederlandwereldwijd.nl opent de Engelse versie op netherlandsworldwide.nl.

## Hoe het werkt

1. `build_map.py` leest de Engelse sitemap, haalt de Engelse pagina's op en leest uit de paginadata (`translations`) welke Nederlandse pagina erbij hoort.
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

Maak een bladwijzer met als URL:

```
javascript:(()=>{location.href='https://nieuwsgierige-kat.github.io/nww-taalwissel/?u='+encodeURIComponent(location.href)})()
```

Liever in een nieuw tabblad: vervang `location.href=` door `window.open(` en sluit af met `)` vóór `})()`:

```
javascript:(()=>{window.open('https://nieuwsgierige-kat.github.io/nww-taalwissel/?u='+encodeURIComponent(location.href))})()
```

Andere taal (bijv. Spaans; ook `fr` of `de`):

```
javascript:(()=>{location.href='https://nieuwsgierige-kat.github.io/nww-taalwissel/?u='+encodeURIComponent(location.href)+'&lang=es'})()
```

## Koppellijst als spreadsheet

Na elke geslaagde run staat de nieuwste versie op
`https://nieuwsgierige-kat.github.io/nww-taalwissel/koppellijst.xlsx`
(ook te vinden via de lookup-pagina zonder `?u=`). Tabbladen:

- **Gekoppeld**: NL-pagina met EN/ES/FR/DE en de NL sub-sitemap (handig om op te filteren).
- **Geen EN-versie**: Nederlandse pagina's uit de sitemap waar geen Engelse pagina naar linkt.
- **Te controleren**: Engelse pagina's die linken naar een NL-URL die niet in de NL-sitemap staat, met status:
  - *verplaatst*: de oude URL stuurt door; de nieuwe URL staat erbij en werkt ook in de bookmarklet.
  - *niet gevonden*: de Engelse pagina linkt naar een verwijderde Nederlandse pagina (fout in het CMS).
  - *niet in sitemap*: de pagina bestaat, maar ontbreekt in de sitemap.
  - *onduidelijk*: niet automatisch vast te stellen; handmatig bekijken.
- **Info**: datum van de run en aantallen.

Het log van elke run begint met een zelftest: hoe de site een niet-bestaande pagina afhandelt. Als daar niet `-> niet gevonden` staat, klopt de detectie van verwijderde pagina's niet en moet het script aangepast worden.

## Bekende beperkingen

- Een Nederlandse pagina zonder Engelse versie geeft "Geen EN-versie gevonden". Datzelfde zie je als de Engelse pagina ontbreekt in de sitemap.
- Pagina's met alleen ES/FR/DE en geen Engelse versie worden niet gevonden.
- Nieuwe of verplaatste pagina's verschijnen pas na de volgende run (maandag, of handmatig starten).
- De koppeling komt uit interne paginadata van de site, geen standaardtag. Bij een redesign kan die verdwijnen; de run faalt dan in plaats van de lijst te wissen.
