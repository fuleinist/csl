---
name: common-sense
description: "Use when validating a high-stakes action or when a mistake should become a durable rule. A self-improving layer of one-line falsifiable rules that gates sends, destructive operations, config edits and promises, and learns from your daily work."
version: 0.1.0
---

# common-sense

A thin layer of one-line rules that decides whether a high-stakes action is *validated* — and
learns from day-to-day work instead of being written once and forgotten.

The layer is a **rule store plus a validation ledger**, not a memory file. It lives in `$CSL_HOME`
(default `~/.csl`).

## The three moments you use it

**1. Before something irreversible or external, ask the gate.**

```bash
csl gate --session "$SESSION" --domain "publish the release notes to the client"
# exit 2 = BLOCKED: a rule matched, this is high-stakes, and there is no verdict this session
# exit 0 = clear
```

The four gated classes: external sends/publishes/posts, destructive or irreversible operations,
config or scheduler edits, and promises of future work. A non-zero exit is not an error — it is a
question you must answer by actually doing the check.

**2. Record the verdict, with evidence.** The ledger is the only source of truth; `ev` and `last`
in the rule file are *derived* from it, so a rule cannot look exercised without a recorded verdict.

```bash
csl record --session "$SESSION" --domain "publish the release notes" \
  --results "R-006=pass:changelog, tag and artifact all point at 9f2c1a4"
```

Each verdict takes the form `R-XXX=pass|fail|skip:<evidence>`. Rules are graded by kind:

* `chk: mech` — a scripted predicate. A bare `pass` is fine.
* `chk: judge` — **must cite named evidence.** A bare verdict is refused: a judgement with nothing
  named cannot be checked later, which is the entire point of the tier.
* `chk: human` — an agent **cannot** record its own verdict; `record` refuses it. Escalate to the
  human and use `csl attest`, which logs `human-pass`/`human-fail` and is what clears the gate.

**3. When something goes wrong, add a candidate — do not edit a rule by hand.**

```bash
csl evolve --apply
```

Candidates must pass three gates: not loosening a guardrail, not contradicting an existing rule,
and discriminating (a rule that fires on everything says nothing). Survivors are promoted;
guardrail-loosening ones are queued for a human; `chk:human` rules are immune to eviction.

## Which rules apply to what

```bash
csl list --domain "writing a json state file"
```

Matching is token overlap on content words with a self-scaling threshold: a rule needs
`min(2, number of content tokens in its `when`)` shared tokens. Function words are ignored, so a
deployment task never matches the json-state-file rule just because both contain "any".

## Reading the numbers honestly

```bash
csl stats
```

Two metrics, with the gaming holes closed on purpose:

* **SECONDARY** — live rules fired in the trailing 14 days. A `skip` does **not** count as a fire:
  a rule you declared inapplicable is not evidence the rule works. Skips are listed separately.
* **PRIMARY** — action-changing validations (`fail`) this week. This is the one that means the layer
  is finding real problems. A clean week with zero fails is not a good week; it usually means the
  pass is not running.

## Rules for using the layer well

* **Never hand-edit the counters.** `ev`/`last` are derived from the ledger; editing them makes the
  file disagree with its own evidence and `csl validate` will say so.
* **A rule is one falsifiable line** — `when / do / chk / scope / ev / last`. If you cannot write
  the `when` as something observable, it is not a rule yet; keep it as a candidate.
* **`scope: local` is the honest default.** A rule that only holds on this machine (your paths,
  your tool wrappers) must not claim `general`: it can never be falsified off this box, so it
  accumulates evidence it does not deserve and crowds out real rules.
* **Do not add a rule for something a linter or test already catches.** The layer is for judgement
  that has no home elsewhere.
* **When the layer blocks, that is information.** Either do the missing check and record the
  verdict, or fix the rule. Recording a meaningless `pass` to get moving destroys the ledger for
  everyone downstream.