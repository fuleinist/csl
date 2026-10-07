# csl — a common-sense layer for agent harnesses

**Beta (v0.1.0).** A thin layer of one-line, falsifiable rules that an agent checks itself against
at high-stakes moments, and that evolves from day-to-day work instead of being written once and
forgotten.

One CLI, one hook, one rule file. Adapters for **Claude Code**, **Codex**, **Hermes** and
**OpenClaw** (DeepSeek Harness documented but unverified).

```bash
pip install -e .        # or pipx install .
csl init                # creates ~/.csl and seeds a rule file
```

Then merge one config file — see [docs/HOOKS.md](docs/HOOKS.md).

---

## The problem it addresses

Agents do not fail from lack of knowledge. They fail from **not pausing at the moment it matters**:
the force-push that skipped a backup, the release published against a stale tag, the config edit
with no rollback. Instructions in a prompt get diluted over a long session; a linter cannot see
"is this the right moment to be doing this?"

`csl` is the smallest thing that survives: a rule store plus a validation ledger. Rules are one
line. Verdicts are append-only. Every counter is *derived* from the ledger, so a rule cannot look
exercised without a recorded verdict.

```
<!-- common-sense v2 | cap 2500 | rules 8 | updated 2026-09-30 -->
- R-002 | when: about to run a destructive or irreversible operation | do: confirm the target and whether a backup or a dry run exists before running it | chk: human | scope: general | ev: 0 | last: 2026-09-30
```

## What happens at runtime

```bash
$ git push --force origin main          # the hook fires before the tool call

$ echo '{"hook_event_name":"PreToolUse","tool_name":"Bash",
         "tool_input":{"command":"git push --force origin main"},"session_id":"s1"}' | csl hook --explain
{
  "high_stakes": ["external send, publish or post", "destructive or irreversible operation"],
  "matched_rules": ["R-001", "R-002"],
  "missing": [{"id": "R-001", "chk": "human", ...}, {"id": "R-002", "chk": "human", ...}],
  "mode": "audit",
  "decision": "advise",
  "reason": "high-stakes (...) with no recorded validation for R-001, R-002 this session"
}
```

In `audit` mode (the default) that is a note. Set `CSL_HOOK_MODE=gate` and the same call exits **2**
— blocked — until the checks are actually done and their verdicts recorded.

## The design in six points

1. **A rule is one falsifiable line** — `when / do / chk / scope / ev / last`. If you cannot write
   `when` as something observable, it is a candidate, not a rule.
2. **Three verdict kinds.** `mech` (a scripted predicate — a bare pass is fine), `judge` (must cite
   named evidence), `human` (an agent cannot record its own verdict; escalate and `attest`). The
   distinction is enforced in code, not in the format — see [docs/LIMITS.md](docs/LIMITS.md).
3. **Two capture paths, two trust levels.** A minimal inline capture from the agent, and
   lower-trust candidates mined from the day's work.
4. **Three promotion gates.** A candidate must not loosen a guardrail, must not contradict an
   existing rule, and must discriminate (a rule that fires on everything says nothing).
5. **Counters are derived, never written.** `ev`/`last` come from the ledger. No rule counts as
   fired without a ledger line, and no line without an explicit verdict.
6. **Never always-on.** The file is read on demand by the gate; it is not injected into every prompt.

## Which of your agents it works on

| Harness | Mechanism | Status |
|---|---|---|
| Claude Code | `PreToolUse` shell hook | verified against a live install |
| Codex | `PreToolUse` shell hook — same `hooks.json` schema as Claude Code | verified against a live install |
| Hermes | `pre_tool_call` shell hook to gate, `pre_llm_call` to comment (`hooks:` in `config.yaml`) | verified against the agent source |
| OpenClaw | plugin hook `before_tool_call`, plus `before_prompt_build` for the comment | contract read from the installed docs; a live block is **unobserved** |
| DeepSeek Harness | command hook through the harness's own Claude Code bridge (`@deepseek-ai/dsh-hooks-claude-code`), mounted by an `insert` patch | verified against a live install: the hook fires, and a `deny` blocks the tool while exit 2 does **not**; a block driven by the layer itself is **unobserved** — see `adapters/deepseek/CONTRACT.md` |

Claude Code, Codex and Hermes share one wire — stdin JSON
`{hook_event_name, tool_name, tool_input, session_id, cwd}`, exit 2 to block — so **one command
covers them**; only the config file differs. OpenClaw uses its own plugin API instead: the adapter
sends it the same stdin JSON, but registers through `api.on` and returns `{ block, blockReason }`.

## CLI

```
csl init                     create $CSL_HOME and seed the rules file
csl validate [--fingerprint] check the live layer; exit 1 on any violation
csl list   --domain "..."    which rules apply to this task domain
csl gate   --session S --domain D          exit 2 when a high-stakes action is unvalidated
csl record --session S --domain D --results "R-002=pass:evidence;R-003=skip:why"
csl attest --session S --domain D --results "R-004=pass:the human's decision"
csl stats                    the metrics, and what they refuse to count
csl evolve [--apply]         mine candidates through the gates; promote or queue
csl hook [--harness H] [--mode audit|gate] [--event FILE] [--explain]
```

Agent-facing usage guide: [skills/common-sense/SKILL.md](skills/common-sense/SKILL.md).

## Tests

Four suites, no test framework required:

```bash
python tests/probe.py              # 41 adversarial cases: every bug this layer has ever had
python tests/test_hook.py          # 19: hook classification, dialects, exit codes, fail-open
python tests/test_hermes_bridge.py # 17: the Hermes comment bridge, the gate passthrough, fail open
python tests/acceptance.py         # 15: candidate -> gates -> live rule -> gate -> clear, end to end
```

`probe.py` is the interesting one: each case was written **after** a real defect, and several were
written before the fix so the failure was observed first. It includes the two properties that are
easy to fake — that a declared tier actually changes enforcement, and that a metric cannot be
improved without doing the work.

## Read before trusting it

* [docs/LIMITS.md](docs/LIMITS.md) — what is enforced vs. what is friction vs. what is unverified.
  **Start here.** `attest` is an audit trail, not a security boundary.
* [docs/HOOKS.md](docs/HOOKS.md) — the verified wire contract per harness, and how each was checked.
* [docs/DESIGN.md](docs/DESIGN.md) — why the design is shaped this way, including what was tried
  and cut.
* [docs/DEBATE.md](docs/DEBATE.md) — this layer was built in a ten-round adversarial review between
  two agents; that record is the reason the code and the docs disagree less than they did.

## Status

Beta. The engine, the CLI and the hook are fully tested; the Claude Code, Codex and Hermes adapters
are verified against live installs; the OpenClaw adapter's blocking path and the DeepSeek adapter
are not. The honest summary is in [docs/LIMITS.md](docs/LIMITS.md) — the short version: **treat
`audit` mode as production-ready and `gate` mode as tested but opinionated.**

MIT.