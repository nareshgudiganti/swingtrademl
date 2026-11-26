"""Adapter convention for outside providers (#259). No provider is added here; new ones follow this shape.

A provider is a small class with `name`, optional `module_id` (its on/off switch in the module registry,
core/modules.py), `fetch()` and `health()`. Every result carries `fetched_at`.
`fetch_with_stale` turns a failure into a stale result that still holds the last good value, so a screen shows
"as of <time>" instead of an error, and one provider failing never touches another. Test double: FakeAdapter.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from swing_trade_ml.core.http_client import HttpError


@dataclass(frozen=True, slots=True)
class Fetched:
    value: Any
    fetched_at: datetime | None  # when `value` was really fetched; None = never
    ok: bool = True
    stale: bool = False  # True: the last attempt failed, `value` (if any) is older data
    disabled: bool = False  # True: the provider's module switch is off
    error: str = ""


@dataclass(frozen=True, slots=True)
class Health:
    ok: bool
    last_success_at: datetime | None = None
    last_error: str = ""


@runtime_checkable
class Adapter(Protocol):
    name: str
    module_id: str | None

    def fetch(self) -> Fetched: ...

    def health(self) -> Health: ...


class _Switches(Protocol):
    def enabled(self, module_id: str, *, fresh: bool = False) -> bool: ...


def _is_on(module_id: str | None, switches: _Switches | None) -> bool:
    if not module_id:
        return True
    if switches is None:
        from swing_trade_ml.core.modules import switches as registry_switches

        switches = registry_switches
    try:
        return switches.enabled(module_id)
    except KeyError:  # an id the registry does not know is not switched off by it
        return True


_last_good: dict[str, Fetched] = {}


def fetch_with_stale(adapter: Adapter, *, switches: _Switches | None = None) -> Fetched:
    """Never raises. Off -> disabled result; failure -> stale result carrying the last good value."""
    if not _is_on(adapter.module_id, switches):
        return Fetched(None, None, ok=False, disabled=True)
    try:
        got = adapter.fetch()
    except HttpError as exc:
        prior = _last_good.get(adapter.name)
        return Fetched(
            prior.value if prior else None,
            prior.fetched_at if prior else None,
            ok=False,
            stale=True,
            error=str(exc),
        )
    _last_good[adapter.name] = got
    return got


@dataclass
class FakeAdapter:
    """Test double. Set `fail_with` to make fetch raise; `calls` counts attempts."""

    name: str
    value: Any = None
    module_id: str | None = None
    fail_with: HttpError | None = None
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    calls: int = 0
    _last_ok: datetime | None = None
    _last_error: str = ""

    def fetch(self) -> Fetched:
        self.calls += 1
        if self.fail_with is not None:
            self._last_error = str(self.fail_with)
            raise self.fail_with
        self._last_error = ""
        self._last_ok = self.clock()
        return Fetched(self.value, self._last_ok)

    def health(self) -> Health:
        return Health(ok=not self._last_error, last_success_at=self._last_ok, last_error=self._last_error)
