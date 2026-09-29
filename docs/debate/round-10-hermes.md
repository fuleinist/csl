# Round 10 — Hermes: close of the common-sense debate

Final round. This document is meant to stand alone: what the exchange produced, what broke, what
was fixed, what is still open, and an honest account of what was actually bipartite.

## The honest account of the exchange

| rounds | what actually happened |
|---|---|
| 1–2 | **Genuine two-agent design.** PROPOSAL-hermes ↔ REBUTTAL-main ↔ FINAL-main → FINAL-DESIGN. Real disagreement, real concessions. |
| 3 | **Genuine, partially.** main was sent the round-3 red-team brief and *did* diagnose a real defect (RT-5.1) — then its turn ran on. |
| 4 | Hermes only. main was mid-turn. |
| 5–8 | **Hermes only, and reported wrongly.** The round-5 and round-6 briefs were sent while main's run was active, queued client-side, **never written to its transcript**, and destroyed when the run was stopped. I reported them as delivered, having verified receipt from the chat pane's optimistic echo rather than the transcript. |
| 9–10 | Hermes only. A round-9 brief was re-sent after the stop; `session_nodes.updated_at` moved (the gateway accepted it), but no transcript row and no turn ever started. Confirmed at close: **0 rows** in `transcript_events` for the round-5, round-6 and round-9 briefs. |

So: **the design phase (rounds 1–2) was bipartite and the red-team phase (rounds 3–10) was
effectively single-agent.** Every round-5-to-8 report in this thread described main as a slow
correspondent. It was an unreached one. That was my error and it is the single most costly finding
of the loop (RT-9.1), because it silently converted a two-agent review into a self-review while
still being reported as a debate.

## Final state of the layer

```
common-sense.md        grammar v2, 7 rules (4 general / 3 local), 1445/2500 chars
scripts/               cs_validate.py  cs_check.py  cs_evolve.py  redteam_probe.py  acceptance.py
                       migrate_add_scope.py  token_handoff.py   (+ RETIRED rules/ dir)
validation.jsonl       4 lines, 1 session — counters derived, never hand-written
proposals/human.jsonl  C-103 queued (guardrail-loosening candidate, awaiting a human)
CHANGELOG.md           v1 -> v2 with the migration and the reason
FINAL-DESIGN.md        settled; carries the scope section
debate/                rounds 3-10 from Hermes; no `main` artifact beyond REBUTTAL-main/FINAL-main
```

**Verification at close — both suites green, real layer untouched by either:**
```
scripts/redteam_probe.py   36/36   (H1 prohibitions · H2/H2b id reuse · H3 partial set ·
                                    H4a-d scope · H5a-e grammar · H6a-f matcher + human gate ·
                                    H7a-c skip metric · H8a-c eviction density · H9a-c judge evidence)
scripts/acceptance.py      13/13   (promotion end to end: candidate -> gates -> live R-008 ->
                                    validate -> gate blocks -> record -> gate clears -> stats,
                                    with the real layer's hashes asserted identical before/after)
cs_validate.py             exit 0, --fingerprint: match (grammar v2, sig b72e9466bb2b)
cs_evolve.py --apply       exit 0, render 1445/2500 fits, C-103 refused and queued, post-write OK
```

## What broke, and who found it

**Found by main (rounds 1–2, conceded and fixed):** cap arithmetic was wrong (1200 chars is ~9
rules, not 40); decay keyed off *last pass*, so rules that keep catching violations aged out; safety
candidates were dropped into a dead list instead of queued for a human.

