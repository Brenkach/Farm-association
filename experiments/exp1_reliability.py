#!/usr/bin/env python3
"""Лаб. 5, Експеримент 1: надійність (Reliability) засобів статичного аналізу.

Той самий файл коду міряється Radon і Lizard у кількох варіантах, які НЕ змінюють логіку:
  A0 оригінал | A1 LF | A2 CRLF | A3 UTF-8 з BOM
Скрипт працює під тим інтерпретатором, яким запущений (сценарій Б = інший інтерпретатор).

Запуск:
    python exp1_reliability.py routes.py                      # заміри + збереження JSON
    python exp1_reliability.py --compare results/a.json results/b.json   # порівняння версій
"""
import argparse
import hashlib
import json
import platform
import statistics
import subprocess
import sys
import tempfile
from importlib import metadata
from pathlib import Path

import lizard


def make_variants(raw: bytes) -> dict:
    lf = raw.replace(b"\r\n", b"\n")
    return {
        "A0_original": raw,
        "A1_LF": lf,
        "A2_CRLF": lf.replace(b"\n", b"\r\n"),
        "A3_UTF8_BOM": b"\xef\xbb\xbf" + lf,
    }


RADON_KEYS = ["radon_blocks", "radon_cc_avg", "radon_cc_max", "radon_loc",
              "radon_sloc", "radon_lloc", "radon_comments", "radon_blank"]
ERRORS = {}   # варіант -> текст помилки інструмента


def radon_metrics(path: Path) -> dict:
    def run(kind):
        p = subprocess.run([sys.executable, "-m", "radon", kind, "-j", str(path)],
                           capture_output=True, text=True)
        return json.loads(p.stdout)[str(path)]

    cc, raw = run("cc"), run("raw")
    bad = cc if isinstance(cc, dict) else raw if "error" in raw else None
    if bad is not None:
        ERRORS[path.parent.name] = bad.get("error", str(bad))
        return {k: "ERROR" for k in RADON_KEYS}
    values = [b["complexity"] for b in cc]
    return {
        "radon_blocks": len(cc),
        "radon_cc_avg": round(statistics.mean(values), 3) if values else 0,
        "radon_cc_max": max(values) if values else 0,
        "radon_loc": raw["loc"], "radon_sloc": raw["sloc"], "radon_lloc": raw["lloc"],
        "radon_comments": raw["comments"], "radon_blank": raw["blank"],
    }


def lizard_metrics(path: Path) -> dict:
    info = lizard.analyze_file(str(path))
    ccn = [f.cyclomatic_complexity for f in info.function_list]
    return {
        "lizard_nloc": info.nloc,
        "lizard_functions": len(ccn),
        "lizard_ccn_max": max(ccn) if ccn else 0,
        "lizard_ccn_avg": round(statistics.mean(ccn), 3) if ccn else 0,
        "lizard_over_15": sum(1 for c in ccn if c > 15),
    }


def measure(target: Path) -> dict:
    raw = target.read_bytes()
    out = {}
    with tempfile.TemporaryDirectory() as tmp:
        for name, data in make_variants(raw).items():
            p = Path(tmp) / name / target.name
            p.parent.mkdir()
            p.write_bytes(data)
            out[name] = {**radon_metrics(p), **lizard_metrics(p)}
    return out


def meta(target: Path) -> dict:
    return {
        "file": target.name,
        "file_sha256": hashlib.sha256(target.read_bytes()).hexdigest()[:16],
        "python": platform.python_version(),
        "platform": platform.platform(),
        "radon": metadata.version("radon"),
        "lizard": metadata.version("lizard"),
    }


def print_table(results: dict) -> None:
    keys = list(next(iter(results.values())).keys())
    names = list(results)
    print(f"{'метрика':<20}" + "".join(f"{n:>14}" for n in names) + "   однакові?")
    for k in keys:
        vals = [results[n][k] for n in names]
        same = "так" if len(set(map(str, vals))) == 1 else "НІ"
        print(f"{k:<20}" + "".join(f"{str(v):>14}" for v in vals) + f"   {same}")


def verdict(results: dict) -> int:
    base = results["A0_original"]
    diffs = [(n, k, base[k], v[k]) for n, v in results.items() for k in base if v[k] != base[k]]
    if diffs:
        print(f"\nРОЗБІЖНОСТІ ({len(diffs)}): метрики залежать від форматування файлу")
        for n, k, a, b in diffs:
            print(f"  {n}: {k}: {a} -> {b}")
    else:
        print("\nВСІ ЧИСЛА ІДЕНТИЧНІ для всіх варіантів файлу (інструменти стійкі до CRLF/LF/BOM)")
    return len(diffs)


def compare(a_path: str, b_path: str) -> None:
    a, b = json.loads(Path(a_path).read_text()), json.loads(Path(b_path).read_text())
    print(f"A: Python {a['meta']['python']}, radon {a['meta']['radon']}, lizard {a['meta']['lizard']}")
    print(f"B: Python {b['meta']['python']}, radon {b['meta']['radon']}, lizard {b['meta']['lizard']}")
    if a["meta"]["file_sha256"] != b["meta"]["file_sha256"]:
        print("УВАГА: заміри зроблені для РІЗНИХ файлів, порівняння некоректне")
    bad = 0
    print(f"\n{'варіант':<14}{'метрика':<20}{'A':>10}{'B':>10}")
    for var, ma in a["results"].items():
        for k, va in ma.items():
            vb = b["results"][var][k]
            if va != vb:
                bad += 1
                print(f"{var:<14}{k:<20}{str(va):>10}{str(vb):>10}   <-- відрізняється")
    print("\nУСЕ ІДЕНТИЧНО між версіями" if not bad else f"\nРОЗБІЖНОСТІ МІЖ ВЕРСІЯМИ: {bad}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file", nargs="?")
    ap.add_argument("--compare", nargs=2, metavar=("A.json", "B.json"))
    args = ap.parse_args()
    if args.compare:
        return compare(*args.compare)
    if not args.file:
        ap.error("вкажіть файл для аналізу або --compare")
    target = Path(args.file)
    m = meta(target)
    print(f"Файл: {m['file']} (sha256 {m['file_sha256']})  Python {m['python']}  "
          f"radon {m['radon']}  lizard {m['lizard']}\n")
    results = measure(target)
    print_table(results)
    for variant, msg in ERRORS.items():
        print(f"\nЗБІЙ ІНСТРУМЕНТА (radon, {variant}): {msg}")
    verdict(results)
    Path("results").mkdir(exist_ok=True)
    out = Path("results") / f"exp1_py{'.'.join(m['python'].split('.')[:2])}.json"
    out.write_text(json.dumps({"meta": m, "results": results}, ensure_ascii=False, indent=2))
    print(f"\nЗбережено: {out}")


if __name__ == "__main__":
    main()
