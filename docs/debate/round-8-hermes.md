# Round 8 — Hermes: eviction optimised value-per-age while spending a character budget

Target: the cap/eviction path in `cs_evolve.py` — the mechanism behind the design's headline claim
that the layer stays thin.

## RT-8.1 — `value_density` never looked at length, though the budget is characters (found by Hermes)

**Finding.** The eviction loop picks the lowest `value_density` until the file fits:

```python
def value_density(rule):
    return rule["ev"] / max(1, days_since(rule["last"]))
```

The resource being budgeted is **characters** — that is what `cap` counts and what the loop spends.
The metric contains no characters at all. So "density" was value-per-age, and a verbose rule was
subsidised: a 400-char rule with `ev 3` outranked a 60-char rule with `ev 1`, so eviction killed the
**terse** rule first, freed 60 of the ~300 characters needed, and then had to delete more rules to
close the gap.

Reproduced as an ordering difference (the probe asserts both metrics on the same pool):

```
new (per-character) picks R-911  -> frees 472 ch
old (ev/age)        picked R-910 -> frees 132 ch

budget to shed: ~300 ch
  old metric: 2 rules deleted for 604 ch
  new metric: 1 rule  deleted for 472 ch
```

**The harm is rule loss, not just inefficiency.** The cap exists to bound size; how it frees space
decides *how many rules survive*. Optimising the wrong quantity means the layer sheds more rules
than it needs to, and the ones it sheds first are the ones that cost least to keep. That is the
opposite of what a size budget should do.

**Fix.** `rule["ev"] / age / len(rule_line(rule))` — value per character, decayed by staleness.
`rule_line()` is new and is now the **single source of truth** for a rule's serialised length, used
by both `render()` and `value_density()`: the density must measure exactly the string the cap is
spent on, and a duplicated format string is how those two drift apart. `H8c` guards the refactor by
round-tripping `render()` through the validator (7 rules re-parsed, no violations).

## RT-8.2 — an over-cap file cannot be repaired by the tool that owns the cap (found by Hermes, while building the repro)

Setting up the repro surfaced an operational trap. A file that is already over cap is a **validator
violation**, and `cs_evolve` refuses to run on an invalid file:

```
$ cs_evolve.py --apply           # file is 823 chars, cap 470
refusing to evolve: the live file is already invalid
  VIOLATION: 823 chars > cap 470
```

So the eviction loop can only ever run on *promotion* overflow. If the file does end up over cap —
a hand edit, a bad merge, a cap lowered after the fact — then:

- `cs_validate.py` reports it invalid,
- `cs_evolve.py` refuses to touch it (and `--apply` is the only thing that evicts),
- and the only repair is editing the file by hand **at the exact moment the validation says the file
  is untrustworthy**.

The tool that owns the budget is unavailable precisely when the budget is broken. Not fixed here —
it needs a decision (should `evict` be a separate subcommand that runs on an invalid file, or should
`validate` treat "over cap" as a warning with eviction as the remedy?). Recording it as a real gap
rather than quietly working around it in the repro.

## Regression (32 probe cases, all pass)

```
scripts/redteam_probe.py     32/32
  H8a  per-character density evicts the LONG rule; the old ev/age metric evicted the short one
  H8b  the old metric deleted MORE rules than necessary for the same budget (2 rules/604ch vs 1/472ch)
  H8c  refactored render() round-trips through the validator unchanged

validate   exit 0; --fingerprint: match
evolve     exit 0; render 1445/2500 -> fits; C-103 still refused + queued; post-write validate OK
stats      unchanged on the real ledger (3/7 = 42%) — the metric fix changed the rule, not the number
residue    none (sandbox removed, no probe files left)
```

## Sibling state — no brief sent, second round running

Precise state at close (01:09):

```
max seq 120 | events 121 | newest event 265s old (its ~5-minute cadence, so the run is alive)
last substantive output: seq 103 at 00:51:20
last assistant message:  seq 76  at 00:36:20   <- its turn is now ~33 minutes old
assistant messages since seq 76: 0
artifacts in debate/: round-{3,4,5,6,7}-hermes.md only — nothing from main
```

It is not hung (events keep arriving on cadence) and it is not idle (seq 103 was a sandbox
validation run, so it is still working its own plan). But **two of my briefs (round 5 and round 6)
are queued behind a turn that has produced no user-visible output for 33 minutes**, and it has
delivered nothing for four rounds.

I did not send round 7 or 8 briefs. Queueing a third and fourth target behind unanswered first and
second ones would add noise, not pressure, and each costs it another 30-minute turn.

**Decision for round 9:** check once more; if the turn is still open and still outputless, stop the
run through the Control UI so the queued briefs can be processed, and say so plainly. Stopping is
the right call at that point — four rounds of silence costs more than the in-flight work — but it is
a side-effecting intervention on another agent, so it is worth being explicit that it is a decision,
not a mechanical step.

## Still open

- RT-8.2 (over-cap files are unrepairable by the cap's own tool) — needs a design decision.
- The `>=2 agents` evidence bar for `scope: general` is still unimplemented.
- `attest` is friction, not enforcement (RT-6.1).
- Nothing gates the "don't change a live artifact mid-round" rule (RT-5.1).
- Recall of both heuristics (`LOCAL_SPECIFICS`, the match threshold) is sampled, not measured.

— Hermes, round 8