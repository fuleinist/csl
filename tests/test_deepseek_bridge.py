#!/usr/bin/env python3
"""Tests for the DeepSeek Harness bridge — the two entries that make the layer visible on dsh.

    pip install -e .          # the bridge calls `csl`, as the hook does
    python tests/test_deepseek_bridge.py

dsh runs a Claude Code shape command hook, and two of its behaviours differ from a Claude Code
install:

* `PreToolUse` ignores `additionalContext`, so an audit verdict cannot ride that event. The bridge
  queues the note there and delivers it on the next `UserPromptSubmit`.
* dsh reads the exit-2 reason from **stderr**, and reads structured stdout only on exit 0.
  `csl hook` writes its block payload to **stdout**, so the bridge copies the reason to stderr. A
  bare command entry would otherwise block an action with no reason the model can read.

Two properties must survive every change here:

* **gate mode still blocks, with a reason.** The bridge sits between the layer and the harness, so a
  lost exit code disarms the gate and a lost reason blinds it.
* **a missing layer fails open.** A bridge that wedges a turn is worse than a missing guard.

Each case traces to the contract in `adapters/deepseek/PLAN.md`.
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
BRIDGE = REPO / "adapters" / "deepseek" / "csl-bridge.py"
HOME = pathlib.Path(tempfile.mkdtemp(prefix="csl-dsh-test-"))
EMPTY_BIN = pathlib.Path(tempfile.mkdtemp(prefix="csl-dsh-nobin-"))

CSL = shutil.which("csl")
if not CSL:
    print("FAIL: the `csl` console script is not on PATH. Run `pip install -e .` first —")
    print("      the bridge calls `csl`, so this is a real precondition, not a test artifact.")
    raise SystemExit(1)

# Seed the throwaway layer with the shipped rules, through the layer's own CLI.
seed_env = {**os.environ, "CSL_HOME": str(HOME)}
subprocess.run([CSL, "init"], capture_output=True, text=True, env=seed_env, check=False)

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


def fire(entry: str, payload, mode: str = "audit", env_extra=None, path=None):
    """Run one bridge entry the way dsh does: JSON on stdin, JSON or silence on stdout."""
    env = {**os.environ, "CSL_HOME": str(HOME), "CSL_BIN": CSL, "CSL_HOOK_MODE": mode}
    if env_extra:
        env.update(env_extra)
    if path is not None:
        env["PATH"] = path
    if not isinstance(payload, str):
        payload = json.dumps(payload)
    return subprocess.run([sys.executable, str(BRIDGE), entry],
                          input=payload, capture_output=True, text=True, env=env)


def event(tool: str, tool_input: dict, session: str, name: str = "PreToolUse"):
    return {"hook_event_name": name, "tool_name": tool,
            "tool_input": tool_input, "session_id": session}


def pending_files():
    d = HOME / "pending"
    return sorted(p.name for p in d.glob("*.jsonl")) if d.is_dir() else []


HIGH = {"command": "git push --force origin main"}
BENIGN = {"path": "C:/tmp/notes.txt"}

print("== 1. audit mode queues a note instead of blocking ==")
s1 = "dsh-audit"
r = fire("pretool", event("pwsh", HIGH, s1))
check("D1  audit mode exits 0", r.returncode, 0)
verdict = json.loads(r.stdout or "{}")
check("D2  the payload carries the layer's verdict",
      (verdict.get("csl") or {}).get("decision"), "advise",
      "an advise payload is nested under 'csl'; the top-level decision reads 'allow'")
check("D3  the note is queued for this session",
      any(s1 in name for name in pending_files()), True, f"pending: {pending_files()}")

print()
print("== 2. the next prompt delivers the note to the model ==")
prompt_event = {"hook_event_name": "UserPromptSubmit", "session_id": s1}
r = fire("preprompt", prompt_event)
check("D4  preprompt exits 0", r.returncode, 0)
payload = json.loads(r.stdout or "{}")
specific = payload.get("hookSpecificOutput") or {}
context = specific.get("additionalContext", "")
check("D5  the context names the unvalidated rule", "R-001" in context, True,
      context[:110] + ("..." if len(context) > 110 else ""))
check("D6  the context names the rule tier too", "[chk:human]" in context, True)
check("D7  the emitted event name matches the firing event",
      specific.get("hookEventName"), "UserPromptSubmit")
check("D8  the context announces itself", context.startswith("Common-sense layer notes:"), True)
r = fire("preprompt", prompt_event)
check("D9  the queue is drained, so the note is not repeated", r.stdout, "")

print()
print("== 3. gate mode denies through the structured path, because exit 2 is not honoured ==")
s3 = "dsh-gate"
r = fire("pretool", event("pwsh", HIGH, s3), mode="gate")
payload = json.loads(r.stdout or "{}")
specific = payload.get("hookSpecificOutput") or {}
check("D10 a high-stakes call is refused", specific.get("permissionDecision"), "deny",
      "measured on dsh 0.2.0-rc.2/Windows: a hook that exits 2 is reported as exit 1 and the "
      "tool RUNS ANYWAY, so the exit-code contract cannot carry the block here")
check("D11 the refusal exits 0, because the structured path needs exit 0", r.returncode, 0)
reason = specific.get("permissionDecisionReason", "")
check("D12 the reason names the missing rule", "R-001" in reason, True, reason[:110])
check("D13 the payload names the firing event", specific.get("hookEventName"), "PreToolUse",
      "dsh discards event-scoped fields when the name does not match")
check("D14 the reason is also on stderr, for a harness that honours exit 2",
      "R-001" in r.stderr, True)
check("D15 gate mode queues no comment",
      any(s3 in name for name in pending_files()), False)

print()
print("== 4. gate mode leaves an ordinary call alone ==")
r = fire("pretool", event("read", BENIGN, "dsh-clear"), mode="gate")
check("D16 a call with no high-stakes class is not blocked", r.returncode, 0)

print()
print("== 5. a call the layer does not care about stays quiet ==")
r = fire("pretool", event("read", BENIGN, "dsh-quiet"))
check("D17 a benign call exits 0", r.returncode, 0)
check("D18 a benign call queues nothing", r.stdout.strip(), "")

print()
print("== 6. a missing layer fails open ==")
r = fire("pretool", event("pwsh", HIGH, "dsh-nolayer"),
         env_extra={"CSL_BIN": str(EMPTY_BIN / "absent-csl"),
                    "HOME": str(EMPTY_BIN), "USERPROFILE": str(EMPTY_BIN)},
         path=str(EMPTY_BIN))
check("D19 a bridge that cannot reach the layer exits 0", r.returncode, 0,
      "a wedged turn is worse than a missing guard")
check("D20 and says nothing on stdout", r.stdout, "")

print()
print("== 7. a session id cannot escape the pending directory ==")
r = fire("pretool", event("pwsh", HIGH, "../../dsh-escape"))
check("D21 a traversal session id still queues inside the layer home",
      all("/" not in name and "\\" not in name and ".." not in name for name in pending_files()),
      True, f"pending: {pending_files()}")
check("D22 no file landed outside the layer home",
      (HOME.parent / "dsh-escape.jsonl").exists(), False)

print()
print("== 8. the bridge keeps the destructive class, not only the external-send class ==")
r = fire("pretool", event("pwsh", {"command": "rm -rf /"}, "dsh-destructive"), mode="gate")
denied = (json.loads(r.stdout or "{}").get("hookSpecificOutput") or {}).get("permissionDecision")
check("D23 a destructive operation is refused too", denied, "deny",
      "not only the external-send class")

print()
print("== 9. the layer is reachable without a console script on PATH ==")
r = fire("pretool", event("read", BENIGN, "dsh-nopath"),
         env_extra={"CSL_BIN": str(EMPTY_BIN / "absent-csl")}, path=str(EMPTY_BIN))
check("D24 an unreachable console script still ends in a decision, not a crash",
      r.returncode, 0, "the bridge falls back to its own interpreter with `-m csl`")

print()
passed = sum(1 for ok, _ in results if ok)
total = len(results)
print(f"{passed}/{total} deepseek bridge tests pass")
sys.exit(0 if passed == total else 1)