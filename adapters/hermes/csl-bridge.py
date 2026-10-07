#!/usr/bin/env python3
"""Bridge the common-sense layer (csl) into Hermes as an actual comment layer.

Why this exists: Hermes honours three directives on `pre_tool_call` — block, modify, approve.
There is no advisory channel, so a `csl` audit verdict is computed and then discarded by
`agent/shell_hooks.py:_parse_pre_tool_call`. Hermes DOES consume `{"context": ...}` on
`pre_llm_call`. This script runs under both events and moves the note between them.

  csl-bridge.py pretool    runs `csl hook --harness hermes`, queues any audit note, and passes
                           the layer's own output and exit code straight through (so gate mode
                           still blocks). Always exits 0 when the layer is absent: fail open.
  csl-bridge.py prellm     drains the queued notes for this session and returns them as context.

Configure with two hook entries:

  hooks:
    pre_tool_call:
      - matcher: "..."
        command: python /path/to/csl-bridge.py pretool
        timeout: 5
    pre_llm_call:
      - command: python /path/to/csl-bridge.py prellm
        timeout: 5
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

MODE = os.environ.get("CSL_HOOK_MODE", "audit").strip().lower() or "audit"


def csl_home() -> Path:
    raw = os.environ.get("CSL_HOME")
    return Path(raw).expanduser() if raw else Path.home() / ".csl"


def csl_bin() -> str | None:
    explicit = os.environ.get("CSL_BIN")
    if explicit and Path(explicit).exists():
        return explicit
    found = shutil.which("csl")
    if found:
        return found
    local = Path.home() / ".local" / "bin" / ("csl.exe" if os.name == "nt" else "csl")
    return str(local) if local.exists() else None


def safe_session(value: object) -> str:
    raw = str(value or "hermes-unknown")
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in raw)[:120]


def pending_file(session: str) -> Path:
    return csl_home() / "pending" / f"hermes-{safe_session(session)}.jsonl"


def queue_note(session: str, text: str) -> None:
    try:
        path = pending_file(session)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"text": text}) + "\n")
    except OSError:
        pass  # ledger-only is an acceptable degradation


def drain_notes(session: str) -> list[str]:
    path = pending_file(session)
    if not path.exists():
        return []
    try:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        path.unlink()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            text = json.loads(line).get("text")
        except ValueError:
            continue
        if isinstance(text, str) and text.strip():
            out.append(text)
    return out


def describe(event: dict, verdict: dict) -> str:
    """One comment line, naming what the layer wants checked."""
    inner = verdict.get("csl") if isinstance(verdict.get("csl"), dict) else {}
    reason = inner.get("reason") or verdict.get("reason") or "high-stakes call with no recorded validation"
    missing = inner.get("missing") or []
    named = " | ".join(f"{m.get('id')} [chk:{m.get('chk')}] {m.get('when')}" for m in missing if isinstance(m, dict))
    rules = ", ".join(inner.get("matched_rules") or [])
    tool = event.get("tool_name") or "a tool"
    parts = [f"before `{tool}`: {reason}"]
    if rules:
        parts.append(f"matched rules: {rules}")
    if named:
        parts.append(f"unvalidated: {named}")
    parts.append("Answer it with `csl record`, or escalate a human-tier rule with `csl attest`.")
    return " ".join(parts)


def pretool() -> int:
    raw = sys.stdin.read()
    binary = csl_bin()
    if not binary:
        print("csl-bridge: csl not found on PATH; layer inactive", file=sys.stderr)
        return 0
    try:
        proc = subprocess.run(
            [binary, "hook", "--harness", "hermes", "--mode", MODE],
            input=raw, capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"csl-bridge: failing open ({exc})", file=sys.stderr)
        return 0

    # Pass the layer's verdict through untouched: a block directive and exit 2 must survive.
    if proc.stdout.strip():
        sys.stdout.write(proc.stdout)
        if not proc.stdout.endswith("\n"):
            sys.stdout.write("\n")

    try:
        event = json.loads(raw or "{}")
    except ValueError:
        return proc.returncode
    verdict = {}
    if proc.stdout.strip():
        try:
            verdict = json.loads(proc.stdout)
        except ValueError:
            verdict = {}
    inner = verdict.get("csl") if isinstance(verdict.get("csl"), dict) else {}
    decision = inner.get("decision") or verdict.get("decision")
    # Queue an audit note only. A block already reaches the agent as a refusal, and an allow
    # needs no comment.
    if decision == "advise" and MODE != "gate":
        queue_note(event.get("session_id"), describe(event, verdict))
    return proc.returncode


def prellm() -> int:
    raw = sys.stdin.read()
    try:
        event = json.loads(raw or "{}")
    except ValueError:
        return 0
    notes = drain_notes(event.get("session_id"))
    if not notes:
        return 0
    body = "\n".join(f"- {note}" for note in notes)
    sys.stdout.write(json.dumps({"context": "Common-sense layer notes:\n" + body}, ensure_ascii=False))
    return 0


def main() -> int:
    which = (sys.argv[1] if len(sys.argv) > 1 else "").strip().lower()
    if which == "pretool":
        return pretool()
    if which == "prellm":
        return prellm()
    print("usage: csl-bridge.py {pretool|prellm}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())