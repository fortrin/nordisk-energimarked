#!/usr/bin/env python3
"""
Henter spotpriser for alle nordiske prisområder og danske tariffer/afgifter
og skriver datafilerne i data/.

Kilder (alle åbne og uden API-nøgle):
  DK1, DK2  Energi Data Service (Energinet), datasættet DayAheadPrices
  NO1–NO5   hvakosterstrommen.no (ENTSO-E-data)
  SE1–SE4   elprisetjustnu.se (ENTSO-E-data)
  FI        Elering (estisk TSO), dashboard.elering.ee
  Tariffer  Energi Data Service, datasættet DatahubPricelist

Filer:
  data/spot_daglig.csv   døgngennemsnit pr. område (seneste ~400 dage)
  data/spot_time.csv     timepriser for de seneste 3 dage med data
  data/spot_maaned.csv   månedsstatistik pr. område
  data/nettariffer.csv   nettarif C (time) og abonnement pr. netselskab
  data/afgifter.csv      elafgift og Energinets tariffer

Alle døgn regnes i dansk tid (Europe/Copenhagen), som er leveringsdøgnet for
det nordiske day-ahead-marked. Priser omregnes fra EUR/MWh til øre/kWh med
dagens EUR/DKK-kurs udledt af Energinets DK1-priser (fallback 7,46).

Kun Pythons standardbibliotek bruges.
"""
from __future__ import annotations

import csv
import json
import statistics
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CPH = ZoneInfo("Europe/Copenhagen")
UA = {"User-Agent": "nordisk-energimarked/1.0 (github.com/fortrin/nordisk-energimarked)"}
DAYS_KEEP = 400
FALLBACK_EURDKK = 7.46
ENERGINET_GLN = "5790000432752"
LAND = {"DK1": "Danmark", "DK2": "Danmark", "FI": "Finland",
        **{f"NO{i}": "Norge" for i in range(1, 6)}, **{f"SE{i}": "Sverige" for i in range(1, 5)}}

ERRORS: list[str] = []


# ------------------------------------------------------------ hjælpere
def annotate(level: str, title: str, message: str) -> None:
    import os
    msg = message.replace("%", "%25").replace("\r", "").replace("\n", "%0A")[:4000]
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::{level} title={title}::{msg}")
    else:
        print(f"[{level}] {title}: {message}")


def get_json(url: str, retries: int = 3):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as res:
                return json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            if err.code == 404:
                return None
            last = err
        except Exception as err:  # noqa: BLE001
            last = err
        time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"{url}: {last}")


def local_dt(s: str) -> datetime:
    """ISO-tid med eller uden offset → dansk lokal tid."""
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=CPH)
    return d.astimezone(CPH)


def daterange(a: date, b: date):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def r2(v: float) -> str:
    return f"{v:.2f}"


# ------------------------------------------------------------ spotpriser
# Hver kilde returnerer {omraade: [(lokal datetime, EUR/MWh), ...]}

def fetch_dk(start: date, end: date) -> tuple[dict, dict]:
    """Energi Data Service. Returnerer (priser, eur_dkk pr. dato)."""
    params = {
        "start": start.isoformat(), "end": (end + timedelta(days=1)).isoformat(),
        "filter": json.dumps({"PriceArea": ["DK1", "DK2"]}),
        "columns": "TimeDK,PriceArea,DayAheadPriceEUR,DayAheadPriceDKK",
        "sort": "TimeDK asc", "limit": "0",
    }
    url = "https://api.energidataservice.dk/dataset/DayAheadPrices?" + urllib.parse.urlencode(params)
    data = get_json(url) or {}
    out, ratio = defaultdict(list), defaultdict(list)
    for r in data.get("records", []):
        eur, dkk = r.get("DayAheadPriceEUR"), r.get("DayAheadPriceDKK")
        if eur is None:
            continue
        t = local_dt(r["TimeDK"])
        out[r["PriceArea"]].append((t, float(eur)))
        if dkk is not None and abs(eur) > 1:
            ratio[t.date()].append(float(dkk) / float(eur))
    rates = {d: statistics.median(v) for d, v in ratio.items() if v}
    return dict(out), rates


