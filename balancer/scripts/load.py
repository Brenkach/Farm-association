#!/usr/bin/env python3
"""Генератор HTTP-навантаження без зовнішніх залежностей.

Режим серії:    load.py URL -n 300 -c 10
    надсилає N запитів і друкує розподіл між екземплярами, коди відповідей,
    затримки та пропускну здатність.
Режим часу:     load.py URL --duration 40 -c 5
    надсилає запити протягом заданого часу й щосекунди друкує, які екземпляри
    відповідали і скільки було помилок (для перевірки відмови й відновлення).

Екземпляр визначається за заголовком X-Instance-Id відповіді.
"""

import argparse
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict

ERROR = "помилка"


def request(url, timeout):
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            resp.read()
            instance = resp.headers.get("X-Instance-Id", "?")
            status = resp.status
    except urllib.error.HTTPError as err:
        instance = err.headers.get("X-Instance-Id", "?") if err.headers else "?"
        status = err.code
    except (urllib.error.URLError, OSError):
        instance, status = ERROR, "з'єднання"
    return instance, status, (time.perf_counter() - started) * 1000


def bar(count, total, width=30):
    return "#" * round(width * count / total) if total else ""


def percentile(values, p):
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(p / 100 * len(ordered)) - 1))
    return ordered[index]


def collect(url, total, concurrency, timeout):
    """Надсилає total запитів у concurrency потоків; повертає результати і час."""
    results = []
    lock = threading.Lock()
    remaining = [total]

    def worker():
        while True:
            with lock:
                if remaining[0] == 0:
                    return
                remaining[0] -= 1
            result = request(url, timeout)
            with lock:
                results.append(result)

    started = time.perf_counter()
    threads = [threading.Thread(target=worker) for _ in range(concurrency)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results, time.perf_counter() - started


def is_error(instance, status):
    return instance == ERROR or (isinstance(status, int) and status >= 500)


def report(url, results, concurrency, elapsed):
    total = len(results)
    by_instance = Counter(r[0] for r in results)
    by_status = Counter(str(r[1]) for r in results)
    latencies = [r[2] for r in results if r[0] != ERROR]
    errors = sum(1 for r in results if is_error(r[0], r[1]))

    print(f"URL: {url}")
    print(f"Запитів: {total}, паралельно: {concurrency}, час: {elapsed:.2f} с, "
          f"пропускна здатність: {total / elapsed:.1f} запитів/с")
    print("Розподіл за екземплярами:")
    for instance, count in sorted(by_instance.items()):
        print(f"  {instance:<10} {count:>5}  {100 * count / total:5.1f}%  {bar(count, total)}")
    print("Коди відповідей: " + ", ".join(f"{s}: {c}" for s, c in sorted(by_status.items())))
    if latencies:
        print(f"Затримка, мс: p50 {statistics.median(latencies):.0f}, "
              f"p95 {percentile(latencies, 95):.0f}, max {max(latencies):.0f}")
    print(f"Помилок: {errors} ({100 * errors / total:.1f}%)")
    return errors


def run_series(url, total, concurrency, timeout):
    results, elapsed = collect(url, total, concurrency, timeout)
    return report(url, results, concurrency, elapsed)


def run_timeline(url, duration, concurrency, timeout):
    per_second = defaultdict(Counter)
    lock = threading.Lock()
    started = time.perf_counter()
    stop_at = started + duration

    def worker():
        while time.perf_counter() < stop_at:
            instance, status, _ = request(url, timeout)
            second = int(time.perf_counter() - started)
            with lock:
                per_second[second][ERROR if is_error(instance, status) else instance] += 1
            time.sleep(0.05)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(concurrency)]
    for thread in threads:
        thread.start()

    printed = 0
    instances = set()
    while printed < duration:
        time.sleep(max(0.0, started + printed + 1 - time.perf_counter()))
        with lock:
            counts = per_second.get(printed, Counter())
            instances.update(k for k in counts if k != ERROR)
        line = "  ".join(f"{name}:{counts.get(name, 0):>3}" for name in sorted(instances))
        print(f"t={printed:>3}s  {line}  {ERROR}:{counts.get(ERROR, 0):>3}", flush=True)
        printed += 1

    for thread in threads:
        thread.join(timeout=timeout + 1)
    total = sum(sum(c.values()) for c in per_second.values())
    errors = sum(c.get(ERROR, 0) for c in per_second.values())
    print(f"Усього запитів: {total}, помилок: {errors}")
    return errors


def main():
    parser = argparse.ArgumentParser(description="Генератор HTTP-навантаження")
    parser.add_argument("url")
    parser.add_argument("-n", "--requests", type=int, default=300, help="кількість запитів (режим серії)")
    parser.add_argument("-c", "--concurrency", type=int, default=10, help="кількість паралельних клієнтів")
    parser.add_argument("--duration", type=int, help="тривалість у секундах (режим часу)")
    parser.add_argument("--timeout", type=float, default=5.0, help="тайм-аут запиту, с")
    args = parser.parse_args()

    if args.duration:
        run_timeline(args.url, args.duration, args.concurrency, args.timeout)
    else:
        run_series(args.url, args.requests, args.concurrency, args.timeout)


if __name__ == "__main__":
    sys.exit(main())
