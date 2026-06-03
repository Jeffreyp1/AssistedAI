"""
Black-box probe for the running AssistedAI API.

Exercises the public HTTP surface from the outside only — no app imports:
happy paths, search/filter edge cases, injection-shaped input, not-found and
method handling, static/path-traversal safety, body robustness, and a small
concurrency burst.

Usage: python blackbox.py [base_url]   (default http://127.0.0.1:8077)
"""

from __future__ import annotations

import concurrent.futures as cf
import sys
import urllib.parse as up

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8077"
client = httpx.Client(base_url=BASE, timeout=30, follow_redirects=False)

results: list[tuple[bool, str, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    results.append((bool(ok), name, detail))


def get(path: str):
    r = client.get(path)
    return r.status_code, r


def n_results(path: str):
    r = client.get(path)
    return r.status_code, (len(r.json()) if r.status_code == 200 else None)


# A. happy path
sc, r = get("/")
record("GET / serves HTML", sc == 200 and "AssistedAI" in r.text, f"status={sc}")
sc, r = get("/api/summary")
record("GET /api/summary shape", sc == 200 and r.json().get("total") == 7
       and set(r.json()["counts"]) == {"attention", "watch", "improving", "stable"}, f"status={sc}")
sc, r = get("/api/patients")
record("GET /api/patients returns 7", sc == 200 and len(r.json()) == 7,
       f"status={sc} n={len(r.json()) if sc == 200 else '-'}")
sc, r = get("/api/patients/p-204")
record("GET /api/patients/p-204 full record",
       sc == 200 and r.json().get("name") == "Margaret Thompson" and "notes" in r.json(), f"status={sc}")
r = client.post("/api/patients/p-204/analyze")
record("POST analyze returns structured insight",
       r.status_code == 200 and {"conclusion", "confidence", "areas", "research", "simulated"} <= set(r.json()),
       f"status={r.status_code}")

# B. search / filter
for q, exp in [("margaret", 1), ("MARGARET", 1), ("204", 1), ("zzznope", 0)]:
    sc, n = n_results(f"/api/patients?q={q}")
    record(f"search q={q!r} -> {exp}", sc == 200 and n == exp, f"status={sc} n={n}")
for st, exp in [("attention", 3), ("improving", 1), ("stable", 2), ("watch", 1), ("all", 7), ("bogus", 0)]:
    sc, n = n_results(f"/api/patients?status={st}")
    record(f"filter status={st!r} -> {exp}", sc == 200 and n == exp, f"status={sc} n={n}")
for raw in ["'; DROP TABLE patients;--", "<script>alert(1)</script>", "../../etc/passwd"]:
    sc, n = n_results("/api/patients?q=" + up.quote(raw))
    record(f"injection-safe q={raw[:16]!r}", sc == 200 and n == 0, f"status={sc} n={n}")

# C. not found
for path, exp in [("/api/patients/nope", 404), ("/api/patients/P-204", 404), ("/api/unknown", 404)]:
    sc, _ = get(path)
    record(f"GET {path} -> {exp}", sc == exp, f"status={sc}")
record("POST analyze unknown -> 404", client.post("/api/patients/nope/analyze").status_code == 404)

# D. method handling
record("GET on analyze -> 405", get("/api/patients/p-204/analyze")[0] == 405)
record("POST on summary -> 405", client.post("/api/summary").status_code == 405)

# E. static / traversal safety
record("GET /static/styles.css -> 200", get("/static/styles.css")[0] == 200)
record("GET /static/nope.css -> 404", get("/static/nope.css")[0] == 404)
r = client.get("/static/..%2f..%2fbackend%2fmain.py")
record("encoded static traversal blocked", r.status_code in (400, 404) and "FastAPI" not in r.text, f"status={r.status_code}")
sc, r = get("/api/patients/..%2f..%2fmain")
record("encoded id traversal blocked", sc in (400, 404), f"status={sc}")

# F. robustness
r = client.post("/api/patients/p-204/analyze", content=b"{garbage", headers={"content-type": "application/json"})
record("analyze ignores junk body", r.status_code == 200, f"status={r.status_code}")

# G. concurrency burst (shared pool)
with cf.ThreadPoolExecutor(max_workers=10) as ex:
    codes = list(ex.map(lambda _: client.get("/api/summary").status_code, range(20)))
record("20 concurrent /api/summary all 200", all(c == 200 for c in codes), f"codes={sorted(set(codes))}")

# report
passed = sum(1 for ok, _, _ in results if ok)
failed = len(results) - passed
print("\nBLACK-BOX PROBE  —  " + BASE)
print("=" * 70)
for ok, name, detail in results:
    print(("PASS  " if ok else "FAIL  ") + name + (("   [" + detail + "]") if not ok and detail else ""))
print("=" * 70)
print(f"{passed}/{len(results)} passed, {failed} failed")
sys.exit(1 if failed else 0)
