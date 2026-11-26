"""The how-to for adding a model or connector (#259) must not go stale.

Every backticked repo path in docs/how-to/add-a-model-or-connector.md must exist, every backticked
`swing_trade_ml...` name must be importable or defined, every backticked test name must exist in tests/,
and every `swingtrade <command>` must be a command in cli.py.
If code moves, this test says which line of the doc to fix.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
PKG = BACKEND / "src" / "swing_trade_ml"
DOC = REPO / "docs" / "how-to" / "add-a-model-or-connector.md"

TICKED = re.compile(r"`([^`\n]+)`")
PATH_EXT = (".py", ".md", ".yml", ".sh", ".json")


def _tokens() -> list[str]:
    return TICKED.findall(DOC.read_text(encoding="utf-8"))


def _paths() -> list[str]:
    return [t for t in _tokens() if "/" in t and " " not in t and t.endswith(PATH_EXT)]


def _symbols() -> list[str]:
    return [t.removesuffix("()") for t in _tokens() if re.fullmatch(r"swing_trade_ml(\.\w+)+(\(\))?", t)]


def _resolve(dotted: str) -> object:
    parts = dotted.split(".")
    for cut in range(len(parts), 0, -1):
        try:
            obj = importlib.import_module(".".join(parts[:cut]))
        except ModuleNotFoundError:
            continue
        for attr in parts[cut:]:
            obj = getattr(obj, attr)
        return obj
    raise ModuleNotFoundError(dotted)


def test_the_doc_exists_and_names_things_to_check():
    assert DOC.is_file()
    assert len(_paths()) >= 8 and len(_symbols()) >= 15


@pytest.mark.parametrize("path", sorted(set(_paths()) if DOC.is_file() else []))
def test_every_path_in_the_doc_exists(path):
    assert any((root / path).is_file() for root in (REPO, PKG)), f"{path} named in the how-to does not exist"


@pytest.mark.parametrize("name", sorted(set(_symbols()) if DOC.is_file() else []))
def test_every_function_or_class_in_the_doc_is_defined(name):
    _resolve(name)  # raises if the module or the name is gone


def test_every_test_named_in_the_doc_exists():
    tests = "\n".join(p.read_text(encoding="utf-8") for p in (BACKEND / "tests").glob("test_*.py"))
    named = [t for t in _tokens() if re.fullmatch(r"test_\w+", t)]
    assert named, "the how-to should name the module-declaration test"
    for t in named:
        assert f"def {t}(" in tests, f"test {t} named in the how-to does not exist"


def test_every_swingtrade_command_in_the_doc_is_real():
    cli = (PKG / "cli.py").read_text(encoding="utf-8")
    for t in _tokens():
        if t.startswith("swingtrade "):
            for word in t.split()[1:]:
                assert word.lstrip("-") in cli, f"`{t}`: {word} not found in cli.py"
