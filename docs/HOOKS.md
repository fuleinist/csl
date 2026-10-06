# Hook contracts — what is verified and what is not

Every claim below was checked on 2026-09-30 against a real install by reading the file named in
the **Verified by** column. Anything not verified is labelled, not guessed — the point of this
document is that you can tell the two apart.

## The one thing that makes this portable

All of these harnesses converge on the same wire for tool hooks:

```jsonc
// stdin
{"hook_event_name": "PreToolUse", "tool_name": "Bash",
 "tool_input": {"command": "git push --force"}, "session_id": "abc", "cwd": "/repo"}

// stdout — either dialect
{"decision": "block", "reason": "..."}     // Claude Code / Codex
{"action":   "block", "message": "..."}    // Hermes

// or simply: exit code 2 blocks the call
```

`csl hook` reads that stdin shape and writes **both** dialects plus exit 2, so one command covers
Claude Code, Codex and Hermes with no per-harness code. Only the config file differs.

## Matrix

| Harness | Mechanism | Config file | Verified by |
|---|---|---|---|
| Claude Code | shell hook on `PreToolUse` | `~/.claude/settings.json` → `hooks` | read a live `settings.json`: events `SessionStart`, `PreToolUse`, `PostToolUse`, `Stop`; entries `{matcher, hooks:[{type:"command", command, timeout}]}` |
| Codex | shell hook on `PreToolUse` | `~/.codex/hooks.json` | read a live `hooks.json`: identical schema to Claude Code, field for field |
| Hermes | shell hook (`pre_tool_call`) **or** Python plugin | `~/.hermes/config.yaml` → `hooks` | `hermes_cli/config_defaults.py` (schema: `event -> [{matcher, command, timeout}]`) and `agent/shell_hooks.py` (wire format, exit-2-blocks, fail-open, consent + allowlist) |
| OpenClaw | plugin hook (`before_tool_call`), plus `before_prompt_build` for the comment | `~/.openclaw/extensions/<id>/` → `openclaw.plugin.json` | read the installed `docs/plugins/hooks/tool-policy.md` and `docs/plugins/hooks/prompt-and-session.md`, and the live extension `~/.openclaw/extensions/rtk-rewrite/` (`openclaw.plugin.json` + `index.ts`). The refusal shape is documented; a live block was **NOT observed** — see `adapters/openclaw/CONTRACT.md` |
| DeepSeek Harness | unknown | unknown | **UNVERIFIED.** No install available to inspect. `adapters/deepseek/` documents the generic contract to wire by hand |

## Install

```bash
pip install -e .          # or: pipx install .
csl init                  # creates ~/.csl and seeds the rules file
```

Then merge the adapter config:

* **Claude Code** — merge `adapters/claude-code/settings.hooks.json` into `~/.claude/settings.json`.
* **Codex** — merge `adapters/codex/hooks.json` into `~/.codex/hooks.json`.
* **Hermes** — merge `adapters/hermes/config.hooks.yaml` into `~/.hermes/config.yaml`. Hermes asks
  for consent on the first run of a new command; for gateway/cron runs approve with
  `--accept-hooks` or `HERMES_ACCEPT_HOOKS=1`.
* **OpenClaw** — copy `adapters/openclaw/` to `~/.openclaw/extensions/csl/`, add `csl` to
  `plugins.allow` in `~/.openclaw/openclaw.json`, run `openclaw plugins registry --refresh`, then
  `openclaw plugins enable csl`. OpenClaw does not read `plugin.yaml`, and it does not load a Python
  module.

Use an absolute path to `csl` in the config if the harness does not inherit your `PATH`.

## Modes

```bash
CSL_HOOK_MODE=audit   # default: annotate, never block
CSL_HOOK_MODE=gate    # block a high-stakes action with no recorded validation this session
CSL_HOOK_FAIL_CLOSED=1  # block when the hook itself errors (default: fail open)
```

**Start in `audit`.** Read the notes for a few days, record verdicts with `csl record`, then flip to
`gate`. Turning on `gate` first is how a guardrail gets uninstalled: on a fresh layer every
high-stakes action blocks, because no rule has a recorded pass yet.

## Two properties worth knowing before you wire it up

* **Fail open.** If `csl` is missing, slow, or crashes, the agent's turn continues (exit 0). A hook
  that wedges an agent is worse than a missing guard. Set `CSL_HOOK_FAIL_CLOSED=1` if you disagree
  for your environment.
* **The hook infers high-stakes classes from the tool call** — a regex table over the command text
  for destructive / external-send / config-edit patterns (`src/csl/hook.py`). It cannot infer
  *promises of future work*; that class has no tool signature and must come from the agent calling
  `csl gate` on its own domain. The inference is deliberately conservative and easy to read.