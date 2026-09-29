#!/usr/bin/env python3
"""The single mechanism behind both the validation pass and the fire metric.

  python3 cs_check.py list --domain "json state file write"
  python3 cs_check.py record --session discord:1553... --domain "json state file write" \
      --results "R-002=pass;R-003=skip:not-applicable"
  python3 cs_check.py stats

Why one CLI: "the rules fired this week" is only measurable if the act of checking is the
same act that increments the counter. `record` writes validation.jsonl and nothing else —
the live file's `ev`/`last` are *derived* from that ledger by cs_evolve.py. So there is no
hand-maintained counter to inflate, no rule counts as fired without a ledger line, and no
ledger line without an explicit pass/fail/skip verdict.

A close with no `record` call is an "unvalidated close" — cs_evolve.py counts those.
"""
import argparse
import datetime
import json
import re
import sys
from pathlib import Path

from .grammar import parse
from .paths import LEDGER, LIVE, ROOT  # noqa: F401
STATUSES = ("pass", "fail", "skip")
# Statuses that mean the rule was actually exercised. `skip` is NOT one of them — see cmd_stats.
EXERCISED = ("pass", "fail", "human-pass", "human-fail")
HIGH_STAKES = (
    "external send, publish or post",
    "destructive or irreversible operation",
    "a promise of future work",
    "config or scheduler edit",
)


# Function words carry no domain signal. Without this list, "any" in "deploying any new
# service" matched R-002 ("writing any *.json state file") and "service" matched R-004, so the
# matcher fired rules that had nothing to do with the task — and, in the gate path, demanded a
# recorded pass for them.
STOPWORDS = frozenset("""
the and for any are not with that this from into its his her our your their was were will would
can could should must may might has have had been being does did doing but out off over under
then than when where which who whom whose why how all each both few more most other some such
only own same too very just about after again against because before below between during above
once here there while these those them they she him you yourself myself itself
""".split())


def toks(s, keep_stop=False):
    ws = re.sub(r"[^a-z0-9 ]", " ", s.lower()).split()
    out = {w for w in ws if len(w) > 2 and (keep_stop or w not in STOPWORDS)}
    if not out and not keep_stop:
        # Every token was a function word (e.g. a rule phrased "the way this is done"). Fall back
        # to the raw tokens rather than let the rule go permanently silent — silently dead rules
        # are the exact failure this layer exists to prevent.
        return {w for w in ws if len(w) > 2}
    return out


def matching_rules(domain, rules):
    """Rules whose `when` shares enough CONTENT with the task domain.

    Threshold is `min(2, len(rule content tokens))` — self-scaling, no magic constant to tune:
    a rule needs a second corroborating token, except when it is phrased so tightly that it only
    has one content token to give. Overlap >= 1 was too weak: "service" alone (a domain-generic
    noun) fired R-004 for an unrelated deployment task, and in the gate path that demanded a
    recorded pass — including for a chk:human rule the task had nothing to do with.
    """
    d = toks(domain)
    scored = []
    for r in rules:
        rt = toks(r["when"])
        if not rt:
            continue
        overlap = len(d & rt)
        if overlap >= min(2, len(rt)):
            scored.append((overlap, r))
    scored.sort(key=lambda p: (-p[0], p[1]["id"]))
    return [r for _, r in scored]


def by_id(rules):
    return {r["id"]: r for r in rules}


def cmd_list(args):
    _, rules, viol = parse()
    hard = [v for v in viol if v.startswith("VIOLATION")]
    if hard:
        for v in hard:
            print(v)
        return 1
    hits = matching_rules(args.domain, rules)
    if not hits:
        print("no live rule matches this domain")
        return 0
    print(f"check these before closing ({len(hits)} match):")
    for r in hits:
        print(f"  {r['id']} [chk:{r['chk']}]  {r['do']}")
    forced = [h for h in HIGH_STAKES if toks(h) & toks(args.domain)]
    if forced:
        print("\nHIGH-STAKES class matched -> runtime gate, not audit:")
        for h in forced:
            print(f"  ! {h}")
    return 0


