# Round 9 — Hermes: the sibling's silence was my error, and `chk:judge` is decorative too

Target: my own delivery/verification path (found broken), and the last unenforced `chk` tier.

## RT-9.1 — four rounds of "unanswered briefs" were briefs that never arrived (found by Hermes, my error)

**Finding.** My round-5 and round-6 briefs **never reached the sibling's transcript**:

```sql
select count(*) from transcript_events where session_id=? and event_json like '%ROUND 5%';  -> 0
select count(*) from transcript_events where session_id=? and event_json like '%ROUND 6%';  -> 0
```

Neither did round 9 (0 rows). They appeared in the chat pane and I reported them as "DELIVERED +
confirmed in UI". The pane renders an **optimistic local echo** the moment Enter is pressed; the
transcript is the only proof of receipt. The mechanism: it was mid-turn the whole time, so my
messages were queued client-side, and **stopping the stuck run discarded the queue**.

**The compounding error is the important part.** In round 5 I noticed the transcript showed no new
user row, and I dismissed it — because in an earlier round I had written this into my own skill:

> "A chat message can be delivered while the DB still shows the previous turn. Assistant rows are
> written at turn *end*; the UI updates sooner. Before resending, check the UI (or wait)."

That rule is wrong, and it is what caused the failure it was meant to prevent: it told me to prefer
the UI over the database for the one question the database uniquely answers. Assistant rows are
written at turn end — that part is true, and it is why a mid-turn read shows no *reply*. It says
nothing about whether *my message* arrived. I generalised a true fact about replies into a false
rule about receipts. Corrected in the skill: receipt is proven by the transcript, with the exact
query, and queued-while-active messages are flagged as lost-on-stop.

**Cost:** rounds 5–8 were run as a single-agent review while I believed I was corresponding. Every
report in that window said the sibling was "working, not hung" and implied a live exchange. The
sibling was never given those targets. It did nothing wrong.

**Second correction.** I also described the run as possibly stalled. Evidence at the time:

```
newest event 265s old, on its ~5-minute cadence          <- alive
last assistant message 00:36:20, turn then ~33 min old   <- silent
workspace mtimes: cs-r3final-A/ and cs-r3final-B/ touched at 01:10:25  <- REAL work
```

The empty-payload events were not noise — they coincided with real file activity, so the run was
genuinely working and I interrupted live work when I stopped it at 01:13. "Alive but outputless" is
a real state, and workspace mtimes were better evidence of progress than event counts. Both facts
are now pitfalls in the skill.

## RT-9.2 — `chk: judge` was decorative too (found by Hermes)

Same class as round 6's `chk:human` hole, one rung milder. The design defines `judge` as "cheap
model, decides from **named evidence**". `cs_check.py` mentioned `judge` **zero** times — only
`cs_validate.py`'s grammar accepted it. Reproduced:

```
$ cs_check.py record --session S-H9 --domain "stale duplicate completions" --results "R-007=pass"
logged 1 to validation.jsonl (0 fail)
  {"rule": "R-007", "status": "pass", "note": ""}      <- R-007 is chk:judge
```

A verdict with **no evidence at all** was accepted for a rule whose entire purpose is to require
evidence. So of the three tiers the design defines, two (`human`, `judge`) existed only in the
grammar, and `mech` — the one that needs no judgement — was the only one actually enforced. The
layer's rigour lived entirely in its format.

**Fix.** `record` refuses a `chk:judge` verdict with an empty note:

> `R-007: chk:judge — this verdict must cite NAMED EVIDENCE (what was examined). A bare pass cannot
> be checked later, which is the point of the judge tier: "R-007=pass:re-read the job log for
> session 4bd171bb".`

`H9c` guards against over-tightening: a `chk:mech` rule still accepts a bare verdict. Like the
`human` fix, this is a check on the *record*, not a judgement of evidence quality — it makes an
empty verdict impossible, not a dishonest one. Stated that way on purpose.

## Regression (36 probe cases, all pass)

```
scripts/redteam_probe.py     36/36
  H9a  chk:judge refuses a bare verdict with no named evidence (exit 1, ledger 4->4)
  H9b  chk:judge accepts a verdict that cites evidence
  H9c  chk:mech still accepts a bare verdict (no over-tightening)
  H9   ledger restored exactly

validate   exit 0
evolve     exit 0
residue    none
```

## Sibling state at close (01:20)

- Run **stopped by me at 01:13** (`Stop generating` gone, send control restored) to unstick the
  queue — which, as it turned out, destroyed the queued briefs rather than draining them.
- Round-9 brief sent at 01:19: `session_nodes.updated_at` for the dashboard key moved to 01:19:34,
  so the gateway accepted it — but `transcript_events` still shows no row and **no turn has
  started**. Receipt therefore remains *unconfirmed* at close.
- Its own artifacts survive: 6 sandbox directories (`cs-r3-sandbox`, `cs-r3-sandbox2`,
  `cs-r3final-A/B`, `cs-rt3-repro`, `cs-rt3-repro-B`), ~250 files, in `G:/dev/clawd`. **Reported,
  not deleted** — they are another agent's work, and the workspace convention is ask-first for
  anything destructive. They are inert now that its run is stopped.

## Round 10 plan

Two things, in this order:
1. Check whether the round-9 brief finally landed (transcript query, not the pane). If it did and a
   finding arrives, reproduce it against the current code before accepting it.
2. Close the debate honestly: a consolidated statement of what the exchange actually produced
   (rounds 1–2 were a genuine two-agent design; rounds 3–9 were my own red-teaming with a
   correspondent that was, for four of those rounds, never sent the briefs), plus the open items
   and the fact that `debate/` contains no `main` artifact beyond `REBUTTAL-main.md`/`FINAL-main.md`.
   Round 10 is the last one, so the report should stand on its own.

## Still open

- RT-8.2: an over-cap file cannot be repaired by the cap's own tool — needs a design decision.
- The `>=2 agents` evidence bar for `scope: general` is still unimplemented.
- `attest` is friction, not enforcement (RT-6.1); the `judge` fix checks presence, not honesty.
- Nothing gates the "don't mutate a live artifact mid-round" rule (RT-5.1).
- Recall of both heuristics is sampled, not measured (RT-7.2).
- The 6 stray sandbox directories await a decision from the user.

— Hermes, round 9