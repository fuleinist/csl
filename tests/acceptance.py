#!/usr/bin/env python3
"""End-to-end acceptance test: the full lifecycle, in a throwaway layer.

    python tests/acceptance.py

`tests/probe.py` checks each mechanism in isolation. This checks the *sequence*: a candidate that
passes all three gates gets promoted into the live layer, and the newly-live rule then behaves
correctly under validate + gate + record + stats.

Everything runs under a temporary ``CSL_HOME``. The shipped seed is hashed before and after and
the run fails if it moved — the package must never write into its own data directory.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
SRC = REPO / "src"
SEED = SRC / "csl" / "data" / "seed.md"

HOME = pathlib.Path(tempfile.mkdtemp(prefix="csl-acceptance-"))
os.environ["CSL_HOME"] = str(HOME)
os.environ["PYTHONPATH"] = str(SRC)
sys.path.insert(0, str(SRC))

from csl import paths  # noqa: E402

paths.refresh()

CANDIDATE = {
    "id": "C-ACC",
    "ts": "2026-09-30T02:00:00+10:00",
    "session": "acceptance",
    "when": "about to publish a release manifest",
    "do": "record the manifest hash before publishing it",
    "chk": "mech",
    "evidence": "acceptance fixture",
    "would_change": "yes - prevents publishing an unverifiable release",
    "source": "acceptance",
}
SESSION = "S-ACCEPT"

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


def run(*args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "csl", *args],
                          capture_output=True, text=True, cwd=str(REPO))


def main() -> int:
    seed_hash_before = hashlib.sha256(SEED.read_bytes()).hexdigest()

    v = run("init")
    check("1. csl init creates and seeds a fresh layer", (v.returncode, paths.LIVE.exists()), (0, True))

    v = run("validate")
    check("2. the seeded layer validates", (v.returncode, "rules: 8" in v.stdout), (0, True),
          v.stdout.strip().splitlines()[1] if len(v.stdout.splitlines()) > 1 else "")

    paths.CANDIDATES.write_text(json.dumps(CANDIDATE) + "\n", encoding="utf-8")
    e = run("evolve", "--apply")
    check("3. a legitimate candidate passes the gates and is promoted", e.returncode, 0,
          " | ".join(l.strip() for l in e.stdout.splitlines() if "promote" in l.lower())[:130])
    check("4. post-write validation passed", "post-write validate: OK" in e.stdout, True)

    live = paths.LIVE.read_text(encoding="utf-8")
    ids = [l.split(" ")[1] for l in live.splitlines() if l.startswith("- ")]
    check("5. the live layer grew by exactly one rule", len(ids), 9, f"ids: {ids}")
    new_id = [i for i in ids if i not in (f"R-{n:03d}" for n in range(1, 9))]
    check("6. the promoted rule got a fresh id", len(new_id), 1)
    if not new_id:
        return finish(seed_hash_before)
    new_id = new_id[0]
    line = next(l for l in live.splitlines() if l.startswith(f"- {new_id} "))
    check("7. promotion defaulted scope to local (fail-closed)", "| scope: local " in line, True,
          line[:100])

    v = run("validate")
    check("8. the promoted live file still validates", (v.returncode, "rules: 9" in v.stdout), (0, True))

    # The gate domain is the new rule's own `when`; "publish" also hits a high-stakes class, which
    # is what makes the gate apply at all.
    _, rules, _ = __import__("csl.grammar", fromlist=["parse"]).parse(paths.LIVE)
    dom = next(r["when"] for r in rules if r["id"] == new_id)

    g = run("gate", "--session", SESSION, "--domain", dom)
    check("9. the gate BLOCKS the high-stakes action before any pass is recorded", g.returncode, 2,
          g.stdout.strip().splitlines()[0][:80] if g.stdout.strip() else "")
    check("10. ...and names the newly-live rule as what is missing", new_id in g.stdout, True)

    r = run("record", "--session", SESSION, "--domain", dom,
            "--results", f"{new_id}=pass:hashed and recorded the manifest")
    check("11. recording a pass for the new rule is accepted", r.returncode, 0, r.stdout.strip()[:90])

    g2 = run("gate", "--session", SESSION, "--domain", dom)
    check("12. the gate now clears", g2.returncode, 0, g2.stdout.strip()[:90])

    s = run("stats")
    check("13. stats sees 9 live rules", "live rules: 9" in s.stdout, True)

    h = run("hook", "--event", "-")  # no event on stdin: must not explode
    check("14. a hook with no event fails open (exit 0, no output)", h.returncode, 0)

    return finish(seed_hash_before)


def finish(seed_hash_before: str) -> int:
    paths.LIVE.unlink(missing_ok=True)
    shutil.rmtree(HOME, ignore_errors=True)
    after = hashlib.sha256(SEED.read_bytes()).hexdigest()
    check("15. the shipped seed was never written to (package data is read-only in practice)",
          after, seed_hash_before, "sha256 identical before/after")
    bad = [n for ok, n in results if not ok]
    print()
    print(f"{len(results) - len(bad)}/{len(results)} acceptance steps pass")
    for n in bad:
        print(f"  FAILED: {n}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())