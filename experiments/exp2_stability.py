#!/usr/bin/env python3
"""Лаб. 5, Експеримент 2: стабільність (Stability) динамічних метрик під інфраструктурним шумом.

Код застосунку НЕ змінюється; змінюється лише середовище (ліміт CPU контейнера, фоновий процес).
Скрипт кілька разів міряє p95 / error rate / RAM і перевіряє Quality Gate:
    PASS  <=>  (p95 <= 200 мс) AND (error rate < 1 %)

Запуск (з папки experiments, Docker і сайт підняті):
    python exp2_stability.py --label baseline
    docker update --cpus 0.3 farm_web
    python exp2_stability.py --label cpu_0.3
    python exp2_stability.py --summary results/exp2_baseline.json results/exp2_cpu_0.3.json
"""
import argparse
import getpass
import json
import os
import platform
import re
import statistics
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

P95_SLO_MS = 200.0
ERR_SLO_PCT = 1.0
CONTAINER = "farm_web"


def docker(*args):
    try:
        p = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return p.stdout.strip() if p.returncode == 0 else None


def cpu_limit():
    v = docker("inspect", "-f", "{{.HostConfig.NanoCpus}}", CONTAINER)
    if v is None or not v.isdigit():
        return None
    return round(int(v) / 1e9, 2) or 0.0   # 0.0 = без ліміту


def mem_mb():
    v = docker("stats", "--no-stream", "--format", "{{.MemUsage}}", CONTAINER)
    m = re.match(r"([\d.]+)\s*([KMG]i?B)", v or "")
    if not m:
        return None
    k = {"KB": 1 / 1024, "KiB": 1 / 1024, "MB": 1, "MiB": 1, "GB": 1024, "GiB": 1024}[m.group(2)]
    return round(float(m.group(1)) * k, 1)


def login(base):
    pw = os.getenv("ADMIN_PASSWORD") or getpass.getpass("ADMIN_PASSWORD: ")
    s = requests.Session()
    r = s.post(base + "/login", data={"login": "admin", "password": pw},
               allow_redirects=False, timeout=15)
    if r.status_code != 302:
        raise SystemExit("Не вдалося увійти як admin (перевірте ADMIN_PASSWORD).")
    return s.cookies.get_dict()


def one_run(base, path, n, workers, cookies):
    local = threading.local()

    def hit(_):
        if not hasattr(local, "s"):
            local.s = requests.Session()
            local.s.cookies.update(cookies)
        t = time.perf_counter()
        try:
            ok = local.s.get(base + path, timeout=15, allow_redirects=False).status_code == 200
        except requests.RequestException:
            ok = False
        return (time.perf_counter() - t) * 1000, ok

    t0 = time.perf_counter()
    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(hit, range(n)))
    wall = time.perf_counter() - t0
    lat = sorted(x for x, _ in res)
    q = statistics.quantiles(lat, n=100, method="inclusive")
    err = 100.0 * sum(1 for _, ok in res if not ok) / n
    p95 = q[94]
    return {
        "p50_ms": round(q[49], 1), "p95_ms": round(p95, 1), "p99_ms": round(q[98], 1),
        "mean_ms": round(statistics.mean(lat), 1), "max_ms": round(lat[-1], 1),
        "error_pct": round(err, 2), "rps": round(n / wall, 1),
        "gate": "PASS" if p95 <= P95_SLO_MS and err < ERR_SLO_PCT else "FAIL",
        "ram_mb": mem_mb(),
    }


def summarize(runs):
    p95 = [r["p95_ms"] for r in runs]
    mean = statistics.mean(p95)
    return {
        "p95_median": round(statistics.median(p95), 1), "p95_min": min(p95), "p95_max": max(p95),
        "p95_cv_pct": round(100 * statistics.pstdev(p95) / mean, 1) if mean else 0,
        "error_max_pct": max(r["error_pct"] for r in runs),
        "ram_mb": next((r["ram_mb"] for r in reversed(runs) if r["ram_mb"] is not None), None),
        "gate_fail": sum(1 for r in runs if r["gate"] == "FAIL"), "runs": len(runs),
    }


def measure(a):
    base = a.base.rstrip("/")
    cookies = login(base)
    limit = cpu_limit()
    print(f"Умова: {a.label} | ліміт CPU контейнера: "
          f"{'невідомо (docker недоступний)' if limit is None else ('немає' if limit == 0 else limit)}"
          f" | {a.requests} запитів, {a.workers} паралельних, {a.runs} прогонів, {a.path}")
    one_run(base, a.path, 20, 5, cookies)   # прогрів, не враховується
    runs = []
    print(f"\n{'#':>2} {'p50':>8} {'p95':>8} {'p99':>8} {'max':>8} {'err%':>6} {'rps':>7} {'RAM МБ':>8}  Gate")
    for i in range(1, a.runs + 1):
        r = one_run(base, a.path, a.requests, a.workers, cookies)
        runs.append(r)
        print(f"{i:>2} {r['p50_ms']:>8} {r['p95_ms']:>8} {r['p99_ms']:>8} {r['max_ms']:>8} "
              f"{r['error_pct']:>6} {r['rps']:>7} {str(r['ram_mb']):>8}  {r['gate']}")
        time.sleep(1)
    s = summarize(runs)
    print(f"\nПідсумок: медіана p95 = {s['p95_median']} мс (від {s['p95_min']} до {s['p95_max']}), "
          f"CV = {s['p95_cv_pct']}%, Gate FAIL у {s['gate_fail']} з {s['runs']} прогонів")
    Path("results").mkdir(exist_ok=True)
    out = Path("results") / f"exp2_{a.label}.json"
    out.write_text(json.dumps({
        "meta": {"label": a.label, "cpu_limit": limit, "base": base, "path": a.path,
                 "requests": a.requests, "workers": a.workers, "python": platform.python_version(),
                 "time": datetime.now().isoformat(timespec="seconds")},
        "runs": runs, "summary": s}, ensure_ascii=False, indent=2))
    print(f"Збережено: {out}")


def summary(files):
    print(f"{'умова':<14}{'CPU-ліміт':>10}{'p95 медіана':>13}{'p95 min–max':>16}{'CV %':>7}"
          f"{'err% max':>10}{'RAM МБ':>9}{'Gate FAIL':>11}")
    for f in files:
        d = json.loads(Path(f).read_text())
        m, s = d["meta"], d["summary"]
        lim = "?" if m["cpu_limit"] is None else ("немає" if m["cpu_limit"] == 0 else m["cpu_limit"])
        rng = f"{s['p95_min']}–{s['p95_max']}"
        print(f"{m['label']:<14}{str(lim):>10}{s['p95_median']:>13}{rng:>16}{s['p95_cv_pct']:>7}"
              f"{s['error_max_pct']:>10}{str(s['ram_mb']):>9}{s['gate_fail']:>7} / {s['runs']}")
    print(f"\nПоріг Quality Gate: p95 <= {P95_SLO_MS:.0f} мс AND error rate < {ERR_SLO_PCT}%")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="run")
    ap.add_argument("--base", default=os.getenv("DEMO_BASE_URL", "http://localhost:5001"))
    ap.add_argument("--path", default="/farms")
    ap.add_argument("--requests", type=int, default=200)
    ap.add_argument("--workers", type=int, default=50)
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--summary", nargs="+", metavar="JSON")
    args = ap.parse_args()
    summary(args.summary) if args.summary else measure(args)
