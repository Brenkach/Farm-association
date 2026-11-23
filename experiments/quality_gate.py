#!/usr/bin/env python3
"""Лаб. 5: стійкий Quality Gate над серією прогонів (результати exp2_stability.py).

Правила (захист від хибних FAIL/PASS через інфраструктурний шум):
  0. Середовище вимірювання має збігатися з еталонним (ліміт CPU), інакше INCONCLUSIVE.
  1. Потрібно щонайменше MIN_RUNS прогонів, інакше INCONCLUSIVE.
  2. Прогін «порушує поріг», якщо p95 > 200 мс АБО error rate >= 1 %.
  3. Жоден прогін не порушує поріг      -> PASS  (з позначкою, якщо запас менше 10 %)
     Усі прогони порушують поріг         -> FAIL
     Частина прогонів порушує поріг      -> INCONCLUSIVE (шум біля порога, не вирок)

Код виходу: 0 = усі PASS, 1 = є FAIL, 2 = немає FAIL, але є INCONCLUSIVE (CI-friendly).

Запуск:
    python quality_gate.py results/exp2_*.json [--expect-cpu 0]
"""
import argparse
import json
import sys
from pathlib import Path

SLO_P95_MS = 200.0
SLO_ERR_PCT = 1.0
LOW_MARGIN = 0.9
MIN_RUNS = 5


def fmt_cpu(v):
    return "немає" if v == 0 else v


def evaluate(data, expect_cpu):
    meta, runs = data["meta"], data["runs"]
    if meta.get("cpu_limit") is None:
        return "INCONCLUSIVE", "ENV_UNKNOWN: ліміт CPU невідомий (docker недоступний)"
    if meta["cpu_limit"] != expect_cpu:
        return "INCONCLUSIVE", (f"ENV_MISMATCH: ліміт CPU {fmt_cpu(meta['cpu_limit'])}, "
                                f"еталон {fmt_cpu(expect_cpu)}: замір недійсний")
    n = len(runs)
    if n < MIN_RUNS:
        return "INCONCLUSIVE", f"NOT_ENOUGH_RUNS: {n} прогонів, потрібно {MIN_RUNS}"
    p95 = [r["p95_ms"] for r in runs]
    bad = [r for r in runs if r["p95_ms"] > SLO_P95_MS or r["error_pct"] >= SLO_ERR_PCT]
    if not bad:
        note = ", малий запас до порога" if max(p95) > LOW_MARGIN * SLO_P95_MS else ""
        return "PASS", f"усі {n} прогонів у нормі, max p95 {max(p95)} мс{note}"
    if len(bad) == n:
        return "FAIL", f"усі {n} прогонів порушують поріг, min p95 {min(p95)} мс"
    return "INCONCLUSIVE", (f"FLAKY: {len(bad)} з {n} прогонів порушують поріг "
                            f"(p95 {min(p95)}–{max(p95)} мс): шум, а не вирок")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--expect-cpu", type=float, default=0.0,
                    help="еталонний ліміт CPU контейнера (0 = без ліміту)")
    args = ap.parse_args()
    print(f"Правило: p95 <= {SLO_P95_MS:.0f} мс AND error < {SLO_ERR_PCT}% у КОЖНОМУ з >= {MIN_RUNS} прогонів; "
          f"еталонне середовище: CPU {fmt_cpu(args.expect_cpu)}\n")
    verdicts = []
    for f in args.files:
        data = json.loads(Path(f).read_text())
        v, why = evaluate(data, args.expect_cpu)
        verdicts.append(v)
        print(f"{data['meta']['label']:<16}{v:<13}{why}")
    sys.exit(1 if "FAIL" in verdicts else 2 if "INCONCLUSIVE" in verdicts else 0)


if __name__ == "__main__":
    main()
