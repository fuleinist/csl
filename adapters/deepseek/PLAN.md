# Plan: verify the DeepSeek Harness adapter

Status: this plan drove the work, and the adapter now sits beside it. Every claim marked as measured
was observed in a live run of the harness; [`CONTRACT.md`](CONTRACT.md) holds the evidence, and
`README.md` carries the status word.

The current `adapters/deepseek/README.md` says, correctly for the date it was written: "No install
was available to inspect, so nothing here is claimed as tested." An install is now available. This
plan uses it.

## What is verified now

All facts below come from a packaged DeepSeek Harness `0.2.0-rc.2` install. Each row names the file
that holds the evidence.

| Fact | Evidence |
|---|---|
| The harness ships hook bridges for the Claude Code and Codex config dialects | `@deepseek-ai/dsh-hooks-claude-code`, `@deepseek-ai/dsh-hooks-codex` package READMEs |
| The Claude Code bridge runs **command hooks** from an existing `hooks.json`, or from a settings file whose `hooks` key holds the config | `@deepseek-ai/dsh-hooks-claude-code` README, section "When to choose it" |
| The bridge plugin id is `hooks-claude-code` | `@deepseek-ai/dsh-hooks-claude-code/lib/index.js`, `const name = "hooks-claude-code"` |
| The bridge reads one process-level config at startup | same README, section "How hooks run and fail" |
| Supported events: `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`, `SubagentStart`, `SubagentStop` | same README, section "What your hooks can do" |
| `PreToolUse` can block or ask for approval. It **cannot** attach context | same README, section "Known Limitations", the "`PreToolUse` is partial" bullet |
| Exit 2 blocks the action. The hook's error output becomes the reason | `@deepseek-ai/dsh-hook-protocol` README, section "What a hook can do" |
| The codec reads the exit-2 reason from **stderr** | `@deepseek-ai/dsh-hook-protocol/lib/index.js`, the block branch of the exit-code decoder |
| The codec reads structured stdout only on exit 0 | same file, the exit-0 branch |
| `deny` and `ask` both work on `PreToolUse`, and the fold is `deny > ask > allow` | `@deepseek-ai/dsh-hooks-claude-code` README, sections "Known Limitations" and "Matcher subjects and serial execution" |
| The payload carries `session_id`, `cwd`, `hook_event_name`, and per-event fields. `transcript_path` is always empty | same README, section "Payloads and environment" |
| The bridge records a `hook/invoked` and `hook/result` pair in the session log | `@deepseek-ai/dsh-hook-protocol` README, section "`hook/*` session events" |
| A profile whose name is `desktop` is owned by the Electron app, and the CLI rejects it | `@deepseek-ai/dsh` README, and the CLI error `profile "desktop" is managed exclusively by the Electron application` |
| `{"continue": false}` is recorded but has no run-level effect | `@deepseek-ai/dsh-hook-protocol` README, section "Known Limitations" |

Consequence for this repository: **the wire is already right.** `csl hook` reads the same stdin
shape and exits 2, so the adapter is configuration plus one small script. No change to the shared
verdict logic in `src/csl/hook.py` is needed.

## The mechanism

Mount the harmless-looking bridge, and point it at a csl hook config. The entry lives in a profile
patch, not in the hook config:

```yaml
- id: hooks-claude-code
  name: '@deepseek-ai/dsh-hooks-claude-code'
  config:
    configPath: ./.claude/hooks.json
    projectDir: .
```

`configPath` is required. The other fields carry defaults. Layer order is the bundle patch, then the
profile `cordis.patch.yml`, then the home `$DSH_HOME/cordis.patch.yml`, then `--patch` overlays. An
id-targeted patch replaces that entry's whole config, so restate every field you keep.

## The note channel

An advisory note cannot ride `PreToolUse` on this harness, because that event ignores
`additionalContext`. The adapter therefore needs two entry points, like the Hermes adapter:

1. `PreToolUse` runs `csl hook --harness deepseek`, passes the verdict through untouched, and queues
   an `advise` note for the session.
2. `UserPromptSubmit` drains the queue and emits the note as context that the model sees.

`PostToolUse` also carries context, and stays a fallback. `UserPromptSubmit` wins, because the note
then reaches the model before it chooses its next tool call.

