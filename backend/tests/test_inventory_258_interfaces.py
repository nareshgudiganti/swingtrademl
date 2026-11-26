"""Pins docs/verification/258-interfaces-inventory.md against drift (#258, parent #237).

No database and no app import: everything is read from the source with `ast`.
If one of these fails, either the code changed (update the inventory, and for an
execution entry point get the owner's approval) or the inventory is wrong.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
PKG = BACKEND / "src" / "swing_trade_ml"
DOC = BACKEND.parent / "docs" / "verification" / "258-interfaces-inventory.md"
FREEZE = BACKEND / "tests" / "trial_freeze.json"

METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
MUTATING = ("POST", "PUT", "PATCH", "DELETE")
# Route files whose every mutating route must appear in the inventory.
MUTATING_FILES = (
    "orders.py",
    "portfolio.py",
    "strategies.py",
    "brain_golive.py",
    "real_report.py",
    "instruments.py",
    "market_data.py",
    "notifications.py",
    "admin_modules.py",
)
# Calls that can place, cancel or record an order or a manual position.
ORDER_NAMES = {
    "place_order",
    "cancel_order",
    "open_position",
    "close_position",
    "manual_open_position",
    "manual_close_position",
    "place_real_holding_buy",
    "place_real_holding_sell",
}

CODE_ROW = re.compile(r"^\| `([\w/]+\.py)::([\w.]+)\(([^)]*)\)` \| ([^|]+) \|")
ROUTE_ROW = re.compile(r"^\| `(GET|POST|PUT|PATCH|DELETE) (/[^`]*)` \| ([^|]+) \|")
SITE_ROW = re.compile(r"^\| `([\w/]+\.py)::([\w.<>]+)->(\w+)` \|")
LOOSE_ROUTE = re.compile(r"^\| `(POST|PUT|PATCH|DELETE) (/[^`]*)` \|")

_trees: dict[str, ast.Module] = {}


def tree(rel: str) -> ast.Module:
    if rel not in _trees:
        _trees[rel] = ast.parse((PKG / rel).read_text(encoding="utf-8"))
    return _trees[rel]


def find(rel: str, qual: str):
    node: ast.AST = tree(rel)
    for part in qual.split("."):
        for child in ast.iter_child_nodes(node):
            if (
                isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
                and child.name == part
            ):
                node = child
                break
        else:
            return None
    return node


def params(node: ast.AST) -> list[str]:
    if isinstance(node, ast.ClassDef):
        inits = [c for c in node.body if isinstance(c, ast.FunctionDef) and c.name == "__init__"]
        if not inits:
            return [
                c.target.id
                for c in node.body
                if isinstance(c, ast.AnnAssign) and isinstance(c.target, ast.Name)
            ]
        node = inits[0]
    a = node.args  # type: ignore[attr-defined]
    names = [x.arg for x in a.posonlyargs + a.args]
    if a.vararg:
        names.append("*" + a.vararg.arg)
    names += [x.arg for x in a.kwonlyargs]
    if a.kwarg:
        names.append("**" + a.kwarg.arg)
    return names


def route_index() -> dict[tuple[str, str], str]:
    """(method, prefix + path) -> endpoint file, from the `@<router>.<method>("...")` decorators of every
    `APIRouter(...)` variable in the file (`router`, `admin`, `console`, ...)."""
    index: dict[tuple[str, str], str] = {}
    for path in sorted((PKG / "api/v1/endpoints").glob("*.py")):
        rel = path.relative_to(PKG).as_posix()
        mod = tree(rel)
        prefixes: dict[str, str] = {}
        for n in mod.body:
            if (
                isinstance(n, ast.Assign)
                and isinstance(n.value, ast.Call)
                and getattr(n.value.func, "id", "") == "APIRouter"
            ):
                prefix = ""
                for kw in n.value.keywords:
                    if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                        prefix = kw.value.value
                for target in n.targets:
                    if isinstance(target, ast.Name):
                        prefixes[target.id] = prefix
        for n in ast.walk(mod):
            if not isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for d in n.decorator_list:
                if (
                    isinstance(d, ast.Call)
                    and isinstance(d.func, ast.Attribute)
                    and d.func.attr.upper() in METHODS
                    and isinstance(d.func.value, ast.Name)
                    and d.func.value.id in prefixes
                    and d.args
                    and isinstance(d.args[0], ast.Constant)
                ):
                    index[(d.func.attr.upper(), prefixes[d.func.value.id] + d.args[0].value)] = rel
    return index


def order_call_sites() -> set[tuple[str, str, str]]:
    sites: set[tuple[str, str, str]] = set()
    for path in sorted(PKG.rglob("*.py")):
        rel = path.relative_to(PKG).as_posix()

        def walk(node: ast.AST, stack: list[str], rel: str = rel) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                    walk(child, [*stack, child.name])
                    continue
                if isinstance(child, ast.Call):
                    f = child.func
                    name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
                    if name in ORDER_NAMES:
                        sites.add((rel, ".".join(stack) or "<module>", name))
                walk(child, stack)

        walk(tree(rel), [])
    return sites


@pytest.fixture(scope="module")
def doc_lines() -> list[str]:
    return DOC.read_text(encoding="utf-8").splitlines()


def test_inventory_exists_and_leads_with_plain_english(doc_lines):
    text = "\n".join(doc_lines)
    assert text.index("## In plain English") < text.index("## 1. Data in")
    for heading in ("## 1. Data in", "## 2. Signals", "## 3. Portfolio", "## 4. Execution"):
        assert heading in text


def test_every_listed_function_exists_with_the_listed_parameters(doc_lines):
    rows = [m for line in doc_lines if (m := CODE_ROW.match(line))]
    assert len(rows) >= 100, "the inventory lost most of its rows"
    problems = []
    for m in rows:
        rel, qual, listed = m.group(1), m.group(2), m.group(3)
        if not (PKG / rel).exists():
            problems.append(f"{rel} is gone")
            continue
        node = find(rel, qual)
        if node is None:
            problems.append(f"{rel}::{qual} is gone")
            continue
        actual = ", ".join(params(node))
        if actual != listed:
            problems.append(f"{rel}::{qual}: listed ({listed}) but the code has ({actual})")
    assert not problems, "\n".join(problems)


def test_every_listed_route_exists(doc_lines):
    index = route_index()
    missing = [
        f"{m.group(1)} {m.group(2)}"
        for line in doc_lines
        if (m := ROUTE_ROW.match(line)) and (m.group(1), m.group(2)) not in index
    ]
    assert not missing, f"listed routes that no longer exist: {missing}"


def test_frozen_column_matches_the_trial_freeze_manifest(doc_lines):
    frozen_files = set(json.loads(FREEZE.read_text(encoding="utf-8"))["files"])
    problems = []
    for line in doc_lines:
        m = CODE_ROW.match(line)
        if not m:
            continue
        rel = m.group(1)
        listed = line.rstrip().rstrip("|").rsplit("|", 1)[1].strip()
        expected = "yes" if rel in frozen_files or rel.startswith(("brain/modules/", "strategies/")) else "no"
        if listed != expected:
            problems.append(f"{rel}: frozen column says {listed}, the manifest says {expected}")
    assert not problems, "\n".join(problems)


def test_every_dated_reader_method_is_listed(doc_lines):
    listed = {
        m.group(2) for line in doc_lines if (m := CODE_ROW.match(line)) and m.group(1) == "brain/reader.py"
    }
    cls = find("brain/reader.py", "DatedReader")
    actual = {
        f"DatedReader.{n.name}"
        for n in cls.body  # type: ignore[union-attr]
        if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")
    }
    assert actual - listed == set(), (
        f"new DatedReader methods not in the inventory: {sorted(actual - listed)}"
    )
    assert listed - actual - {"DatedReader"} == set(), "listed DatedReader methods no longer exist"


def test_public_execution_and_broker_functions_are_listed(doc_lines):
    listed = {(m.group(1), m.group(2)) for line in doc_lines if (m := CODE_ROW.match(line))}
    unlisted = []
    for rel in (
        "services/execution.py",
        "services/real_orders.py",
        "brokers/__init__.py",
        "services/trading_rules.py",
        "simulation/momentum.py",
    ):
        for n in tree(rel).body:
            if isinstance(n, ast.FunctionDef) and not n.name.startswith("_") and (rel, n.name) not in listed:
                unlisted.append(f"{rel}::{n.name}")
    for rel, cls_name in (
        ("brokers/paper.py", "PaperBroker"),
        ("brokers/kite.py", "KiteBroker"),
        ("brokers/base.py", "Broker"),
    ):
        cls = find(rel, cls_name)
        for n in cls.body:  # type: ignore[union-attr]
            if (
                isinstance(n, ast.FunctionDef)
                and n.name in {"place_order", "cancel_order", "get_order_status", "get_ltp"}
                and (rel, f"{cls_name}.{n.name}") not in listed
            ):
                unlisted.append(f"{rel}::{cls_name}.{n.name}")
    assert not unlisted, f"public execution interfaces missing from the inventory: {unlisted}"


def test_execution_entry_points_match_the_inventory_exactly(doc_lines):
    documented = {(m.group(1), m.group(2), m.group(3)) for line in doc_lines if (m := SITE_ROW.match(line))}
    actual = order_call_sites()
    assert actual - documented == set(), (
        "NEW execution entry point(s): add to the inventory and get the owner's approval first: "
        f"{sorted(actual - documented)}"
    )
    assert documented - actual == set(), (
        f"inventory lists entry points that no longer exist: {sorted(documented - actual)}"
    )


def test_only_one_place_outside_get_broker_calls_a_broker_order_method():
    """The paper path goes through get_broker(); the single bypass is the real-holdings helper."""
    direct = {
        (rel, fn)
        for rel, fn, name in order_call_sites()
        if name == "place_order" and not rel.startswith("brokers/")
    }
    assert direct == {
        ("services/execution.py", "open_position"),
        ("services/execution.py", "close_position"),
        ("services/execution.py", "_place_real_holding_order"),
    }


def test_every_mutating_route_in_the_money_adjacent_files_is_listed(doc_lines):
    documented = {(m.group(1), m.group(2)) for line in doc_lines if (m := LOOSE_ROUTE.match(line))}
    actual = {
        key
        for key, rel in route_index().items()
        if key[0] in MUTATING and rel.rsplit("/", 1)[1] in MUTATING_FILES
    }
    assert actual - documented == set(), (
        f"NEW mutating route(s) not in the inventory: {sorted(actual - documented)}"
    )
    assert documented - set(route_index()) == set(), "a listed mutating route is gone"


def test_the_published_inventory_holds_no_secret_or_host_detail(doc_lines):
    """The repo is public: the inventory names interfaces, never credentials, hosts or route guards."""
    text = chr(10).join(doc_lines)
    assert not re.search(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", text), "an IP address"
    banned_words = (
        "KITE_API",
        "KITE_PASSWORD",
        "TOTP",
        "JWT_SECRET",
        "POSTGRES_PASSWORD",
        "TELEGRAM_BOT_TOKEN",
        "API_KEY",
        "droplet",
        "digitalocean",
        "swingtrademl.com",
        "plan default",
    )
    for banned in banned_words:
        assert banned.lower() not in text.lower(), f"{banned!r} must not be published"
