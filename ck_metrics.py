#!/usr/bin/env python3
"""Лаб. 8: метрики Чидамбера-Кемерера (WMC, CBO, LCOM, RFC, DIT), Лоренца-Кіда (NMA, NMO, PIM)
та проєктні коефіцієнти MOOD (MHF, AHF, COF) для Python-проєкту.

Навіщо власний скрипт: SonarQube Community не має метрик CBO, LCOM, DIT та MOOD
(сервер відповідає 404 на ключі coupling_between_objects, class_complexity, lcom4).

Визначення (статичний аналіз AST, лише класи проєкту):
  WMC   сума цикломатичної складності методів класу (Radon);
  CBO   кількість ІНШИХ класів проєкту, на які клас посилається (створення, типи, атрибути, предки);
  LCOM  Henderson-Sellers: (середнє μ(a) - m) / (1 - m), 0 = ідеальна згуртованість, 1 = її повна відсутність;
        μ(a) = кількість методів, що використовують атрибут a, m = кількість методів;
  LCOM4 кількість компонентів зв'язності методів (спільні атрибути або виклики self.метод), 1 = ідеал;
  RFC   власні методи + різні методи/функції, які клас викликає;
  DIT   глибина успадкування: клас без явних предків = 1 (object); зовнішній предок дає 2;
  NMA   нові (не перевизначені) методи; NMO перевизначені методи предків проєкту;
  PIM   публічні методи інтерфейсу (власні + успадковані з класів проєкту);
  MHF   частка прихованих (_name) методів; AHF частка прихованих атрибутів; COF = зв'язки / (TC² - TC).

Запуск з кореня проєкту:
    python ck_metrics.py                       # таблиця класів + MOOD
    python ck_metrics.py --json out.json       # + збереження сирих даних
    python ck_metrics.py --files routes.py anonymization.py models.py
"""
import argparse
import ast
import fnmatch
import json
import subprocess
from pathlib import Path

from radon.complexity import cc_visit

DEFAULT_EXCLUDE = ["tests/*", "experiments/*", "ci/*", "git-hooks/*", ".venv*", "complexity-report/*",
                   "demo_lab4.py", "halstead_scan.py", "load_test.py", "audit_demo.py", "ck_metrics.py",
                   "apply_*.py", "chapin_candidates.py"]


# ----------------------------------------------------------------------------- допоміжні функції AST
def tracked_python_files(exclude):
    """Файли Git (відстежувані та нові, але не ігноровані) без виключень."""
    cmd = ["git", "ls-files", "--cached", "--others", "--exclude-standard", "*.py"]
    out = subprocess.run(cmd, capture_output=True, text=True).stdout.split()
    return sorted({f for f in out if Path(f).exists() and not any(fnmatch.fnmatch(f, p) for p in exclude)})


def is_dunder(name):
    return name.startswith("__") and name.endswith("__")


def methods_of(cls):
    return [i for i in cls.body if isinstance(i, (ast.FunctionDef, ast.AsyncFunctionDef))]


def base_names(cls):
    names = []
    for b in cls.bases:
        names.append(b.id if isinstance(b, ast.Name) else getattr(b, "attr", ""))
    return [n for n in names if n]


def name_of(node):
    """Ім'я, яке «вживає» вузол AST: змінна, атрибут або текст анотації."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.isidentifier():
        return node.value
    return None


def referenced_names(node):
    return {n for n in map(name_of, ast.walk(node)) if n}


def self_attribute(node):
    """Повертає ім'я x для виразу self.x, інакше None."""
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
        return node.attr
    return None


def class_level_attributes(cls):
    attrs = set()
    for item in cls.body:
        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            attrs.add(item.target.id)
        elif isinstance(item, ast.Assign):
            attrs.update(t.id for t in item.targets if isinstance(t, ast.Name))
    return attrs


def instance_attributes(cls):
    attrs = set()
    for m in methods_of(cls):
        for n in ast.walk(m):
            if isinstance(getattr(n, "ctx", None), ast.Store) and self_attribute(n):
                attrs.add(n.attr)
    return attrs


def all_attributes(cls):
    return class_level_attributes(cls) | instance_attributes(cls)


# ----------------------------------------------------------------------------- згуртованість (LCOM)
def method_usage(method, attrs, method_names):
    used, called = set(), set()
    for n in ast.walk(method):
        x = self_attribute(n)
        if x in method_names:
            called.add(x)
        elif x in attrs:
            used.add(x)
    return used, called