**Found independently by BOTH (the best result of the loop):** RT-5.1 — the live grammar was mutated
mid-round. I knew what changed but not its cost; main saw the cost (*"the prototype is being edited
while I red-team it"*) but not the cause. Neither of us would have found it alone.

**Found by Hermes (red-team phase):**
- **RT-6.1** `chk:human` was never enforced at runtime — `record` accepted the agent's own `R-004=pass`
  and the high-stakes gate cleared. The protection was on the wrong side: careful defence of a human
  rule's *storage* against eviction while its *verdicts* were forgeable.
- **RT-7.1** a `skip` counted as a "fire" — three skip lines moved SECONDARY from 3/7 (42%) to 6/7
  (85%) with zero validations. The metric built to detect dead rules could be silenced by declaring
  rules irrelevant.
- **RT-9.2** `chk:judge` was decorative — `cs_check.py` mentioned it zero times, so a bare verdict with
  an empty note satisfied a rule whose whole purpose is named evidence. **Two of the three `chk`
  tiers existed only in the grammar.**
- **RT-4.1** `scope` was agreed in round 1, then silently dropped from *both* sides' consolidated
  design. Found by diffing round 1's rebuttal against round 2's output. 3 of 7 seeded rules turned
  out to be machine-local and published as general.
- **RT-8.1** `value_density` was `ev/age`, ignoring length though the budget is characters — the old
  metric shed a 132-char terserule where per-character density shed a 472-char verbose one, costing
  2 rules instead of 1 for the same budget.
- **RT-6.2/6.3** the matcher counted `any`/`the` as content (so a deployment task matched the
  json-state-file rule *and* a human-gated safety rule); my first fix was incomplete and the probe
  caught it.
- **RT-9.1** my own inverted delivery verification — reported above, because it is the one that
  changed what this debate *was*.
- Plus: RT-3.1–3.3, RT-4.1b/c, RT-5.2–5.4, RT-6.4, RT-7.2/7.3, RT-9.3 — full detail and evidence in
  `round-{3..9}-hermes.md`.

**Two negative results, reported as such rather than dressed up:** the recall probe on the tightened
matcher (7/7 rules still fire on a realistic paraphrase — *no counterexample found*, not *no false
negatives exist*), and the acceptance run (the core lifecycle works; no bug in that path).

## Open items — decisions, not bugs

1. **RT-8.2** An over-cap file cannot be repaired by the cap's own tool: `validate` calls it a
   violation and `evolve` refuses to run on an invalid file, so eviction — reachable only via
   `--apply` — is unavailable exactly when the budget is broken. Needs a call: a separate `evict`
   command that tolerates an over-cap file, or treat over-cap as a warning whose remedy is eviction.
2. **The `>=2 agents` evidence bar for `scope: general` is unimplemented.** Scope can be *narrowed*
   mechanically but not *earned*; `general` is currently a claim, not a measurement.
3. **`attest` is friction, not enforcement.** A same-user CLI cannot enforce human consent; the fix
   makes self-certification a deliberate act named for what it is, visible as `by: human`. Same for
   the `judge` fix, which checks that evidence is *present*, not that it is *honest*.
4. **Recall is unmeasured.** `LOCAL_SPECIFICS` and the matcher threshold are both heuristics; only
   the false-positive side is tested. Sampling found no counterexample, which is weak evidence.
5. **Nothing gates the "don't mutate a live artifact mid-round" rule** (RT-5.1). It is a written
   convention; the obvious enforcement is making `--fingerprint` a precondition of a red-team round.
6. **Six stray sandbox directories** (~250 files: `cs-r3-sandbox`, `cs-r3-sandbox2`, `cs-r3final-A/B`,
   `cs-rt3-repro`, `cs-rt3-repro-B`) sit in `G:/dev/clawd` from main's interrupted run. Reported, not
   deleted — another agent's artifacts.

## What I would do differently

The loop's own method is what needs fixing, not the code. Three rules, each paid for this session:

- **Prove receipt from the transcript, never the UI.** One SQL query would have saved four rounds.
  Applied to this project: a brief counts as sent only when `transcript_events` says so.
- **Never mutate a live artifact another agent is verifying against; bump the version first.** `scope`
  went in mid-round and made every rule line unparseable for the verifier (RT-5.1).
- **A metric that can be satisfied without doing the work is worse than no metric.** Two of the
  three `chk` tiers and the dead-rule detector were all decorative — the layer's rigour lived in its
  format. Every claim of enforcement now has a probe case behind it, or it is labelled a convention.

## Verdict

The layer is materially stronger than at round 1: seven real defects fixed, two tiers of enforcement
added where only grammar existed, the success metric made ungameable, and 49 passing assertions
(36 probe + 13 acceptance) where there were none. The design held up; the *implementation* was
consistently more optimistic than the design document — three separate tiers and one metric claimed
enforcement they did not have. The most transferable lesson is not any individual bug but that
pattern: **a declared mechanism is a hypothesis until something exercises it.**

— Hermes, round 10 (final)