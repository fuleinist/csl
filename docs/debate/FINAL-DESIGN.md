# common-sense.md — final design (Hermes + OpenClaw, 2 rounds, settled)

Status: **design settled, prototype running.** Live dir `G:/dev/clawd/common-sense/`.
Round 1 `PROPOSAL-hermes.md` / `REBUTTAL-main.md`; round 2 `FINAL-main.md`.

## What this is

Not a memory file. It is a **rule store + validation ledger + sweep process**. The file is
read-mostly and small; the *ledger* is what accumulates the evidence. Two consumers:

- **Validation** — read on demand at task close, before anything high-stakes goes out.
- **System-1** — a derived ≤150-token slice of the top rules, never hand-maintained.

## What it is not

- Not a knowledge base. Skills hold procedures, memory holds facts, **common-sense holds
  judgment heuristics and validity checks**. Overlap resolves by that rule, not by who wrote last.
- Not always-on. Calling it the top injection target and leaving it always-in-context can't
  both stand — the file is read on demand; only the derived slice is always present.
- Not prose. Prose common sense is unverifiable, uncompactable and unmergeable across agents.

## Settled config

**Form.** One rule per line, atomic and falsifiable. A rule that would never have changed an
action is a note, not common sense.

```
- R-002 | when: writing any *.json state file | do: back up first, then rewrite-validate, never in-place edit | chk: mech | scope: general | ev: 2 | last: 2026-09-28
```

`chk` ∈ `mech` (scripted predicate over the tool log — no model self-report) · `judge` (cheap
model, named evidence) · `human` (Chris decides).

`scope` ∈ `general` | `local` | `<agent>` — **required**, and the field that keeps this layer from
becoming a second memory file. A rule that holds only on this machine cannot be falsified by the
gates (replay, refire and the sweep all re-observe the same box), so it would live forever and
crowd out real rules. A `scope: general` rule citing local specifics (drive path, `~`, the `rtk`
wrapper, a product name, `localhost`, "here") is a hard validation violation; promotion is
fail-closed — no declared scope means `local`, and a `general` claim that cites local specifics is
downgraded with the reason logged. The round-1 bar for `general` — evidence spanning ≥2 agents —
is **not yet implemented**, so `general` is currently a claim, not a measurement.

**Budget.** Hard cap **2500 chars / ~15–20 rules**, enforced by the job, measured on the
rendered file. *Hermes conceded the cap:* the original 1200 chars ≈ 9 rules at 110–160
chars/rule, not the ~40 claimed. **`chk: human` rules are immune to eviction and decay**; if
safety rules alone exceed the cap the job **refuses and escalates** — a budget algorithm must
never delete a guardrail. *This was not hypothetical:* at cap 1200 the prototype evicted `R-004`,
the human-gated safety rule, purely on value density.

**Ownership.** One shared file, one promoter. Both agents append candidates; **only the evolve
job writes live** — no editorial self-promotion. Disputes are filed as candidate lines, never as
private forks; per-agent copies diverge immediately, so there are none.

**Capture — two paths, two trust levels.** Every surprise costs a tool call, so a single eager
path starves by week 2:
- *inline* (`src: inline`) — minimal 3 fields `when` / `do` / `would_change`; the discriminating
  field is only answerable at the moment of surprise, which is why it is captured there.
- *sweep* (`src: sweep`) — the daily job mines session transcripts for candidates nobody captured.
  Lower trust: must clear refire **and** falsification.

**Promotion — gate pair, then probation.**
1. **refire** (positive, out-of-sample): ≥2 sightings across sessions. Replay is cut — it re-reads
   the same distribution and LLM verdicts aren't reproducible; a refire is ground truth.
2. **falsification** (negative): no counterexamples since capture. Refire alone only proves the
   observation *recurs* — a confidently wrong generalisation recurs too. Neither is a gate alone.
3. **safety**: a candidate that loosens a guardrail never auto-promotes; it lands in
   `proposals/human.jsonl`, never silently dropped.
4. **contradiction**: same trigger → winner by `ev`, loser quarantined with the reason recorded.
5. **probation 14d**, one counterexample → back to candidates.

**Check + fire counting — one mechanism.** `cs_check.py` is the only counter. `record` writes
`validation.jsonl` and nothing else; the live file's `ev`/`last` are **derived from the ledger**,
so there is no hand-maintained number to inflate. No rule counts as fired without a ledger line;
no ledger line without an explicit pass/fail/skip verdict.
- `ev` = pass count. `last` = last **exercise** (pass *or* fail) — a rule that keeps catching
  violations is doing its job, and keying decay off `last pass` would age out exactly the rules
  earning their place. *(OpenClaw caught this bug in my implementation; fixed.)*
- A close with no `record` call is an **unvalidated close**, counted by the job.

**Enforcement — split, not uniform.** The four high-stakes classes — external sends, destructive
or irreversible ops, promises of future work, config/scheduler edits — are **runtime-gated from
day 1** (`cs_check.py gate`, non-zero exit = stop/rework), because an audit after the send has
already left the machine, and that boundary is already in the workspace charter. Everything else
is audit-only in v1. A procedural gate with no violation audit is theatre, so the sweep flags
high-stakes actions with no gate line.

**Decay / calcification**, ranked honestly: falsification > contradiction > provenance > human
skim > TTL. TTL is garbage collection only — a blind timer kills good rules as readily as bad ones.
30d unexercised → dormant into `rules/<id>.md`, never deleted.

**Cadence.** Daily, watermark-idempotent, standalone job (not a chat session). Weekly digest
≤40 lines. RMW + backup + re-validate after write, same discipline as `pr-loop-state.json`.

## Layout (live)

```
common-sense/
  common-sense.md        live layer, cap 2500, 7 rules — the thin layer
  candidates.jsonl       append-only captures (+ would_change, safety, src)
  validation.jsonl       the ledger — the only fire counter
  state.json             counters, promotion/eviction log
  proposals/human.jsonl  guardrail-loosening candidates awaiting a human
  rules/<id>.md          dormant/evicted rules, with the reason
  evolve/YYYY-MM-DD.md   per-run report
  scripts/cs_validate.py char cap, ids, contradictions, safety lint, staleness, unconfirmed
  scripts/cs_evolve.py   capture → gates → probation → decay → cap → atomic write
  scripts/cs_check.py    list | record | stats | gate
```

## Metrics (the only numbers that count)

- **Primary:** action-changing validations/week — **≥2 by day 14**, ≥50% judged legitimate.
  Zero after two weeks means the layer is decorative: either the format is too vague to ever
  fail, or the pass isn't running.
- **Secondary:** ≥50% of live rules exercised in the trailing 14d.
- **Anti-metric:** rule count and candidate volume are never success. Promotion 1–3/week;
  faster growth is a red flag.

## Verified this session

`cs_validate.py` clean; `cs_evolve.py` promoted 2, dropped the duplicate, refused the
guardrail-loosening candidate and **queued it for a human** instead of dropping it; counters
derived from the ledger; `cs_check.py gate` returned **exit 2 blocked → record → exit 0 clear**,
and a `fail` kept it blocked until rework; post-write validate OK.

## Not built yet (go-live list)

refire across sessions · the falsification sweep · the ≤150-token slice writer · probation
timer · transcript mining for `src: sweep` · schedule the daily job · per-session gate wiring.