def cmd_record(args):
    _, rules, _ = parse()
    known = {r["id"] for r in rules}
    rid_to_rule = by_id(rules)
    ts = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    written, bad = [], []
    for chunk in args.results.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        rid, _, verdict = chunk.partition("=")
        rid, verdict = rid.strip(), verdict.strip()
        status, _, note = verdict.partition(":")
        status = status.strip().lower()
        if re.match(r"^R-\d{3}\s*=", note.strip()):
            bad.append(
                f"{rid}: note looks like another result token ({note.strip()[:40]!r}) — "
                "separate entries with ';', not ':'"
            )
            continue
        if status not in STATUSES:
            bad.append(f"{rid}: bad status {status!r} (want {'/'.join(STATUSES)})")
            continue
        if rid not in known:
            bad.append(f"{rid}: not a live rule")
            continue
        if rid_to_rule[rid]["chk"] == "human":
            # The party being constrained must not be able to certify its own safety rule.
            bad.append(
                f"{rid}: chk:human — this rule needs a HUMAN verdict, and `record` is the "
                f"agent's path. Escalate to proposals/human.jsonl for the decision, then log it "
                f"with `attest`. (An ordinary pass here would be self-certification.)"
            )
            continue
        if rid_to_rule[rid]["chk"] == "judge" and not note.strip():
            # `judge` means "a cheap model decides, citing NAMED EVIDENCE". Nothing enforced that,
            # so a bare `R-007=pass` was accepted and the tier was decorative — the same class of
            # bug as the chk:human hole, one rung milder: the evidence requirement was never
            # checked, and a verdict with no evidence cannot be re-examined later.
            bad.append(
                f"{rid}: chk:judge — this verdict must cite NAMED EVIDENCE (what was examined). "
                f'A bare pass cannot be checked later, which is the point of the judge tier: '
                f'"{rid}=pass:re-read the job log for session 4bd171bb".'
            )
            continue
        written.append(
            {
                "ts": ts,
                "session": args.session,
                "domain": args.domain,
                "rule": rid,
                "status": status,
                "note": note.strip(),
            }
        )
    if bad:
        print("refusing to record a partial set:")
        for b in bad:
            print("  ", b)
        return 1
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as fh:
        for rec in written:
            fh.write(json.dumps(rec) + "\n")
    n_fail = sum(1 for r in written if r["status"] == "fail")
    print(f"logged {len(written)} to {LEDGER.name} ({n_fail} fail)")
    if n_fail:
        print("FAIL forces rework, or a waiver with a reason recorded in the completion report")
    return 0


def load_ledger():
    if not LEDGER.exists():
        return []
    out = []
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def cmd_attest(args):
    """Log a HUMAN verdict for a chk:human rule (status `human-pass` / `human-fail`).

    Deliberately separate from `record`. A rule whose whole purpose is to make a human decide
    must not be satisfiable through the agent's routine path — round 6 proved that it was: the
    agent recorded ``R-004=pass`` and the high-stakes gate went straight to exit 0.

    This is procedural friction, NOT a security boundary: the agent runs as the same OS user and
    could invoke this too. What it buys is that self-certification has to be a deliberate act
    named for what it is, visible in the ledger as ``by: human``, instead of blending into
    ordinary passes where nobody would ever notice.
    """
    _, rules, _ = parse()
    rid_to_rule = by_id(rules)
    ts = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    written, bad = [], []
    for chunk in args.results.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        rid, _, verdict = chunk.partition("=")
        rid = rid.strip()
        status, _, note = verdict.partition(":")
        status = status.strip().lower()
        if rid not in rid_to_rule:
            bad.append(f"{rid}: not a live rule")
            continue
        chk = rid_to_rule[rid]["chk"]
        if chk != "human":
            bad.append(f"{rid}: chk:{chk} — `attest` is only for chk:human rules; use `record`")
            continue
        if status not in STATUSES:
            bad.append(f"{rid}: bad status {status!r} (want {'/'.join(STATUSES)})")
            continue
        written.append(
            {
                "ts": ts,
                "session": args.session,
                "domain": args.domain,
                "rule": rid,
                "status": "human-" + status,
                "note": note.strip(),
                "by": "human",
            }
        )
    if bad:
        print("refusing to attest a partial set:")
        for b in bad:
            print("  ", b)
        return 1
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as fh:
        for rec in written:
            fh.write(json.dumps(rec) + "\n")
    print(f"attested {len(written)} human verdict(s) to {LEDGER.name}")
    for rec in written:
        print(f"  {rec['rule']} = {rec['status']}  ({rec['note'] or 'no note'})")
    return 0


