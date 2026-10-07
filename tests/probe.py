#!/usr/bin/env python3
"""Red-team probe for the common-sense gates. Prints PASS/FAIL per hypothesis.

Run BEFORE a fix to see the bug, and after to see it closed.
    python tests/probe.py
"""
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile

# Isolate the whole run in a throwaway layer: the probe must never touch a real one.
_HOME = pathlib.Path(tempfile.mkdtemp(prefix="csl-probe-"))
_SRC = pathlib.Path(__file__).resolve().parent.parent / "src"
os.environ["CSL_HOME"] = str(_HOME)
os.environ["PYTHONPATH"] = str(_SRC)          # inherited by every child process
sys.path.insert(0, str(_SRC))

from csl import evolve as cs_evolve  # noqa: E402
from csl import grammar as cs_validate  # noqa: E402
from csl import paths  # noqa: E402

paths.refresh()
paths.ensure_home()
ROOT = paths.HOME

def _live():
    return cs_validate.parse()[1]


def ids_by_chk(chk):
    return [r["id"] for r in _live() if r["chk"] == chk]


def id_for(*tokens):
    """The single live rule whose `when` contains all of these tokens."""
    hits = [r for r in _live() if all(tok in r["when"] for tok in tokens)]
    if len(hits) != 1:
        raise SystemExit(f"probe fixture: expected exactly 1 rule matching {tokens}, "
                         f"got {[h['id'] for h in hits]}")
    return hits[0]["id"]


def when_of(rid):
    return next(r["when"] for r in _live() if r["id"] == rid)

results = []


