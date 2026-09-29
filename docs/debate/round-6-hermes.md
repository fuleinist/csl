# Round 6 — Hermes: the human-gated tier was decorative, and the matcher fired on function words

Target: the runtime enforcement path (`cs_check.py`) — the part that decides whether a rule
actually acts, as opposed to whether it is stored well. Two real bugs, both reproduced before
fixing, both now asserted by the probe.

## RT-6.1 — `chk: human` was never enforced at runtime (found by Hermes; the serious one)

**Finding.** The design put a lot of work into human-gated rules: round 2 made them immune to
eviction and decay, and made the job REFUSE rather than evict when safety rules alone exceed the
cap. At **runtime, none of it exists** — `cs_check.py` never branches on `chk == "human"`
anywhere:

```
grep 'chk.*human' scripts/cs_check.py  ->  NO MATCHES
```

So `record` — the agent's own path — accepted a verdict for a human-gated rule, and `gate`
counted it. Reproduced end-to-end before fixing:

```
1) the AGENT records a pass for R-004 — a chk:human safety rule:
   logged 1 to validation.jsonl (0 fail)
   {"ts": "...", "session": "S-RT6-FORGERY", "domain": "writing any json state file",
    "rule": "R-004", "status": "pass", "note": "self-certified, no human involved"}

2) gate for a HIGH-STAKES domain needing R-004:
   exit: 0 (0 = NOT blocked)
   gate clear — 1 rule(s) recorded and passing for this session
```

The party the rule constrains certified its own safety rule, and the gate opened. **The protection
was on the wrong side of the system:** careful defence of a human rule's *storage* against
eviction, while its *verdicts* were forgeable by the constrained party.

**Fix.**
- `record` now **refuses** a `chk:human` verdict: *"this rule needs a HUMAN verdict, and `record`
  is the agent's path … an ordinary pass here would be self-certification."* Nothing is written.
- New `attest` subcommand logs status `human-pass` / `human-fail` with `by: human`; it refuses any
  non-human rule, so it cannot be used as a general bypass of the normal path.
- `gate` accepts **only** `human-pass` for a `chk:human` rule, and names the rule as needing a
  human verdict rather than silently demanding a pass.
- `derive_counters` treats `human-pass` as a pass and `human-fail` as an exercise (otherwise a
  human-approved rule would show `ev 0` and look stale); `stats` counts `human-fail` in the
  PRIMARY metric.

**Stated honestly, in the code and to the sibling:** this is **procedural friction, not a security
boundary.** The agent runs as the same OS user and can call `attest` itself. What the change buys
is that self-certification must be a deliberate act named for what it is and greppable as
`by: human`, instead of blending into ordinary passes where nobody would look. Claiming a security
property here would be worse than the bug — a same-user CLI cannot enforce human consent.

## RT-6.2 — the matcher fired on function words (found by Hermes)

**Finding.** `toks()` filtered only on length > 2, so `"any"`, `"the"`, `"for"` counted as content
tokens. A deployment task matched two rules that had nothing to do with it:

```
$ cs_check.py list --domain "deploying any new service to production"
   R-002  <- via "any"      (when: writing ANY *.json state file)
   R-004  <- via "service"  (when: a schema/version gate refuses to start a SERVICE)
```

R-004 is `chk: human`, so this compounded RT-6.1: an unrelated task demanded a recorded pass for a
human-gated safety rule, and (before the fix) the agent could satisfy it by self-certification.
Rules firing on unrelated work also destroys the meaning of the ledger — the one thing the whole
design treats as ground truth.

**Fix.** A `STOPWORDS` set (function words only) filters `toks()`, with an explicit fallback: if a
rule's `when` is *entirely* function words, fall back to raw tokens rather than let the rule go
permanently silent — silently dead rules are the failure this layer exists to prevent.

## RT-6.3 — my fix was incomplete, and the probe caught it (Hermes)

After the stopwords fix, `H6a` **still failed**: the deployment domain still matched R-004, now via
`"service"` — a single shared *content* noun. One common noun is not evidence that two tasks are
the same kind of work.

**Fix.** A rule must share `min(2, len(rule content tokens))` tokens with the domain. Self-scaling,
so there is no magic constant to tune: a second corroborating token is required, except for a rule
phrased so tightly it has only one content token to offer. After this, the deployment domain
matches nothing, and the real domain (`"writing a json state file before publish"`) still matches
R-002.

**The mirror risk is live and handed to the sibling.** Tightening matching trades false positives
for false *negatives*, and a false negative is the more dangerous direction: the rule is stored,
looks healthy, and never fires. I already found one myself — `R-001` ("reading a file under
`~/.openclaw` or `G:/dev/clawd`") no longer matches the domain `"json state file write before
publish"`, previously matched via `"file"` alone. I judge that *correct* (the domain genuinely has
nothing to do with the rtk wrapper), but it is precisely the class of change that silently disables
a rule. Round 6 asks the sibling to find a worse one.

## Regression (25 probe cases, all pass)

```
scripts/redteam_probe.py     25/25
  H6a  a deployment task no longer matches the json-state-file / version-marker rules
  H6b  a real domain still matches R-002
  H6c  `record` refuses a chk:human verdict and writes nothing (exit 1, ledger 4->4)
  H6d  the gate still BLOCKS a chk:human rule with no human verdict (exit 2)
  H6e  an attested human verdict DOES clear the gate (exit 0) — the human path works
  H6f  `attest` refuses a non-human rule (no general bypass)
  H6   ledger restored exactly — no probe residue in real evidence

validate   exit 0; --fingerprint: match (grammar v2, sig b72e9466bb2b)
evolve     exit 0; C-103 still refused + queued; post-write validate OK
gate smoke exit 2 blocked -> record -> exit 0 clear   (the mech path still works)
```

Note the grammar version did **not** change: `chk` is unchanged, and the new ledger status family
(`human-pass`/`human-fail`) is a ledger value, not a rule-line field. No migration needed.

## Sibling state at close

Round-6 brief delivered and confirmed in its UI (composer empty, message visible in the log). Its
round-3 turn is now ~25 minutes old with no artifact and no new assistant message since seq 76 —
it is still appending tool results (seq 99 → 105), so it is working, not hung, but two rounds have
passed without a deliverable from it. Round 7 checks that before anything else; if it is still
mute, the honest report is that this has become a single-agent review with a slow correspondent,
and the loop should say so rather than imply a live debate.

## Still open

- The `>=2 agents` evidence bar for `scope: general` is still unimplemented.
- `LOCAL_SPECIFICS` (round 4) and the new match threshold (round 6) are both heuristics; both trade
  one error class for another, and only the false-positive side is currently measured.
- `attest` is friction, not enforcement — the agent can still call it.
- Nothing gates the new "don't change a live artifact mid-round" rule.

— Hermes, round 6