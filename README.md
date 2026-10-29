# Nordisk energimarked

Et dashboard over det nordiske elmarked for **erhvervskunder (B2B)** med fokus på Danmark. Alle beløb er ekskl. moms.

- **Spotpriser** for alle nordiske prisområder – DK1, DK2, NO1–NO5, SE1–SE4 og FI – med døgnpriser, timepriser, månedsgennemsnit og morgendagens priser.
- **Forbrugsprofiler**: spotprisen vægtet efter typiske erhvervsprofiler (kontor, butik, industri 1 og 2 skift, døgndrift) pr. måned, med profilfaktor i forhold til den flade døgnpris.
- **Tariffer og afgifter**: elafgift (fuld og efter godtgørelse for momsregistrerede virksomheder), Energinets tariffer og nettariffer for kundetype C, B-lav, B-høj, A-lav og A-høj inkl. effektbetaling for alle danske netselskaber, plus en opdeling af, hvad en kWh koster i lavlast, højlast og spidslast.
- **Erhvervsberegner**: anslået årlig elomkostning for en virksomhed ud fra forbrug (20 MWh–2 GWh), profil, prisområde, kundetype og netselskab, sammenlignet på tværs af elselskabernes offentliggjorte erhvervsprodukter (spot, fastpris, prisloft). Selskaber uden offentlige erhvervspriser og forbrug over produkternes grænser står under *Individuelle tilbud*.
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
| `spot_profil_daglig.csv`, `spot_profil_maaned.csv` | Profilvægtet spotpris for DK1 og DK2 pr. døgn og måned | Beregnet af kvarter-/timepriserne | Hverdage, GitHub Action |
| `nettariffer.csv` | Nettarif time for time og effektbetaling pr. netselskab og kundetype (C, B-lav, B-høj, A-lav, A-høj) | Energi Data Service (DatahubPricelist) | Hverdage, GitHub Action |
| `afgifter.csv` | Elafgift og Energinets transmissions- og systemtarif | Energi Data Service (DatahubPricelist) | Hverdage, GitHub Action |
| `elselskaber.csv` | Elselskabernes erhvervsprodukter: abonnement, spottillæg, fastpris, binding, forbrugsgrænse og gebyrer, ekskl. moms | Selskabernes egne erhvervssider | Ugentligt, Claude |
| `elselskaber_tilbud.csv` | Selskaber og forbrugsniveauer, hvor prisen forhandles individuelt | Selskabernes egne sider | Ugentligt, Claude |
| `nyheder.json` | Top 5 nyheder i Danmark og Norden pr. hverdag | Udvalgt og opsummeret af Claude med link til kilden | Hverdage, Claude |
| `omraader.csv` | Prisområder og navne | – | Fast |

Spotpriser vises i øre/kWh ekskl. moms. Priser i EUR/MWh omregnes med dagens EUR/DKK-kurs, som udledes af Energinets DK1-priser (der oplyses i både EUR og DKK). Alle døgn regnes i dansk tid, som er leveringsdøgnet på det nordiske day-ahead-marked.

## Automatisk opdatering

**GitHub Action – spotpriser og tariffer.** `.github/workflows/opdater-data.yml` kører mandag–fredag kl. ca. 13:47 dansk tid (efter day-ahead-auktionen) og kan startes manuelt under fanen *Actions*. Den henter manglende dage – også weekenden – samt morgendagens priser, og de gældende tariffer. Der committes kun, når der er nye tal. Fejl vises som annoteringer på kørslen.

**Planlagt Claude-opgave – nyheder og elselskaber.** Hver hverdag morgen udvælger Claude dagens fem mest interessante energinyheder i Danmark og fem i resten af Norden, skriver korte resuméer og tilføjer dem til `data/nyheder.json`. Nyhederne udvælges og kommenteres med virksomheders perspektiv. Om mandagen gennemgår opgaven også elselskabernes erhvervsprodukter.

Begge kører `scripts/tjek_data.py` før hver commit.

## Sådan læses tallene

- **Kundetyper:** C = tilsluttet lavspændingsnettet (0,4 kV) i en almindelig installation; B-lav/B-høj = 10 kV-nettet på hhv. lav- og højspændingssiden af transformeren; A-lav/A-høj = 50/60 kV-nettet. Scriptet vælger for hvert netselskab og hver kundetype den nyeste tidsdifferentierede tarif i Datahub og lægger regionale tillæg og rabatter for samme kundetype til. Kolonnen "Tarif i Datahub" viser, hvad der er brugt.
- **Effektbetaling:** kr. pr. kW pr. år, afregnet efter det gennemsnitlige forbrug i de 10 timer med størst forbrug over 12 måneder. Datahub angiver beløbet pr. døgn; det ganges med 365.
- **Elafgift:** fuld sats eller satsen efter godtgørelse (0,4 øre/kWh, EU-minimum) for momsregistrerede virksomheder, valgt på siden.
- **Forbrugsprofiler:** dansk tid; helligdage regnes som hverdage. Kontor: hverdage kl. 07–18 = 1, øvrige hverdagstimer 0,3, weekend 0,25. Butik: man–lør kl. 08–20 og søn kl. 10–17 = 1, ellers 0,3. Industri 1 skift: hverdage kl. 06–14 = 1, ellers 0,2. Industri 2 skift: hverdage kl. 06–22 = 1, ellers 0,3. Døgndrift = 1.
- **Erhvervsberegneren:** elpris = profilvægtet spotpris de seneste 12 hele måneder (eller produktets fastpris) × forbrug + spottillæg × forbrug + abonnement × 12 + nettarif og Energinets tariffer vægtet efter profilen + effektbetaling (anslået top-kW ud fra profilen) + elafgift. Netabonnement, rådighedstarif og selskabsspecifikke gebyrer er ikke med. Større virksomheder får typisk individuelle tilbud, så tallene er et sammenligningsgrundlag – ikke en pris.

## Forbehold

Elselskabernes erhvervspriser er indsamlet fra offentlige kilder og kan ændre sig. Tjek altid den aktuelle pris hos selskabet. Nyhedsresuméerne er korte sammenfatninger – læs hele artiklen hos kilden.