def check(name, got, want, detail=""):
    ok = got == want
    results.append((ok, name, got, want, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if detail:
        print(f"        {detail}")


print("== H1: the safety lint must not flag a rule that FORBIDS a dangerous thing ==")
for text, want_flag in [
    ("never pass --force on this repo", False),
    ("refuse to skip the backup", False),
    ("do not bypass the approval gate", False),
    ("pass --force to get past it", True),
    ("skip the confirmation step", True),
    ("bypass the approval gate", True),
]:
    fn = getattr(cs_validate, "loosens_guardrail", None)
    got = bool(cs_validate.LOOSEN.search(text)) if fn is None else fn(text)[0]
    check(f"H1 {text!r}", got, want_flag, "old naive regex" if fn is None else "")

print()
print("== H2: rule ids must never be reused after eviction ==")
# R-004 was evicted earlier, so rules/R-004.md exists (dormant) while live is R-001..R-003.
(ROOT / "rules").mkdir(exist_ok=True)
(ROOT / "rules" / "R-004.md").write_text("---\nid: R-004\nstatus: dormant\n---\n", encoding="utf-8")
live_three = [
    {"id": f"R-{n:03d}", "when": f"w{n}", "do": f"d{n}", "chk": "mech", "ev": 1, "last": "2026-09-28"}
    for n in (1, 2, 3)
]
nid = cs_evolve.next_id(live_three, [])
check("H2 next_id must skip an id that has a dormant rules/ file", nid == "R-004", False,
      f"got {nid}; rules/R-004.md already exists -> the new rule and the dormant rule share id R-004")
(ROOT / "rules" / "R-004.md").unlink(missing_ok=True)  # test residue, not a real dormant rule

# H2b: exercise the rules/*.md branch DIRECTLY. Without this, state.json's ever_used alone
# would satisfy H2 and the on-disk scan could be deleted without any test noticing.
tmp_dormant = ROOT / "rules" / "R-042.md"
tmp_dormant.write_text("---\nid: R-042\nstatus: dormant\n---\n", encoding="utf-8")
try:
    check("H2b ever_used_ids() sees an id that exists only as a dormant file",
          "R-042" in cs_evolve.ever_used_ids(), True,
          f"rules/R-042.md exists; ever_used_ids()={'R-042' in cs_evolve.ever_used_ids()}")
finally:
    tmp_dormant.unlink(missing_ok=True)

print()
print("== H3: a note that looks like another result token must be refused, not silently merged ==")
ledger = ROOT / "validation.jsonl"
_bak = ledger.read_text(encoding="utf-8") if ledger.exists() else None
try:
    before = len(ledger.read_text(encoding="utf-8").splitlines()) if ledger.exists() else 0
    # Two chk:mech rules, so the ONLY thing that can refuse this is the malformed result string.
    _mech2 = [r["id"] for r in _live() if r["chk"] == "mech"]
    p = subprocess.run(
        [sys.executable, "-m", "csl", "record",
         "--session", "RT", "--domain", "rt",
         "--results", f"{_mech2[0]}=pass:{_mech2[1]}=fail:swallowed"],
        capture_output=True, text=True,
    )
    after = len(ledger.read_text(encoding="utf-8").splitlines()) if ledger.exists() else 0
    out = (p.stdout + p.stderr).lower()
    refused = "refusing" in out and p.returncode != 0
    check("H3 colon-separated entries are refused and nothing is written",
          (refused, after - before), (True, 0),
          f"exit={p.returncode} wrote={after - before} lines")
finally:
    if _bak is None:
        ledger.unlink(missing_ok=True)
    else:
        ledger.write_text(_bak, encoding="utf-8")

print()
print("== H4: scope is required, general must not cite local specifics, promotion is fail-closed ==")
_bad = ("- R-900 | when: writing a file under G:/dev/clawd | do: check the path | "
        "chk: mech | scope: general | ev: 1 | last: 2026-09-30")
_probe_live = ROOT / "probe-live.md"
_probe_live.write_text(
    f"<!-- common-sense v{cs_validate.GRAMMAR} | cap 2500 | rules 1 | updated 2026-09-30 -->\n"
    + _bad + "\n",
    encoding="utf-8",
)
try:
    _, _, _v = cs_validate.parse(_probe_live)
    _hard = [x for x in _v if x.startswith("VIOLATION") and "scope: general" in x]
    check("H4a a general rule citing a local path is a hard violation", bool(_hard), True,
          _hard[0][:100] if _hard else "no violation raised")
finally:
    _probe_live.unlink(missing_ok=True)

# H4b/H4c: the promotion default must be fail-closed.
_s, _n = cs_evolve.decide_scope({"when": "w", "do": "d"})
check("H4b a candidate with NO scope defaults to local, never general", _s, "local", _n)
_s2, _n2 = cs_evolve.decide_scope(
    {"when": "a file under G:/dev/clawd is rewritten", "do": "re-read it", "scope": "general"})
check("H4c a general claim citing local specifics is downgraded", _s2, "local", _n2)
_s3, _n3 = cs_evolve.decide_scope(
    {"when": "any json state file is rewritten", "do": "re-read it", "scope": "general"})
check("H4d an honest general claim survives untouched", _s3, "general", _n3)

print()
print("== H5: a grammar change must read as a version mismatch, never as corruption ==")
# Construct the pre-grammar file here. Depending on a leftover .bak from someone's working
# directory makes the test pass or fail on the state of the filesystem, not on the code.
_bak = ROOT / "probe-grammar-v1.md"
_bak.write_text(
    "<!-- common-sense v1 | cap 2500 | rules 1 | updated 2026-09-30 -->\n"
    "- R-900 | when: rewriting a json state file | do: back up first | chk: mech | ev: 0 "
    "| last: 2026-09-30\n",
    encoding="utf-8",
)
_, _r, _vv = cs_validate.parse(_bak)
_hard = [x for x in _vv if x.startswith("VIOLATION")]
check("H5a a pre-grammar file yields ONE actionable error, not one per rule",
      len(_hard), 1, f"got {len(_hard)}: {_hard[0][:90] if _hard else 'none'}")
check("H5b the single error names the grammar mismatch",
      "grammar v1" in (_hard[0] if _hard else ""), True,
      (_hard[0][:90] if _hard else "none"))
_buf = io.StringIO()
_code = cs_validate.fingerprint(_bak, out=lambda s: _buf.write(s + "\n"))
check("H5c fingerprint exits non-zero and says MISMATCH for the old file",
      (_code, "MISMATCH" in _buf.getvalue()), (1, True),
      _buf.getvalue().splitlines()[-4] if _buf.getvalue() else "")
_bak.unlink(missing_ok=True)

_buf2 = io.StringIO()
_code2 = cs_validate.fingerprint(ROOT / "common-sense.md", out=lambda s: _buf2.write(s + "\n"))
check("H5d fingerprint exits 0 and says match for the live file",
      (_code2, "MISMATCH" not in _buf2.getvalue(),
       any(ln.strip().startswith("verdict") and "match —" in ln for ln in _buf2.getvalue().splitlines())),
      (0, True, True), _buf2.getvalue().splitlines()[0])

# H5e: the encoding hypothesis itself, asserted rather than investigated.
_raw = (ROOT / "common-sense.md").read_bytes()
_stray = [b for b in _raw if b < 0x20 and b not in (0x09, 0x0a, 0x0d)]
check("H5e the live file has no BOM, no stray control chars, no non-ascii",
      (_raw[:3] == b"\xef\xbb\xbf", _stray, sum(1 for b in _raw if b > 0x7f)), (False, [], 0),
      "so 'invisible characters' is ruled out by assertion, not by investigation")

print()
print("== H6: the matcher must not fire on function words, and chk:human must not be self-certifiable ==")
import shutil
import subprocess

_LED = ROOT / "validation.jsonl"
_bak6 = ROOT / "validation.jsonl.rt6bak"
shutil.copy2(_LED, _bak6)
_base6 = len(_LED.read_text(encoding="utf-8").splitlines())


def _run(*a):
    return subprocess.run([sys.executable, "-m", "csl", *a],
                          capture_output=True, text=True, cwd=str(ROOT))


try:
    # -- matcher precision --
    _json_rule = id_for("json", "state")
    _ver_rule = id_for("version", "gate")
    _r = _run("list", "--domain", "deploying any new service to production")
    check("H6a a deployment task no longer matches the json-state-file / version-marker rules",
          [x for x in (_json_rule, _ver_rule) if x in _r.stdout], [],
          f"still matched: {[x for x in (_json_rule, _ver_rule) if x in _r.stdout] or 'none'}")

    _r = _run("list", "--domain", "writing a json state file before publish")
    check(f"H6b a real domain still matches the json-state rule ({_json_rule})",
          _json_rule in _r.stdout, True,
          _r.stdout.strip().splitlines()[1] if len(_r.stdout.strip().splitlines()) > 1 else "")

    # -- chk:human must not be self-certifiable --
    _S, _D = "S-RT6-PROBE", "writing any json state file"
    # The human rule is resolved, and the gate domain is derived from that rule's own `when`, so
    # the fixture cannot drift from the seed. A destructive-operation rule is also a high-stakes
    # class, which is what makes the gate apply at all.
    _human = id_for("destructive", "irreversible")
    _GATE_DOM = when_of(_human)
    _r = _run("record", "--session", _S, "--domain", _D,
              "--results", f"{_human}=pass:self-certified")
    _after = len(_LED.read_text(encoding="utf-8").splitlines())
    check("H6c `record` refuses a chk:human verdict and writes nothing",
          (_r.returncode, _after), (1, _base6),
          f"exit {_r.returncode}, ledger {_base6}->{_after}")

    _r = _run("gate", "--session", _S, "--domain", _GATE_DOM)
    check(f"H6d the gate still BLOCKS the chk:human rule {_human} with no human verdict",
          _r.returncode, 2, f"exit {_r.returncode}: {_r.stdout.strip().splitlines()[0][:70]}")

    _r = _run("attest", "--session", _S, "--domain", _D, "--results", f"{_human}=pass:Chris approved")
    _ok = _r.returncode == 0
    _g = _run("gate", "--session", _S, "--domain", _GATE_DOM)
    check("H6e an attested human verdict DOES clear the gate (the human path works)",
          (_ok, _g.returncode), (True, 0), f"attest exit {_r.returncode}, gate exit {_g.returncode}")

    _r = _run("attest", "--session", _S, "--domain", _D, "--results", f"{_json_rule}=pass:not human")
    check("H6f `attest` refuses a non-human rule (no general bypass)", _r.returncode, 1,
          _r.stdout.strip().splitlines()[1][:80] if _r.returncode else "accepted — BUG")
finally:
    shutil.copy2(_bak6, _LED)
    _bak6.unlink(missing_ok=True)
    check("H6 ledger restored exactly", len(_LED.read_text(encoding="utf-8").splitlines()), _base6,
          "no probe residue in real evidence")

print()
print("== H7: a skip must not count as a fire (the dead-rule detector must not be silenceable) ==")
import re as _re

_bak7 = ROOT / "validation.jsonl.h7bak"
shutil.copy2(_LED, _bak7)
_base7 = len(_LED.read_text(encoding="utf-8").splitlines())


def _pct(out):
    m = _re.search(r"SECONDARY live rules fired in trailing 14d: (\d+)/(\d+) = (\d+)%", out)
    return m.group(3) if m else "?"


try:
    _before_out = _run("stats").stdout
    _before = _pct(_before_out)
    _sessions_before = _before_out.split("sessions with a validation pass: ")[1].split()[0]
    # Skip the rules the gate does NOT protect; a chk:human id would be refused set-wide.
    _skippable = [r["id"] for r in _live() if r["chk"] != "human"][:3]
    _r = _run("record", "--session", "S-H7-PROBE", "--domain", "misc",
              "--results", ";".join(f"{i}=skip:did not apply" for i in _skippable))
    _after_out = _run("stats").stdout
    _after = _pct(_after_out)
    check("H7a recording 3 skips does NOT raise the fired percentage",
          (_r.returncode, _after), (0, _before), f"{_before}% -> {_after}%")
    check("H7b skips are surfaced separately, not silently dropped",
          "skipped in 14d (NOT counted as fired)" in _after_out, True,
          [l for l in _after_out.splitlines() if l.startswith("skipped")][:1])
    _sessions_now = _run("stats").stdout.split("sessions with a validation pass: ")[1].split()[0]
    check("H7c a skip-only session does not count as 'sessions with a validation pass'",
          _sessions_now, _sessions_before, f"unchanged at {_sessions_now}")
finally:
    shutil.copy2(_bak7, _LED)
    _bak7.unlink(missing_ok=True)
    check("H7 ledger restored exactly", len(_LED.read_text(encoding="utf-8").splitlines()), _base7,
          "no probe residue in real evidence")

print()
print("== H8: eviction must optimise the budget it is spending (characters), not just age/value ==")
import datetime as _dt

_y = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()


def _r(rid, ev, do):
    return {"id": rid, "when": "situation " + rid, "do": do, "chk": "mech",
            "scope": "local", "ev": ev, "last": _y}


_terse = _r("R-910", 1, "s" * 40)     # low value, SHORT
_verbose = _r("R-911", 3, "v" * 380)  # higher value, LONG


def _old_density(rule):
    return rule["ev"] / max(1, cs_evolve.days_since(rule["last"]))


_pick_new = min([_terse, _verbose], key=cs_evolve.value_density)["id"]
_pick_old = min([_terse, _verbose], key=_old_density)["id"]
check("H8a per-character density evicts the LONG rule; the old ev/age metric evicted the short one",
      (_pick_new, _pick_old), ("R-911", "R-910"),
      f"new picks {_pick_new} ({len(cs_evolve.rule_line(_verbose))} ch freed), "
      f"old picked {_pick_old} ({len(cs_evolve.rule_line(_terse))} ch)")

# Budget cost: shedding ~300 chars.
_need = 300
_freed_new = len(cs_evolve.rule_line(_verbose))
_gone_old, _freed_old = ["R-910"], len(cs_evolve.rule_line(_terse))
for _x in (_verbose,):
    if _freed_old < _need:
        _gone_old.append(_x["id"])
        _freed_old += len(cs_evolve.rule_line(_x))
check("H8b the old metric deleted MORE rules than necessary to shed the same budget",
      (len(_gone_old), _freed_new >= _need), (2, True),
      f"old: {len(_gone_old)} rules for {_freed_old} ch; new: 1 rule for {_freed_new} ch")

# H8c: the render refactor must still emit exactly the grammar the validator accepts.
_, _live_rules, _ = cs_validate.parse()
_text = cs_evolve.render(2, 2500, _live_rules, _y)
_p = ROOT / "probe-render.md"
_p.write_text(_text, encoding="utf-8")
try:
    _, _rt, _v = cs_validate.parse(_p)
    check("H8c refactored render() round-trips through the validator unchanged",
          (len(_rt), [x for x in _v if x.startswith("VIOLATION")]), (len(_live_rules), []),
          f"{len(_rt)} rules re-parsed, no violations")
finally:
    _p.unlink(missing_ok=True)

print()
print("== H9: chk:judge must actually require named evidence (not just be accepted by the grammar) ==")
_bak9 = ROOT / "validation.jsonl.h9bak"
shutil.copy2(_LED, _bak9)
_base9 = len(_LED.read_text(encoding="utf-8").splitlines())
try:
    _judge = ids_by_chk("judge")[0]
    _bare = _run("record", "--session", "S-H9-PROBE", "--domain", "stale duplicate completions",
                 "--results", f"{_judge}=pass")
    _after9 = len(_LED.read_text(encoding="utf-8").splitlines())
    check("H9a chk:judge refuses a bare verdict with no named evidence",
          (_bare.returncode, _after9), (1, _base9),
          f"exit {_bare.returncode}, ledger {_base9}->{_after9}")

    _ev = _run("record", "--session", "S-H9-PROBE", "--domain", "stale duplicate completions",
               "--results", f"{_judge}=pass:re-read the job log for session 4bd171bb")
    check("H9b chk:judge accepts a verdict that cites evidence", _ev.returncode, 0,
          _ev.stdout.strip().splitlines()[0])

    _mech = _run("record", "--session", "S-H9-PROBE", "--domain", "writing a json state file",
                 "--results", f"{_mech2[0]}=pass")
    check("H9c a chk:mech rule still accepts a bare verdict (no over-tightening)", _mech.returncode, 0,
          _mech.stdout.strip().splitlines()[0])
finally:
    shutil.copy2(_bak9, _LED)
    _bak9.unlink(missing_ok=True)
    check("H9 ledger restored exactly", len(_LED.read_text(encoding="utf-8").splitlines()), _base9,
          "no probe residue in real evidence")

print()
print("== H10: a layer home that is not an absolute path must be refused, not silently created ==")
# Two cases. The first is platform-dependent: `/c/Users/nobody/.csl` is absolute on POSIX and NOT
# absolute on Windows, and the assertion has to follow the platform's own answer.
# The second is platform-independent and is the one that makes the probe bite everywhere: a RELATIVE
# home resolves against whatever cwd the harness happens to use, which is how two shells end up with
# two different layers. Before the fix, `csl init` created the directory, printed a mangled path, and
# exited 0 — while a later `csl hook` read a different, empty layer and reported "no rule matched".
_posixish = "/c/Users/nobody/.csl"
_posixish_is_absolute = pathlib.Path(_posixish).is_absolute()
_scratch10 = pathlib.Path(tempfile.mkdtemp(prefix="csl-h10-"))
_old10 = os.environ.get("CSL_HOME")
os.environ["CSL_HOME"] = _posixish
try:
    _refusal10 = paths.home_refusal()
    try:
        paths.ensure_home()
        _raised10 = None
    except Exception as exc:                      # noqa: BLE001 - the type IS the assertion
        _raised10 = type(exc).__name__
finally:
    if _old10 is None:
        os.environ.pop("CSL_HOME", None)
    else:
        os.environ["CSL_HOME"] = _old10

if _posixish_is_absolute:
    check("H10a an absolute CSL_HOME is accepted on this platform",
          (_refusal10, _raised10), (None, None),
          f"{_posixish!r} is absolute here, so nothing may be refused")
else:
    check("H10a a non-absolute CSL_HOME is refused before anything is created",
          (_raised10, isinstance(_refusal10, str) and "CSL_HOME" in _refusal10),
          ("HomeNotAbsoluteError", True),
          f"{_posixish!r} is not absolute here")

# A relative home is not absolute on ANY platform, so this case asserts the same thing everywhere.
_rel10 = "rel-layer"
_r10a = subprocess.run([sys.executable, "-m", "csl", "init"], capture_output=True, text=True,
                       cwd=str(_scratch10), env={**os.environ, "CSL_HOME": _rel10})
check("H10b a relative CSL_HOME is refused on every platform", _r10a.returncode, 2,
      (_r10a.stderr.strip().splitlines() or [""])[0])
check("H10c nothing was created for the refused home",
      sorted(p.name for p in _scratch10.iterdir()), [],
      "the old code wrote the layer and reported success")
check("H10d the refusal names the cause and the fix",
      ("CSL_HOME" in _r10a.stderr, "absolute" in _r10a.stderr), (True, True))

# The hook must NOT inherit this refusal: it runs inside an agent's tool call and has to fail open.
_h10 = subprocess.run([sys.executable, "-m", "csl", "hook", "--harness", "hermes"],
                      input='{"hook_event_name":"pre_tool_call","tool_name":"terminal",'
                            '"tool_input":{"command":"git push --force"},"session_id":"h10"}',
                      capture_output=True, text=True, cwd=str(_scratch10),
                      env={**os.environ, "CSL_HOME": _rel10})
check("H10e the hook still fails open with a bad home (exit 0, never a block)", _h10.returncode, 0,
      "a config mistake must not wedge a turn")
shutil.rmtree(_scratch10, ignore_errors=True)

print()
print("== summary ==")
bad = [r for r in results if not r[0]]
print(f"{len(results) - len(bad)}/{len(results)} pass")
for _, name, got, want, _ in bad:
    print(f"  BUG: {name} -> got {got!r}, want {want!r}")
sys.exit(1 if bad else 0)