def lcom_henderson_sellers(usage, m_count):
    used_attrs = {a for used, _ in usage.values() for a in used}
    if m_count < 2 or not used_attrs:
        return 0.0
    mu = [sum(1 for used, _ in usage.values() if a in used) for a in used_attrs]
    value = (sum(mu) / len(mu) - m_count) / (1 - m_count)
    return round(max(0.0, min(1.0, value)), 3)


def connected(usage, a, b):
    return bool(usage[a][0] & usage[b][0]) or b in usage[a][1] or a in usage[b][1]


def lcom4_components(usage):
    parent = {n: n for n in usage}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    names = sorted(usage)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if connected(usage, a, b):
                parent[find(a)] = find(b)
    return len({find(n) for n in usage})


def cohesion(cls):
    attrs = all_attributes(cls)
    names = {m.name for m in methods_of(cls)}
    measured = [m for m in methods_of(cls) if m.name != "__init__"] or methods_of(cls)
    usage = {m.name: method_usage(m, attrs, names) for m in measured}
    return lcom_henderson_sellers(usage, len(measured)), lcom4_components(usage)


# ----------------------------------------------------------------------------- ієрархія
class Hierarchy:
    """Успадкування серед класів проєкту: DIT, успадковані публічні методи, перевизначення."""

    def __init__(self, classes):
        self.classes = classes
        self._dit = {}

    def parents(self, name):
        return [b for b in base_names(self.classes[name]["node"]) if b in self.classes and b != name]

    def dit(self, name):
        if name not in self._dit:
            self._dit[name] = 1
            value = 1
            for b in base_names(self.classes[name]["node"]):
                parent_dit = self.dit(b) if b in self.classes and b != name else 1
                value = max(value, parent_dit + 1)
            self._dit[name] = value
        return self._dit[name]

    def ancestors(self, name, seen=None):
        seen = seen if seen is not None else set()
        for p in self.parents(name):
            if p not in seen:
                seen.add(p)
                self.ancestors(p, seen)
        return seen

    def inherited_public(self, name):
        pub = set()
        for anc in self.ancestors(name):
            pub |= {m.name for m in methods_of(self.classes[anc]["node"]) if not m.name.startswith("_")}
        return pub

    def overridden(self, name):
        parent_methods = set()
        for anc in self.ancestors(name):
            parent_methods |= {m.name for m in methods_of(self.classes[anc]["node"])}
        own = {m.name for m in methods_of(self.classes[name]["node"])}
        return (own & parent_methods) - {"__init__"}


# ----------------------------------------------------------------------------- збір класів і рядків таблиці
def class_complexity_map(code):
    return {blk.name: sum(m.complexity for m in blk.methods) for blk in cc_visit(code) if hasattr(blk, "methods")}


def collect_classes(files):
    classes, parsed = {}, set()
    for f in files:
        code = Path(f).read_text(encoding="utf-8-sig")
        cc = class_complexity_map(code)
        parsed.add(f)
        for node in ast.walk(ast.parse(code)):
            if isinstance(node, ast.ClassDef):
                classes[node.name] = {"file": f, "node": node, "wmc": cc.get(node.name, 0)}
    return classes, parsed


def called_names(node):
    return {n.func.id if isinstance(n.func, ast.Name) else n.func.attr
            for n in ast.walk(node)
            if isinstance(n, ast.Call) and isinstance(n.func, (ast.Name, ast.Attribute))}


def class_row(name, info, hierarchy, project_names):
    node = info["node"]
    meths = {m.name for m in methods_of(node)}
    refs = (referenced_names(node) & project_names) - {name}
    lcom, lcom4 = cohesion(node)
    overridden = hierarchy.overridden(name)
    public = {m for m in meths if not m.startswith("_")}
    return {"class": name, "file": info["file"], "methods": len(meths), "attributes": len(all_attributes(node)),
            "WMC": info["wmc"], "CBO": len(refs), "LCOM": lcom, "LCOM4": lcom4,
            "RFC": len(meths | called_names(node)), "DIT": hierarchy.dit(name),
            "NMA": len(meths - overridden - {"__init__"}), "NMO": len(overridden),
            "PIM": len(public | hierarchy.inherited_public(name)),
            "_couplings": len(refs - set(base_names(node))), "_refs": sorted(refs)}


