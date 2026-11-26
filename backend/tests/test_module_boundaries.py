"""#413: module boundaries and router protection are enforced by tests, not by convention.

1. Layering: `core`, `db`, `services` and `brain` must not import `api`.
2. Product modules (finance, brain, research lanes) must not import each other's internals. Each justified
   exception is on an allow-list below with the reason.
3. Router protection: every router in `api/v1/router.py` is behind `protected` or `optional(...)`, or is
   named on the public allow-list below with the reason it checks access itself.

The scan is by AST over every file under `src/swing_trade_ml`, and counts imports anywhere in a file (inside a
function or under `if TYPE_CHECKING:` too). A new violation fails here, naming the file and line. The helper
functions take source text, so the tests prove they would catch a violation without a real one existing.
"""

from __future__ import annotations

import ast
from pathlib import Path

import swing_trade_ml

SRC = Path(swing_trade_ml.__file__).parent
PACKAGE = "swing_trade_ml"

# ---------------------------------------------------------------- 1. layering
NO_API_IMPORTS_FROM = ("core", "db", "services", "brain", "workers", "ml")

#: (file, imported module) pairs allowed to break the layering rule. Each needs a reason.
LAYERING_ALLOW: dict[tuple[str, str], str] = {
    (
        "services/tester_paper.py",
        "swing_trade_ml.api.v1.endpoints.portfolio",
    ): (
        "TEMPORARY. tester_paper reads the pure stop/target helper `_derive_stop_target` from the "
        "portfolio endpoint; it belongs in services. Not moved yet because #426 is changing this area "
        "and would conflict. Expires when #426 merges: move the helper, then delete this entry (the "
        "stale-entry test fails once the import is gone, so it cannot be forgotten). Tracked in #413."
    ),
}

# ---------------------------------------------------------------- 2. product modules
#: product -> the packages that belong to it (the module registry's `packages`, core/modules.py).
PRODUCTS: dict[str, tuple[str, ...]] = {
    "finance": ("swing_trade_ml.services.finance",),
    "brain": ("swing_trade_ml.brain",),
    "research_lanes": ("swing_trade_ml.shadow_lanes", "swing_trade_ml.brain.lanes"),
}

#: (file, imported module) pairs where one product reads another's code. Each needs a reason.
_LANES_USE_BRAIN = (
    "the research lanes evaluate the brain's own models, so they reuse its training and replay code "
    "(read-only; nothing in the brain depends on the lanes for a decision)"
)
CROSS_PRODUCT_ALLOW: dict[tuple[str, str], str] = {
    ("brain/eligibility_report.py", "swing_trade_ml.brain.lanes.h05_protocol"): (
        "the weekly eligibility report reads the h05 lane's protocol numbers; read-only, "
        "and tests/test_h05_service.py pins this file as one of the lane's few allowed importers"
    ),
    ("brain/prediction_reliability.py", "swing_trade_ml.shadow_lanes.lane_review"): (
        "reads the lane review's checkpoint constants only (no lane code runs)"
    ),
    ("shadow_lanes/lane_freeze.py", "swing_trade_ml.brain.selection_lab"): _LANES_USE_BRAIN,
    ("shadow_lanes/lane_freeze.py", "swing_trade_ml.brain.selection_lab_run"): _LANES_USE_BRAIN,
    ("shadow_lanes/lane_service.py", "swing_trade_ml.brain.ten_day"): _LANES_USE_BRAIN,
    ("shadow_lanes/lane_service.py", "swing_trade_ml.brain.replay_scoring"): _LANES_USE_BRAIN,
    ("shadow_lanes/lane_universe.py", "swing_trade_ml.brain.selection_lab_run"): _LANES_USE_BRAIN,
}

