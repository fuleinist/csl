# Round 3 — Hermes red-team findings (2 bugs, both fixed and proven)

Target: the running prototype in `G:/dev/clawd/common-sense/`.
Method: a probe script (`scripts/redteam_probe.py`) that asserts the gates' intended
behaviour, run BEFORE the fix to reproduce and AFTER to prove closure. It exits non-zero
when any hypothesis fails, so it is a regression test, not a demonstration.

## RT-3.1 — the safety lint flagged prohibitions as permissions (found by Hermes)

**Finding.** `LOOSEN`, the regex deciding whether a rule "loosens a guardrail", matched on a
bare dangerous token with no regard for negation. A rule that *forbids* the dangerous thing
was therefore classified as the dangerous thing.

**Repro (before the fix):**
```
python3 scripts/redteam_probe.py
[FAIL] H1 'never pass --force on this repo'
[FAIL] H1 'refuse to skip the backup'
[FAIL] H1 'do not bypass the approval gate'
```

**Expected vs actual.** Expected: these are the SAFEST rules in the corpus, so no flag.
Actual: all three matched `LOOSEN`, so `gate_safety` (G1) would refuse them auto-promotion
and push them to `proposals/human.jsonl` as guardrail-loosening candidates.

**Why it matters.** Exactly backwards, and self-defeating: the more safety-conscious a rule
is, the more likely it is quarantined as a threat. Over time the live layer would fill with
the rules that *mention* danger least carefully and the explicit prohibitions would rot in
a human queue nobody reads. This is a silent, structural inversion of the safety gate —
the worst class of bug here, because it makes the layer less safe the more it is used.

**Fix.** `cs_validate.loosens_guardrail(text) -> (bool, matched)`: a match only counts when
no negation precedes it **in the same clause**, within 60 chars. Clause-scoping is the point
— a naive whole-string negation check would let `"don't worry, just pass --force"` through,
because that sentence contains `don't` before `--force`. Splitting on `, . ; : — but then`
puts the permission in its own clause with no negation, so it is still caught.
`cs_validate`'s lint and `cs_evolve.gate_safety` both call it; the lint now reports the
matched text so a reviewer sees *what* tripped it.

**Evidence after the fix.** 7/7 probe cases pass — the three prohibitions no longer flag,
and the three genuine permissions still do. `C-103` (`skip the confirmation and force it
through with --force`) is still caught, now with the specific match quoted
(`'skip the confirm'`) instead of a bare "loosens a guardrail".

## RT-3.2 — rule ids were reusable after eviction (found by Hermes)

**Finding.** `next_id()` only knew about live and promoted rules. An evicted rule is not
live — it moves to `rules/<id>.md` as dormant — so its id went straight back into the pool.

**Repro (before the fix):**
```
python3 scripts/redteam_probe.py
[FAIL] H2 next_id must skip an id that has a dormant rules/ file
        got R-004; rules/R-004.md already exists
```

**Expected vs actual.** With live `R-001..R-003` and `rules/R-004.md` on disk, the next
promotion must get `R-005`. Actual: `R-004`.

**Why it matters.** Two different rules would share one id — the new live `R-004` and the
dormant `rules/R-004.md` archive would both claim it. Every derived counter keys off the id:
`validation.jsonl` lines, `ev`, `last`, the dormant file, the promotion log. One reused id
silently blends a dead rule's evidence into a live one's, which is precisely the failure the
ledger was built to make impossible. It also corrupts any later resurrection of the dormant
rule, which is the whole point of keeping the archive.

**Fix.** `ever_used_ids()` — the union of live, promoted, `rules/*.md` on disk, and an
`ever_used` list now persisted in `state.json`. `next_id()` allocates above that, so ids are
monotonic for the lifetime of the layer and never recycled. `state.json` records `ever_used`
on every apply, making the ledger the fallback when the dormant file is gone for any reason.

**Evidence after the fix.** Probe H2 passes (`R-005` allocated while `rules/R-004.md` exists);
the probe now deletes its own test file so it leaves no residue (`ls rules/` is empty after a
run).

## Regression after both fixes

```
scripts/redteam_probe.py        9/9 pass
scripts/cs_validate.py          7 rules, only soft UNCONFIRMED (no hard violations)
scripts/cs_evolve.py --apply    4 candidates -> 0 promoted (all dups/known), C-103 still
                                refused and queued for a human, post-write validate OK
scripts/cs_check.py gate        exit 2 blocked -> record -> exit 0 clear
ls rules/                       empty (no probe residue)
state.json ever_used            R-001..R-007
```

Neither fix regressed the gate, the cap, the queue, or the counters.

## RT-3.3 — the partial-set guard was untested code (found by Hermes, closed in-round)

Claimed in round 2 as "record refuses partial sets", but nothing exercised it. A guard with
no test is a comment. Added H3: drives the real CLI with `--results "R-002=pass:R-003=fail:x"`,
asserts a non-zero exit and that the ledger is byte-identical afterwards (it backs up and
restores `validation.jsonl`, so the probe never pollutes real evidence). Result: exit=1,
0 lines written.

Also added H2b, which asserts `ever_used_ids()` directly for the `rules/*.md` branch.
Without it, H2 would pass on `state.json`'s `ever_used` alone and the on-disk scan could be
deleted by a future refactor with no test failing.

## Still open (specified but unexercised — no repro, so not claimed as bugs)

- probation timer, refire, and the falsification sweep are specified but unimplemented, so
  nothing in the prototype exercises the 14-day probation tier.
- The `UNCONFIRMED` warning is soft (exit 0). If it is meant to block, it does not.
- `next_id` is linear and `ever_used` grows monotonically; fine at R-042, unproven at R-999.

— Hermes, round 3