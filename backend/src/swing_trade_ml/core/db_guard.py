"""Refuse any database that is not a local, throwaway test database.

Used by the test suite (tests/_env_safety.py) and the migration check
(scripts/check_migrations.py). Deliberately standalone — it imports nothing from the app, so the
tests can run it before the application settings are read.

A URL is accepted only if ALL of these hold:
* it is a PostgreSQL URL;
* its host is exactly localhost / 127.0.0.1 / ::1 (no comma-separated host lists, no unix sockets);
* its database name ends in "_test";
* it has NO query string. libpq lets query parameters (host, hostaddr, dbname, service, options, ...)
  override the host and database the rest of the URL names, so checking host and path alone would
  validate a target the connection never uses.

The URL is not the whole story: libpq (the driver underneath) fills in any setting the URL leaves out
from PG* environment variables. PGHOSTADDR makes it connect to a different IP than the URL's host,
PGPORT chooses the port when the URL has none (a forwarded local port can reach a remote database),
PGSERVICE loads host/hostaddr/port from a service file. `assert_no_connection_overrides` therefore
refuses to run while any of those variables is set.

The error message never contains the URL, user, password or query string — only a reason, plus the
host and database name when those are plain identifiers.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from sqlalchemy.engine import make_url

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_PLAIN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


# Environment variables that can change WHERE or HOW the driver connects. PGPASSWORD, PGSSL*, etc. are
# harmless and deliberately not listed.
ROUTING_ENV_VARS = (
    "PGHOSTADDR",
    "PGHOST",
    "PGPORT",
    "PGDATABASE",
    "PGSERVICE",
    "PGSERVICEFILE",
    "PGSYSCONFDIR",
    "PGOPTIONS",
    "PGTARGETSESSIONATTRS",
)


def _shown(value: str | None) -> str:
    return value if value and _PLAIN.match(value) else "<hidden>"


def _refusal(reason: str, host: str | None = None, database: str | None = None) -> RuntimeError:
    where = f" (host {_shown(host)}, database {_shown(database)})" if host or database else ""
    return RuntimeError(
        f"Refusing to use this database: {reason}{where}. Tests and migration checks may only use "
        "a PostgreSQL database on localhost whose name ends in '_test', with no URL query parameters. "
        "Unset DATABASE_URL or point it at the local test database."
    )


def assert_local_test_database(url: str) -> None:
    try:
        parsed = make_url(url)
    except Exception:  # noqa: BLE001 — never echo an unparseable URL
        raise _refusal("the URL could not be read") from None

    host, database = parsed.host, parsed.database
    if not parsed.drivername.startswith("postgresql"):
        raise _refusal("it is not a PostgreSQL URL", host, database)
    if parsed.query:
        raise _refusal("URL query parameters can reroute the connection", host, database)
    if (host or "") not in LOCAL_HOSTS:
        raise _refusal("the host is not localhost", host, database)
    if not (database or "").endswith("_test"):
        raise _refusal("the database name does not end in '_test'", host, database)


def assert_no_connection_overrides(environ: Mapping[str, str]) -> None:
    """Refuse to run while an inherited PG* variable could reroute the connection.

    Names the variables, never their values. An empty value counts as unset.
    """
    found = [name for name in ROUTING_ENV_VARS if environ.get(name)]
    if found:
        raise RuntimeError(
            "Refusing to use a database: these environment variables can reroute the connection "
            f"away from the URL ({', '.join(found)}). Unset them before running tests or migration "
            "checks (e.g. `unset PGHOSTADDR`)."
        )