def _fetch_day_files(base: str, areas: list[str], days: list[date], key_eur: str) -> dict:
    out = defaultdict(list)

    def one(args):
        area, d = args
        url = f"{base}/{d.year}/{d.month:02d}-{d.day:02d}_{area}.json"
        try:
            return area, get_json(url) or []
        except Exception as err:  # noqa: BLE001
            return area, err

    jobs = [(a, d) for a in areas for d in days]
    errs = 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        for area, res in ex.map(one, jobs):
            if isinstance(res, Exception):
                errs += 1
                if errs <= 3:
                    ERRORS.append(str(res))
                continue
            for r in res:
                if r.get(key_eur) is None:
                    continue
                out[area].append((local_dt(r["time_start"]), float(r[key_eur]) * 1000))
    if errs:
        annotate("warning", f"{base}: {errs} dagfiler fejlede", "\n".join(ERRORS[-3:]))
    return dict(out)


def fetch_no(days: list[date]) -> dict:
    return _fetch_day_files("https://www.hvakosterstrommen.no/api/v1/prices",
                            [f"NO{i}" for i in range(1, 6)], days, "EUR_per_kWh")


def fetch_se(days: list[date]) -> dict:
    return _fetch_day_files("https://www.elprisetjustnu.se/api/v1/prices",
                            [f"SE{i}" for i in range(1, 5)], days, "EUR_per_kWh")


def fetch_fi(start: date, end: date) -> dict:
    out = []
    cur = start
    while cur <= end:
        stop = min(end, cur + timedelta(days=30))
        a = datetime.combine(cur, datetime.min.time(), CPH).astimezone(timezone.utc)
        b = datetime.combine(stop + timedelta(days=1), datetime.min.time(), CPH).astimezone(timezone.utc)
        params = {"start": a.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "end": b.strftime("%Y-%m-%dT%H:%M:%S.000Z")}
        data = get_json("https://dashboard.elering.ee/api/nps/price?" + urllib.parse.urlencode(params)) or {}
        for r in (data.get("data") or {}).get("fi", []):
            t = datetime.fromtimestamp(int(r["timestamp"]), tz=timezone.utc).astimezone(CPH)
            if r.get("price") is not None and a <= t.astimezone(timezone.utc) < b:
                out.append((t, float(r["price"])))
        cur = stop + timedelta(days=1)
    return {"FI": out}


