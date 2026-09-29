# common-sense.md — rebuttal (main, round 1)

One framing fix before the questions: stop calling this an "always-on memory file". The durable
value is a **rule store + validation ledger + sweep process**; the file itself is read-mostly and
small, and the ledger is what accumulates the evidence. Build around the process, not the file.
Everything below assumes that.

## Q1 — shared vs per-agent

Shared single file, and the promoter is a **job, not an agent**. Three teeth added: (1) **no
editorial self-promotion** — only the evolve job ever writes the live file; an agent's only write
path is `candidates.jsonl`, and `rules/<id>.md` records `src_agents` + `src_sessions` so
provenance is auditable. (2) **Disagreement is a first-class move**: an agent that rejects a live
rule files a `dispute` candidate; silent local variants and per-agent forks are banned. (3)
`scope: general` rules prefer evidence spanning ≥2 agents where available; agent-specific rules
carry `scope: <agent>` and are read only by that agent. "One file" doesn't prevent divergence by
itself — making disagreement logged and cheap does.

## Q2 — budget and injection point

Your 1200-char cap and your ~40-rule target contradict each other: at your own line layout
(separators + `when` + `do` + counters ≈ 110–160 chars/rule), 1200 chars ≈ **10 rules**, and 40
rules need ~5 KB. I resolve it at **≤2500 chars (~15–20 rules)**, enforced by the evolve job; on
overflow, lowest net-confirmation rules demote to candidates (logged, never deleted). Injection:
validation mode injects **nothing** — it reads from disk and filters by task domain; System-1
gets a **≤150-token, top-5-by-net-confirmations slice** in the system prompt, opt-in per agent,
marked experimental in v1. And the full file is **never always-on**: you flag it yourself as the
highest-value injection target in H6, then make it always-in-context — those can't both stand. An
on-demand read removes both the surface and the per-turn tax.

## Q3 — gated vs eager

Gated. The latency argument against gating is fake: at daily cadence worst-case promotion lag is
24h and nothing depends on sub-day promotion, while eager+decay gives one bad day's rule live
policy status for its entire decay window. But I'd rebuild the gates so they're cheap and
reproducible: **discrimination moves to capture time** — `candidates.jsonl` lines require
`would_change: <which specific action>` and `safety: true|false`. By your own H4 argument, the
moment of surprise is the only time that context exists; the evolve job cannot honestly
reconstruct it later. New gate list: (1) **refire** — candidate must recur in a later session
(out-of-sample) before promotion; (2) **contradiction** — vs live rules, winner by net
confirmations, loser quarantined with reason; (3) **safety** — flagged candidates go to a human,
never auto. **Session replay is cut**: it re-reads the same distribution, its LLM verdicts aren't
reproducible, and it costs a nightly scan; a refire is ground truth.

## Q4 — calcification defence

Ranked, honestly: **falsification > contradiction > provenance > human skim > TTL**. Probation
tier: new promotions enter `status: probation` for **14d**; one counterexample during probation
quarantines back to candidates. Counterexamples are captured the same way rules are — at surprise
time, as `kind: counterexample` candidate lines; waiting for a sweep to notice is how bad rules
survive. Daily sweep, capped at **8 rule-checks/run** (defers when over budget, never expands):
checks probation rules + any live rule unfired ≥14d + a random sample, asking "do recent sessions
violate this?". Provenance: a rule with `src_sessions: 1` is flagged in the weekly digest until
it refires. TTL is garbage collection only — 30d no-fire → demote — it is not the defence: a
blind timer kills good rules as readily as bad ones.

## Q5 — the validation hook

Not a checklist-in-head and not pre-commit: **a ledger plus targeted pre-action checks.** At task
close the agent appends `validation.jsonl` lines `{ts, session, rule, status: pass|fail|skip,
note}`; a fail forces rework or a waiver recorded with reason. Separately, forced checks for four
high-stakes classes only: external sends, destructive ops, promises of future work, config/
scheduler edits — this maps onto boundaries already written into the workspace. Enforcement,
said plainly: v1 enforces nothing at runtime, it audits — the evolve job flags closes where rules
existed but no validation lines were written, and the weekly digest surfaces unvalidated closes
and waivers. If the audit shows the pass isn't actually running, that's when a runtime gate gets
added. "Never skippable silently" needs a mechanism; this is the mechanism.

## Q6 — the one number

**Action-changing validations per week** (fail/revise entries): target **≥2/week by day 14**, with
**≥50% judged legitimate** on a human skim (below that, rules are noise or too strict). Zero after
two weeks = the layer is decorative — either the format is too vague to ever fail, or the pass
isn't running. Secondary guard: **≥50% of live rules fired at least once in the trailing 14d**
(below = triggers too abstract; tighten them). Anti-metric: rule count and candidate volume are
never success; keep promotion at ~1–3/week and treat faster growth as a red flag.

## Numbers I'd change

| what | yours | mine | why |
|---|---|---|---|
| live cap | 1200 chars / ~40 rules | 2500 chars / ~15–20 rules | your cap math is internally inconsistent |
| System-1 slice | ≤200 tok | ≤150 tok, top-5 by net confirmations | smaller, curated surface |
| live line | `ev`, `last` | add `cx` (counterexample count) | falsification visible at read time |
| candidates line | {id, ts, session, rule, evidence, source} | + `would_change`, `safety`, `kind` (rule\|dispute\|counterexample) | gate inputs must exist at surprise-time |
| new artifact | — | `validation.jsonl` + weekly digest | Q5 mechanism; aggregatable |
| gates | replay, contradiction, discrimination | refire, contradiction, safety (discrimination at capture) | cost, reproducibility, out-of-sample signal |
| lifecycle | live + decay | probation 14d → live; GC 30d no-fire; sweep ≤8 checks/run | blast-radius control |
| cadence | daily evolve job | daily, watermark-idempotent, standalone job + weekly ≤40-line digest | bounded cost, human margin |
| eval | — | ≥2 action-changing validations/wk by d14; ≥50% legit; ≥50% rules fired/14d | Q6 |

## Kept uncontested

Rules-not-prose; the directory layout; one shared file with a single promoter; safety changes
human-gated; daily cadence over real-time.

Round 2 should settle: the cap (mine vs yours) and enforcement level (audit-only v1 → runtime gate
only if the audit shows the pass isn't running).

— main