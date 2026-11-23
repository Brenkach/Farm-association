#!/usr/bin/env python3
"""Лаб. 6, Завдання 1: Halstead-скринінг репозиторію (Radon).

Для кожного .py файлу: η1, η2, N1, N2 -> η, N, V, D, E (за формулами Холстеда).
Глобальна базова лінія: η1 = об'єднання унікальних операторів усіх файлів,
η2 = сума унікальних операндів по файлах, N1, N2 = суми.

Запуск з кореня проєкту:
    python halstead_scan.py                 # таблиця по файлах + глобальна лінія
    python halstead_scan.py --functions 12  # ТОП-12 функцій за E
    python halstead_scan.py --json out.json # зберегти сирі дані
"""
import argparse
import json
import math
import sys
from importlib import metadata
from pathlib import Path

from radon.visitors import HalsteadVisitor

SKIP_DIRS = {".venv", ".venv312", "venv", "env", ".git", "__pycache__", "node_modules",
             "reports", "static", "templates", ".idea", "results", "gate_test"}


def derived(h1, h2, n1, n2):
    """Похідні міри Холстеда із первинних."""
    eta, length = h1 + h2, n1 + n2
    volume = length * math.log2(eta) if eta > 1 else 0.0
    difficulty = (h1 / 2) * (n2 / h2) if h2 else 0.0
    return {"eta": eta, "N": length, "V": volume, "D": difficulty, "E": volume * difficulty}


def scan_file(path: Path):
    visitor = HalsteadVisitor.from_code(path.read_text(encoding="utf-8-sig"))
    primitives = dict(h1=len(visitor.operators_seen), h2=len(visitor.operands_seen),
                      n1=visitor.operators, n2=visitor.operands)
    funcs = []
    for fv in visitor.function_visitors:
        p = dict(h1=len(fv.operators_seen), h2=len(fv.operands_seen), n1=fv.operators, n2=fv.operands)
        funcs.append({"name": fv.context, **p, **derived(**p)})
    return visitor, {**primitives, **derived(**primitives)}, funcs


def python_files(root: Path):
    for p in sorted(root.rglob("*.py")):
        if not any(part in SKIP_DIRS for part in p.relative_to(root).parts):
            yield p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--functions", type=int, metavar="N", help="показати ТОП-N функцій за E")
    ap.add_argument("--json", metavar="FILE", help="зберегти результат у JSON")
    a = ap.parse_args()
    root = Path(a.root).resolve()

    rows, all_funcs, union_ops = [], [], set()
    totals = dict(h2=0, n1=0, n2=0)
    for p in python_files(root):
        try:
            visitor, m, funcs = scan_file(p)
        except (SyntaxError, UnicodeDecodeError) as e:
            print(f"ПРОПУЩЕНО {p.relative_to(root)}: {e}", file=sys.stderr)
            continue
        rel = str(p.relative_to(root))
        union_ops |= set(visitor.operators_seen)
        totals["h2"] += m["h2"]; totals["n1"] += m["n1"]; totals["n2"] += m["n2"]
        rows.append({"file": rel, "loc": len(p.read_text(encoding="utf-8-sig").splitlines()), **m})
        all_funcs += [{"file": rel, **f} for f in funcs]

    rows.sort(key=lambda r: -r["E"])
    print(f"radon {metadata.version('radon')} | файлів: {len(rows)} | корінь: {root}\n")
    print(f"{'файл':<34}{'LOC':>6}{'η1':>5}{'η2':>6}{'N1':>7}{'N2':>7}{'η':>6}{'N':>7}{'V':>10}{'D':>8}{'E':>12}")
    for r in rows:
        print(f"{r['file']:<34}{r['loc']:>6}{r['h1']:>5}{r['h2']:>6}{r['n1']:>7}{r['n2']:>7}"
              f"{r['eta']:>6}{r['N']:>7}{r['V']:>10.1f}{r['D']:>8.2f}{r['E']:>12.0f}")

    g = dict(h1=len(union_ops), **totals)
    gm = derived(g["h1"], g["h2"], g["n1"], g["n2"])
    print("\nГЛОБАЛЬНА БАЗОВА ЛІНІЯ (весь репозиторій)")
    print(f"  η1 (унікальні оператори, об'єднання)   = {g['h1']}")
    print(f"  η2 (унікальні операнди, сума по файлах) = {g['h2']}")
    print(f"  N1 = {g['n1']}   N2 = {g['n2']}   словник η = {gm['eta']}   довжина N = {gm['N']}")
    print(f"  V = {gm['V']:.1f} біт   D = {gm['D']:.2f}   E = {gm['E']:.0f}")

    if a.functions:
        all_funcs.sort(key=lambda f: -f["E"])
        print(f"\nТОП-{a.functions} функцій за E (η = η1 + η2 не менше 10-15 для вибору файлів)")
        print(f"{'файл : функція':<46}{'η1':>5}{'η2':>6}{'N1':>6}{'N2':>6}{'η':>5}{'V':>9}{'D':>7}{'E':>10}")
        for f in all_funcs[:a.functions]:
            label = f"{f['file']} : {f['name']}"
            print(f"{label[:45]:<46}{f['h1']:>5}{f['h2']:>6}{f['n1']:>6}{f['n2']:>6}{f['eta']:>5}"
                  f"{f['V']:>9.1f}{f['D']:>7.2f}{f['E']:>10.0f}")

    if a.json:
        Path(a.json).write_text(json.dumps({"files": rows, "global": {**g, **gm}, "functions": all_funcs},
                                           ensure_ascii=False, indent=2))
        print(f"\nЗбережено: {a.json}")


if __name__ == "__main__":
    main()
