"""OpenClaw extension adapter for the common-sense layer.

`plugin.yaml` declares ``hooks: [pre_tool_call]`` and ``provides_hooks``; OpenClaw loads this module
and calls ``register(ctx)``. That much is **verified** — see ``CONTRACT.md`` for the file that
established it (a working ``rtk-rewrite`` extension on this machine, read 2026-09-30).

What is **not** verified: how an OpenClaw hook *refuses* a call. The reference extension only
mutates ``args`` in place and returns ``None``; nothing in it demonstrates a block. So this adapter
tries the most likely mechanism and, critically, never fails silently — it either blocks loudly or
records that it could not, rather than pretending to guard something it does not.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

#: Where the layer records what OpenClaw could and could not enforce.
LEDGER = os.path.join(os.path.expanduser("~/.csl"), "hook-openclaw.jsonl")

_csl = None


def _csl_path():
    global _csl
    if _csl is None:
        _csl = shutil.which("csl")
    return _csl


def register(ctx):
    """Entry point OpenClaw calls to wire this extension."""
    if not _csl_path():
        _warn("csl not found on PATH; the common-sense layer is NOT guarding this agent")
        return
    ctx.register_hook("pre_tool_call", _pre_tool_call)


def _pre_tool_call(tool_name=None, args=None, **_kwargs):
    """Gate a tool call. Returns a blocking directive when the layer says block.

    UNVERIFIED: whether OpenClaw treats a returned directive, a raised exception, or an exit code
    as a refusal. This returns a dict AND raises on the strict path, so whichever the host honours
    will stop the call; ``CSL_OPENCLAW_STRICT=0`` downgrades it to an audit-only warning.
    """
    try:
        event = {
            "hook_event_name": "pre_tool_call",
            "tool_name": tool_name or "",
            "tool_input": args if isinstance(args, dict) else {"value": args},
            "session_id": os.environ.get("OPENCLAW_SESSION_ID")
            or os.environ.get("OPENCLAW_CHAT_ID") or "openclaw-unknown",
            "cwd": os.getcwd(),
        }
        proc = subprocess.run(
            [_csl_path(), "hook", "--harness", "openclaw"],
            input=json.dumps(event), capture_output=True, text=True, timeout=5,
            env={**os.environ, "CSL_HOOK_MODE": os.environ.get("CSL_HOOK_MODE", "audit")},
        )
    except Exception as e:                     # fail open: never wedge the agent
        _warn(f"hook error, failing open: {e}")
        return None

    verdict = {}
    if proc.stdout.strip():
        try:
            verdict = json.loads(proc.stdout)
        except Exception:
            verdict = {}

    _record(event, verdict, proc.returncode)

    if proc.returncode == 2 or verdict.get("decision") == "block" \
            or verdict.get("action") == "block":
        reason = verdict.get("reason") or verdict.get("message") or proc.stderr.strip() \
            or "blocked by common-sense"
        if os.environ.get("CSL_OPENCLAW_STRICT", "1") != "0":
            # Loud, unambiguous refusal — and a raised error is *not* silently swallowed.
            raise PermissionError(f"common-sense: {reason}")
        _warn(f"WOULD BLOCK (strict=0): {reason}")
        return {"decision": "block", "action": "block", "message": reason}
    return None


def _record(event, verdict, code):
    """Append to an OpenClaw-local ledger so you can see what actually fired."""
    try:
        os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
        entry = {"harness": "openclaw", "tool": event["tool_name"], "session": event["session_id"],
                 "exit": code, "decision": verdict.get("decision", "allow"),
                 "reason": verdict.get("reason", ""), "domain": verdict.get("domain", "")}
        with open(LEDGER, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def _warn(message):
    print(f"csl: openclaw adapter warning: {message}", file=sys.stderr)