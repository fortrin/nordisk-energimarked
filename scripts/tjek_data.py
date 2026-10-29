#!/usr/bin/env python3
"""
Kontrollerer datafilerne, før de committes:

- alle filer i data/datasets.json findes og kan læses
- hver CSV-række har lige så mange felter som overskriften
  (tekst med komma skal stå i anførselstegn)
- tal bruger punktum som decimaltegn
- JSON-filer er gyldige og indeholder en liste af rækker

Afslutter med kode 1 og en liste over fejl, hvis noget er galt.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def check_csv(path: Path, errors: list[str]) -> None:
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    if not rows:
        errors.append(f"{path.name}: tom fil")
        return
    head = rows[0]
    for i, r in enumerate(rows[1:], start=2):
        if len(r) != len(head):
            errors.append(f"{path.name} linje {i}: {len(r)} felter, forventede {len(head)} – mangler anførselstegn om tekst med komma?")
    # Tal med komma som decimaltegn bliver ikke læst som tal på siden
    comma = re.compile(r"^-?\d+,\d+$")
    for i, r in enumerate(rows[1:], start=2):
        for name, cell in zip(head, r):
            if comma.match(cell.strip()):
                errors.append(f"{path.name} linje {i}: {name} = {cell!r} – brug punktum som decimaltegn")


def main() -> int:
    errors: list[str] = []
    manifest = json.loads((ROOT / "data" / "datasets.json").read_text(encoding="utf-8"))
    for ds_id, meta in manifest["datasets"].items():
        f = ROOT / meta["fil"]
        if not f.exists():
            errors.append(f"{ds_id}: filen {meta['fil']} findes ikke")
            continue
        for k in ("titel", "beskrivelse", "opdateret"):
            if not meta.get(k):
                errors.append(f"{ds_id}: mangler {k} i datasets.json")
        if f.suffix == ".csv":
            check_csv(f, errors)
        elif f.suffix == ".json":
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if not isinstance(data, list):
                    errors.append(f"{f.name}: forventede en liste af rækker")
            except json.JSONDecodeError as err:
                errors.append(f"{f.name}: ugyldig JSON ({err})")
    if errors:
        print("Datafejl:\n- " + "\n- ".join(errors))
        return 1
    print(f"OK: {len(manifest['datasets'])} datasæt kontrolleret.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