This mirrors `adapters/hermes/csl-bridge.py`, which solves the same problem for a harness that drops
an advisory payload on its pre-tool event. Reuse its three rules: pass the layer's output and exit
code through unchanged, queue only an `advise` verdict, and fail open when `csl` is absent.

**Timing limit.** A note queues on the tool call and drains on the next prompt in that session. A
note may therefore arrive one turn later than the action that raised it.

**Unverified.** The exact stdout key that the bridge reads for `UserPromptSubmit` context. The
README states that JSON `additionalContext` works, and does not show the enclosing shape. Determine
it in step 9 below. Do not guess it.

## The gate channel

**Measured: exit 2 does not block on this harness.** A hook process that exited 2 was recorded as
`"exitCode": 1` with `"decision": "pass"`, and the tool ran anyway. An adapter built on the
exit-code contract fails **open** here, which is the worst failure mode: the guard looks installed.

The block must therefore ride the structured channel: exit 0 with
`hookSpecificOutput.permissionDecision: "deny"` and `permissionDecisionReason`. That form was
observed to block the tool and to deliver the reason text to the model verbatim. See
[`CONTRACT.md`](CONTRACT.md), section "The block path".

- `csl hook` returns exit 2 for a `block` verdict, and writes the payload to **stdout**
  (see `emit` in `src/csl/hook.py`).
- The bridge translates that verdict into the structured deny, and repeats the reason on stderr for
  a harness that honours exit 2.

This is the one place where the existing adapters are not a sufficient template.

csl has no `ask` decision today (`decide` returns `block`, `advise`, or `allow`). The harness
supports `ask` on `PreToolUse`, and an absent approval answer fails closed under approval policy
`never`. Two options:

| Option | Change |
|---|---|
| Adapter-local | The adapter script maps an adapter-local signal to `ask`. `src/csl/hook.py` stays untouched. |
| Shared | `src/csl/hook.py` gains an `ask` decision, and every adapter gains it. |

This plan recommends the adapter-local option first, and leaves the shared decision to the
maintainer.

## Artifacts

| Path | Status | Content |
|---|---|---|
| `adapters/deepseek/hooks.json` | new | The hook config to merge. Mirror the shape of `adapters/codex/hooks.json`. Declare `PreToolUse` and `UserPromptSubmit`. |
| `adapters/deepseek/csl-bridge.py` | new | The script that queues the `PreToolUse` note, drains it on `UserPromptSubmit`, and turns a block verdict into the structured deny. Adapt `adapters/hermes/csl-bridge.py`. |
| `adapters/deepseek/CONTRACT.md` | new | The observed contract, the section names that hold it, and the harness version. Follow `adapters/openclaw/CONTRACT.md`. |
| `adapters/deepseek/README.md` | rewrite | Replace the placeholder text. Keep the status word `UNVERIFIED` until the live procedure passes. |
| `tests/test_deepseek_bridge.py` | new | The cases below. Follow `tests/test_hermes_bridge.py`. |
| `docs/HOOKS.md` | edit | The Matrix row and the Install entry. |
| `README.md` | edit | The adapter status table row. |

## Tests

New file `tests/test_deepseek_bridge.py`, using the stdlib only, as the other suites do:

| Case | Assertion |
|---|---|
| `test_pretool_passes_verdict_through` | The script returns the layer's exit code and stdout unchanged. |
| `test_pretool_fails_open_without_csl` | A missing `csl` binary exits 0. |
| `test_advise_queues_note` | An `advise` verdict writes one pending note for the session. |
| `test_block_does_not_queue_note` | A `block` verdict writes no pending note. |
| `test_block_writes_reason_to_stderr` | An exit-2 block carries the reason on stderr. |
| `test_preprompt_drains_note_as_context` | The drain emits the context payload and removes the pending file. |
| `test_preprompt_drains_once` | A second drain for the same session emits nothing. |
| `test_note_names_missing_rules` | The note text names each missing rule id and its `chk` tier. |
| `test_session_id_is_sanitized` | A session id with path characters cannot escape the pending directory. |

These tests exercise csl and the adapter script. They do not boot the harness. A passing suite does
not exercise the adapter inside a harness.

Add one row to `tests/probe.py` only after the live procedure passes.

## Live verification procedure

