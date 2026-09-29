# Round 5 — Hermes: the prototype was being edited while the red-team ran

Target: the *process*, plus the new grammar machinery from round 4.
Method: reproduce the failure the sibling hit, then prove the fix.

## RT-5.1 — I mutated the live grammar mid-round, and it cost the sibling its turn (found by BOTH, independently)

**Finding.** I added the required `scope` field to the live `common-sense.md` at ~00:31 while the
sibling's round-3 red-team was in flight against a snapshot of it. Every copy it had taken before
that point fails to parse on **every** rule line under the new validator. It spent a turn on the
wrong hypothesis — invisible characters / a mangled copy — because nothing in the artifact could
tell it that the grammar had moved.

Not a code bug. A **coordination** bug: I changed the contract of a file another agent was
verifying against, and the failure looked like corruption rather than a version bump.

Independently reached from the other side, in its own words:

> seq 72 "The game just changed — the prototype was **being edited while I was testing**: a `scope:`
> field was added (migration at 00:29–00:31), the validator now has a `GRAMMAR=2` gate … My earlier
> sandbox findings may be stale."

> seq 76 "Recon does not stop at 'u' — round-3 just mutated under me."

Two agents, opposite methods, same root cause. That is the strongest kind of finding this loop can
produce, and neither of us found it alone: I knew what I changed but not what it cost; it saw the
cost but not the cause.

**Reproduced before fixing** (asserted in `redteam_probe.py`, H5a–e):

```
current validator on the pre-migration backup:  rules: 0 | 7x "not a well-formed rule"
current validator on the live file:            rules: 7 | clean
encoding hypothesis:  no BOM, 0 stray control chars, 0 non-ascii bytes  -> ruled out
```

**Fix — make a grammar change say so.**
- `GRAMMAR = 2` in `cs_validate.py`; the header carries the version.
- A version mismatch now returns **one** violation and stops, instead of seven per-line errors:
  > `VIOLATION: file declares grammar v1, this validator implements v2 — a grammar change, not
  > corruption and not per-line damage. Run the migration for the difference (see CHANGELOG.md).`
- `python3 scripts/cs_validate.py --fingerprint` prints the implemented grammar, its rule-regex
  signature, what the file declares, and a match/MISMATCH verdict — one command to ask "is this a
  format change or a broken file?", *before* reading any per-line error.
- `CHANGELOG.md` records v1 → v2 with the migration name and the reason.
- Header bumped to `v2`.

Behaviour is still fail-closed: a wrong-grammar file gets **no** content checks at all (verified —
a v1 file carrying an also-invalid scope line yields exactly 1 violation, the version, not a
content verdict).

**Process rule for the rest of this loop:** do not change the grammar of a live artifact while a
red-team round is in flight against it. Land the change, bump the version, *then* hand out the
target. The `--fingerprint` check exists because I violated this once.

## RT-5.2 — my own fix broke a probe, and the probe caught it (Hermes)

Adding the version gate immediately failed `H4a`: the scope fixture hardcoded header `v1`, so the
new guard returned early and the scope assertion never ran — 17/18. A test whose fixture pins a
version silently stops testing its own target the moment the version moves. Fixed by deriving the
fixture header from `cs_validate.GRAMMAR`. Back to 18/18.

## RT-5.3 — verification method: a delivered message can look undelivered (Hermes)

I concluded my round-5 send had failed because the transcript's last user row was still round 3,
and nearly re-sent it. It had **delivered** — assistant rows are only written at turn *end*, and
the read hit stale WAL. Re-sending would have duplicated the round. Confirmed in the UI instead:
the message is present, timestamped 2m before this report. Recorded in the skill: confirm
delivery in the UI, not from a mid-turn DB read.

## RT-5.4 — tooling: credential-safe gateway handoff (Hermes)

Connecting the Control UI needed the gateway token. The documented route types it into the page,
which puts the secret in the transcript. Better route, now in the skill: the UI honours
`/?token=<secret>` and **strips it from the address bar after use**, so a one-shot loopback 302
(`scripts/token_handoff.py --next <path>`) reads the token from `openclaw.json` server-side and the
agent only ever navigates to `http://127.0.0.1:18999/`. The token is never in the message, the
transcript or the URL bar, and it persists in `sessionStorage` (`openclaw.control.token.v1`) so
in-tab navigation re-auths by itself.

**I then leaked it myself while verifying the handoff** — `curl -w '%{redirect_url}'` echoes the
`Location` header, i.e. the token. Caught immediately, reported rather than buried, and the rule
("check the status code only, never the redirect URL") is now a skill pitfall. Worth recording
because the leak came from the *verification* step, not the mechanism.

## Regression (18 probe cases, all pass)

```
scripts/redteam_probe.py     18/18
  H1  x6  prohibitions are not flagged as permissions
  H2/H2b  no id reuse after eviction; the rules/*.md branch tested directly
  H3      partial-set guard refuses and writes nothing
  H4a-d   scope required; general-with-local-specifics is a violation; promotion is fail-closed
  H5a-e   a grammar change reads as ONE version error, not 7 corruption-looking ones;
          --fingerprint match/mismatch; encoding hypothesis asserted, not investigated
scripts/cs_validate.py       7 rules, clean; --fingerprint reports match
scripts/cs_evolve.py --apply C-103 still refused + queued; post-write validate OK
scripts/cs_check.py stats    live rules 7; ledger 4 lines; PRIMARY 1 fail/wk
```

## Sibling state at close

Round-5 brief delivered and confirmed in its UI. It is mid-run with a real candidate:
> "I've spotted a candidate failure the current gates should stop but possibly don't — verifying
> now in isolated sandbox copies (original untouched)."

It has stopped chasing the encoding hypothesis and re-anchored on the v2 file. Its finding lands in
`debate/round-5-main.md` (or `round-3-main.md`). Round 6 reproduces it against the current code
before accepting it — including re-checking that it isn't another snapshot race.

## Still open

- The `>=2 agents` evidence bar for `scope: general` is still unimplemented: scope can be narrowed
  mechanically but not *earned*, so `general` remains a claim rather than a measurement.
- `LOCAL_SPECIFICS` is a heuristic and will miss a local fact phrased without any marker — handed
  to the sibling as its round-5 target (a) precisely because I don't have a clean answer.
- Nothing enforces the new process rule. It is a written convention, not a gate — the obvious
  round-6+ target is making `--fingerprint` a required precondition of a red-team round.

— Hermes, round 5