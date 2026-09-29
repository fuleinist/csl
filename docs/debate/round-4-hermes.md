# Round 4 — Hermes red-team finding: `scope` was agreed, then silently lost

Target: the prototype *and* the settled design docs, not just the code.
Method: compare what round 1 agreed against what round 2 shipped.

## RT-4.1 — a mechanism both sides agreed on vanished in consolidation (found by Hermes)

**Finding.** Round 1's rebuttal proposed a `scope` field with a rule attached:

> `scope: general` rules prefer evidence spanning ≥2 agents where available; agent-specific
> rules carry `scope: <agent>` and are read only by that agent.

By round 2 it was gone — from the sibling's own settled position, from my consolidated
`FINAL-DESIGN.md`, and from the prototype.

```
REBUTTAL-main.md   (round 1):  "scope: general` rules prefer evidence spanning >=2 agents ..."
FINAL-main.md      (round 2):  grep -c scope = 0
FINAL-DESIGN.md    (mine):     grep -c scope = 0
common-sense.md line fields:   when, do, chk, ev, last        <- no scope
cs_validate.py / cs_evolve.py / cs_check.py: no scope logic
```

**Expected vs actual.** Expected: the settled design carries every agreed mechanism, or the
drop is recorded. Actual: the field disappeared from three documents at once without either
agent noticing, so nothing downstream could enforce it — and nothing did.

**Why it matters.** This is the drift the whole design was written to prevent, and it is
load-bearing for exactly one property: telling a **general judgment rule** apart from a
**machine-local fact**. Without it those are identical to every gate. The promotion gates
cannot falsify a local fact — replay, refire and the falsification sweep all re-observe the
same machine, so a rule that is only true here passes every test forever, accumulates `ev`,
and crowds out real rules. That is precisely how a "thin layer" decays into a second memory
file, which is the failure mode `common-sense.md` was introduced to avoid.

The second-order lesson is worth more than the field: **round 1's rebuttal is the most
mechanism-dense artifact in this debate, and consolidation is where mechanisms die.** A
final-design doc that is a summary rather than a superset silently drops constraints. That
is a process bug, not a code bug, so the fix is in the artifact the code is generated from.

**Fix.**
- `scope` is now a **required** field on every rule line, validated by the `RULE` regex —
  a line without it is "not a well-formed rule", not a default.
- `cs_validate.LOCAL_SPECIFICS` flags machine specifics (drive paths, `~`, `/c/`, the `rtk`
  wrapper, product names, `localhost`, "here"). A rule declaring `scope: general` that cites
  any of them is a **hard violation**, not a warning.
- Promotion is **fail-closed** in `cs_evolve.decide_scope()`: absent scope → `local`; a
  `general` claim that cites local specifics is downgraded to `local` with the reason
  recorded in the decision log. Silence must never be read as "this generalises", and since
  the round-1 evidence bar (≥2 agents) is not implemented, nothing else may widen scope.
- `scripts/migrate_add_scope.py` migrates pre-existing rules by **test, not by hand**, with a
  backup and a post-write validate. Result on the 7 seeded rules:

```
R-001 -> local    (~/)                R-005 -> local    (here)
R-002 -> general  (no local specifics)  R-006 -> local  (OpenClaw)
R-003 -> general  (no local specifics)  R-007 -> general(no local specifics)
R-004 -> general  (no local specifics)
```

**3 of 7 seeded rules were machine-local and published as general.** That is the drift,
already present in the seed corpus, and it was invisible before this field existed.

**Second bug found while fixing it.** My first migration read `when`/`do` via `cs_validate.parse()`
— which now *requires* a scope field, so it rejected exactly the pre-migration lines the
script existed to fix. It would have silently done nothing. Fixed by parsing the raw line.
Worth recording because the failure mode is quiet: a no-op migration that reports success.

**Third fix.** `decide_scope()` was originally inline in `main()`, so the fail-closed path
was unverifiable except by mutating the live layer. Extracted to a function and covered
directly.

## Regression (13 probe cases, all pass)

```
scripts/redteam_probe.py   13/13 pass
  H1  x6  prohibitions are not flagged as permissions
  H2      no id reuse after eviction
  H2b     the rules/*.md branch is tested directly, not via state.json
  H3      partial-set guard refuses and writes nothing
  H4a     general rule citing a local path = hard violation
  H4b/H4c candidate with no scope -> local; general claim w/ local specifics -> downgraded
  H4d     an honest general claim survives untouched
scripts/cs_validate.py      7 rules, no hard violations
scripts/cs_evolve.py --apply  scope survives the render round-trip; C-103 still refused+queued;
                              post-write validate OK
scripts/cs_check.py stats    PRIMARY 1 fail/wk (target >=2 by d14); SECONDARY 3/7 = 42%
ls rules/ probe-live.md      no residue
```

## Still open

- The `>=2 agents` evidence bar for `scope: general` is still not implemented — scope can be
  narrowed mechanically but not *earned*. `general` is currently a claim, not a measurement.
- `LOCAL_SPECIFICS` is a heuristic. It will miss a local fact phrased without any of its
  markers ("the default shell mangles redirects" — true only here, cites nothing local).
- The sibling's round-3 finding had not landed when this round closed (its session was at 67
  events and climbing, so it is working, not stalled). Round 5 reproduces it before accepting
  it.

— Hermes, round 4