# ---------------------------------------------------------------- 3. router protection
#: routers included without `protected`: each checks access itself, or must answer before anyone can sign in.
PUBLIC_ROUTERS: dict[str, str] = {
    "system.router": (
        "the health and readiness probes must answer without credentials (the orchestrator sends none); the "
        "other routes in it (/status, /market/session, /refresh-data) each carry require_auth themselves"
    ),
    "auth.router": "login has no credential yet; the Kite redirect cannot send headers",
    "account_auth.router": "sign-up, verification and reset: the emailed one-time token is the credential",
    "account_auth.admin": "each admin route checks for the signed-in owner itself",
    "invites.router": "asking for an invite is public and rate-limited",
    "invites.admin": "each admin route checks for the signed-in owner itself",
    "plans.router": "/me/plan must answer every signed-in user whatever their plan",
    "plans.admin": "each admin route checks for the owner itself",
    "service_keys.admin": "owner-only router (require_owner on the router)",
    "admin_modules.admin": "owner-only router (require_owner on the router)",
    "billing.router": "404 unless BILLING_ENABLED; each route checks its own caller",
    "billing.admin": "each admin route checks for the owner itself",
    "account_deletion.router": "404 unless enabled; each route checks its own caller or token",
    "admin_console.mfa_router": "owner-role person plus two-step code; anyone else gets 404",
    "admin_console.console": "owner-role person plus two-step code; anyone else gets 404",
}


def module_name(path: Path) -> str:
    rel = path.relative_to(SRC.parent).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _dotted(rel: str) -> tuple[str, bool]:
    """(dotted module name, is a package's __init__) for a path relative to src/swing_trade_ml."""
    parts = [PACKAGE, *rel.removesuffix(".py").split("/")]
    is_package = parts[-1] == "__init__"
    if is_package:
        parts.pop()
    return ".".join(parts), is_package


def _known_modules() -> frozenset[str]:
    """Every real module of the app, so `from pkg import name` can tell a submodule from a plain name."""
    return frozenset(_dotted(p.relative_to(SRC).as_posix())[0] for p in SRC.rglob("*.py"))


KNOWN = _known_modules()


def imported_modules(
    source: str, this_module: str, is_package: bool = False
) -> list[tuple[int, str, list[str]]]:
    """Every import in a source file as (line, absolute dotted module, imported names). Relative imports are
    resolved from the file's own package (for an `__init__.py` that is the package itself)."""
    found: list[tuple[int, str, list[str]]] = []
    base = this_module.split(".") if is_package else this_module.split(".")[:-1]
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name, []) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                prefix = base[: len(base) - (node.level - 1)]
                name = ".".join([*prefix, *([node.module] if node.module else [])])
            else:
                name = node.module or ""
            found.append((node.lineno, name, [alias.name for alias in node.names]))
    return found


def targets(name: str, aliases: list[str]) -> list[str]:
    """The modules an import really reaches. `from pkg import x` reaches `pkg.x` when that is a module of the
    app (so `from swing_trade_ml.brain import service` is `brain.service`, never just the brain package);
    otherwise `x` is a plain name inside `pkg` and the module is `pkg`."""
    if not aliases:
        return [name]
    return sorted({f"{name}.{a}" if f"{name}.{a}" in KNOWN else name for a in aliases})


def _hits(name: str, aliases: list[str], bad) -> list[str]:
    """The imported modules that break the rule."""
    return [t for t in targets(name, aliases) if bad(t)]


def _top(rel_file: str) -> str:
    return rel_file.split("/")[0]


def _is_api(module: str) -> bool:
    return module == f"{PACKAGE}.api" or module.startswith(f"{PACKAGE}.api.")


def layering_violations(files: dict[str, str]) -> list[tuple[str, int, str]]:
    """files: {path relative to src/swing_trade_ml: source}. (file, line, imported) for each api import."""
    out = []
    for rel, source in files.items():
        if _top(rel) not in NO_API_IMPORTS_FROM:
            continue
        this, is_package = _dotted(rel)
        for line, name, aliases in imported_modules(source, this, is_package):
            for hit in _hits(name, aliases, _is_api):
                if (rel, hit) not in LAYERING_ALLOW:
                    out.append((rel, line, hit))
    return sorted(set(out))


