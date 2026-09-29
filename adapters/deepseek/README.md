# DeepSeek Harness — UNVERIFIED adapter

**No install was available to inspect, so nothing here is claimed as tested.** This file describes
the generic contract, which is what the other four harnesses turned out to share. If DeepSeek's
hook wire matches it, the adapter is the two lines below; if it does not, fix this file rather than
trusting it.

## What we know

Nothing specific. We did not read a DeepSeek Harness config, and none of the harness code on this
machine belongs to it.

## The generic contract to wire by hand

If the harness can run a command before a tool call and pass it a JSON event, then:

```bash
# one command, whole adapter
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

1. **Does the harness honour exit code 2 as a block?** If it only reads stdout JSON, use the
   `decision`/`reason` pair. If it has its own verdict schema, add a formatter in
   `src/csl/hook.py:emit()` — that function is the only place harness output shape lives.
2. **What is the session id field called?** `csl` reads `session`/`session_id`/`chat_id`/
   `conversation_id` and falls back to `"unknown"`. A wrong session id is not cosmetic: verdicts
   recorded this session are what clear the gate, so an id that changes per tool call means every
   call looks unvalidated and `gate` mode blocks everything.

Then update the matrix in `docs/HOOKS.md` from **UNVERIFIED** to verified, and say what you read.