# Nordisk energimarked

Et dashboard over det nordiske elmarked med fokus på Danmark:

- **Spotpriser** for alle nordiske prisområder – DK1, DK2, NO1–NO5, SE1–SE4 og FI – med døgnpriser, timepriser, månedsgennemsnit og morgendagens priser.
- **Afgifter og nettariffer**: elafgift, Energinets tariffer og nettarif C for alle danske netselskaber, plus en opdeling af, hvad en kWh koster i lavlast, højlast og spidslast.
- **Elselskaber**: abonnement, spottillæg, binding og gebyrer hos 15 af de største danske elselskaber, med en beregner for elselskabets del af regningen ved et givet forbrug.
- **Nyheder**: dagens top 5 energinyheder i Danmark og i Norden, opdateret hver hverdag morgen, med arkiv.

Siden er ren HTML, CSS og JavaScript uden byggetrin. Alle tal ligger som CSV- og JSON-filer i `data/`.

## Kør siden lokalt

Browseren må ikke hente datafilerne, når `index.html` åbnes direkte som fil. Start en lille webserver i mappen:

```bash
python3 -m http.server 8000
```

Åbn derefter <http://localhost:8000>. Siden henter d3 v7 fra jsDelivr.

## Struktur

```
index.html                    Siden: markup, layout og diagrammer
css/tema.css                  Farver, skrift og afstande (lys og mørk tilstand)
js/dash.js                    Indlæser datafilerne og tegner siden, når data eller valg ændrer sig
data/datasets.json            Liste over datasæt med titel, beskrivelse, fil og opdateringsdato
scripts/hent_data.py          Henter spotpriser og tariffer (køres af GitHub Actions)
scripts/tjek_data.py          Kontrollerer datafilerne før hver commit
.github/workflows/            Automatisk opdatering hver hverdag
```

## Datakilder

| Fil | Indhold | Kilde | Opdateres |
|---|---|---|---|
| `spot_daglig.csv` | Døgngennemsnit, min. og maks. pr. prisområde, ca. 400 dage | DK: [Energi Data Service](https://www.energidataservice.dk/) (DayAheadPrices). NO: [hvakosterstrommen.no](https://www.hvakosterstrommen.no/). SE: [elprisetjustnu.se](https://www.elprisetjustnu.se/). FI: [Elering](https://dashboard.elering.ee/). NO, SE og FI bygger på ENTSO-E-data | Hverdage, GitHub Action |
| `spot_time.csv` | Timepriser for de seneste tre døgn | Samme | Hverdage, GitHub Action |
| `spot_maaned.csv` | Månedsgennemsnit pr. område | Beregnet af døgnpriserne | Hverdage, GitHub Action |
| `nettariffer.csv` | Nettarif C time for time og netabonnement pr. netselskab | Energi Data Service (DatahubPricelist) | Hverdage, GitHub Action |
| `afgifter.csv` | Elafgift og Energinets transmissions- og systemtarif | Energi Data Service (DatahubPricelist) | Hverdage, GitHub Action |
| `elselskaber.csv` | Elselskabernes priser og gebyrer | [Strømligning](https://stromligning.dk/) og selskabernes egne sider | Ugentligt, Claude |
| `nyheder.json` | Top 5 nyheder i Danmark og Norden pr. hverdag | Udvalgt og opsummeret af Claude med link til kilden | Hverdage, Claude |
| `omraader.csv` | Prisområder og navne | – | Fast |

Spotpriser vises i øre/kWh ekskl. moms. Priser i EUR/MWh omregnes med dagens EUR/DKK-kurs, som udledes af Energinets DK1-priser (der oplyses i både EUR og DKK). Alle døgn regnes i dansk tid, som er leveringsdøgnet på det nordiske day-ahead-marked.

## Automatisk opdatering

**GitHub Action – spotpriser og tariffer.** `.github/workflows/opdater-data.yml` kører mandag–fredag kl. ca. 13:47 dansk tid (efter day-ahead-auktionen) og kan startes manuelt under fanen *Actions*. Den henter manglende dage – også weekenden – samt morgendagens priser, og de gældende tariffer. Der committes kun, når der er nye tal. Fejl vises som annoteringer på kørslen.

**Planlagt Claude-opgave – nyheder og elselskaber.** Hver hverdag morgen udvælger Claude dagens fem mest interessante energinyheder i Danmark og fem i resten af Norden, skriver korte resuméer og tilføjer dem til `data/nyheder.json`. Om mandagen gennemgår opgaven også elselskabernes priser og gebyrer.

Begge kører `scripts/tjek_data.py` før hver commit.

## Sådan læses tallene

- **Nettarif C:** Scriptet vælger for hvert netselskab den gældende tarif i Datahub, hvis note indeholder "Nettarif C", og foretrækker den tidsdifferentierede ("time"). Kolonnen "Tarif i Datahub" viser, hvilken der er brugt.
- **Hvad koster en kWh:** spotprisen er gennemsnittet for tidsrummet den valgte dag i det valgte prisområde. Elselskabets tillæg er det valgte produkts. Alle komponenter vises inkl. moms; abonnementer er ikke med.
- **Elselskabets del af regningen pr. år:** abonnement × 12 (efter forbrugstrin, hvor selskabet har det) + spottillæg × forbrug + Betalingsservice-gebyr. Spotpris, nettarif, afgifter og moms er ens hos alle selskaber og indgår derfor ikke.

## Forbehold

Elselskabernes priser er indsamlet fra offentlige kilder og kan ændre sig. Tjek altid den aktuelle pris hos selskabet. Nyhedsresuméerne er korte sammenfatninger – læs hele artiklen hos kilden.
