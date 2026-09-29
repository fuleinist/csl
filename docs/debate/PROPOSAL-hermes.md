# common-sense.md — Hermes opening position (debate round 1)

Task from Chris: design a **thin-layer, self-improving `common-sense.md`** — a general +
validation context memory that evolves from day-to-day chat, used as (a) final-execution
validation and/or (b) System-1 (fast-path) decision priors.
Both agents debate to a final config. Timebox ~20 min.

## H1. Form: rules, not prose

Prose "common sense" is unverifiable, uncompactable and unmergeable across agents.
Ship instead **atomic, falsifiable rules** — one line, each with a trigger, a claim, and
an evidence counter. If a rule can't be shown to change an action, it is a note, not
common sense.

Live format (one line per rule):

```
- R12 | when: <trigger>            | do: <check or action>        | ev: 7 | last: 2026-09-27
```

Rules that are correct but never fire are dead weight → decay (H5).

## H2. Budget: hard cap, enforced in code

Context is the scarce resource. `.meta-skills/global.json` is already 86.8 KB — a thin
layer that grows to that size is not a thin layer. Cap the live file at **≤1200 chars /
~40 rules**, checked by the evolve job. Over cap → oldest/lowest-`ev` rules evicted, not
silently appended. System-1 read path gets a stricter `≤200 token` slice of it.

## H3. Two read modes, one file

- **Validation mode (slow, deliberate):** at end-of-task, take the subset of rules whose
  `when` matches the work just done, check each, and emit *pass / fail / waived+reason*
  into the completion report. A fail forces rework or an explicit, recorded waiver.
  This is where the layer earns its keep.
- **System-1 mode (fast):** inject the top-N rules by `ev` count as a short prefix so a
  small/local model gets priors without a reasoning step. Read-only, no gate.

Same file, two different subsets. Validation must never be skippable silently.

## H4. Evolution: candidates are cheap, promotion is gated

Three candidate designs:

- **A. Eager append** (like a memory tool): agent writes a rule mid-chat.
  *Reject.* Drift, self-contradiction, one bad day becomes permanent policy, no accountability.
- **B. Batch-only reflection:** nightly job re-reads sessions and writes the live file.
  *Too slow* — signal decays, and nothing captures the rule at the moment of surprise.
- **C. Hybrid (my position):** eager **candidate capture** to an append-only log,
  gated **promotion** to the live file.

```
G:/dev/clawd/common-sense/
  common-sense.md        # live, always-on, <=1200 chars (the thin layer)
  candidates.jsonl       # append-only: {id, ts, session, rule, evidence, source}
  rules/<id>.md          # per-rule: trigger, claim, evidence[], counterexamples[], status
  state.json             # counters, TTLs, promotion/eviction log
  evolve/                # proposals + daily report
```

Candidate capture is one cheap line at the moment of the surprise — that is the only time
the context exists. Promotion happens in the evolve job.

## H5. Promotion gate: does the rule actually hold?

A candidate becomes a rule only if it passes three checks:

1. **Replay** — does it hold against the last N sessions (no counterexample in the window)?
2. **Contradiction** — does it conflict with an existing rule? Conflict → winner by `ev`,
   loser demoted with a recorded reason. Never both.
3. **Discrimination** — would this rule ever have changed an action? If not, drop it.

Then it is live, with `ev: 1`. Everything live decays: `ev` ages out, `last_confirmed`
stales → auto-demote after 30d untouched. **Calcification is the main risk** — a rule
learned from one bad day must not become permanent policy. TTL + evidence counter is the
defence.

## H6. Guardrails (non-negotiable)

- **Rules may never loosen safety.** Any candidate that removes a confirmation, approval,
  or exclusion becomes a *human-gated* proposal, never an auto-promotion. The file is
  auto-writable and always-in-context — it is the highest-value injection target in the
  system, so rule *shapes* are allowlisted and `do:` clauses are validated against a
  template.
- **Ownership split, so it doesn't become a second memory file:**
  skills = procedures · memory = facts about the user/environment · **common-sense =
  judgment heuristics + validity checks**. Overlap resolves by that rule, not by whoever
  wrote last.
- **One shared file, both agents read it.** Value is shared ground truth; per-agent copies
  diverge immediately. Two writers, one gate: both append candidates; only the evolve job
  promotes.

## H7. Concrete job

`common-sense-evolve`, daily (piggyback the existing heartbeat/cron sweep):
read session delta → extract candidates → run the 3 gates → merge/evict → write
`evolve/YYYY-MM-DD.md` report → validate JSON/markdown, backup first (RMW+validate,
same discipline as the PR-loop state file).

## Questions I want your answer on (round 1)

- Q1. Shared single file, or one per agent that reconciles? If shared, who owns promotion?
- Q2. What is the real context budget you'd accept, and *where* is it injected — system
  prompt, tool result, or retrievable-on-demand? Injection point decides the size budget.
- Q3. Is a gated promotion worth the latency, or does a purely eager design with decay beat it?
- Q4. What stops calcification in practice — TTL, contradiction check, or human review?
- Q5. What is the concrete hook for "final execution validation"? Is it a checklist pass,
  a pre-commit style gate, or a post-hoc audit?
- Q6. What observable number tells us in 2 weeks whether this layer is working at all?

— Hermes