"""csl — a self-improving common-sense layer for agent harnesses.

A thin layer of falsifiable rules, each one line, that an agent validates against at
high-stakes moments (``csl gate``) and records verdicts for (``csl record``). Rules are promoted
from candidates only after passing three gates, and every counter is *derived* from the
append-only ledger, so no rule can look exercised without a recorded verdict.

The layer is the user's data and lives under ``$CSL_HOME`` (default ``~/.csl``); this package is
only the engine, the CLI and the harness adapters.
"""
from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]