# ----------------------------------------------------------------------------- MOOD
def hidden_ratio(names):
    return sum(1 for n in names if n.startswith("_")), len(names)


def compute_mood(classes, rows):
    hm = tm = ha = ta = 0
    for info in classes.values():
        node = info["node"]
        h, t = hidden_ratio([m.name for m in methods_of(node) if not is_dunder(m.name)])
        hm, tm = hm + h, tm + t
        h, t = hidden_ratio(all_attributes(node))
        ha, ta = ha + h, ta + t
    tc = len(classes)
    couplings = sum(r["_couplings"] for r in rows)
    pct = lambda part, whole: round(100 * part / whole, 1) if whole else 0.0
    return {"classes": tc, "MHF_percent": pct(hm, tm), "AHF_percent": pct(ha, ta),
            "COF_percent": pct(couplings, tc * tc - tc), "couplings": couplings,
            "hidden_methods": hm, "total_methods": tm, "hidden_attributes": ha, "total_attributes": ta}


# ----------------------------------------------------------------------------- виведення
def print_table(rows):
    print(f"{'клас':<24}{'файл':<22}{'мет.':>5}{'WMC':>5}{'CBO':>5}{'LCOM':>7}{'LCOM4':>6}"
          f"{'RFC':>5}{'DIT':>5}{'NMA':>5}{'NMO':>5}{'PIM':>5}")
    for r in rows:
        print(f"{r['class'][:23]:<24}{r['file'][:21]:<22}{r['methods']:>5}{r['WMC']:>5}{r['CBO']:>5}"
              f"{r['LCOM']:>7}{r['LCOM4']:>6}{r['RFC']:>5}{r['DIT']:>5}{r['NMA']:>5}{r['NMO']:>5}{r['PIM']:>5}")


def print_file_notes(files, parsed, rows):
    for f in files or []:
        if f not in parsed:
            print(f"\n{f}: файл не входить до аналізу (виключено або не відстежується Git)")
        elif not any(r["file"] == f for r in rows):
            print(f"\n{f}: класів немає (функціональний модуль): метрики CK не визначені")


def print_mood(mood):
    tc = mood["classes"]
    print(f"\nMOOD (весь проєкт): MHF = {mood['MHF_percent']} %  ({mood['hidden_methods']}/{mood['total_methods']} методів приховано)"
          f"   AHF = {mood['AHF_percent']} %  ({mood['hidden_attributes']}/{mood['total_attributes']} атрибутів)"
          f"   COF = {mood['COF_percent']} %  ({mood['couplings']} зв'язків із {tc * tc - tc} можливих)")


def print_graph(rows, name):
    """Граф залежностей класу у форматі Mermaid (епіцентр хаосу: клас і всі класи, на які він посилається)."""
    row = next((r for r in rows if r["class"] == name), None)
    if row is None:
        print(f"\nКлас {name} не знайдено")
        return
    print(f"\n```mermaid\nflowchart LR\n    {name}[\"{name}<br/>CBO = {row['CBO']}\"]:::core")
    for dep in row["_refs"]:
        print(f"    {name} --> {dep}")
    print("    classDef core fill:#fde2e2,stroke:#c0392b\n```")


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", nargs="*", help="показати лише класи з цих файлів (MOOD рахується по всьому проєкту)")
    ap.add_argument("--exclude", nargs="*", default=DEFAULT_EXCLUDE)
    ap.add_argument("--json")
    ap.add_argument("--graph", metavar="CLASS", help="надрукувати граф залежностей класу (Mermaid)")
    return ap.parse_args()


def main():
    a = parse_args()
    files = tracked_python_files(a.exclude)
    classes, parsed = collect_classes(files)
    hierarchy, project_names = Hierarchy(classes), set(classes)
    rows = [class_row(n, i, hierarchy, project_names) for n, i in classes.items()]
    mood = compute_mood(classes, rows)

    shown = sorted((r for r in rows if not a.files or r["file"] in a.files), key=lambda r: (-r["CBO"], -r["WMC"]))
    print(f"Класів у проєкті: {len(classes)}; файлів проаналізовано: {len(files)}\n")
    print_table(shown)
    print_file_notes(a.files, parsed, rows)
    print_mood(mood)
    if a.graph:
        print_graph(rows, a.graph)
    if a.json:
        clean = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
        Path(a.json).write_text(json.dumps({"mood": mood, "classes": clean}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nЗбережено: {a.json}")


if __name__ == "__main__":
    main()
