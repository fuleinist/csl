#!/usr/bin/env python3
"""Tests for the evolve counters and the cap ranking.

    python tests/test_evolve.py

The cap evicts the rule with the lowest value density. A rule that catches violations but has
no pass yet held density 0, so the cap evicted it first. These tests pin the fix: a caught
violation adds value to the ranking and does not inflate the `ev` confidence counter.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
SRC = REPO / "src"
HOME = pathlib.Path(tempfile.mkdtemp(prefix="csl-evolvetest-"))
os.environ["CSL_HOME"] = str(HOME)
sys.path.insert(0, str(SRC))

from csl import evolve, paths  # noqa: E402

paths.refresh()
paths.ensure_home()

results: list[tuple[bool, str]] = []


def check(name, got, want, note=""):
    ok = got == want
    results.append((ok, name))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if note:
        print(f"        {note}")
    if not ok:
        print(f"        got {got!r}, want {want!r}")
    return ok


def rule(rid, ev=0, last="2026-10-30", when="w", do="d", chk="mech"):
    return {"id": rid, "when": when, "do": do, "chk": chk,
            "scope": "local", "ev": ev, "last": last}


ledger = HOME / "ledger-test.jsonl"
rows = [
    {"rule": "R-100", "status": "pass", "ts": "2026-10-30T00:00:00+11:00"},
    {"rule": "R-100", "status": "fail", "ts": "2026-10-30T01:00:00+11:00"},
    {"rule": "R-100", "status": "fail", "ts": "2026-10-30T02:00:00+11:00"},
    {"rule": "R-100", "status": "fail", "ts": "2026-10-30T03:00:00+11:00"},
    {"rule": "R-101", "status": "pass", "ts": "2026-10-30T00:00:00+11:00"},
    {"rule": "R-102", "status": "skip", "ts": "2026-10-30T00:00:00+11:00"},
]
ledger.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

rules = [rule("R-100"), rule("R-101"), rule("R-102")]
evolve.derive_counters(rules, ledger_path=ledger)
by = {r["id"]: r for r in rules}

print("== counters ==")
check("1. a pass raises ev", by["R-100"]["ev"], 1)
check("2. a fail raises caught, not ev",
      (by["R-100"]["caught"], by["R-100"]["ev"]), (3, 1))
check("3. a skip is not evidence",
      (by["R-102"]["ev"], by["R-102"]["caught"]), (0, 0))
check("4. last keys off the latest exercise", by["R-100"]["last"], "2026-10-30")

print()
print("== cap ranking ==")
d100 = evolve.value_density(by["R-100"])
d101 = evolve.value_density(by["R-101"])
d102 = evolve.value_density(by["R-102"])
check("5. caught violations rank above pass-only", d100 > d101, True,
      f"{d100:.3e} > {d101:.3e}")
check("6. a rule with no evidence ranks lowest", d102 < d101 and d102 < d100, True,
      f"no-evidence {d102:.3e} < pass-only {d101:.3e} < caught {d100:.3e}")

bad = [n for ok, n in results if not ok]
print()
print(f"{len(results) - len(bad)}/{len(results)} evolve tests pass")
for n in bad:
    print(f"  FAILED: {n}")
sys.exit(0 if not bad else 1)