def update_spot(today: date) -> None:
    daily_path = DATA / "spot_daglig.csv"
    old = read_csv(daily_path)
    have = defaultdict(set)
    for r in old:
        have[r["omraade"]].add(r["dato"])

    first = today - timedelta(days=DAYS_KEEP)
    tomorrow = today + timedelta(days=1)

    def missing(area: str) -> list[date]:
        """Manglende dage samt de seneste 3 dage (genhentes altid)."""
        ds = [d for d in daterange(first, tomorrow) if d.isoformat() not in have[area]]
        recent = [today - timedelta(days=2), today - timedelta(days=1), today, tomorrow]
        return sorted(set(ds) | set(recent))

    prices: dict[str, list] = {}
    rates: dict[date, float] = {}

    sources = [
        ("DK", ["DK1", "DK2"], lambda ds: fetch_dk(min(ds), max(ds))),
        ("NO", [f"NO{i}" for i in range(1, 6)], lambda ds: (fetch_no(ds), {})),
        ("SE", [f"SE{i}" for i in range(1, 5)], lambda ds: (fetch_se(ds), {})),
        ("FI", ["FI"], lambda ds: (fetch_fi(min(ds), max(ds)), {})),
    ]
    for name, areas, fn in sources:
        ds = sorted(set(d for a in areas for d in missing(a)))
        try:
            got, rt = fn(ds)
            rates.update(rt)
            n = sum(len(v) for v in got.values())
            annotate("notice", f"Spotpriser {name}", f"{len(ds)} dage forespurgt, {n} prispunkter, områder: {', '.join(sorted(got))}")
            prices.update(got)
        except Exception as err:  # noqa: BLE001
            annotate("error", f"Spotpriser {name} fejlede", str(err))
            ERRORS.append(f"{name}: {err}")

    # Kurser fra eksisterende rækker bruges, hvor DK-data mangler
    old_rates = {r["dato"]: float(r["eur_dkk"]) for r in old if r.get("eur_dkk")}

    def rate(d: date) -> float:
        if d in rates:
            return rates[d]
        if d.isoformat() in old_rates:
            return old_rates[d.isoformat()]
        prev = [v for k, v in rates.items() if k <= d] or list(rates.values())
        return prev[-1] if prev else FALLBACK_EURDKK

    # Døgnaggregering
    new_daily: dict[tuple, dict] = {}
    hourly: dict[tuple, list] = defaultdict(list)
    for area, pts in prices.items():
        by_day = defaultdict(list)
        for t, eur in pts:
            by_day[t.date()].append((t, eur))
        for d, lst in by_day.items():
            if d < first or d > tomorrow:
                continue
            k = rate(d) / 10  # EUR/MWh → øre/kWh
            vals = [e for _, e in lst]
            if len(vals) < 20:  # ufuldstændigt døgn
                continue
            new_daily[(d.isoformat(), area)] = {
                "dato": d.isoformat(), "omraade": area, "land": LAND[area],
                "gns_eur_mwh": r2(statistics.fmean(vals)),
                "gns_oere_kwh": r2(statistics.fmean(vals) * k),
                "min_oere_kwh": r2(min(vals) * k), "max_oere_kwh": r2(max(vals) * k),
                "negative_timer": f"{sum(1 for v in vals if v < 0) * 24 / len(vals):.2f}",
                "eur_dkk": f"{rate(d):.4f}",
            }
            for t, eur in lst:
                hourly[(d.isoformat(), t.hour, area)].append(eur)

    merged = {(r["dato"], r["omraade"]): r for r in old if r["dato"] >= first.isoformat()}
    merged.update(new_daily)
    daily = sorted(merged.values(), key=lambda r: (r["dato"], int(_order(r["omraade"]))))
    write_csv(daily_path, ["dato", "omraade", "land", "gns_eur_mwh", "gns_oere_kwh", "min_oere_kwh",
                           "max_oere_kwh", "negative_timer", "eur_dkk"], daily)

    # Timepriser: de seneste 3 dage med data (beholdes fra sidste kørsel, hvis kilden fejlede)
    old_h = {(r["dato"], int(r["time"]), r["omraade"]): r for r in read_csv(DATA / "spot_time.csv")}
    for (d, h, area), vals in hourly.items():
        k = rate(date.fromisoformat(d)) / 10
        e = statistics.fmean(vals)
        old_h[(d, h, area)] = {"dato": d, "time": str(h), "omraade": area, "eur_mwh": r2(e), "oere_kwh": r2(e * k)}
    days_with = sorted({k[0] for k in old_h})[-3:]
    hrows = sorted((v for k, v in old_h.items() if k[0] in days_with),
                   key=lambda r: (r["dato"], int(_order(r["omraade"])), int(r["time"])))
    write_csv(DATA / "spot_time.csv", ["dato", "time", "omraade", "eur_mwh", "oere_kwh"], hrows)

    # Månedsstatistik
    m = defaultdict(list)
    for r in daily:
        m[(r["dato"][:7], r["omraade"])].append(r)
    mrows = []
    for (mon, area), lst in sorted(m.items(), key=lambda kv: (kv[0][0], int(_order(kv[0][1])))):
        mrows.append({
            "maaned": mon, "omraade": area, "land": LAND[area],
            "gns_oere_kwh": r2(statistics.fmean(float(x["gns_oere_kwh"]) for x in lst)),
            "min_oere_kwh": r2(min(float(x["min_oere_kwh"]) for x in lst)),
            "max_oere_kwh": r2(max(float(x["max_oere_kwh"]) for x in lst)),
            "dage": str(len(lst)),
        })
    write_csv(DATA / "spot_maaned.csv", ["maaned", "omraade", "land", "gns_oere_kwh", "min_oere_kwh", "max_oere_kwh", "dage"], mrows)

    last = max((r["dato"] for r in daily), default="–")
    per_area = defaultdict(str)
    for r in daily:
        per_area[r["omraade"]] = max(per_area[r["omraade"]], r["dato"])
    annotate("notice", "Spotpriser skrevet", f"{len(daily)} døgnrækker, seneste dato {last}. Seneste pr. område: "
             + ", ".join(f"{a} {d}" for a, d in sorted(per_area.items(), key=lambda kv: _order(kv[0]))))


ORDER = ["DK1", "DK2", "NO1", "NO2", "NO3", "NO4", "NO5", "SE1", "SE2", "SE3", "SE4", "FI"]


def _order(area: str) -> int:
    return ORDER.index(area) if area in ORDER else 99


# ------------------------------------------------------------ tariffer
def hourly_prices(r: dict) -> list[float] | None:
    vals = [r.get(f"Price{i}") for i in range(1, 25)]
    if vals[0] is None:
        return None
    first = float(vals[0])
    return [float(v) if v is not None else first for v in vals]


def valid_now(r: dict, now: datetime) -> bool:
    vf = r.get("ValidFrom")
    vt = r.get("ValidTo")
    if not vf or local_dt(vf) > now:
        return False
    return not vt or local_dt(vt) > now


