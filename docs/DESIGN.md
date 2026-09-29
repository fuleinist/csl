# Design

Why the layer is shaped this way. Each decision below was argued for, and several replaced an
earlier choice that looked reasonable until it was tested.

## The shape: rule store + ledger, not a memory file

The original instinct was "a memory file that gets smarter". That fails for a specific reason: a
memory file has no falsification. You cannot tell a rule that keeps preventing mistakes from a rule
that has never once applied, and the file grows until it is ignored.

So there are two artefacts with different jobs:

* **`common-sense.md`** — the rule store. Small, capped, human-readable, versioned grammar.
* **`validation.jsonl`** — the append-only ledger of verdicts.

Every counter in the rule store (`ev`, `last`) is **derived** from the ledger. There is no
hand-maintained number to inflate, no rule that counts as fired without a ledger line, and no
ledger line without an explicit verdict. That single decision is what makes the rest measurable.

## A rule is one line, with six fields

```
- R-002 | when: <observable trigger> | do: <the check> | chk: mech|judge|human | scope: <general|agent> | ev: N | last: YYYY-MM-DD
```

* **`when` must be observable.** If you cannot say what you would see when it applies, it is not a
  rule. This constraint is what keeps the layer from becoming a pile of platitudes.
* **`do` is one check, not advice.** "Confirm the target and whether a backup exists" is a check.
  "Be careful with destructive operations" is not.

## Three verdict kinds, and why the distinction is enforced in code

| Kind | Means | Recorded by |
|---|---|---|
| `mech` | a scripted predicate over the tool log — no self-report | anyone; a bare pass is fine |
| `judge` | a judgement, decided from **named evidence** | anyone; the evidence must be cited |
| `human` | a person decides | `csl attest` only; `record` refuses it |

The design always had three tiers. For most of its life **only `mech` was enforced** — `chk:human`
verdicts could be recorded by the agent they constrain, and `chk:judge` needed no evidence at all.
Both were discovered by adversarial review, not by reading the doc. The lesson is now a rule of the
project: *a declared mode needs an enforcement site, or every value behaves like the most
permissive one.*

`human` is **procedural friction, not a security boundary** — the CLI runs as the same user as the
agent. Its value is that self-certification becomes a distinct act, named for what it is, visible in
the ledger as `"by": "human"`. See docs/LIMITS.md.

## `scope` — the field that stops the layer decaying into a second memory file

Every rule declares `scope: general` or an agent name. A rule true only on this machine (local paths,
this box's tool wrappers) must not claim to be general judgment, because **the gates cannot falsify a
local fact**: replay, refire and falsification all re-observe the same box, so a machine-local rule
passes every test forever, accrues evidence it does not deserve, and crowds out real rules.

Scope is **fail-closed**: an undeclared scope becomes `local`, and a `general` claim that cites local
specifics is downgraded with the reason logged. Silence is never read as "this generalises".

This field was agreed in round 1 of the adversarial review and then silently dropped from both
sides' consolidated design. When it was reinstated, 3 of the 7 seeded rules turned out to be
machine-local while claiming general — the drift was already in the corpus and invisible.

## The gate pair

Candidates must pass three gates before promotion, plus a human queue for anything that would loosen
a guardrail:

1. **Safety** — a candidate whose `do` loosens a guardrail is refused and queued for a human.
2. **Contradiction** — a candidate that conflicts with an existing rule is refused.
3. **Discrimination** — a rule that fires on everything says nothing, so it is refused.

**Replay was considered and cut.** Re-running a rule against historical sessions re-reads the same
distribution the rule was mined from, and its verdicts are not reproducible between runs. A gate
whose answer depends on when you run it is worse than no gate.

**Refire** (does the rule fire again out-of-sample?) and **falsification** (does anything contradict
it?) are the two that stayed.

## The eviction/cap problem

The rule file is capped so it cannot grow unbounded. When promotion would exceed the cap, the
lowest-value rule is evicted to `rules/` (ids are never reused).

* `chk:human` rules are **immune to eviction and decay**. The prototype evicted a human-gated safety
  rule purely on value density, which is exactly the failure the cap was supposed to prevent.
* If safety rules alone exceed the cap, the job **refuses and escalates** instead of choosing.
* Value density is **value per character, decayed by age** — the budget is characters, so length must
  be in the denominator. The first implementation used `ev/age` with no length term, which meant
  eviction shed terse rules first and had to delete *more* rules than necessary to recover the same
  budget.

## Metrics, with the gaming holes closed

Two numbers, both derived from the ledger (see `csl stats`). The design of each was driven by trying
to satisfy it without doing the work:

* **Rules fired in the trailing 14 days.** A `skip` deliberately does **not** count: three skip lines
  once moved this metric from 42% to 85% with zero validations, which would have silenced the very
  detector meant to find dead rules. Skips are reported separately.
* **Action-changing validations (`fail`) per week.** This is the metric that means the layer is
  finding real problems. Zero fails is not success — it usually means the pass is not running.

## The hook: one command, four harnesses

Claude Code, Codex and Hermes converged on the same wire for tool hooks (stdin JSON with
`hook_event_name`/`tool_name`/`tool_input`/`session_id`, exit 2 to block). The two response dialects
differ only in which key carries the reason, so the hook emits both and needs no per-harness code.
Only the config file differs. OpenClaw uses its own extension manifest; DeepSeek is unwired.

Two hook properties are non-negotiable:

1. **Fail open.** A hook that wedges an agent's turn is worse than a missing guard.
2. **Audit by default.** A beta that blocks on a heuristic gets uninstalled. `gate` is opt-in.

## What this is not

* Not a memory system. It holds judgement that is checkable, not facts.
* Not a linter. If a test or type-checker can catch it, it does not belong here.
* Not always-on. Nothing is injected into every prompt; the file is read when the gate runs.