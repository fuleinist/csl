# DeepSeek Harness — verified against a live install, with one gap

**The bridge fires inside the harness, and a deny blocks a tool call with a reason the model reads.
One step stays unobserved: a block produced by the layer itself inside the harness.** Install:
`0.2.0-rc.2` on Windows 11.

Read [`CONTRACT.md`](CONTRACT.md) for the measured contract, and [`PLAN.md`](PLAN.md) for the plan
that produced it.

## What we know now

* The harness ships a bridge that runs one command hook from a Claude Code `hooks.json`:
  `@deepseek-ai/dsh-hooks-claude-code`. `csl hook` already reads that wire, so the shared verdict
  logic needs no change.
* Exit code 2 blocks the tool call.
* The harness reads the exit-2 reason from **stderr**. `csl hook` writes the reason to **stdout**.
  The adapter must copy the reason to stderr, or the block carries no reason the model can read.
  See "The gate channel" in `PLAN.md`.
* `PreToolUse` cannot attach context. An advisory note therefore needs a second entry point, and
  `UserPromptSubmit` is the recommended one.
* The session id field is `session_id`, and the bridge always fills it.

Sources for each claim, with the section name that holds it: `PLAN.md`, section "What is verified
now".

## The generic contract, as a fallback

If a build cannot run the Claude Code bridge, wire the harness by hand. The command is the whole
adapter:

```bash
csl hook --harness deepseek
```

It accepts (any of these keys, all optional):

```json
{"hook_event_name": "PreToolUse", "tool_name": "...", "tool_input": {...},
 "session_id": "...", "cwd": "...", "domain": "optional semantic task description"}
```

and responds with:

```bash
exit 0   # allow (default, and in audit mode always)
exit 2   # block — stderr/stdout carries the reason
# stdout JSON: {"decision":"block","action":"block","reason":"...","message":"..."}
```

Two things to check when you wire it:

1. **Does the harness honour exit code 2 as a block?** On `0.2.0-rc.2` it does, and it reads the
   reason from stderr. If a harness only reads stdout JSON, use the `decision`/`reason` pair. If it
   has its own verdict schema, add a formatter in `src/csl/hook.py:emit()` — that function is the
   only place the harness output shape lives.
2. **What is the session id field called?** `csl` reads `session`/`session_id`/`chat_id`/
   `conversation_id` and falls back to `"unknown"`. A wrong session id is not cosmetic: verdicts
   recorded this session are what clear the gate, so an id that changes per tool call means every
   call looks unvalidated and `gate` mode blocks everything.

Then update the matrix in `docs/HOOKS.md` from **UNVERIFIED** to verified, and say what you read.