Run these steps on a machine with DeepSeek Harness installed. Use a scratch harness home. Never use
the `desktop` profile, because the CLI rejects it.

1. Set `DSH_HOME` to a scratch directory.
2. Record the version with `dsh --version`. The observed build was `0.2.0-rc.2`.
3. Make sure that the harness can reach a model, because a tool call needs a working route.
4. Write the profile patch that mounts `@deepseek-ai/dsh-hooks-claude-code` with the csl
   `hooks.json`. Restate every field of the entry.
5. Run `--dump-config --profile headless` and read the composed tree. Make sure the entry holds the
   intended `configPath`.
6. Run the agent in the background. A foreground command cap killed an earlier run.
7. Prompt the agent to run a tool that matches a high-stakes class in gate mode.
   Make sure the tool does not run, and that the refusal reason reaches the model.
8. Record the verdict with `csl record`. Run the same prompt again. Make sure the action proceeds.
9. Prompt the agent to run a tool that yields an `advise` verdict in audit mode. Make sure the
   advisory note reaches the model on the next request.
10. Read the session log and extract the `hook/invoked` and `hook/result` events.

Collect this evidence:

| Evidence | Proves |
|---|---|
| The `dsh --version` string | Which build this contract describes |
| The composed config dump | The bridge entry mounts with the intended `configPath` |
| The `hook/invoked` and `hook/result` pair | The hook fired at the named event |
| The recorded exit code of 2 | The gate blocked through the exit-code path |
| The blocking stderr text in the model-visible output | The reason channel works |
| The model-visible advisory note | The `UserPromptSubmit` context path works |
| The same run with csl absent | The fail-open path returns exit 0 |

Then change the status words in `README.md`, `docs/HOOKS.md`, and
`adapters/deepseek/README.md` from `UNVERIFIED` to `verified`, and cite this evidence.

## Docs and README updates

`docs/HOOKS.md`, Matrix row. Replace the current row for DeepSeek Harness. Record the bridge package
name, the two events, and the version recorded. Then add a `DeepSeek Harness` entry to the Install
section that names the profile patch and the two hook entries.

`README.md`, adapter status table. Keep the row honest. Three states are available:

| State | When |
|---|---|
| `unverified` | The contract is read, and no live run happened yet. This state holds today. |
| `verified against the installed docs` | The contract is read from an installed build, and a live block is unobserved. The OpenClaw row uses this wording. |
| `verified against a live install` | The live procedure above passed. |

## Risks and limits

- **Unverified note delivery.** The `UserPromptSubmit` context path is documented, not observed.
- **Unverified reason channel.** The harness reads the exit-2 reason from stderr. Whether the reason
  text reaches the model is unobserved until step 8 of the procedure.
- **Unverified `ask` mapping.** csl has no `ask` decision. The mapping needs new code and a new test.
- **No context on `PreToolUse`.** A note always arrives on the next prompt.
- **One config per process.** Per-session hook discovery is not implemented.
- **Serial hook runs.** The harness runs matched hooks one after another, in config order.
- **A detached `SessionStart`.** Session-start context may miss the first request.
- **`transcript_path` is always empty.** The session log is compressed, and a hook script cannot
  read it.
- **`{"continue": false}` has no effect.** Do not build a stop path on it.
- **A blocking `Stop` hook loops.** The `stop_hook_active` flag stays `false`, so a blocking `Stop`
  hook force-continues every step unless it self-limits.
- **Version drift.** Every fact is from `0.2.0-rc.2`. A newer build may change the contract.
- **Process cost.** The adapter adds one Python process per tool call. This plan does not measure
  that cost.

This plan does **not** cover: a real harness boot, the note path end to end, the reason text path,
the `ask` path, the approval path, or the Windows path behaviour of the bridge.

## Open questions for the maintainer

1. Does `ask` belong in the shared verdict in `src/csl/hook.py`, or in the DeepSeek adapter only?
2. Should the adapter ship a ready `hooks.json`, or only document the config?
3. Is `UserPromptSubmit` the accepted note channel, or is `PostToolUse` preferred?
4. Should the adapter ship a `cordis.patch.yml` fragment, or only document the profile entry?
5. Does the harness version floor belong in `adapters/deepseek/CONTRACT.md`?
6. Should `tests/probe.py` gain a DeepSeek row that stays `unverified` until a maintainer runs it?