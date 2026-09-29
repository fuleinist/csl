# Round 7 — Hermes: the dead-rule detector could be silenced by skipping rules

Target: the metrics in `cs_check.py stats` — the numbers that decide whether the layer is working.
One real bug, one honest negative result.

## RT-7.1 — a `skip` counted as a "fire", so the metric could be satisfied without validating anything (found by Hermes)

**Finding.** `cmd_stats` computed the SECONDARY metric as "live rules that appear anywhere in the
ledger", including `skip` lines. A `skip` means *the rule did not apply* — it is the one status that
carries no evidence the rule works. Counting it as a fire means the measurement designed to detect
dead rules can be silenced by declaring those rules irrelevant. Reproduced:

```
BEFORE   SECONDARY live rules fired in trailing 14d: 3/7 = 42%  [target >=50%]
         never fired in 14d: R-004, R-005, R-006, R-007

$ cs_check.py record --session S-H7 --domain "misc" \
    --results "R-005=skip:did not apply;R-006=skip:did not apply;R-007=skip:did not apply"
logged 3 to validation.jsonl (0 fail)

AFTER    SECONDARY live rules fired in trailing 14d: 6/7 = 85%  [target >=50%]
         never fired in 14d: R-004
```

**42% → 85%, from three lines whose entire content is "this rule did not apply", recorded against
the domain `"misc"`.** The layer's own success criterion (≥50% of live rules firing) was met
without a single validation. This is the most dangerous class of bug in this whole design: the
design treats the ledger as ground truth, and a metric that can be met without doing the work
converts the ledger into a *record of activity* rather than a record of verification. Every
downstream decision — which rules are dead, which get evicted for never earning their place — is
made from these numbers.

**Fix.**
- `EXERCISED = ("pass", "fail", "human-pass", "human-fail")`; only these count as fired. `skip`
  is explicitly excluded, with the reason in the code.
- Skips are surfaced rather than dropped: `skipped in 14d (NOT counted as fired): R-005, R-006,
  R-007`. "We skipped it" should be visible, not flattering.
- A skip-only session no longer counts toward `sessions with a validation pass` — a session where
  nothing was exercised is not a session with a validation pass.

## RT-7.2 — I probed the *other* direction and found nothing (negative result, reported as such)

Round 6 tightened matching and I flagged the mirror risk: a false negative silently disables a
rule, and that is the more dangerous direction. So this round I attacked it directly — for every
live rule I wrote a **paraphrased** realistic domain (not the rule's own `when`, which would match
trivially) and asked whether the rule still fires:

```
R-001  "read the openclaw config file"                     -> matches
R-002  "rewrite the state json after backing it up"        -> matches
R-003  "check whether my merged PR is in the repo"         -> matches
R-004  "the version gate blocked startup"                  -> matches
R-005  "the shell output has text"                         -> matches
R-006  "is the openclaw agent serving the discord channel"  -> matches
R-007  "a background job sent the same completion again"   -> matches
```

**7/7.** No rule was disabled by the round-6 threshold, so there is no fix to make and no test to
add here — the invariant "a rule still matches a realistic paraphrase of its own trigger" is a
one-off measurement, not a regression guard, because the paraphrases are judgment calls rather than
derived values. Reporting it as a negative result rather than dressing it up: the tightening looks
safe on recall, but one sampled paraphrase per rule is weak evidence, and the honest statement is
"no counterexample found", not "no false negatives exist".

## Incidentally observed, from my own round-6 fix

`record` now refuses a `chk:human` rule, and the refusal is **set-wide**: trying
`R-004=skip` alongside three mech rules refused all four. A `skip` is not a verdict, so arguably it
should be permitted for a human rule — but refusing is fail-closed, and the alternative (allowing
the agent to write *any* status for a human-gated rule) reopens the hole RT-6.1 closed. Keeping the
refusal; recording it here so the trade-off is deliberate rather than accidental.

## Regression (29 probe cases, all pass)

```
scripts/redteam_probe.py     29/29
  H7a  recording 3 skips does NOT raise the fired percentage  (42% -> 42%)
  H7b  skips are surfaced separately, not silently dropped
  H7c  a skip-only session does not count as a validation pass
  H7   ledger restored exactly

validate   exit 0; --fingerprint: match
evolve     exit 0; post-write validate OK
gate smoke exit 2 blocked -> record -> exit 0 clear; a chk:human verdict still refused (exit 1)
real stats SECONDARY still 3/7 = 42% on the real ledger — the fix changed the *rule*, not the number
```

## Sibling state at close — no brief sent this round, on purpose

Its round-3 turn is now ~30 minutes old. It is **not hung** — the newest transcript event moved
99 → 105 → 108 and was written 3 minutes before this round started — but it has produced no
artifact for three rounds, and my round-6 target remains unanswered.

I did **not** send a round-7 brief. The loop's step 3 exists to keep the exchange moving; piling a
fourth target onto a correspondent still working through the third would add noise, not pressure,
and each brief costs it a 30-minute turn. The useful thing to report is the state, not another
message. Round 8 re-checks: if it has answered, I hand it the new target (the skip-metric fix is a
good one — "can you meet the ≥50% target without validating?" is exactly its kind of question); if
it is still mute, the honest conclusion is that rounds 3–10 are a single-agent review with a slow
correspondent, and the loop should say that rather than imply a live debate.

## Still open

- The `>=2 agents` evidence bar for `scope: general` is still unimplemented.
- Recall of the matcher (and of `LOCAL_SPECIFICS`) is sampled, not measured — false negatives are
  now explicitly the *less* tested direction.
- `attest` is friction, not enforcement (RT-6.1, unchanged).
- Nothing gates the "don't change a live artifact mid-round" rule from RT-5.1.
- PRIMARY ("≥2 fails/week") is presumably inflatable by recording spurious fails; not examined yet.

— Hermes, round 7