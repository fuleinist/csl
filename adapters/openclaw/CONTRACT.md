# OpenClaw adapter — CONTRACT

## Verified (read from a working extension on the author's machine, 2026-09-30)

**Manifest.** `~/.openclaw/extensions/rtk-rewrite/plugin.yaml`:

```yaml
name: rtk-rewrite
version: "0.1.0"
description: Rewrite Hermes terminal commands through RTK before execution.
author: RTK Contributors
hooks:
  - pre_tool_call
provides_hooks:
  - pre_tool_call
```

So the adapter is a directory under `~/.openclaw/extensions/<name>/` containing `plugin.yaml` with
`name`/`version`/`description`/`author`, the `hooks:` list it wants, and `provides_hooks:`.

**Registration and hook signature.** From that extension's `__init__.py`:

```python
def register(ctx):
    ctx.register_hook("pre_tool_call", _pre_tool_call)

def _pre_tool_call(tool_name=None, args=None, **_kwargs):
    ...
    args["command"] = rewritten          # mutate in place
```

Verified from the source: the entry point is `register(ctx)`, the hook is registered with
`ctx.register_hook("<event>", fn)`, the callback receives keyword arguments `tool_name` and `args`
(plus others, hence `**_kwargs`), and `args` is a **mutable dict** the hook edits in place. The
reference implementation returns `None` in every path.

## NOT verified — the part that matters for a guardrail

**How an OpenClaw hook refuses a call.** The reference extension only rewrites arguments; nothing in
it demonstrates a block. It therefore provides no evidence for any of:

* whether returning a directive dict from the hook blocks the call;
* whether raising an exception blocks the call;
* whether there is a documented refusal value or exit convention.

`__init__.py` in this directory handles that honestly: it calls `csl hook --harness openclaw`, and

* on a block verdict it **raises `PermissionError`** (and returns a `{"decision":"block"}` directive
  on the non-strict path), so whichever mechanism the host honours will stop the call;
* it **never fails silently** — every call is appended to `~/.csl/hook-openclaw.jsonl` with the exit
  code and verdict, so you can see what actually fired;
* it **fails open** on any internal error, because a wedged agent is worse than a missing guard.

## How to verify it in five minutes

```bash
# 1. install and see what the hook decides, without OpenClaw in the loop
echo '{"hook_event_name":"pre_tool_call","tool_name":"bash",
       "tool_input":{"command":"git push --force"},"session_id":"probe"}' \
  | csl hook --harness openclaw --explain

# 2. put the extension in place, then trigger a high-stakes call with CSL_HOOK_MODE=gate
export CSL_HOOK_MODE=gate
# -> did the tool call actually stop? that single observation settles the question

# 3. read what the adapter recorded
cat ~/.csl/hook-openclaw.jsonl
```

If the call did **not** stop, the mechanism is wrong, not the verdict: change the refusal in
`_pre_tool_call` to whatever OpenClaw honours, and record the answer here. Until then this adapter
is a **logger with an attempted block**, not a guard.

## Contribution note

This adapter was written by Hermes after three failed attempts to have the sibling agent `main`
produce it through its own gateway (the Control UI path stopped delivering to that session, verified
by querying `transcript_events` — 0 rows). The manifest and signature above are verified first-hand;
the blocking mechanism is the open question it was asked to settle. If `main` produces its own
version with the refusal verified, replace this one and delete this note.