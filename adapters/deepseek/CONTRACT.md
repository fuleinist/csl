# DeepSeek Harness — the observed hook contract

Checked on 2026-10-07 against DeepSeek Harness `0.2.0-rc.2` on Windows 11. Two sources: the installed
package READMEs and compiled libraries, and live runs of the harness CLI with this adapter mounted.

Anything not observed is labelled. This file is the evidence behind the status word in
[`README.md`](README.md).

## The bridge

| Fact | How it was observed |
|---|---|
| The harness runs command hooks from a Claude Code `hooks.json` through `@deepseek-ai/dsh-hooks-claude-code` | package README, section "When to choose it" |
| The entry id is `hooks-claude-code` | `dsh-hooks-claude-code/lib/index.js`, `const name = "hooks-claude-code"` |
| The config field is `configPath`, read once per process | package README, field table and "How hooks run and fail" |
| **The entry must be INSERTED, not patched** | `dsh --dump-config` printed `dsh: patch: entry "hooks-claude-code" not found` for an id-targeted patch. No shipped bundle (`dsh-base`, `dsh-web-app`, `dsh-headless`) declares a hooks entry, so a patch is a silent no-op. The working form is `- insert: [ { id: hooks-claude-code, ... } ]`. |
| Both events fire | four runs logged `hook/invoked` + `hook/result` for `PreToolUse` and `UserPromptSubmit` |
| The `PreToolUse` matcher subject is the tool name, and the harness shell tool is `pwsh` | `hook/invoked` recorded `"matcher": "bash\|pwsh\|shell\|write\|edit\|str_replace_editor"` and the agent's call used `tool: "pwsh"` |

## The command string runs through a shell

dsh runs a hook command through the platform shell, which is **PowerShell** on Windows. Two
consequences, both observed:

* A leading **quoted** token is read as an expression, not as a command name. Both `"path"` and
  `'path'` failed with `Unexpected token ... in expression`.
* Use a bare command name or a bare path, exactly as the shipped `hooks.json` does. A path that
  contains a space needs the `&` call operator.

## The block path

| Channel | Result |
|---|---|
| Exit code 2, reason on stderr | **Does not block.** The harness recorded `"exitCode": 1` for a hook process that exited 2, `"decision": "pass"`, and the tool ran. |
| Exit 0 with `hookSpecificOutput.permissionDecision: "deny"` and `permissionDecisionReason` | **Blocks.** `"decision": "deny"`, no process spawned, and the model saw the reason text verbatim as the tool error. |

An adapter that relies on exit 2 alone fails **open** on this platform: the guard looks installed
and refuses nothing. `adapters/deepseek/csl-bridge.py` therefore blocks through the structured
channel and repeats the reason on stderr for a harness that honours exit 2.

The codec reserves the top-level `decision` for `approve` and `block`, and
`hookSpecificOutput.permissionDecision` for `allow`, `deny`, and `ask`
(`dsh-hook-protocol/lib/index.js`, `codec` region).

## The note path

`PreToolUse` ignores `additionalContext` (package README, "Known Limitations", the "`PreToolUse` is
partial" bullet), so an advisory note cannot ride the event that raised it. The bridge queues the
note on `PreToolUse` and delivers it on the next `UserPromptSubmit` as
`hookSpecificOutput.additionalContext`.

**Unverified:** that the delivered context reaches the model on this harness. The drain emits the
documented shape; no run has yet observed the model quoting it.

## Evidence

The harness appends a `hook/invoked` and `hook/result` pair to the session log for every hook run.
Read them from `<DSH_HOME>/sessions/<workspace>/<session-id>/session.v4.jsonl.zstd`. The pair is the
only durable proof that a hook fired and what it decided.

## Limits of this contract

* One config applies per process, and hooks run serially in config order.
* `{"continue": false}` is recorded and has no run-level effect.
* `transcript_path` is always empty, because the session log is compressed.
* **Unobserved:** a block produced by the csl layer itself inside the harness. The harness half was
  observed with a stub hook, and the layer half was observed standalone. The seam between them is
  covered by unit tests, not by a live run.