"""Where the layer lives on disk, and how a fresh one gets created.

One rule: the layer is the *user's* data, never the package's. Code ships here; rules, ledger and
candidates live under CSL_HOME (default ``~/.csl``). That separation is what makes this installable
as a plugin — an upgrade must never overwrite the rules an agent has earned.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

#: Environment override, so tests and multi-agent setups can point at their own layer.
ENV_HOME = "CSL_HOME"

DATA = Path(__file__).resolve().parent / "data"
SEED = DATA / "seed.md"


def resolve_home() -> Path:
    raw = os.environ.get(ENV_HOME)
    return Path(raw).expanduser() if raw else Path.home() / ".csl"


#: Layer root. `ROOT` is the historical alias the engine modules import.
HOME = resolve_home()
ROOT = HOME

LIVE = HOME / "common-sense.md"          # the rule store
LEDGER = HOME / "validation.jsonl"       # append-only verdicts; every counter is derived here
CANDIDATES = HOME / "candidates.jsonl"   # mined, lower-trust candidates awaiting the gates
STATE = HOME / "state.json"              # evolve bookkeeping (ever_used ids, last run)
HUMAN = HOME / "proposals" / "human.jsonl"   # gold candidates + guardrail-loosening: human queue
RETIRED = HOME / "rules"                 # evicted rules, one file each (ids never reused)
EVOLVE_LOG = HOME / "evolve"             # one report per evolve run
PROPOSALS = HOME / "proposals"


def ensure_home(seed: bool = True) -> Path:
    """Create the layer directory, seeding a fresh rules file from the shipped seed.

    Returns the home path. Idempotent: never overwrites an existing layer.
    """
    for d in (HOME, RETIRED, EVOLVE_LOG, PROPOSALS):
        d.mkdir(parents=True, exist_ok=True)
    for f in (LEDGER, CANDIDATES):
        if not f.exists():
            f.write_text("", encoding="utf-8")
    if seed and not LIVE.exists():
        shutil.copy2(SEED, LIVE)
    return HOME


def refresh() -> None:
    """Re-resolve HOME from the environment. Used by tests/embedders that set CSL_HOME late."""
    global HOME, ROOT, LIVE, LEDGER, CANDIDATES, STATE, HUMAN, RETIRED, EVOLVE_LOG, PROPOSALS
    HOME = resolve_home()
    ROOT = HOME
    LIVE = HOME / "common-sense.md"
    LEDGER = HOME / "validation.jsonl"
    CANDIDATES = HOME / "candidates.jsonl"
    STATE = HOME / "state.json"
    HUMAN = HOME / "proposals" / "human.jsonl"
    RETIRED = HOME / "rules"
    EVOLVE_LOG = HOME / "evolve"
    PROPOSALS = HOME / "proposals"