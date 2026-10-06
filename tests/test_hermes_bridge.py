#!/usr/bin/env python3
"""Tests for the Hermes bridge — the pair of entries that make the layer a comment layer.

    pip install -e .          # the bridge calls `csl`, as the hook does
    python tests/test_hermes_bridge.py

Hermes honours only `block`, `modify` and `approve` on `pre_tool_call`, so an audit verdict cannot
ride that event: `agent/shell_hooks.py:_parse_pre_tool_call` parses it and discards it. The bridge
runs the layer, keeps the block directive and the exit code, and queues the audit note for
`pre_llm_call` to deliver as `{"context": ...}`.

Two properties must survive every change here:

* **gate mode still blocks.** The bridge sits between the layer and the harness, so a lost exit code
  silently disarms the gate.
* **a missing layer fails open.** A bridge that wedges a turn is worse than a missing guard.

Each case traces to a real defect found while wiring the adapter, not to a hypothetical.
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
BRIDGE = REPO / "adapters" / "hermes" / "csl-bridge.py"
HOME = pathlib.Path(tempfile.mkdtemp(prefix="csl-bridgetest-"))
EMPTY_BIN = pathlib.Path(tempfile.mkdtemp(prefix="csl-nobin-"))

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
    """Run one bridge entry the way Hermes does: JSON on stdin, JSON or silence on stdout."""
    env = {**os.environ, "CSL_HOME": str(HOME), "CSL_BIN": CSL, "CSL_HOOK_MODE": mode}
    if env_extra:
        env.update(env_extra)
    if path is not None:
        env["PATH"] = path
    if not isinstance(payload, str):
        payload = json.dumps(payload)
    return subprocess.run([sys.executable, str(BRIDGE), entry],
                          input=payload, capture_output=True, text=True, env=env)


def event(tool: str, tool_input: dict, session: str):
    return {"hook_event_name": "pre_tool_call", "tool_name": tool,
            "tool_input": tool_input, "session_id": session}


def pending_files():
    d = HOME / "pending"
    return sorted(p.name for p in d.glob("*.jsonl")) if d.is_dir() else []


HIGH = {"command": "git push --force origin main"}
BENIGN_TOOL_INPUT = {"path": "C:/tmp/notes.txt"}


print("== 1. audit mode queues a note instead of blocking ==")
s1 = "bridge-audit"
r = fire("pretool", event("terminal", HIGH, s1))
check("H1  audit mode exits 0", r.returncode, 0)
verdict = json.loads(r.stdout or "{}")
check("H2  the payload carries the layer's verdict",
      (verdict.get("csl") or {}).get("decision"), "advise",
      "an advise payload is nested under 'csl'; the top-level decision reads 'allow'")
check("H3  the note is queued for this session",
      any(s1 in name for name in pending_files()), True, f"pending: {pending_files()}")

print()
print("== 2. pre_llm_call delivers the note to the model ==")
note_event = {"hook_event_name": "pre_llm_call", "session_id": s1}
r = fire("prellm", note_event)
check("H4  prellm exits 0", r.returncode, 0)
context = json.loads(r.stdout or "{}").get("context", "")
check("H5  the context names the unvalidated rule", "R-001" in context, True,
      context[:110] + ("..." if len(context) > 110 else ""))
check("H6  the context is a useful note, not an empty string",
      context.startswith("Common-sense layer notes:"), True)
r = fire("prellm", note_event)
check("H7  the queue is drained, so the note is not repeated", r.stdout, "")

print()
print("== 3. gate mode still blocks ==")
s3 = "bridge-gate"
r = fire("pretool", event("terminal", HIGH, s3), mode="gate")
check("H8  a high-stakes call is blocked with exit 2", r.returncode, 2)
blocked = json.loads(r.stdout or "{}")
check("H9  the block names the missing rules", "R-001" in blocked.get("reason", ""), True)
check("H10 the block carries both dialects",
      (blocked.get("decision"), blocked.get("action")), ("block", "block"))
check("H11 gate mode queues no comment",
      any(s3 in name for name in pending_files()), False)

print()
print("== 4. gate mode leaves an ordinary call alone ==")
r = fire("pretool", event("read_file", BENIGN_TOOL_INPUT, "bridge-clear"), mode="gate")
check("H12 a call with no high-stakes class is not blocked", r.returncode, 0)

print()
print("== 5. a call the layer does not care about stays quiet ==")
r = fire("pretool", event("read_file", BENIGN_TOOL_INPUT, "bridge-quiet"))
check("H13 a benign call exits 0", r.returncode, 0)
check("H14 a benign call queues nothing", r.stdout.strip(), "")

print()
print("== 6. a missing layer fails open ==")
# Every resolution path must miss: CSL_BIN, PATH, and the ~/.local/bin fallback inside the bridge.
# Path.home() reads HOME on POSIX and USERPROFILE on Windows, so both point at the empty directory.
r = fire("pretool", event("terminal", HIGH, "bridge-nolayer"),
         env_extra={"CSL_BIN": str(EMPTY_BIN / "absent-csl"),
                    "HOME": str(EMPTY_BIN), "USERPROFILE": str(EMPTY_BIN)},
         path=str(EMPTY_BIN))
check("H15 a bridge that cannot reach the layer exits 0", r.returncode, 0,
      "a wedged turn is worse than a missing guard")
check("H16 and says nothing on stdout", r.stdout, "")

print()
print("== 7. the bridge does not lose the layer's own exit code ==")
r = fire("pretool", event("terminal", {"command": "rm -rf /"}, "bridge-destructive"), mode="gate")
check("H17 a destructive operation is blocked too", r.returncode, 2,
      "the destructive class, not only the external-send class")

print()
passed = sum(1 for ok, _ in results if ok)
total = len(results)
print(f"{passed}/{total} bridge tests pass")
sys.exit(0 if passed == total else 1)