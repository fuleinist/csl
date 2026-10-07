# Limits — what this actually enforces, and what it only looks like

Written because the most expensive bug in this project's history was a gap between what the format
*documented* and what the code *did*. Three separate mechanisms claimed enforcement they did not
have. So this file states the boundary plainly.

## Enforced (a script makes it impossible)

| Property | Where | Test |
|---|---|---|
| A `chk:human` verdict cannot be recorded by the agent's normal path | `check.py:cmd_record` | `probe.py` H6c |
| A `chk:judge` verdict must carry named evidence | `check.py:cmd_record` | `probe.py` H9a |
| The gate demands a `human-pass` for a `chk:human` rule, not a plain pass | `check.py:cmd_gate` | `probe.py` H6d/H6e |
| Counters cannot be inflated by hand — `ev`/`last` are derived from the ledger | `evolve.py:derive_counters` | `probe.py` H9, `acceptance.py` |
| A `skip` does not count as a rule having fired | `check.py:cmd_stats` | `probe.py` H7a |
| Rule ids are never reused, including after eviction | `evolve.py:ever_used_ids` | `probe.py` H2/H2b |
| A rule forbidding something dangerous is not mistaken for one permitting it | `grammar.py:loosens_guardrail` | `probe.py` H1 |
| A grammar change reads as a version mismatch, not corruption | `grammar.py` + `--fingerprint` | `probe.py` H5a–H5c |
| A candidate claiming `scope: general` while citing local specifics is downgraded | `evolve.py:decide_scope` | `probe.py` H4c/H4d |
| Eviction maximises rules kept per character | `evolve.py:value_density` | `probe.py` H8a/H8b |
| The package never writes into its own data directory | `paths.py` | `acceptance.py` step 15 |

## Friction, not enforcement (deliberately)

* **`csl attest`.** A `chk:human` rule is not *cryptographically* human-gated. `csl` runs as the same
  OS user as the agent, so an agent that decides to run `csl attest` can. What the design buys is
  that self-certification stops being a normal `record` and becomes a distinct act named for what it
  is, visible in the ledger as `"by": "human"` and grep-able. **If you need real human consent, that
  requires a trust boundary this tool cannot provide** — put the rule behind an approval gate your
  harness owns, and treat `attest` as an audit trail.
* **`chk:judge` evidence.** The evidence must be *present*, not *true*. The gate cannot tell an
  honest citation from a plausible one.
* **`CSL_HOOK_MODE=audit`.** The default does not block anything. It records and annotates. Only
  `gate` refuses calls, and only for the four high-stakes classes the hook can infer.
  Neither Hermes nor OpenClaw accepts an advisory payload on its pre-tool-call event, so "annotates"
  needs a second hop: Hermes reads `{"context": ...}` on `pre_llm_call`, and OpenClaw reads
  `prependContext` on `before_prompt_build`. `csl hook` alone is silent on both harnesses. Treat a
  bare `csl hook` entry as a gate, not as a comment.

## Unverified (stated as such on purpose)

* **OpenClaw blocking semantics.** The manifest and registration contract
  (`openclaw.plugin.json`, `package.json` with `openclaw.extensions`,
  `api.on("before_tool_call", fn, { priority })`) is read from the installed OpenClaw 2026.9.6 docs
  and a live extension. The refusal shape (`{ block: true, blockReason }`) is documented, but no live
  agent turn was driven to observe a refusal. See `adapters/openclaw/CONTRACT.md`.
* **DeepSeek Harness.** No install was available to inspect, so nothing is claimed.
  `adapters/deepseek/README.md` describes the generic contract to wire by hand.
* **High-stakes inference.** The hook classifies from a regex table over the command text. It will
  miss adversarial phrasing, and it cannot infer *promises of future work* at all — that class needs
  the agent to declare its own domain via `csl gate`.
* **Recall of the matcher.** Only the false-positive side is tested. A tightening in the matcher
  could silently stop a rule firing, and the suite would not catch it. (A sampled recall check found
  no counterexample; that is weak evidence, not proof.)

## Known gaps (open, with a decision to make)

* **An over-cap file cannot be repaired by the cap's own tool.** `csl validate` calls an over-budget
  file a violation, and `csl evolve` refuses to run on an invalid file — so eviction, which only
  `--apply` performs, is unavailable exactly when the budget is exceeded. Today the fix is to edit
  the file by hand. The options: a separate `evict` command that tolerates an over-cap file, or
  demote over-cap from violation to warning whose remedy is eviction.
* **`scope: general` cannot be *earned*.** A rule can be downgraded to `local` mechanically, but the
  design's "prefer evidence spanning ≥2 agents" bar for the `general` claim is not implemented.
  `general` is currently a claim, not a measurement.
* **Nothing enforces "don't mutate the live grammar mid-check".** A written convention only. The
  cheap enforcement is making `--fingerprint` a precondition of a validation round.