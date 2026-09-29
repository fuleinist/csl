#!/usr/bin/env python3
"""Evolve the common-sense layer: candidates -> gates -> live file.

    python3 cs_evolve.py            # dry run (default): print the decision table
    python3 cs_evolve.py --apply    # write live file + state.json (with backup)

Pipeline
    candidates.jsonl
      -> gate 1 safety      (a rule that loosens a guardrail is never auto-promoted)
      -> gate 2 contradiction (same trigger -> winner by ev, loser recorded and demoted)
      -> gate 3 discrimination (would this rule ever have changed an action?)
      -> promote ev:1
      -> decay   (live rule not confirmed in DECAY_DAYS -> dormant)
      -> cap     (over budget -> evict lowest value density)
      -> atomic write + backup + validate + report

Value density = ev / days_since_last_confirmed. Only *mechanically* confirmed rules
(ev incremented by cs_confirm.py) survive the decay sweep, so a rule nobody can check
ages out on its own.
"""
import argparse
import datetime
import json
import re
import shutil
import sys
from pathlib import Path

from .paths import CANDIDATES, HUMAN, LEDGER, ROOT, STATE
from .grammar import (  # noqa: E402
    HEADER,
    LIVE,
    LOCAL_SPECIFICS,
    LOOSEN,
    ROOT,
    contradiction_pairs,
    loosens_guardrail,
    norm_do,
    norm_when,
    parse,
)

RULES_DIR = ROOT / "rules"
REPORT_DIR = ROOT / "evolve"
DECAY_DAYS = 30
CAP_DEFAULT = 2500


