"""Normalise a harness tool-call event into a verdict. One command, several harnesses.

VERIFIED wire contracts (checked 2026-09-30 against installed harnesses — see docs/HOOKS.md):

* **Hermes** ``agent/shell_hooks.py``: stdin JSON
  ``{hook_event_name, tool_name, tool_input, session_id, cwd, extra}``; stdout JSON
  ``{"decision"|"action": "block", ...}``; **exit 2 blocks even with no JSON**; fail-open
  unless ``fail_closed``.
* **Claude Code / Codex**: identical event shape and the same ``hooks`` config schema
  (``{event: [{matcher, command, timeout}]}``).
* **OpenClaw**: see ``adapters/openclaw/CONTRACT.md`` (contributed and verified separately).

The two dialects differ only in which key carries the reason, so this emits both:
``{"decision": "block", "action": "block", "reason": ..., "message": ...}``.

Design rules, both learned the hard way in the debate this came from:

1. **Fail open.** A hook that breaks an agent's turn is worse than a missing guard. Any internal
   error exits 0 unless ``CSL_HOOK_FAIL_CLOSED=1`` is set deliberately.
2. **Audit by default.** ``CSL_HOOK_MODE=audit`` (default) never blocks — it annotates. Blocking
   is opt-in via ``gate``, because a beta that blocks on a heuristic will be uninstalled.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from . import paths
from .check import STOPWORDS, load_ledger, matching_rules, toks  # noqa: F401
from .grammar import parse

#: Conservative, tool-level inference of the high-stakes classes the design gates. It knowingly
#: covers only what a tool call can show; the semantic classes (promises of future work) have no
#: tool signature and must be declared by the agent via the layer's normal `check` path.
DESTRUCTIVE = re.compile(
    r"\brm\s+-[rf]{1,2}\b|\bgit\s+reset\s+--hard\b|\bgit\s+push\b[^|;]*--force\b|\bgit\s+clean\s+-[fdx]"
    r"|\bdrop\s+(table|database)\b|\btruncate\s+table\b|\bdel\s+/[fqs]\b|\bformat\s+[a-z]:"
    r"|\bmkfs\b|\bshutdown\b|\breg\s+delete\b",
    re.I,
)
EXTERNAL = re.compile(
    r"\bgit\s+push\b|\bgh\s+(pr|issue)\s+(create|comment|close|merge|edit)\b|\bgh\s+release\b"
    r"|\bnpm\s+publish\b|\btwine\s+upload\b|\bcargo\s+publish\b|\bdocker\s+push\b"
    r"|\bcurl\b[^|;]*\s-X\s*(POST|PUT|PATCH|DELETE)\b|\bcurl\b[^|;]*\s--data\b"
    r"|\bmail\b|\bsendmail\b|\bsmtp\b|\btwurl\b|\bmastodon\b|\bpost\s+to\b",
    re.I,
)
CONFIG_EDIT = re.compile(
    r"\bcrontab\b|\bsystemctl\b|\bschtasks\b|\bln\s+-s\b|\bconfig\.(ya?ml|json|toml)\b"
    r"|\b\.env\b|\bopenclaw\.json\b|\bsettings\.json\b|\bscheduler\b|\bcron\b",
    re.I,
)

HIGH_STAKES = {
    "external send, publish or post": EXTERNAL,
    "destructive or irreversible operation": DESTRUCTIVE,
    "config or scheduler edit": CONFIG_EDIT,
}

DEFAULT_BLOCK = "blocked by common-sense: unvalidated high-stakes action"


def _salient(tool: str, tool_input) -> str:
    """The part of a tool call worth matching on. Unknown shapes fall back to their scalars."""
    if isinstance(tool_input, str):
        return tool_input
    if not isinstance(tool_input, dict):
        return ""
    for key in ("command", "file_path", "path", "url", "query", "prompt", "pattern",
                "description", "content", "notebook_path"):
        v = tool_input.get(key)
        if isinstance(v, str) and v.strip():
            return v
    # Unknown tool: keep every string value so a matcher at least sees the words.
    return " ".join(v for v in tool_input.values() if isinstance(v, str))


def normalise(raw: dict, harness: str | None = None) -> dict:
    """Accept the native harness event (or this project's normalised one) and fill the gaps."""
    ev = {
        "harness": harness or raw.get("harness") or "generic",
        "event": raw.get("event") or raw.get("hook_event_name") or "pre_tool_use",
        "session": (raw.get("session") or raw.get("session_id") or raw.get("chat_id")
                    or raw.get("conversation_id") or "unknown"),
        "tool": raw.get("tool") or raw.get("tool_name") or "",
        "input": raw.get("input") if isinstance(raw.get("input"), dict) else raw.get("tool_input"),
        "cwd": raw.get("cwd") or "",
        "domain": raw.get("domain") or "",
    }
    text = _salient(ev["tool"], ev["input"])
    ev["text"] = text
    ev["high_stakes"] = infer_high_stakes(ev["tool"], text)
    # The bridge between a raw tool call and a semantic rule. A push shares no words with
    # "about to run a destructive or irreversible operation", so matching would never fire; the
    # high-stakes CLASS labels are the design's own vocabulary, so putting them in the domain is
    # what lets a rule written in that vocabulary match a real event. An agent-supplied `domain`
    # is still preferred and used verbatim.
    labels = " ".join(ev["high_stakes"])
    ev["derived_domain"] = ev["domain"] or f"{ev['tool']} {text} {labels}".strip()
    return ev


def infer_high_stakes(tool: str, text: str) -> list[str]:
    hay = f"{tool} {text}"
    return [name for name, rx in HIGH_STAKES.items() if rx.search(hay)]


def decide(ev: dict, mode: str = "audit") -> dict:
    """The verdict. Pure function of the event and the layer, so it is directly testable."""
    _, rules, _ = parse(paths.LIVE)
    need = matching_rules(ev["derived_domain"], rules)
    rows = [r for r in load_ledger() if r.get("session") == ev["session"]]
    recorded = {r["rule"] for r in rows if r.get("status") in ("pass", "human-pass")}
    human_ok = {r["rule"] for r in rows if r.get("status") == "human-pass"}

    missing = []
    for r in need:
        if r["chk"] == "human":
            if r["id"] not in human_ok:
                missing.append(r)
        elif r["id"] not in recorded:
            missing.append(r)

    high = ev["high_stakes"]
    verdict = {
        "session": ev["session"],
        "harness": ev["harness"],
        "domain": ev["derived_domain"],
        "high_stakes": high,
        "matched_rules": [r["id"] for r in need],
        "missing": [{"id": r["id"], "chk": r["chk"], "when": r["when"]} for r in missing],
        "mode": mode,
    }
    # A block needs BOTH: a high-stakes class, and a matched rule with no verdict this session.
    # High-stakes alone with no matching rule is an audit note, not a block — the layer must not
    # pretend to gate what it has no rule about.
    if high and missing:
        verdict["decision"] = "block" if mode == "gate" else "advise"
        verdict["reason"] = (
            f"high-stakes ({'; '.join(high)}) with no recorded validation for "
            f"{', '.join(m['id'] for m in missing)} this session"
        )
    elif high:
        verdict["decision"] = "allow"
        verdict["reason"] = f"high-stakes ({'; '.join(high)}) but no live rule covers it"
    elif missing:
        verdict["decision"] = "allow" if mode == "audit" else "allow"
        verdict["reason"] = f"rules matched, not high-stakes: {', '.join(m['id'] for m in missing)}"
    else:
        verdict["decision"] = "allow"
        verdict["reason"] = "no rule matched"
    return verdict


def emit(verdict: dict, harness: str, stream=None) -> int:
    """Write the harness's expected response and return the process exit code.

    Both block dialects are emitted together: Hermes reads ``action``+``message``, Claude Code and
    Codex read ``decision``+``reason``. Exit 2 is the belt-and-braces path every one of them
    honours for ``pre_tool_use``.
    """
    out = stream or sys.stdout
    if verdict["decision"] == "block":
        payload = {
            "decision": "block",
            "action": "block",
            "reason": verdict["reason"],
            "message": verdict["reason"],
            "csl": {k: verdict[k] for k in ("session", "domain", "high_stakes", "missing")},
        }
        out.write(json.dumps(payload, ensure_ascii=False))
        out.write("\n")
        return 2
    if verdict["decision"] == "advise":
        out.write(json.dumps({"csl": verdict, "decision": "allow"}, ensure_ascii=False))
        out.write("\n")
        return 0
    return 0


def run(argv: list[str]) -> int:
    mode = os.environ.get("CSL_HOOK_MODE", "audit").strip().lower()
    fail_closed = os.environ.get("CSL_HOOK_FAIL_CLOSED", "") not in ("", "0", "false")
    harness, explain, event_path = "generic", False, None

    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--harness" and i + 1 < len(argv):
            harness = argv[i + 1]; i += 2; continue
        if a == "--event" and i + 1 < len(argv):
            event_path = argv[i + 1]; i += 2; continue
        if a == "--mode" and i + 1 < len(argv):
            mode = argv[i + 1].strip().lower(); i += 2; continue
        if a == "--explain":
            explain = True; i += 1; continue
        i += 1

    try:
        raw = json.loads(Path(event_path).read_text(encoding="utf-8")) if event_path \
            else json.loads(sys.stdin.read() or "{}")
    except Exception as e:
        # Unreadable event: there is nothing to judge. Fail open unless told otherwise.
        if fail_closed:
            sys.stdout.write(json.dumps({"decision": "block", "action": "block",
                                         "reason": f"csl: unreadable hook event ({e})"}))
            return 2
        return 0

    try:
        ev = normalise(raw, harness)
        paths.ensure_home()
        v = decide(ev, mode=mode)
        if explain:
            print(json.dumps(v, indent=2, ensure_ascii=False))
            return 0
        return emit(v, harness)
    except Exception as e:
        if fail_closed:
            sys.stdout.write(json.dumps({"decision": "block", "action": "block",
                                         "reason": f"csl: hook error ({e})"}))
            return 2
        print(f"csl: hook error, failing open: {e}", file=sys.stderr)
        return 0