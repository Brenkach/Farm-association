#!/usr/bin/env python3
"""Лаб. 7, завдання 3: синергетична матриця критичних зон (Hotspots).

Об'єднує:
  * статичну складність: CSV-звіт Lizard (максимальна CCN функції у файлі);
  * динаміку процесу: Churn Rate з git log (кількість комітів файлу за 90 днів).

Категорії (за методичкою):
  Hotspot            складність > поріг  і  churn >= поріг   (червона зона)
  Sleeping Danger    складність > поріг  і  churn <  поріг   (жовта зона)
  Active Development складність <= поріг і  churn >= поріг   (зелена зона)
  Stable             складність <= поріг і  churn <  поріг   (сіра зона)

Використання (CI та локально):
  hotspots.py --lizard lizard.csv --churn churn-90d.txt --json out.json --md out.md
"""
import argparse
import csv
import fnmatch
import json
import os
import re
from collections import defaultdict
from pathlib import Path

ORDER = {"Hotspot": 0, "Sleeping Danger": 1, "Active Development": 2, "Stable": 3}
ZONE = {"Hotspot": "червона", "Sleeping Danger": "жовта", "Active Development": "зелена", "Stable": "сіра"}


def read_lizard(path):
    """CSV Lizard без заголовка: NLOC,CCN,token,PARAM,length,location,file,function,long_name,start,end."""
    files = defaultdict(lambda: {"max_ccn": 0, "max_ccn_function": "-", "nloc": 0, "functions": 0})
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.reader(fh):
            if len(row) < 8:
                continue
            nloc, ccn, name, fname = int(row[0]), int(row[1]), row[7], row[6].removeprefix("./")
            f = files[fname]
            f["nloc"] += nloc
            f["functions"] += 1
            if ccn > f["max_ccn"]:
                f["max_ccn"], f["max_ccn_function"] = ccn, name
    return files


def read_churn(path):
    """Вивід `sort | uniq -c | sort -nr`: рядки виду '  12 routes.py'."""
    churn = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*(\d+)\s+(.+)$", line)
        if m:
            churn[m.group(2).strip().removeprefix("./")] = int(m.group(1))
    return churn


def classify(max_ccn, churn, cc_threshold, churn_threshold):
    complex_ = max_ccn > cc_threshold
    busy = churn >= churn_threshold
    if complex_ and busy:
        return "Hotspot"
    if complex_:
        return "Sleeping Danger"
    return "Active Development" if busy else "Stable"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lizard", required=True)
    ap.add_argument("--churn", required=True)
    ap.add_argument("--json", required=True)
    ap.add_argument("--md", required=True)
    ap.add_argument("--cc-threshold", type=int, default=10)
    ap.add_argument("--churn-threshold", type=int, default=3,
                    help="мінливість вважається високою від N комітів за 90 днів")
    ap.add_argument("--exclude", nargs="*", default=[], metavar="PATTERN",
                    help="шаблони шляхів, які не входять у матрицю (тести, службові скрипти)")
    ap.add_argument("--limit", type=int, default=15, help="скільки рядків показати в Markdown")
    a = ap.parse_args()

    complexity, churn = read_lizard(a.lizard), read_churn(a.churn)
    rows = []
    for fname, c in complexity.items():
        if any(fnmatch.fnmatch(fname, pat) for pat in a.exclude):
            continue
        n = churn.get(fname, 0)
        rows.append({"file": fname, "max_ccn": c["max_ccn"], "max_ccn_function": c["max_ccn_function"],
                     "nloc": c["nloc"], "functions": c["functions"], "commits_90d": n,
                     "category": classify(c["max_ccn"], n, a.cc_threshold, a.churn_threshold)})
    rows.sort(key=lambda r: (ORDER[r["category"]], -r["commits_90d"], -r["max_ccn"]))

    counts = {k: sum(1 for r in rows if r["category"] == k) for k in ORDER}
    report = {"commit": os.environ.get("GITHUB_SHA", "local"),
              "thresholds": {"cc_greater_than": a.cc_threshold, "commits_90d_at_least": a.churn_threshold},
              "summary": counts, "files": rows}
    Path(a.json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["## Синергетична матриця Hotspots", "",
             f"Поріг складності: CC > {a.cc_threshold}; висока мінливість: >= {a.churn_threshold} комітів за 90 днів.",
             "", "| Файл | Макс. CC (функція) | Комітів (90 днів) | Категорія ризику |", "|---|---|---|---|"]
    for r in rows[:a.limit]:
        lines.append(f"| `{r['file']}` | {r['max_ccn']} (`{r['max_ccn_function']}`) | {r['commits_90d']} | "
                     f"{r['category']} ({ZONE[r['category']]}) |")
    lines += ["", "Підсумок: " + ", ".join(f"{k}: {v}" for k, v in counts.items())]
    Path(a.md).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
