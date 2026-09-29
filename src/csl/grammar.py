#!/usr/bin/env python3
"""Validate the live common-sense layer.

Exit 0 = clean. Exit 1 = violations (printed, one per line, prefixed VIOLATION:).

Checks, in order:
  1. header parses and its `rules`/`cap` counters match reality
  2. char budget: len(live) <= cap
  3. every non-comment line parses as a rule
  4. rule ids unique
  5. no contradictory pair (same normalised `when`, different `do`)
  6. safety lint: a rule whose `do` loosens a guardrail must be chk: human
  7. staleness: last confirmed within STALE_DAYS

Runnable directly:  python3 cs_validate.py [path/to/common-sense.md]
"""
import datetime
import re
import sys
from pathlib import Path

from .paths import LIVE, ROOT  # noqa: F401  (ROOT kept for callers)

CAP_DEFAULT = 2500
STALE_DAYS = 30

# The rule grammar version. Bump on ANY change to the rule line's field set, and add a
# CHANGELOG.md entry plus a migration. The header carries it so an external verifier can tell
# a format change apart from a corrupted file — see `--fingerprint`.
GRAMMAR = 2

HEADER = re.compile(
    r"^<!-- common-sense v(?P<v>\d+) \| cap (?P<cap>\d+) \| rules (?P<n>\d+) "
    r"\| updated (?P<d>\d{4}-\d{2}-\d{2}) -->$"
)
RULE = re.compile(
    r"^- (?P<id>R-\d{3}) \| when: (?P<when>.+?) \| do: (?P<do>.+?) "
    r"\| chk: (?P<chk>mech|judge|human) \| scope: (?P<scope>[a-z][a-z0-9_-]{0,31}) "
    r"\| ev: (?P<ev>\d+) \| last: (?P<last>\d{4}-\d{2}-\d{2})$"
)

# `scope` is required, and it is the field that keeps this layer from decaying into a second
# memory file. A rule that holds only on this machine (local paths, this box's tool wrappers)
# must not be published as general judgment: the gates cannot falsify a local fact, so it
# would live forever and crowd out real rules. Round 1 agreed `scope: general | <agent>`;
# it was then dropped from the settled design, so it is enforced here instead of assumed.
LOCAL_SPECIFICS = re.compile(
    r"[A-Za-z]:[\\/]"          # C:/ D:/ drive paths
    r"|~/|/c/"                 # home / msys paths
    r"|\brtk\b|\bopenclaw\b|\bhermes\b"   # wrappers and products that exist on this box
    r"|\bDESKTOP-[A-Z0-9]+\b"
    r"|\b(?:localhost|127\.0\.0\.1)\b"
    r"|\bhere\b",              # "a shell here" — machine-relative
    re.I,
)

# A `do:` that removes a guardrail may only exist as a human-gated rule.
LOOSEN = re.compile(
    r"--force|--yes|(?:^|\s)-y(?:\s|$)|rm -rf|"
    r"skip (?:the )?(?:backup|confirm|check|approval|gate)|"
    r"without (?:asking|confirming|backup|approval)|"
    r"bypass|disable (?:the )?(?:guard|check|gate|safety)|"
    r"assume (?:it|that) (?:is|was) fine|no need to (?:back up|confirm|verify)",
    re.I,
)

# A rule can mention a dangerous token in order to FORBID it ("never pass --force",
# "refuse to skip the backup"). Flagging those as guardrail-loosening is exactly backwards:
# the safest rules would be quarantined as the most dangerous. So a match only counts as
# loosening when no negation precedes it *in the same clause* (clause-scoped so that
# "don't worry, just pass --force" still gets caught).
NEGATION = re.compile(
    r"\b(?:never|not|no|don'?t|do not|does not|must not|refuse[ds]?|refusing|avoid|"
    r"forbid(?:s|den)?|prohibit(?:s|ed)?|stop|block|prevent|without|unless|"
    r"only after|instead of|require[sd]?(?: that)?|must)\b",
    re.I,
)
CLAUSE_BREAK = re.compile(r"[,.;:—–]|\bbut\b|\bthen\b|\band then\b", re.I)
NEGATION_WINDOW = 60


def loosens_guardrail(text: str):
    """``(bool, matched_text)`` — True only when the text PERMITS a guardrail bypass."""
    for m in LOOSEN.finditer(text or ""):
        window = (text or "")[max(0, m.start() - NEGATION_WINDOW):m.start()]
        window = CLAUSE_BREAK.split(window)[-1]
        if NEGATION.search(window):
            continue  # a prohibition, not a permission
        return True, m.group(0)
    return False, ""


