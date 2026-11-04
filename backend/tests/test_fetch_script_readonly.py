"""Static safety check for the read-only Kite comparison script (no DB, no network, script is never run)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "brain"
    / "evidence"
    / "corporate_actions"
    / "hul_fresh_fetch_readonly.sh"
)
FORBIDDEN = [
    "commit(",
    "add(",
    "merge(",
    "delete(",
    "auto_login",
    "reauth_and_retry",
    "load_session",
    "place_order",
]
SENSITIVE = re.compile(r"token|secret|key|password|dsn|database_url", re.I)


def _text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _python_body() -> str:
    m = re.search(r"<<'PY'\n(.*?)\nPY\n", _text(), re.S)
    assert m, "embedded python block not found"
    return m.group(1)


def test_script_text_has_no_write_calls():
    t = _text()
    for word in FORBIDDEN:
        assert word not in t, f"forbidden word in script: {word}"


def test_script_has_no_write_sql():
    body = _python_body()
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|TRUNCATE|DROP|ALTER|CREATE)\b", body, re.I)
    assert "execute(" in body  # selects only; each execute call must be a SELECT/SET/SHOW
    for call in re.finditer(r'execute\(\s*text\(\s*((?:"[^"]*"\s*)+)', body):
        sql = call.group(1).replace('"', "").strip().upper()
        assert sql.startswith(("SELECT", "SET TRANSACTION READ ONLY", "SHOW")), sql


def test_script_declares_read_only_and_cleans_up():
    t = _text()
    assert "READ ONLY" in t
    assert "postgresql_readonly=True" in t
    assert "conn.rollback()" in t and "conn.close()" in t
    assert "sys.exit(code)" in t


def test_script_parses_and_never_prints_credentials():
    tree = ast.parse(_python_body())
    printed = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "print":
            for arg in list(node.args) + [k.value for k in node.keywords]:
                for sub in ast.walk(arg):
                    if isinstance(sub, ast.Name):
                        printed.append(sub.id)
                    elif isinstance(sub, ast.Attribute):
                        printed.append(sub.attr)
    assert printed, "expected print calls"
    bad = [n for n in printed if SENSITIVE.search(n)]
    assert not bad, f"print touches sensitive-looking names: {bad}"
    # the only value printed from an exception goes through clean()
    assert "clean(exc)" in _python_body()