def cmd_stats(args):
    _, rules, _ = parse()
    rows = load_ledger()
    today = datetime.date.today()
    week_ago = (today - datetime.timedelta(days=7)).isoformat()
    fortnight_ago = (today - datetime.timedelta(days=14)).isoformat()

    wk = [r for r in rows if r["ts"][:10] >= week_ago]
    fn = [r for r in rows if r["ts"][:10] >= fortnight_ago]
    fails = [r for r in wk if r["status"] in ("fail", "human-fail")]
    # A `skip` means the rule did not apply — it is NOT evidence the rule works. Counting skips as
    # "fired" let 3 skip lines move SECONDARY from 3/7 (42%) to 6/7 (85%) with no validation at
    # all, silencing the very metric meant to detect dead rules. Only genuinely exercised
    # statuses count; skips are surfaced separately so "we skipped it" is visible, not flattering.
    fired = {r["rule"] for r in fn if r["status"] in EXERCISED}
    skipped = {r["rule"] for r in fn if r["status"] == "skip"}
    live_ids = {r["id"] for r in rules}
    fired_live = fired & live_ids
    sessions_closed = {r["session"] for r in fn if r["status"] in EXERCISED}

    print(f"live rules: {len(rules)}")
    print(f"ledger lines: {len(rows)}   sessions with a validation pass: {len(sessions_closed)}")
    print("")
    print(f"PRIMARY   action-changing validations (fail) this week: {len(fails)}  [target >=2 by day 14]")
    print(f"SECONDARY live rules fired in trailing 14d: {len(fired_live)}/{len(live_ids)}"
          f" = {(100 * len(fired_live) // max(1, len(live_ids)))}%  [target >=50%]")
    dead = sorted(live_ids - fired_live)
    if dead:
        print(f"never fired in 14d: {', '.join(dead)}  -> triggers too abstract, or the pass is not running")
    if skipped:
        print(f"skipped in 14d (NOT counted as fired): {', '.join(sorted(skipped & live_ids))}")
    return 0


def cmd_gate(args):
    """Runtime gate: high-stakes work does not proceed without a recorded check.

    Exit 0 = clear to proceed, exit 2 = BLOCKED. A non-zero exit is the whole point: a
    procedural rule with no enforcement point is theatre, and an audit after an external
    send has already left the machine.
    """
    _, rules, _ = parse()
    forced = [h for h in HIGH_STAKES if toks(h) & toks(args.domain)]
    if not forced:
        print("no high-stakes class matched — audit-only path, proceed")
        return 0
    need = matching_rules(args.domain, rules)
    rows = [r for r in load_ledger() if r.get("session") == args.session]
    satisfied = {r["rule"] for r in rows if r.get("status") == "pass"}
    # chk:human rules are satisfied ONLY by a human attestation — a self-recorded `pass` is not
    # evidence a human decided, and must not clear the gate (see cmd_attest).
    human_ok = {r["rule"] for r in rows if r.get("status") == "human-pass"}
    missing = []
    for r in need:
        ok = (r["id"] in human_ok) if r["chk"] == "human" else (r["id"] in satisfied)
        if not ok:
            missing.append(r)
    if missing:
        print("BLOCKED — high-stakes class(es) matched:")
        for h in forced:
            print(f"  ! {h}")
        print("no recorded pass this session for:")
        for r in missing:
            human = "  <- needs a HUMAN verdict (`attest`), the agent cannot self-certify this" \
                if r["chk"] == "human" else ""
            print(f"  {r['id']} [chk:{r['chk']}] {r['do']}{human}")
        print('\nthen: cs_check.py record --session ... --results "<id>=pass|fail:<note>"')
        print('      cs_check.py attest --session ... --domain ... --results "<id>=pass:<decision>"')
        return 2
    print(f"gate clear — {len(need)} rule(s) recorded and passing for this session")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", help="show the rules matching a task domain")
    p.add_argument("--domain", required=True)
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("record", help="write validation results (the only fire counter)")
    p.add_argument("--session", required=True)
    p.add_argument("--domain", required=True)
    p.add_argument("--results", required=True, help='"R-001=pass;R-002=fail:no backup"')
    p.set_defaults(fn=cmd_record)

    p = sub.add_parser("attest", help="log a HUMAN verdict for a chk:human rule (not the agent's path)")
    p.add_argument("--session", required=True)
    p.add_argument("--domain", required=True)
    p.add_argument("--results", required=True, help='"R-004=pass:<the human decision>"')
    p.set_defaults(fn=cmd_attest)

    p = sub.add_parser("stats", help="the Q6 metrics, computed from the ledger")
    p.set_defaults(fn=cmd_stats)

    p = sub.add_parser("gate", help="runtime gate for the high-stakes classes (exit 2 = stop)")
    p.add_argument("--domain", required=True)
    p.add_argument("--session", required=True)
    p.set_defaults(fn=cmd_gate)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())