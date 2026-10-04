import sys
import time
import requests
from concurrent.futures import ThreadPoolExecutor

BASE_URL = "http://127.0.0.1:5000"
LOGIN = "admin"
PASSWORD = "admin123"

SLO_P95_MS = 200
SLO_ERROR_RATE = 1.0


def get_session():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/login", data={"login": LOGIN, "password": PASSWORD}, timeout=5)
    print(f"[DEBUG] Login status: {r.status_code}, url after: {r.url}")
    return s


def send_request(session):
    start = time.time()
    try:
        res = session.get(f"{BASE_URL}/offers", timeout=5)
        return res.status_code == 200, (time.time() - start) * 1000
    except Exception:
        return False, (time.time() - start) * 1000


def percentile(sorted_values, p):
    if not sorted_values:
        return 0.0
    idx = min(int(len(sorted_values) * p), len(sorted_values) - 1)
    return sorted_values[idx]


def run_test(session, name, num_requests, concurrency):
    print(f"\n--- {name}: {num_requests} запитів ({concurrency} паралельних) ---")

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        results = list(executor.map(lambda _: send_request(session), range(num_requests)))
    total_time = time.time() - t0

    failures = [r for r in results if not r[0]]
    latencies = sorted(r[1] for r in results)

    p90 = percentile(latencies, 0.90)
    p95 = percentile(latencies, 0.95)
    p99 = percentile(latencies, 0.99)
    rps = num_requests / total_time
    error_rate = len(failures) / num_requests * 100

    print(f"Успішних запитів: {num_requests - len(failures)}/{num_requests}")
    print(f"p90: {p90:.2f} ms | p95: {p95:.2f} ms (SLO <= {SLO_P95_MS}) | p99: {p99:.2f} ms")
    print(f"Throughput: {rps:.1f} req/s")
    print(f"Error Rate: {error_rate:.2f}% (SLO < {SLO_ERROR_RATE}%)")

    ok = p95 <= SLO_P95_MS and error_rate < SLO_ERROR_RATE
    print("Підсумок: PASS" if ok else "Підсумок: FAIL")
    return ok


if __name__ == "__main__":
    session = get_session()
    run_test(session, "Нормальне навантаження", 50, 10)
    run_test(session, "Підвищене навантаження", 200, 100)
    ok = run_test(session, "Стрес-навантаження", 500, 300)
    sys.exit(0 if ok else 1)