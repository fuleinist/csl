# OpenClaw adapter — CONTRACT

## What changed and why

This directory used to ship `plugin.yaml` and a Python `__init__.py`. Neither is the OpenClaw plugin
format, and the manifest was recorded as **verified** when it was not. This version replaces both
with a TypeScript plugin and states its evidence.

## Verified (OpenClaw 2026.9.6, 2026-10-06)

Read from the installed harness, not from memory. Sources:

* `node_modules/openclaw/docs/plugins/hooks/tool-policy.md` — the tool-call policy hook.
* `node_modules/openclaw/docs/plugins/hooks/prompt-and-session.md` — the prompt hooks.
* `node_modules/openclaw/docs/plugins/sdk-entrypoints.md` — plugin shapes and entry points.
* the live extension directory `~/.openclaw/extensions/rtk-rewrite/`, which holds
  `openclaw.plugin.json` (705 bytes) and `index.ts` (4536 bytes). It has **no** `plugin.yaml` and
  **no** `__init__.py`.

**Manifest.** A directory under `~/.openclaw/extensions/<id>/` holding:

* `openclaw.plugin.json` — at least `id`, `name`, `version`, `description`, plus optional
  `configSchema` and `uiHints`.
* `package.json` — `main`, and `openclaw.extensions` naming the entry module.
* the entry module, `index.ts`.

**Registration.** The module's default export receives the plugin API:

```ts
export default function register(api: any) {
  api.on("before_tool_call", (event, ctx) => { /* ... */ }, { priority: 50 });
}
```

There is no `ctx.register_hook`. The event is `before_tool_call`, not `pre_tool_call`.

**Refusal.** `before_tool_call` returns one of:

```ts
type BeforeToolCallResult = {
  params?: Record<string, unknown>;   // rewrite the tool parameters
  block?: boolean;                    // terminal: skips lower-priority handlers
  blockReason?: string;
  requireApproval?: {
    title: string;
    description: string;
    severity?: "info" | "warning" | "critical";
    /* ... */
  };
};
```

Raising an exception is not part of that contract. `index.ts` returns `{ block: true, blockReason }`.

**No advisory channel.** `before_tool_call` cannot carry a note. An audit verdict has to ride a
prompt hook, which returns `{ prependContext }` or `{ appendContext }`. `index.ts` registers
`before_prompt_build` for exactly that. Without it, `audit` mode computes a verdict and discards it.

**Enablement.** A plugin must appear in `plugins.allow` in `~/.openclaw/openclaw.json`.
`openclaw plugins enable <id>` refuses a plugin that is absent from that list, with
`blocked by allowlist`. A new directory becomes visible after `openclaw plugins registry --refresh`.

**Tool name.** OpenClaw names its shell tool `exec`. A handler reads `event.toolName` and
`event.params`.

## NOT verified

**That a block stops a live call.** The refusal shape and the `block: true` semantics are documented,
and the docs carry a caveat this adapter cannot test from here: native tool relays can have narrower
contracts, and Codex native tools reject parameter rewrites while still supporting blocking. No live
agent turn was driven on this machine to observe a refusal. Treat the blocking path as documented but
unobserved.

The adapter does not hide that. Every decision, and every failure to reach the layer, is appended to
`$CSL_HOME/hook-openclaw.jsonl` with its exit code.

## Verify it in two minutes

```bash
# 1. what the layer decides, with OpenClaw out of the loop
echo '{"hook_event_name":"before_tool_call","tool_name":"exec",
       "tool_input":{"command":"git push --force"},"session_id":"probe"}' \
  | csl hook --harness openclaw --explain

# 2. drive both hooks directly, no live agent turn needed
node adapters/openclaw/verify.mjs

# 3. read what the adapter recorded
cat ~/.csl/hook-openclaw.jsonl
```

`verify.mjs` needs Node 22.18+ or 23+, which strip TypeScript types natively. It loads `index.ts`,
registers it against a stub plugin API, and asserts: `audit` never blocks, `gate` blocks, the ledger
is written, the comment is delivered and then drained, a benign call stays quiet, and a `chk:human`
rule cannot be cleared through the agent's own `record` path. It is not part of
`.github/workflows/csl-matrix.yml`, which stays Python-only.

## Contribution note

The earlier text here recorded that the adapter was written after three failed attempts to have a
sibling agent produce it through its own gateway. That history stands. What changed is that the
manifest it was built on was stale, and the mistake was recording verification from a remembered
filename instead of from the format. Read the harness's own schema before you mark a line verified.