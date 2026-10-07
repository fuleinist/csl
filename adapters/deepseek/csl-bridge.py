#!/usr/bin/env python3
"""Bridge the common-sense layer (csl) into DeepSeek Harness (dsh).

Why this exists: dsh runs a Claude Code shape command hook, and two of its behaviours differ from a
Claude Code install.

* `PreToolUse` ignores `additionalContext`. An audit note therefore cannot ride the event that
  raised it. This script queues the note there and delivers it on the next `UserPromptSubmit`.
* dsh reads the exit-2 reason from **stderr**, and reads structured stdout only on exit 0.
  `csl hook` writes its block payload to **stdout**. This script copies the reason to stderr before
  it exits 2, so a block always carries a reason the model can read.

  csl-bridge.py pretool     runs `csl hook --harness deepseek`, passes the layer's stdout and exit
                            code through, copies the block reason to stderr, and queues an audit
                            note for this session. Always exits 0 when the layer is absent.
  csl-bridge.py preprompt   drains the queued notes for this session and emits them as
                            `hookSpecificOutput.additionalContext`.

Configure with two hook entries in the Claude Code shape, and mount the harness bridge that reads
them:

  # the hook config
  {"hooks": {"PreToolUse":      [{"matcher": "...", "hooks": [{"type": "command",
              "command": "python /abs/path/csl-bridge.py pretool", "timeout": 10}]}],
             "UserPromptSubmit": [{"hooks": [{"type": "command",
              "command": "python /abs/path/csl-bridge.py preprompt", "timeout": 10}]}]}}

  # the profile patch that mounts the reader
  - id: hooks-claude-code
    name: '@deepseek-ai/dsh-hooks-claude-code'
    config:
      configPath: /abs/path/hooks.json
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

MODE = os.environ.get("CSL_HOOK_MODE", "audit").strip().lower() or "audit"
HARNESS = os.environ.get("CSL_HARNESS", "deepseek").strip() or "deepseek"
CONTEXT_PREFIX = "Common-sense layer notes:"


def csl_home() -> Path:
    raw = os.environ.get("CSL_HOME")
    return Path(raw).expanduser() if raw else Path.home() / ".csl"


def csl_command() -> list[str] | None:
    """Resolve the layer to a command prefix, most explicit source first.

    `CSL_BIN`, then `csl` on PATH, then the conventional install directory, and finally this
    script's own interpreter with `-m csl`. The last step matters because a harness may run a hook
    with a scrubbed environment: dsh keeps the hook's own interpreter working, and a console-script
    shim on PATH can point at an interpreter the harness refuses to start.
    """
    explicit = os.environ.get("CSL_BIN")
    if explicit and Path(explicit).exists():
        return [explicit]
    found = shutil.which("csl")
    if found:
        return [found]
    local = Path.home() / ".local" / "bin" / ("csl.exe" if os.name == "nt" else "csl")
    if local.exists():
        return [str(local)]
    try:
        import csl  # noqa: F401  (the layer must be importable by this interpreter)
        return [sys.executable, "-m", "csl"]
    except Exception:
        return None


def safe_session(value: object) -> str:
    raw = str(value or "deepseek-unknown")
    cleaned = "".join(c if c.isalnum() or c in "._-" else "_" for c in raw)[:120]
    # A dot run cannot survive as a parent reference, and a leading dot cannot hide the file.
    return cleaned.replace("..", "_").lstrip(".") or "deepseek-unknown"


def pending_file(session: str) -> Path:
    return csl_home() / "pending" / f"deepseek-{safe_session(session)}.jsonl"


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


def block_reason(verdict: dict, stderr_text: str) -> str:
    """The text dsh shows as the refusal reason. It travels on stderr, never on stdout."""
    inner = verdict.get("csl") if isinstance(verdict.get("csl"), dict) else {}
    for candidate in (verdict.get("reason"), verdict.get("message"), inner.get("reason")):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return stderr_text.strip() or "blocked by the common-sense layer"


def pretool() -> int:
    raw = sys.stdin.read()
    try:
        event = json.loads(raw or "{}")
    except ValueError:
        event = {}
    binary = csl_command()
    if not binary:
        print("csl-bridge: csl not found and not importable; layer inactive", file=sys.stderr)
        return 0
    try:
        proc = subprocess.run(
            [*binary, "hook", "--harness", HARNESS, "--mode", MODE],
            input=raw, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"csl-bridge: failing open ({exc})", file=sys.stderr)
        return 0

    verdict: dict = {}
    if proc.stdout.strip():
        try:
            verdict = json.loads(proc.stdout)
        except ValueError:
            verdict = {}
    inner = verdict.get("csl") if isinstance(verdict.get("csl"), dict) else {}
    # The nested verdict wins: an advise payload is `{"csl": {...}, "decision": "allow"}`, where the
    # top-level field is the dialect's allow, not the layer's verdict.
    decision = inner.get("decision") or verdict.get("decision")

    if proc.returncode == 2 or decision == "block":
        # The block rides the structured path. Measured on dsh 0.2.0-rc.2, Windows: a hook process
        # that exits 2 is reported as exit 1 and the tool RUNS ANYWAY, so the exit-code contract
        # cannot carry the block here. Exit 0 with `permissionDecision: deny` does carry it, and the
        # model sees `permissionDecisionReason` verbatim. The reason also goes to stderr, which is
        # the documented channel for harnesses that honour exit 2.
        reason = block_reason(verdict, proc.stderr)
        payload = {
            "hookSpecificOutput": {
                "hookEventName": event.get("hook_event_name") or "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
        print(json.dumps(payload, ensure_ascii=False))
        print(reason, file=sys.stderr)
        return 0

    if proc.returncode != 0 and proc.stderr.strip():
        # A crash in the layer must not be silent: dsh logs only what this script prints.
        print(f"csl-bridge: the layer exited {proc.returncode}: {proc.stderr.strip()[:600]}",
              file=sys.stderr)

    # Pass the layer's own output and exit code through untouched.
    if proc.stdout.strip():
        sys.stdout.write(proc.stdout)
        if not proc.stdout.endswith("\n"):
            sys.stdout.write("\n")

    # Queue an audit note only. A block already reaches the agent as a refusal, and an allow needs
    # no comment.
    if decision == "advise" and MODE != "gate":
        queue_note(event.get("session_id"), describe(event, verdict))
    return proc.returncode


def preprompt() -> int:
    raw = sys.stdin.read()
    try:
        event = json.loads(raw or "{}")
    except ValueError:
        event = {}
    notes = drain_notes(event.get("session_id"))
    if not notes:
        return 0
    body = "\n".join(f"- {note}" for note in notes)
    payload = {
        "hookSpecificOutput": {
            "hookEventName": event.get("hook_event_name") or "UserPromptSubmit",
            "additionalContext": f"{CONTEXT_PREFIX}\n{body}",
        }
    }
    # The Hermes dialect stays as a fallback for a reader that wants the bare key.
    payload["context"] = payload["hookSpecificOutput"]["additionalContext"]
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    return 0


def main() -> int:
    which = (sys.argv[1] if len(sys.argv) > 1 else "").strip().lower()
    if which == "pretool":
        return pretool()
    if which == "preprompt":
        return preprompt()
    print("usage: csl-bridge.py {pretool|preprompt}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())