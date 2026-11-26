"""One small HTTP helper for outbound calls (#259): a timeout on every call, 2 retries with backoff, and a
classified error. Used by the NSE feeds, company filings and AMFI.
Before this, only brokers/kite.py retried.

Retries happen for a timeout, a network error, HTTP 429 and HTTP 5xx. Other 4xx answers are final: asking
again
gets the same answer. The error text never carries the URL query (it can hold a token).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Literal

import httpx

ErrorKind = Literal["timeout", "network", "server", "rate_limited", "not_found", "client"]

DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
RETRIES = 2
BACKOFF_SECONDS = (0.5, 1.5)  # wait before retry 1 and retry 2

#: Test hooks: a transport to use instead of the network, and the sleep function.
_TRANSPORT: Any = None
_sleep: Callable[[float], None] = time.sleep


class HttpError(Exception):
    """A call failed for good (retries used up, or not worth retrying). `kind` says why."""

    def __init__(self, kind: ErrorKind, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.status = status

    @property
    def retryable(self) -> bool:
        return self.kind in ("timeout", "network", "server", "rate_limited")


def _where(url: str) -> str:
    return url.split("?", 1)[0]


def _classify_status(status: int, url: str) -> HttpError:
    kind: ErrorKind
    if status == 429:
        kind = "rate_limited"
    elif status >= 500:
        kind = "server"
    elif status == 404:
        kind = "not_found"
    else:
        kind = "client"
    return HttpError(kind, f"HTTP {status} from {_where(url)}", status=status)


def _classify_exc(exc: Exception, url: str) -> HttpError:
    kind: ErrorKind = "timeout" if isinstance(exc, httpx.TimeoutException) else "network"
    return HttpError(kind, f"{type(exc).__name__} calling {_where(url)}")


def _check(resp: httpx.Response, url: str, ok_statuses: Iterable[int]) -> None:
    if resp.status_code >= 400 and resp.status_code not in tuple(ok_statuses):
        raise _classify_status(resp.status_code, url)


def _backoff(attempt: int) -> float:
    return BACKOFF_SECONDS[min(attempt - 1, len(BACKOFF_SECONDS) - 1)]


def get(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: httpx.Timeout | float = DEFAULT_TIMEOUT,
    retries: int = RETRIES,
    ok_statuses: Iterable[int] = (),
    follow_redirects: bool = True,
    transport: Any = None,
    sleep: Callable[[float], None] | None = None,
    **kw: Any,
) -> httpx.Response:
    """GET with a timeout and retries. Raises HttpError; a status in `ok_statuses` (say 404) is returned."""
    pause = sleep or _sleep
    use = transport or _TRANSPORT
    last: HttpError | None = None
    for attempt in range(retries + 1):
        if attempt:
            pause(_backoff(attempt))
        try:
            with httpx.Client(
                headers=headers, timeout=timeout, follow_redirects=follow_redirects, transport=use
            ) as client:
                resp = client.get(url, **kw)
            _check(resp, url, ok_statuses)
            return resp
        except HttpError as exc:
            last = exc
        except httpx.HTTPError as exc:
            last = _classify_exc(exc, url)
        if not last.retryable:
            break
    assert last is not None
    raise last


async def aget(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: httpx.Timeout | float = DEFAULT_TIMEOUT,
    retries: int = RETRIES,
    ok_statuses: Iterable[int] = (),
    follow_redirects: bool = True,
    transport: Any = None,
    sleep: Callable[[float], Any] | None = None,
    **kw: Any,
) -> httpx.Response:
    """Async twin of `get`."""
    use = transport or _TRANSPORT
    last: HttpError | None = None
    for attempt in range(retries + 1):
        if attempt:
            await (sleep(_backoff(attempt)) if sleep else asyncio.sleep(_backoff(attempt)))
        try:
            async with httpx.AsyncClient(
                headers=headers, timeout=timeout, follow_redirects=follow_redirects, transport=use
            ) as client:
                resp = await client.get(url, **kw)
            _check(resp, url, ok_statuses)
            return resp
        except HttpError as exc:
            last = exc
        except httpx.HTTPError as exc:
            last = _classify_exc(exc, url)
        if not last.retryable:
            break
    assert last is not None
    raise last