def derive_counters(rules, ledger_path=LEDGER):
    """ev/last are DERIVED from validation.jsonl, never hand-maintained.

    ev   = number of `pass` lines      (the confidence counter)
    last = date of last *exercise*     (pass OR fail; `skip` does not refresh)

    last must key off exercise, not off passing: a rule that keeps catching violations on
    every run is doing its job, and keying decay off `last pass` would age out exactly the
    rules that are earning their place.
    """
    passes, exercised = {}, {}
    if Path(ledger_path).exists():
        for line in Path(ledger_path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            rid, status, ts = rec.get("rule"), rec.get("status"), rec.get("ts", "")[:10]
            if not rid or not ts:
                continue
            if status in ("pass", "fail", "human-pass", "human-fail"):
                exercised.setdefault(rid, []).append(ts)
            if status in ("pass", "human-pass"):
                passes.setdefault(rid, []).append(ts)
    for r in rules:
        ex = sorted(exercised.get(r["id"], []))
        r["ev"] = len(passes.get(r["id"], []))
        if ex:
            r["last"] = ex[-1]
    return rules


def safety_rules(rules):
    return [r for r in rules if r["chk"] == "human"]


def days_since(iso):
    try:
        return (datetime.date.today() - datetime.date.fromisoformat(iso[:10])).days
    except ValueError:
        return 10**6


def load_candidates(path=CANDIDATES):
    out, bad = [], []
    if not Path(path).exists():
        return out, bad
    for i, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except ValueError as exc:
            bad.append(f"line {i}: unparseable candidate ({exc})")
            continue
        if not rec.get("when") or not rec.get("do"):
            bad.append(f"line {i}: candidate missing when/do")
            continue
        out.append(rec)
    return out, bad


def gate_safety(cand):
    loosens, hit = loosens_guardrail(cand.get("do", ""))
    if loosens and cand.get("chk") != "human":
        return False, f"G1 safety: permits a guardrail bypass ({hit!r}) -> human-gated proposal only"
    return True, "G1 safety: pass"


def gate_discrimination(cand):
    wc = str(cand.get("would_change", "")).strip().lower()
    if wc in ("", "no", "false", "0", "n"):
        return False, "G3 discrimination: would never have changed an action -> drop"
    return True, "G3 discrimination: pass"


def gate_contradiction(cand, live):
    for r in live:
        if set(norm_when(cand["when"])) == set(norm_when(r["when"])):
            if norm_do(cand["do"]) == norm_do(r["do"]):
                return False, f"G2 contradiction: duplicate of live {r['id']} -> drop"
            if int(cand.get("ev", 1)) > r["ev"]:
                return True, f"G2 contradiction: outranks live {r['id']} (ev {r['ev']}) -> replace"
            return False, f"G2 contradiction: live {r['id']} keeps it (ev {r['ev']} >= candidate)"
    return True, "G2 contradiction: no collision"


def ever_used_ids():
    """Every id this layer has EVER allocated: live, dormant/evicted, and the ledger of last resort.

    Ids must never be reused. `next_id` only knowing about live+promoted meant an evicted
    R-004 (still on disk as rules/R-004.md) could be handed to a brand-new rule — two
    different rules sharing one id, across the live file and the dormant archive.
    """
    used = set()
    rules_dir = ROOT / "rules"
    if rules_dir.is_dir():
        used |= {p.stem for p in rules_dir.glob("R-*.md")}
    if STATE.exists():
        try:
            used |= set(json.loads(STATE.read_text(encoding="utf-8")).get("ever_used", []))
        except (ValueError, OSError):
            pass
    return used


def decide_scope(cand):
    """``(scope, note)`` for a promoted candidate. Fail-closed on purpose.

    A candidate defaults to `local` and may only claim `general` if it explicitly says so AND
    cites nothing machine-specific — silence must never be read as "this generalises". The
    round-1 bar for `general` was evidence spanning >=2 agents, which is not implemented, so
    nothing else may widen scope. Extracted from main() so it is testable: inline logic in the
    promotion loop was unverifiable except by mutating the live layer.
    """
    scope = str(cand.get("scope", "local")).strip().lower() or "local"
    note = f"scope {scope}"
    if scope == "general":
        m = LOCAL_SPECIFICS.search(f"{cand.get('when', '')} {cand.get('do', '')}")
        if m:
            return "local", f"scope downgraded general->local ({m.group(0)!r})"
    return scope, note


def next_id(live, promoted):
    used = {r["id"] for r in live} | {p["id"] for p in promoted} | ever_used_ids()
    for n in range(1, 10000):
        rid = f"R-{n:03d}"
        if rid not in used:
            return rid
    raise RuntimeError("id space exhausted")


def value_density(rule):
    """Value per CHARACTER, decayed by staleness.

    The budget being spent is characters, so the denominator has to contain characters. `ev / age`
    never looked at length, so a 400-char rule with ev 3 outranked a 60-char rule with ev 1 — and
    eviction then killed the terse rule first, freeing 60 of the ~300 characters needed. It had to
    delete MORE rules than necessary to get back under the cap, and verbose rules were subsidised
    at the cost of terse ones. Value per character is what "density" means for a size budget.
    """
    return rule["ev"] / max(1, days_since(rule["last"])) / max(1, len(rule_line(rule)))


def rule_line(r):
    """Render ONE rule line. Single source of truth: `value_density` must measure the same string
    the cap is spent on, or the two drift apart and eviction optimises the wrong quantity."""
    return (
        f"- {r['id']} | when: {r['when']} | do: {r['do']} | chk: {r['chk']} "
        f"| scope: {r.get('scope', 'local')} | ev: {r['ev']} | last: {r['last']}"
    )


def render(header_v, cap, rules, today):
    lines = [f"<!-- common-sense v{header_v} | cap {cap} | rules {len(rules)} | updated {today} -->"]
    lines.extend(rule_line(r) for r in rules)
    return "\n".join(lines) + "\n"


def atomic_write(path, text):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = ap.parse_args()

    today = datetime.date.today().isoformat()
    header, live, viol = parse()
    hard = [v for v in viol if v.startswith("VIOLATION")]
    if hard:
        print("refusing to evolve: the live file is already invalid")
        for v in hard:
            print(" ", v)
        return 1

    cands, bad = load_candidates()
    decisions, promoted, rejected, human_queue = [], [], [], []

    for cand in cands:
        cid = cand.get("id", "?")
        if any(norm_do(cand["do"]) == norm_do(r["do"]) for r in live) or any(
            norm_do(cand["do"]) == norm_do(p["do"]) for p in promoted
        ):
            decisions.append((cid, "drop", "duplicate action already represented"))
            rejected.append(cid)
            continue
        ok = gate_safety(cand)
        res = ok[1] if not ok[0] else None
        if ok[0]:
            ok = gate_contradiction(cand, live)
            res = ok[1] if not ok[0] else None
        if ok[0]:
            ok = gate_discrimination(cand)
            res = ok[1] if not ok[0] else None
        if not ok[0]:
            decisions.append((cid, "drop", res))
            rejected.append(cid)
            if res.startswith("G1"):
                # a guardrail-loosening candidate is never dropped silently: it queues for a human
                human_queue.append({"queued": today, "candidate": cand, "reason": res})
            continue
        reasons = [gate_safety(cand)[1], gate_contradiction(cand, live)[1], gate_discrimination(cand)[1]]
        rid = next_id(live, promoted)
        scope, scope_note = decide_scope(cand)
        rule = {
            "id": rid,
            "when": cand["when"],
            "do": cand["do"],
            "chk": cand.get("chk", "mech"),
            "scope": scope,
            "ev": 1,
            "last": today,
        }
        promoted.append(rule)
        decisions.append((cid, "promote", f"{rid} <- {'; '.join(reasons + [scope_note])}"))

    working = list(live) + promoted
    derive_counters(working)

    # decay: a live rule nobody confirmed recently goes dormant.
    # chk:human rules are human-owned — machine decay does not touch them.
    dormant = []
    kept = []
    for r in working:
        if (
            r["id"].startswith("R-")
            and r["chk"] != "human"
            and days_since(r["last"]) > DECAY_DAYS
            and r not in promoted
        ):
            dormant.append(r)
        else:
            kept.append(r)
    working = kept

    # cap: evict the lowest value density until the rendered file fits.
    # chk:human rules are eviction-immune — a budget algorithm must never delete a guardrail.
    cap = header["cap"] or CAP_DEFAULT
    evicted = []
    safety_ids = {r["id"] for r in safety_rules(working)}
    cap_error = None
    while len(render(header["v"], cap, working, today)) > cap:
        pool = [r for r in working if r["id"] not in safety_ids and r not in promoted]
        if not pool:
            only = render(header["v"], 10**9, safety_rules(working), today)
            cap_error = (
                f"over cap {cap} with only chk:human rules left: {len(safety_rules(working))} "
                f"safety rules render to {len(only)} chars. Refusing to evict a guardrail — "
                "raise the cap and get a human decision."
            )
            break
        victim = min(pool, key=value_density)
        working.remove(victim)
        evicted.append(victim)

    text = render(header["v"], cap, working, today)
    fits = len(text) <= cap

    print(f"candidates: {len(cands)}   live before: {len(live)}   live after: {len(working)}")
    for cid, action, why in decisions:
        print(f"  [{action:7}] {cid}: {why}")
    for r in dormant:
        print(f"  [dormant] {r['id']}: unconfirmed {days_since(r['last'])}d")
    for r in evicted:
        print(f"  [evict  ] {r['id']}: over cap {cap}")
    for b in bad:
        print(f"  [bad    ] {b}")
    if human_queue:
        print(f"  [HUMAN  ] {len(human_queue)} guardrail-loosening candidate(s) queued — not dropped:")
        for h in human_queue:
            print(f"            {h['candidate'].get('id')}: {str(h['candidate'].get('do'))[:70]}")
    print(f"render: {len(text)} chars (cap {cap}) -> {'fits' if fits else 'OVER CAP'}")

    if cap_error:
        print(f"\nREFUSING: {cap_error}")
        return 1

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply.")
        return 0

    # RMW with backup, then validate what we wrote
    if LIVE.exists():
        shutil.copy2(LIVE, LIVE.with_suffix(".md.bak-" + today))
    atomic_write(LIVE, text)

    if human_queue:
        q = ROOT / "proposals"
        q.mkdir(exist_ok=True)
        with (q / "human.jsonl").open("a", encoding="utf-8") as fh:
            for h in human_queue:
                fh.write(json.dumps(h) + "\n")

    RULES_DIR.mkdir(exist_ok=True)
    for r in dormant + evicted:
        (RULES_DIR / f"{r['id']}.md").write_text(
            f"---\nid: {r['id']}\nstatus: dormant\nwhen: {r['when']}\ndo: {r['do']}\n"
            f"ev: {r['ev']}\nlast_confirmed: {r['last']}\ndormant_since: {today}\n---\n\n"
            "Left the live layer (decay/eviction). Promote again only with fresh evidence.\n",
            encoding="utf-8",
        )

    STATE.write_text(
        json.dumps(
            {
                "version": header["v"],
                "cap_chars": cap,
                "updated": today,
                "live": [r["id"] for r in working],
                "promoted": {p["id"]: p for p in promoted},
                "dormant_since": {r["id"]: today for r in dormant},
                "evicted": [r["id"] for r in evicted],
                "rejected": rejected,
                "ever_used": sorted(
                    ever_used_ids() | {r["id"] for r in working} | {p["id"] for p in promoted}
                ),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    REPORT_DIR.mkdir(exist_ok=True)
    (REPORT_DIR / f"{today}.md").write_text(
        f"# common-sense evolve — {today}\n\n"
        + f"- candidates read: {len(cands)}\n- promoted: {len(promoted)} "
        + f"({', '.join(p['id'] for p in promoted) or 'none'})\n"
        + f"- dropped: {len(rejected)} ({', '.join(rejected) or 'none'})\n"
        + f"- dormant: {len(dormant)} ({', '.join(r['id'] for r in dormant) or 'none'})\n"
        + f"- evicted: {len(evicted)} ({', '.join(r['id'] for r in evicted) or 'none'})\n"
        + f"- live size: {len(text)}/{cap} chars\n\n## decisions\n"
        + "\n".join(f"- {cid}: {action} — {why}" for cid, action, why in decisions)
        + "\n",
    )

    from .grammar import parse as reparse  # re-read from disk, do not trust the write

    h2, r2, v2 = reparse()
    hard2 = [v for v in v2 if v.startswith("VIOLATION")]
    print("post-write validate: " + ("OK" if not hard2 else f"{len(hard2)} violations"))
    for v in hard2:
        print(" ", v)
    return 1 if hard2 else 0


if __name__ == "__main__":
    sys.exit(main())