def _owner(module: str) -> str | None:
    """The product that owns a module: the longest matching package wins (brain.lanes beats brain)."""
    best: tuple[int, str] | None = None
    for product, packages in PRODUCTS.items():
        for pkg in packages:
            if (module == pkg or module.startswith(pkg + ".")) and (best is None or len(pkg) > best[0]):
                best = (len(pkg), product)
    return None if best is None else best[1]


def cross_product_violations(files: dict[str, str]) -> list[tuple[str, int, str]]:
    out = []
    for rel, source in files.items():
        this, is_package = _dotted(rel)
        mine = _owner(this)
        if mine is None:
            continue

        def other_product(module: str, mine: str = mine) -> bool:
            theirs = _owner(module)
            return theirs is not None and theirs != mine

        for line, name, aliases in imported_modules(source, this, is_package):
            for hit in _hits(name, aliases, other_product):
                if (rel, hit) not in CROSS_PRODUCT_ALLOW:
                    out.append((rel, line, hit))
    return sorted(set(out))


def unprotected_routers(router_source: str) -> list[tuple[int, str]]:
    """(line, 'module.attr') of every `include_router` without `protected`, `optional(...)` or `switchable(...)`."""
    out = []
    for node in ast.walk(ast.parse(router_source)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "include_router" or not node.args:
            continue
        target = ast.unparse(node.args[0])
        deps = next((kw.value for kw in node.keywords if kw.arg == "dependencies"), None)
        guarded = (isinstance(deps, ast.Name) and deps.id == "protected") or (
            isinstance(deps, ast.Call)
            and isinstance(deps.func, ast.Name)
            and deps.func.id in ("optional", "switchable")
        )
        if not guarded:
            out.append((node.lineno, target))
    return out


ROUTE_VERBS = {"get", "post", "put", "patch", "delete", "head", "options", "websocket", "route", "api_route"}


def direct_routes(router_source: str) -> list[tuple[int, str]]:
    """(line, text) of every route declared straight on `api_router` (a decorator or add_api_route): such a
    route would skip the router-level protection check, so none may exist."""
    out = []
    for node in ast.walk(ast.parse(router_source)):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            for deco in node.decorator_list:
                call = deco.func if isinstance(deco, ast.Call) else deco
                if (
                    isinstance(call, ast.Attribute)
                    and isinstance(call.value, ast.Name)
                    and call.value.id == "api_router"
                    and call.attr in ROUTE_VERBS
                ):
                    out.append((deco.lineno, ast.unparse(deco)))
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "api_router"
            and node.func.attr in {"add_api_route", "add_route", "add_api_websocket_route"}
        ):
            out.append((node.lineno, ast.unparse(node)))
    return out


def _read_all() -> dict[str, str]:
    return {p.relative_to(SRC).as_posix(): p.read_text(encoding="utf-8") for p in SRC.rglob("*.py")}


# ---------------------------------------------------------------- the real tree
def test_core_db_services_and_brain_do_not_import_the_api_layer():
    assert layering_violations(_read_all()) == []


def test_product_modules_do_not_import_each_others_internals():
    assert cross_product_violations(_read_all()) == []


def test_every_router_is_protected_or_named_public():
    source = (SRC / "api" / "v1" / "router.py").read_text(encoding="utf-8")
    loose = {target for _, target in unprotected_routers(source)}
    assert sorted(loose - set(PUBLIC_ROUTERS)) == [], (
        "a router is included without `protected`, `optional()` or `switchable()`"
    )
    assert sorted(set(PUBLIC_ROUTERS) - loose) == [], "a public allow-list entry no longer matches a router"


def test_the_allow_lists_have_no_stale_entries_and_every_entry_has_a_reason():
    files = _read_all()
    for allowed in (LAYERING_ALLOW, CROSS_PRODUCT_ALLOW):
        for (rel, name), reason in allowed.items():
            assert reason.strip(), (rel, name)
            assert rel in files, f"{rel} no longer exists: remove its allow-list entry"
            this, is_package = _dotted(rel)
            imports = imported_modules(files[rel], this, is_package)
            reached = {t for _, n, names in imports for t in targets(n, names)}
            assert name in reached, f"{rel} no longer imports {name}: remove its allow-list entry"
    assert all(reason.strip() for reason in PUBLIC_ROUTERS.values())