def parse(path=LIVE):
    """Return (header_dict|None, [rule_dict], [violation]) ."""
    text = Path(path).read_text(encoding="utf-8")
    viol = []
    lines = text.splitlines()
    if not lines:
        return None, [], ["VIOLATION: empty live file"]
    m = HEADER.match(lines[0].strip())
    if not m:
        viol.append("VIOLATION: header does not match the required shape")
        header = {"v": 1, "cap": CAP_DEFAULT, "n": 0, "d": ""}
    else:
        header = {"v": int(m["v"]), "cap": int(m["cap"]), "n": int(m["n"]), "d": m["d"]}

    rules = []
    if header["v"] != GRAMMAR:
        # Fail with ONE actionable line and stop. Emitting per-line grammar errors here is what
        # makes a format change look like file corruption.
        viol.append(
            f"VIOLATION: file declares grammar v{header['v']}, this validator implements "
            f"v{GRAMMAR} — a grammar change, not corruption and not per-line damage. "
            f"Run the migration for the difference (see CHANGELOG.md) and re-validate."
        )
        return header, [], viol

    for i, raw in enumerate(lines[1:], start=2):
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.strip().startswith("<!--"):
            viol.append(f"VIOLATION: line {i}: comment is only allowed on line 1")
            continue
        rm = RULE.match(line)
        if not rm:
            viol.append(f"VIOLATION: line {i}: not a well-formed rule: {line[:80]!r}")
            continue
        rules.append(
            {
                "id": rm["id"],
                "when": rm["when"],
                "do": rm["do"],
                "chk": rm["chk"],
                "scope": rm["scope"],
                "ev": int(rm["ev"]),
                "last": rm["last"],
                "line": i,
            }
        )

    if len(rules) != header["n"]:
        viol.append(f"VIOLATION: header says {header['n']} rules, found {len(rules)}")

    n_chars = len(text)
    if n_chars > header["cap"]:
        viol.append(f"VIOLATION: {n_chars} chars > cap {header['cap']}")

    seen = {}
    for r in rules:
        if r["id"] in seen:
            viol.append(f"VIOLATION: duplicate id {r['id']} on line {r['line']}")
        seen[r["id"]] = r

    for key, rule in contradiction_pairs(rules):
        viol.append(f"VIOLATION: contradiction {key}: {rule}")

    for r in rules:
        loosens, hit = loosens_guardrail(r["do"])
        if loosens and r["chk"] != "human":
            viol.append(
                f"VIOLATION: {r['id']} loosens a guardrail ({hit!r}) but is chk: {r['chk']} "
                f"(must be chk: human): {r['do'][:60]!r}"
            )
        if r["scope"] == "general":
            m = LOCAL_SPECIFICS.search(f"{r['when']} {r['do']}")
            if m:
                viol.append(
                    f"VIOLATION: {r['id']} claims scope: general but cites local specifics "
                    f"({m.group(0)!r}) — a general rule must hold off this machine. Either "
                    f"narrow it to scope: local or remove the local reference."
                )

    if header["d"]:
        today = datetime.date.today()
        for r in rules:
            if r["ev"] == 0:
                viol.append(
                    f"UNCONFIRMED: {r['id']} has no recorded pass in the ledger "
                    "(counters are derived, never hand-written)"
                )
            try:
                age = (today - datetime.date.fromisoformat(r["last"])).days
            except ValueError:
                viol.append(f"VIOLATION: {r['id']} has an unparseable date {r['last']!r}")
                continue
            if age > STALE_DAYS:
                viol.append(f"STALE: {r['id']} last confirmed {age}d ago (limit {STALE_DAYS}d)")
    return header, rules, viol


def norm_when(when):
    return re.sub(r"[^a-z0-9 ]", " ", when.lower()).split()  # token list


def contradiction_pairs(rules):
    """Yield (key, description) for rule pairs that share a trigger but disagree."""
    buckets = {}
    for r in rules:
        key = frozenset(norm_when(r["when"]))
        buckets.setdefault(key, []).append(r)
    for key, group in buckets.items():
        if len(group) < 2:
            continue
        dos = {norm_do(g["do"]) for g in group}
        if len(dos) > 1:
            yield (
                ",".join(sorted(g["id"] for g in group)),
                "same trigger, different action: " + " / ".join(sorted(dos))[:120],
            )


def norm_do(do):
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", do.lower()).split())


def fingerprint(path=LIVE, out=print):
    """Report the grammar this validator implements vs the grammar the file declares.

    The point is to answer "am I looking at a format change or a broken file?" in one command,
    BEFORE reading any per-line error. A red-teamer working from a snapshot needs this: without
    it, a field added mid-flight is indistinguishable from corruption. (Round 5: a sibling
    verifier spent a whole turn hypothesising invisible characters for exactly this reason.)
    """
    import hashlib

    sig = hashlib.sha256((RULE.pattern or "").encode("utf-8")).hexdigest()[:12]
    header, _, _ = parse(path)
    declared = header.get("v")
    out(f"validator grammar : v{GRAMMAR}   (rule-grammar signature {sig})")
    out(f"file declares     : v{declared}")
    if declared == GRAMMAR:
        out("verdict           : match — per-line results are meaningful")
        return 0
    out("verdict           : MISMATCH — the file predates or postdates this validator, so")
    out("                    per-line parse errors are meaningless. Run the migration named")
    out("                    in CHANGELOG.md, then re-validate. Do NOT chase encoding/")
    out("                    corruption: check the grammar version first.")
    return 1


def main():
    if "--fingerprint" in sys.argv:
        args = [a for a in sys.argv[1:] if not a.startswith("--")]
        return fingerprint(Path(args[0]) if args else LIVE)

    path = Path(sys.argv[1]) if len(sys.argv) > 1 else LIVE
    header, rules, viol = parse(path)
    hard = [v for v in viol if v.startswith("VIOLATION")]
    soft = [v for v in viol if v.startswith("STALE")]
    print(f"live: {path}")
    print(f"rules: {len(rules)}  header: {header}")
    for v in viol:
        print(v)
    if not viol:
        print("OK: no violations")
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main())