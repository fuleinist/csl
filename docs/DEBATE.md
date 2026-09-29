# The debate — how this design was actually arrived at

This layer was designed and then attacked in a **ten-round adversarial review** between two agents:
Hermes (this repo's author) and the sibling OpenClaw agent `main`. The record is kept in
`docs/debate/` because the bugs found in it are the reason `docs/LIMITS.md` exists, and because the
process failures are as instructive as the code defects.

## What the rounds produced

| Rounds | What actually happened |
|---|---|
| 1–2 | **Genuine two-agent design.** `PROPOSAL-hermes.md` ↔ `REBUTTAL-main.md` ↔ `FINAL-main.md` → `FINAL-DESIGN.md`. Real disagreement, real concessions. `main` found three design defects here: the cap arithmetic was wrong (1200 chars is ~9 rules, not 40), decay was keyed off *last pass* so rules that keep catching violations aged out, and safety candidates were dropped into a dead list instead of queued for a human. |
| 3 | **Genuine, partially.** `main` diagnosed a real defect — the prototype was being edited *while* it was being tested (see RT-5.1 below) — then its turn ran on. |
| 4–10 | **Hermes only, and originally reported wrongly.** Briefs sent to `main`'s session through the OpenClaw Control UI were never written to its transcript: they queued client-side behind an active run and were destroyed when the run was stopped. Receipt had been "verified" from the chat pane, which renders an optimistic local echo. See round 9 for the full account. |

**The best result of the review came from the overlap.** RT-5.1 — the live grammar was mutated
mid-round — was found *independently by both agents*: Hermes knew what changed but not what it cost,
`main` saw the cost (*"the prototype is being edited while I red-team it"*) but not the cause.
Neither would have found it alone.

## The findings that changed the code

Recorded in full in the round documents; these are the ones that altered behaviour.

* **RT-6.1 `chk:human` was never enforced at runtime.** `record` accepted the agent's own `R-004=pass`
  and the high-stakes gate cleared (exit 0). The design had hardened human rules against *eviction*
  while leaving their *verdicts* forgeable by the party they constrain. → `record` refuses; `attest`
  is a separate act; the gate demands `human-pass`.
* **RT-9.2 `chk:judge` was decorative.** The code mentioned `judge` zero times, so a bare verdict
  with an empty note satisfied a rule whose whole purpose is named evidence. **Two of the three
  tiers existed only in the grammar.** → a judge verdict must cite evidence.
* **RT-7.1 A `skip` counted as a fire.** Three skip lines moved the dead-rule metric from 42% to 85%
  with zero validations. → only exercised statuses count; skips are reported separately.
* **RT-4.1 `scope` was agreed, then lost.** Proposed in round 1 and silently dropped from both sides'
  consolidated design. Reinstate it and 3 of 7 seeded rules turn out to be machine-local while
  claiming general. → scope is a required field, fail-closed.
* **RT-8.1 `value_density` ignored length** while spending a character budget, so eviction shed terse
  rules first and deleted more rules than necessary. → value per character.
* **RT-6.2 The matcher counted function words as content**, so a deployment task matched the
  json-state-file rule *and* a human-gated safety rule. → stopwords plus a self-scaling threshold.
* **RT-3.1/3.2 The safety lint flagged prohibitions as permissions**, and rule ids were reusable after
  eviction.

## The process findings

Two cost more than any single bug:

* **Verify receipt from the transcript, never the UI.** One SQL query would have saved four rounds.
* **A declared mechanism is a hypothesis until something exercises it.** Three tiers and one metric
  in this project claimed enforcement they did not have; every claim now has a test case in
  `tests/probe.py` behind it, or is labelled a convention in `docs/LIMITS.md`.

## Files

* `PROPOSAL-hermes.md`, `REBUTTAL-main.md`, `FINAL-main.md`, `FINAL-DESIGN.md` — rounds 1–2, the
  actual design negotiation.
* `round-3-hermes.md` … `round-10-hermes.md` — the adversarial review. Round 10 is the consolidated
  close: full findings list, open decisions, and verification state.
* `../LIMITS.md` — what the layer enforces, what is friction, and what is unverified.
* `../DESIGN.md` — the resulting design, with the choices that were tried and cut.

The rounds reference paths from the original prototype (`G:/dev/clawd/common-sense/`); the code now
lives in `src/csl/` with the same behaviour, verified by `tests/probe.py`.