# ---------------------------------------------------------------- proof the checks would catch a violation
def test_a_new_services_to_api_import_would_fail_the_layering_check():
    bad = {"services/new_report.py": "def f():\n    from swing_trade_ml.api.deps import PlanAccess\n"}
    assert layering_violations(bad) == [("services/new_report.py", 2, "swing_trade_ml.api.deps")]
    typing_only = {
        "core/x.py": "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import swing_trade_ml.api.x\n"
    }
    assert layering_violations(typing_only), "a TYPE_CHECKING import is still a layering violation"
    relative = {"brain/x.py": "from ..api import deps\n"}
    assert layering_violations(relative)
    fine = {
        "services/ok.py": "from swing_trade_ml.core import plan_access\n",
        "api/v1/x.py": "import swing_trade_ml.api.deps\n",
    }
    assert layering_violations(fine) == []


def test_a_new_cross_product_import_would_fail_the_boundary_check():
    bad = {"services/finance/new.py": "from swing_trade_ml.brain.service import run\n"}
    assert cross_product_violations(bad) == [("services/finance/new.py", 1, "swing_trade_ml.brain.service")]
    lanes = {"shadow_lanes/x.py": "from swing_trade_ml.brain import reader\n"}
    assert cross_product_violations(lanes)
    inside = {"brain/x.py": "from swing_trade_ml.brain import reader\n"}
    assert cross_product_violations(inside) == []
    brain_lanes = {
        "brain/lanes/x.py": "from swing_trade_ml.brain import reader\n"
    }  # lanes belong to research_lanes
    assert cross_product_violations(brain_lanes)


def test_a_package_init_resolves_relative_imports_from_the_package_itself():
    # `from ..api import deps` in brain/__init__.py is swing_trade_ml.api, not swing_trade_ml.brain.api
    assert layering_violations({"brain/__init__.py": "from ..api import deps\n"}) == [
        ("brain/__init__.py", 1, "swing_trade_ml.api.deps")
    ]
    assert layering_violations({"brain/__init__.py": "from .reader import DatedReader\n"}) == []
    assert layering_violations({"services/__init__.py": "from .. import api\n"})


def test_importing_a_submodule_by_name_is_judged_as_that_submodule_not_the_package():
    # one allow-listed brain module must not let a lane file reach any other brain module
    both = {"shadow_lanes/lane_freeze.py": "from swing_trade_ml.brain import selection_lab, reader\n"}
    reader = ("shadow_lanes/lane_freeze.py", 1, "swing_trade_ml.brain.reader")
    assert cross_product_violations(both) == [reader]


def test_workers_and_ml_do_not_import_the_api_layer_either():
    assert layering_violations({"workers/x.py": "from swing_trade_ml.api.deps import PlanAccess\n"})
    assert layering_violations({"ml/x.py": "import swing_trade_ml.api.deps\n"})


def test_no_route_is_declared_straight_on_the_api_router():
    source = (SRC / "api" / "v1" / "router.py").read_text(encoding="utf-8")
    assert direct_routes(source) == []


def test_a_route_declared_straight_on_the_api_router_would_be_caught():
    bad = '@api_router.get("/x")\ndef x():\n    pass\n\napi_router.add_api_route("/y", y)\n'
    assert [line for line, _ in direct_routes(bad)] == [1, 5]
    assert direct_routes("@other.get('/x')\ndef x():\n    pass\n") == []


def test_a_new_unprotected_router_would_fail_the_router_check():
    bad = (
        "protected = []\n"
        "api_router.include_router(a.router, dependencies=protected)\n"
        "api_router.include_router(b.router, dependencies=optional('x'))\n"
        "api_router.include_router(c.router)\n"
        "api_router.include_router(d.router, dependencies=[])\n"
    )
    assert unprotected_routers(bad) == [(4, "c.router"), (5, "d.router")]
