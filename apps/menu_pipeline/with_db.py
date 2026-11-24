"""Run a module or a PostgreSQL client tool against another database of the same server (ADR-0030).

    python -m apps.menu_pipeline.with_db <dbname> -m <module> [args...]
    python -m apps.menu_pipeline.with_db <dbname> --pg <tool> [args...]

``DATABASE_URL`` keeps its role, password and host; only the database name changes. ``-m``
runs the module in this process with the rewritten ``DATABASE_URL`` (the batch loop points the
pipeline CLIs at the master this way). ``--pg`` runs a client tool (``pg_dump``,
``pg_restore``, ``psql``) with the connection in ``PG*`` variables, so the password never
appears on a command line. Nothing is printed.
"""

from __future__ import annotations

import os
import runpy
import subprocess
import sys

from sqlalchemy.engine import make_url

USAGE = "usage: with_db <dbname> (-m <module> | --pg <tool>) [args...]"


def database_url(url: str, dbname: str) -> str:
    """``url`` with its database name replaced."""
    return make_url(url).set(database=dbname).render_as_string(hide_password=False)


def pg_environment(url: str, dbname: str) -> dict[str, str]:
    """The ``PG*`` variables libpq tools read, for ``dbname`` on ``url``'s server."""
    parsed = make_url(url)
    return {
        "PGHOST": parsed.host or "localhost",
        "PGPORT": str(parsed.port or 5432),
        "PGUSER": parsed.username or "",
        "PGPASSWORD": parsed.password or "",
        "PGDATABASE": dbname,
    }


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if len(args) < 3 or args[1] not in {"-m", "--pg"}:  # noqa: PLR2004 - dbname, mode, target
        raise SystemExit(USAGE)
    dbname, mode, target, *rest = args
    url = os.environ["DATABASE_URL"]
    if mode == "--pg":
        env = os.environ | pg_environment(url, dbname)
        raise SystemExit(subprocess.run([target, *rest], env=env, check=False).returncode)  # noqa: S603 - an operator's own tool and arguments
    os.environ["DATABASE_URL"] = database_url(url, dbname)
    sys.argv = [target, *rest]
    runpy.run_module(target, run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
