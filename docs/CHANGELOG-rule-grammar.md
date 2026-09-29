# common-sense rule-grammar CHANGELOG

The header line of `common-sense.md` carries the grammar version:

```
<!-- common-sense v2 | cap 2500 | rules 7 | updated 2026-09-30 -->
```

**Bump the version on ANY change to the field set of a rule line, and add an entry here plus a
migration.** Before touching the grammar of a live file, check whether a red-team round or any
external verifier is working against a snapshot of it — a field added mid-round makes every
rule line fail to parse for them, which reads as file corruption rather than a format change.
Run `python3 scripts/cs_validate.py --fingerprint` before concluding anything about per-line
errors.

## v2 — 2026-09-30 — required `scope` field

- **Added** `scope` ∈ `general` | `local` | `<agent>` as a **required** field, placed between
  `chk:` and `ev:`.
- **Why:** without it a general judgment rule and a machine-local fact are indistinguishable to
  every gate. The gates cannot falsify a local fact — replay, refire and the falsification
  sweep all re-observe the same machine — so a rule true only here passes forever, accumulates
  `ev`, and crowds out real rules. That is how a "thin layer" decays into a second memory file.
  The field was agreed in debate round 1 and then silently dropped from both sides' settled
  design documents, so it is now enforced rather than assumed.
- **Migration:** `python3 scripts/migrate_add_scope.py [--apply]` — classifies by test
  (`local` when `when`/`do` cite drive paths, `~`, `/c/`, the `rtk` wrapper, product names,
  `localhost`, "here"), backs up as `common-sense.md.bak-scope-<date>`, backs nothing else up
  and rewrites atomically.
- **Migration result:** 4 rules `general` (R-002/3/4/7), 3 rules `local` (R-001/5/6) — i.e.
  3 of the 7 seeded rules were machine-local and had been published as general.
- **Validator:** a `scope: general` rule citing local specifics is now a hard violation;
  promotion is fail-closed (`cs_evolve.decide_scope`: absent → `local`; an unearned `general`
  claim is downgraded with the reason logged). The round-1 bar for `general` — evidence
  spanning ≥2 agents — is **not implemented**, so `general` is a claim, not a measurement.

## v1 — initial — `when` / `do` / `chk` / `ev` / `last`

- Fields: `when`, `do`, `chk` ∈ `mech|judge|human`, `ev` (pass count), `last` (last exercise).
- `ev`/`last` are **derived** from `validation.jsonl` by `cs_evolve.derive_counters()` — never
  hand-written — and `last` tracks the last *exercise* (pass or fail), not the last pass, so a
  rule that keeps catching violations does not age out for doing its job.