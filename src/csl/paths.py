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


class HomeNotAbsoluteError(ValueError):
    """The configured layer home is not an absolute path on this platform."""


def home_refusal() -> str | None:
    """A refusal message when the configured home is not absolute, else ``None``.

    A POSIX-looking value such as ``/c/Users/you/.csl`` arrives unchanged on Windows, where it is
    **not** absolute: Windows resolves it against the current drive. The layer was then created at
    ``<drive>:\\c\\Users\\you\\.csl``, ``csl init`` reported success, and a later ``csl hook`` read a
    different, empty layer — so the hook answered "no rule matched" instead of reporting an error.

    ``Path.is_absolute()`` already answers this per platform: ``/c/Users/x`` is absolute on POSIX
    and not absolute on Windows. That is exactly the distinction that matters, so no per-OS branch
    is needed here.
    """
    home = resolve_home()
    if home.is_absolute():
        return None
    return (
        f"CSL_HOME resolves to {str(home)!r}, which is not an absolute path on this platform.\n"
        f"  The layer would be created somewhere the shell did not name.\n"
        f"  Set CSL_HOME to a native absolute path, for example "
        f"{os.path.join(str(Path.home()), '.csl')!r}"
    )


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

    Refuses a home that is not an absolute path, before it creates anything. See
    :func:`home_refusal`.
    """
    refusal = home_refusal()
    if refusal:
        raise HomeNotAbsoluteError(refusal)
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