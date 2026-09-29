#!/usr/bin/env python3
"""Tests for the hook — the piece every harness actually runs.

    python tests/test_hook.py

The hook is the one component whose failure the agent *feels*, so its two safety properties get
their own assertions:

* **fail open** — a broken hook must never wedge a turn (exit 0), unless fail-closed is asked for;
* **audit by default** — the default mode annotates and never blocks, because a beta that blocks
  on a heuristic gets uninstalled.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
SRC = REPO / "src"
HOME = pathlib.Path(tempfile.mkdtemp(prefix="csl-hooktest-"))
os.environ["CSL_HOME"] = str(HOME)
os.environ["PYTHONPATH"] = str(SRC)
sys.path.insert(0, str(SRC))

from csl import hook, paths  # noqa: E402

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


def cli(event, *args, mode="audit"):
    env = {**os.environ, "CSL_HOOK_MODE": mode}
    inp = event if isinstance(event, str) else json.dumps(event)
    return subprocess.run([sys.executable, "-m", "csl", "hook", *args],
                          input=inp, capture_output=True, text=True, cwd=str(REPO), env=env)


FORCE_PUSH = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
              "tool_input": {"command": "git push --force origin main"}, "session_id": "s-hook"}
INNOCENT = {"hook_event_name": "PreToolUse", "tool_name": "Read",
            "tool_input": {"file_path": "src/app.py"}, "session_id": "s-hook"}

print("== classification ==")
check("1. a force-push is destructive AND external", (
    "destructive or irreversible operation" in hook.infer_high_stakes("Bash", "git push --force origin main"),
    "external send, publish or post" in hook.infer_high_stakes("Bash", "git push --force origin main")),
    (True, True))
check("2. `rm -rf` is destructive", hook.infer_high_stakes("Bash", "rm -rf build/"),
      ["destructive or irreversible operation"])
check("3. editing a scheduler is a config edit", "config or scheduler edit" in
      hook.infer_high_stakes("Bash", "crontab -e"), True)
check("4. an ordinary read is not high-stakes", hook.infer_high_stakes("Read", "src/app.py"), [])

print()
print("== the domain bridge ==")
ev = hook.normalise(FORCE_PUSH)
check("5. the derived domain carries the high-stakes class labels",
      "destructive or irreversible operation" in ev["derived_domain"], True,
      ev["derived_domain"][:100])
check("6. an agent-supplied domain is used verbatim (semantic wins)",
      hook.normalise({**FORCE_PUSH, "domain": "deploying the nightly job"})["derived_domain"],
      "deploying the nightly job")

print()
print("== decisions ==")
v = hook.decide(hook.normalise(FORCE_PUSH), mode="audit")
check("7. audit mode ADVISES, never blocks", (v["decision"], bool(v["missing"])), ("advise", True),
      v["reason"][:90])
v = hook.decide(hook.normalise(FORCE_PUSH), mode="gate")
check("8. gate mode BLOCKS an unvalidated high-stakes action", v["decision"], "block", v["reason"][:90])
v = hook.decide(hook.normalise(INNOCENT), mode="gate")
check("9. gate mode allows a benign action", v["decision"], "allow", v["reason"][:70])
v = hook.decide(hook.normalise({**FORCE_PUSH, "session_id": "s-clean"}), mode="audit")
check("10. an unrelated session's verdicts do not leak in", bool(v["missing"]), True)

print()
print("== exit codes and dialects (what the harness reads) ==")
r = cli(FORCE_PUSH, mode="gate")
check("11. gate mode exits 2 so every harness honours the block", r.returncode, 2)
body = json.loads(r.stdout) if r.stdout.strip() else {}
check("12. both block dialects are emitted (Hermes `action`, Claude/Codex `decision`)",
      (body.get("decision"), body.get("action")), ("block", "block"))
check("13. the reason is present under both key names",
      (bool(body.get("reason")), bool(body.get("message"))), (True, True))
check("14. the block payload names the missing rules",
      [m["id"] for m in body.get("csl", {}).get("missing", [])], ["R-001", "R-002"],
      "a block that does not say what to validate is not actionable")

r = cli(FORCE_PUSH, mode="audit")
check("15. audit mode exits 0 and stays out of the way", r.returncode, 0)
check("16. ...but still emits a machine-readable note",
      json.loads(r.stdout).get("csl", {}).get("decision"), "advise")

print()
print("== fail open ==")
r = cli("{not json at all", mode="gate")
check("17. an unreadable event FAILS OPEN by default", r.returncode, 0,
      "a hook that wedges a turn is worse than a missing guard")
env = {**os.environ, "CSL_HOOK_MODE": "gate", "CSL_HOOK_FAIL_CLOSED": "1"}
r = subprocess.run([sys.executable, "-m", "csl", "hook"], input="{not json",
                   capture_output=True, text=True, cwd=str(REPO), env=env)
check("18. ...unless fail-closed is asked for explicitly", r.returncode, 2)

print()
print("== the recorded path clears it ==")
r = cli(FORCE_PUSH, "--explain", mode="gate")
ev = hook.normalise(FORCE_PUSH)
r1 = subprocess.run([sys.executable, "-m", "csl", "attest", "--session", "s-hook",
                     "--domain", ev["derived_domain"],
                     "--results", "R-001=pass:Chris approved the force-push"],
                    capture_output=True, text=True, cwd=str(REPO), env=os.environ)
r2 = subprocess.run([sys.executable, "-m", "csl", "attest", "--session", "s-hook",
                     "--domain", ev["derived_domain"],
                     "--results", "R-002=pass:Chris confirmed the target"],
                    capture_output=True, text=True, cwd=str(REPO), env=os.environ)
g = cli(FORCE_PUSH, mode="gate")
check("19. after the human attests both rules, the gate clears",
      (r1.returncode, r2.returncode, g.returncode), (0, 0, 0),
      f"attest {r1.returncode},{r2.returncode} -> gate {g.returncode}")

shutil.rmtree(HOME, ignore_errors=True)
bad = [n for ok, n in results if not ok]
print()
print(f"{len(results) - len(bad)}/{len(results)} hook tests pass")
for n in bad:
    print(f"  FAILED: {n}")
sys.exit(0 if not bad else 1)