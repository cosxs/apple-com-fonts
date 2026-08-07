from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.request import getproxies

import httpx

from apple_com_fonts import __version__

APPLE_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    f"Chrome/140.0 Safari/537.36 apple-com-fonts/{__version__}"
)

RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True, slots=True)
class ProxySettings:
    url: str | None
    trust_env: bool


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    retries: int = 2
    base_delay: float = 0.4

    def __post_init__(self) -> None:
        if self.retries < 0:
            raise ValueError("retries cannot be negative")
        if self.base_delay < 0:
            raise ValueError("base_delay cannot be negative")

    def attempts(self) -> range:
        return range(self.retries + 1)

    def can_retry(self, attempt: int) -> bool:
        return attempt < self.retries

    @staticmethod
    def should_retry_status(status_code: int) -> bool:
        return status_code in RETRYABLE_STATUS_CODES

    @staticmethod
    def should_retry_exception(error: httpx.HTTPError) -> bool:
        return isinstance(error, httpx.TransportError)

    async def wait(self, attempt: int) -> None:
        await asyncio.sleep(self.base_delay * (2**attempt))


def resolve_proxy_settings(
    proxy: str | None,
    *,
    system_proxies: Mapping[str, str] | None = None,
) -> ProxySettings:
    if proxy == "none":
        return ProxySettings(url=None, trust_env=False)
    if proxy == "env":
        return ProxySettings(url=None, trust_env=True)
    if proxy and proxy != "auto":
        return ProxySettings(url=proxy, trust_env=False)

    available_proxies = getproxies() if system_proxies is None else system_proxies
    automatic_proxy = available_proxies.get("https") or available_proxies.get("http")
    if automatic_proxy:
        return ProxySettings(url=automatic_proxy, trust_env=False)
    return ProxySettings(url=None, trust_env=True)


def build_http_client(
    *,
    timeout: float,
    proxy: str | None,
) -> httpx.AsyncClient:
    proxy_settings = resolve_proxy_settings(proxy)
    kwargs: dict[str, Any] = {
        "follow_redirects": True,
        "http2": True,
        "timeout": httpx.Timeout(timeout),
        "trust_env": proxy_settings.trust_env,
    }
    if proxy_settings.url:
        kwargs["proxy"] = proxy_settings.url
    return httpx.AsyncClient(**kwargs)
