#!/usr/bin/env python3
"""Лаб. 10, завд. 1: метрики актуальності документації через Git CLI.

Для кожного документа рахує: дату останнього коміту, вік у днях (Last Updated Age),
кількість комітів .py-коду ПІСЛЯ останнього оновлення документа (дрейф) і вердикт.
Запуск з кореня репозиторію:  python3 doc_audit.py [--today YYYY-MM-DD]
"""
import argparse
import re
import subprocess
from datetime import date

DOC_PATTERN = re.compile(r"(\.md|\.ya?ml|Dockerfile[^/]*|requirements.*\.(txt|in)|\.properties|\.env\.example)$")
SUSPICIOUS_DAYS, STALE_DAYS, DRIFT_LIMIT = 90, 180, 20


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()


def tracked_docs():
    return sorted(f for f in git("ls-files").splitlines() if DOC_PATTERN.search(f))


def last_commit(path):
    sha, day = git("log", "-1", "--format=%h %cs", "--", path).split()
    return sha, date.fromisoformat(day)


def code_commits_since(sha):
    return int(git("rev-list", "--count", f"{sha}..HEAD", "--", "*.py"))


def verdict(age, drift):
    if age > STALE_DAYS or drift > DRIFT_LIMIT:
        return "ЗАСТАРІЛИЙ"
    if age > SUSPICIOUS_DAYS:
        return "ПІДОЗРІЛИЙ"
    return "актуальний"


def row(path, today):
    sha, day = last_commit(path)
    age = (today - day).days
    drift = code_commits_since(sha)
    return path, day.isoformat(), age, drift, verdict(age, drift)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", default=date.today().isoformat())
    today = date.fromisoformat(ap.parse_args().today)
    print(f"{'Документ':42} {'Останній коміт':14} {'Вік,дн':>6} {'Коміти .py після':>17}  Вердикт")
    for path in tracked_docs():
        print("%-42s %-14s %6d %17d  %s" % row(path, today))


if __name__ == "__main__":
    main()
