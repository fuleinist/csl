"""The ``csl`` command line.

The engine keeps its own, already-tested argument parsers; this dispatch layer only routes to
them. Rewriting them would risk the behaviour the test suites pin.
"""
from __future__ import annotations

import sys

from . import paths

USAGE = """csl — a self-improving common-sense layer for agent harnesses (beta)

  csl init                     create ~/.csl (or $CSL_HOME) and seed the rules file
  csl validate [--fingerprint] check the live layer; exit 1 on any violation
  csl list   --domain "..."    which rules apply to this task domain
  csl gate   --session S --domain D      exit 2 when a high-stakes action is unvalidated
  csl record --session S --domain D --results "R-002=pass:evidence;R-003=skip:why"
  csl attest --session S --domain D --results "R-004=pass:the human's decision"
  csl stats                    the metrics (and what they refuse to count)
  csl evolve [--apply]         mine candidates through the gates; promote or queue
  csl hook [--harness H] [--mode audit|gate] [--event FILE] [--explain]

Environment:
  CSL_HOME            layer directory (default ~/.csl)
  CSL_HOOK_MODE       audit (default, never blocks) | gate (blocks)
  CSL_HOOK_FAIL_CLOSED  set to 1 to block when the hook itself errors
"""


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0

    cmd, rest = argv[0], argv[1:]

    if cmd == "init":
        home = paths.ensure_home()
        print(f"layer home: {home}")
        print(f"rules file: {paths.LIVE}")
        if not paths.LIVE.exists():
            print("seeded from package data")
        return 0

    if cmd == "hook":
        from . import hook
        return hook.run(rest)

    # The engine modules read sys.argv themselves; give each the argv shape it expects.
    if cmd == "validate":
        from . import grammar
        sys.argv = ["csl validate"] + rest
        return grammar.main()
    if cmd == "evolve":
        from . import evolve
        sys.argv = ["csl evolve"] + rest
        return evolve.main()
    if cmd in ("list", "gate", "record", "attest", "stats"):
        from . import check
        sys.argv = ["csl check"] + argv
        return check.main()

    print(f"csl: unknown command {cmd!r}\n", file=sys.stderr)
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())