def update_tariffs(now: datetime) -> None:
    params = {
        "start": "2018-01-01", "filter": json.dumps({"ChargeType": ["D01", "D03"]}),
        "limit": "0",
    }
    url = "https://api.energidataservice.dk/dataset/DatahubPricelist?" + urllib.parse.urlencode(params)
    try:
        data = get_json(url) or {}
    except Exception as err:  # noqa: BLE001
        annotate("error", "Tariffer fejlede", str(err))
        ERRORS.append(f"tariffer: {err}")
        return
    recs = [r for r in data.get("records", []) if valid_now(r, now)]
    annotate("notice", "DatahubPricelist", f"{len(data.get('records', []))} poster hentet, {len(recs)} gældende nu")

    def text(r):
        return f"{r.get('Note') or ''} {r.get('Description') or ''}".lower()

    # Energinet og afgifter
    afg = []
    en = [r for r in recs if r.get("GLN_Number") == ENERGINET_GLN and r.get("ChargeType") == "D03"]
    picks = {
        "elafgift": lambda r: "elafgift" in text(r) and "reduceret" not in text(r) and "tilbagebetal" not in text(r),
        "nettarif": lambda r: "transmission" in text(r) and "nettarif" in text(r),
        "systemtarif": lambda r: "systemtarif" in text(r),
    }
    names = {"elafgift": "Elafgift", "nettarif": "Energinet nettarif (transmission)", "systemtarif": "Energinet systemtarif"}
    for key, ok in picks.items():
        cands = sorted([r for r in en if ok(r)], key=lambda r: r.get("ValidFrom") or "", reverse=True)
        if not cands:
            annotate("warning", f"Fandt ikke {names[key]}", "Energinet-poster: " + "; ".join(sorted({(r.get('Note') or '') for r in en}))[:1500])
            continue
        r = cands[0]
        p = hourly_prices(r) or [0.0]
        afg.append({"id": key, "navn": names[key], "kr_kwh": f"{statistics.fmean(p):.5f}",
                    "gyldig_fra": (r.get("ValidFrom") or "")[:10], "note": r.get("Note") or ""})
    if afg:
        write_csv(DATA / "afgifter.csv", ["id", "navn", "kr_kwh", "gyldig_fra", "note"], afg)

    # Netselskabernes C-tarif (husholdninger og mindre virksomheder).
    # Hovedtariffen er den nyeste tidsdifferentierede "Nettarif C". Nogle netselskaber deler
    # tariffen op i flere poster, som lægges til: regional nettarif C, rabat på nettarif C og
    # tarif for overliggende/overordnet net.
    import re
    MAIN = re.compile(r"nettarif\s*c\b|c-kunde nettarif|nettarif fra 0")
    EXCL = re.compile(r"kollektiv|fællesskab|flex|skabelon|rådighed|effekt|nettab|rabat|regional|overliggende|overordnet|"
                      r"produktion|indfød|egenprod|erhverv|fritid|midlertidig|reaktiv|\bb\b|\ba\b|b-lav|b-høj|a-lav|a-høj|"
                      r"100\.000|1\.000\.000")
    REGIONAL = re.compile(r"regional nettarif c")
    REBATE = re.compile(r"rabat.*nettarif c")
    UPSTREAM = re.compile(r"overliggende net|overordnet net")
    UP_EXCL = re.compile(r"rabat|produktion|indfød|\bb\b|\ba\b|b-lav|b-høj|a-lav|a-høj|b kunde|a kunde")
    by_owner = defaultdict(list)
    for r in recs:
        if r.get("GLN_Number") != ENERGINET_GLN and r.get("ChargeType") == "D03":
            by_owner[(r.get("GLN_Number"), r.get("ChargeOwner"))].append(r)

    rows, log = [], []
    for (gln, owner), lst in sorted(by_owner.items(), key=lambda kv: kv[0][1] or ""):
        cands = []
        for r in lst:
            t = text(r)
            if not MAIN.search(t) or EXCL.search(t):
                continue
            p = hourly_prices(r)
            if not p or max(p) <= 0:
                continue
            cands.append(((max(p) - min(p)) > 1e-6, r.get("ValidFrom") or "", r, p))
        if not cands:
            continue
        cands.sort(key=lambda x: (x[0], x[1]), reverse=True)
        _, _, main, total = cands[0]
        total = list(total)
        parts = [main.get("Note") or main.get("Description") or ""]
        for r in lst:
            if r is main:
                continue
            t = text(r)
            add = (REGIONAL.search(t) or (REBATE.search(t) and not re.search(r"lokal|kollektiv", t))
                   or (UPSTREAM.search(t) and not UP_EXCL.search(t)))
            if not add:
                continue
            p = hourly_prices(r)
            if not p or not any(abs(v) > 1e-9 for v in p):
                continue
            total = [x + y for x, y in zip(total, p)]
            parts.append(r.get("Note") or r.get("Description") or "")
        row = {
            "netselskab": owner, "gln": gln, "tarif": " + ".join(parts),
            "kode": main.get("ChargeTypeCode") or "", "gyldig_fra": (main.get("ValidFrom") or "")[:10],
            "lavlast_kr": f"{total[3]:.5f}", "hoejlast_kr": f"{total[10]:.5f}", "spidslast_kr": f"{total[18]:.5f}",
        }
        row.update({f"t{h:02d}": f"{total[h]:.5f}" for h in range(24)})
        rows.append(row)
        log.append(f"{owner}: {float(row['lavlast_kr']) * 125:.2f}/{float(row['hoejlast_kr']) * 125:.2f}/"
                   f"{float(row['spidslast_kr']) * 125:.2f} øre inkl. moms ({row['tarif']})")
    # Diagnose: alle gældende D03-poster for udvalgte netselskaber (DIAG="navn1,navn2")
    import os
    diag = [d.strip().lower() for d in os.environ.get("DIAG", "").split(",") if d.strip()]
    if diag:
        picked = {r["gln"] for r in rows}
        missing = sorted({o for (g, o) in by_owner if g not in picked})
        annotate("notice", "Netselskaber uden valgt tarif", "; ".join(missing)[:3900])
        chunks, cur = [], ""
        for (gln, owner), lst in sorted(by_owner.items(), key=lambda kv: kv[0][1] or ""):
            if not any(d in (owner or "").lower() for d in diag):
                continue
            for r in sorted(lst, key=lambda x: x.get("ValidFrom") or ""):
                if r.get("ChargeType") != "D03":
                    continue
                p = hourly_prices(r) or [0.0] * 24
                line = (f"{owner} | {r.get('ChargeType')} | {r.get('Note')} | {r.get('Description')} | {r.get('ChargeTypeCode')} | "
                        f"{(r.get('ValidFrom') or '')[:10]}–{(r.get('ValidTo') or '')[:10]} | {r.get('ResolutionDuration')} | "
                        f"t03 {p[3]:.4f} t10 {p[10]:.4f} t18 {p[18]:.4f}\n")
                if len(cur) + len(line) > 3800:
                    chunks.append(cur); cur = ""
                cur += line
        if cur:
            chunks.append(cur)
        for i, c in enumerate(chunks[:9]):
            annotate("warning", f"DIAG {i + 1}", c)
    if rows:
        write_csv(DATA / "nettariffer.csv",
                  ["netselskab", "gln", "tarif", "kode", "gyldig_fra", "lavlast_kr", "hoejlast_kr", "spidslast_kr"]
                  + [f"t{h:02d}" for h in range(24)], rows)
    text_log = "\n".join(log)
    for i in range(0, min(len(text_log), 7600), 3800):
        annotate("notice", f"Nettariffer: {len(rows)} netselskaber ({i // 3800 + 1})", text_log[i:i + 3800])


# ------------------------------------------------------------ datasæt-manifest
def touch_manifest(ids: list[str], today: date) -> None:
    p = DATA / "datasets.json"
    m = json.loads(p.read_text(encoding="utf-8"))
    for i in ids:
        if i in m["datasets"]:
            m["datasets"][i]["opdateret"] = today.isoformat()
    p.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    now = datetime.now(CPH)
    today = now.date()
    before = {f.name: f.read_bytes() for f in DATA.glob("*.csv")}
    update_spot(today)
    update_tariffs(now)
    changed = [f.stem for f in DATA.glob("*.csv") if before.get(f.name) != f.read_bytes()]
    ids = {"spot_daglig": "spot_daglig", "spot_time": "spot_time", "spot_maaned": "spot_maaned",
           "nettariffer": "nettariffer", "afgifter": "afgifter"}
    touch_manifest([ids[c] for c in changed if c in ids], today)
    print("Ændrede filer:", ", ".join(changed) or "ingen")
    return 1 if ERRORS and not changed else 0


if __name__ == "__main__":
    sys.exit(main())
