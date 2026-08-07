from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import httpx

from apple_com_fonts.models import FontLink
from apple_com_fonts.network import APPLE_USER_AGENT, RetryPolicy

DownloadStatus = Literal["downloaded", "skipped", "failed"]

_FONT_SIGNATURES = {
    ".otf": (b"OTTO", b"\x00\x01\x00\x00"),
    ".ttf": (b"\x00\x01\x00\x00", b"true", b"OTTO"),
    ".woff": (b"wOFF",),
    ".woff2": (b"wOF2",),
}


@dataclass(slots=True)
class DownloadResult:
    path: str
    url: str
    local_path: str | None
    status: DownloadStatus
    size: int = 0
    content_type: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "url": self.url,
            "local_path": self.local_path,
            "status": self.status,
            "size": self.size,
            "content_type": self.content_type,
            "etag": self.etag,
            "last_modified": self.last_modified,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class _DownloadAttempt:
    result: DownloadResult
    retryable: bool = False


@dataclass(slots=True)
class DownloadReport:
    destination: str
    results: list[DownloadResult]
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def as_dict(self) -> dict[str, Any]:
        downloaded = [result for result in self.results if result.status == "downloaded"]
        skipped = [result for result in self.results if result.status == "skipped"]
        failed = [result for result in self.results if result.status == "failed"]
        return {
            "schema_version": 1,
            "generated_at": self.generated_at,
            "destination": self.destination,
            "summary": {
                "files_requested": len(self.results),
                "files_downloaded": len(downloaded),
                "files_skipped": len(skipped),
                "files_failed": len(failed),
                "bytes_downloaded": sum(result.size for result in downloaded),
                "bytes_stored": sum(result.size for result in downloaded + skipped),
            },
            "files": [
                result.as_dict() for result in sorted(self.results, key=lambda item: item.path)
            ],
        }


class FontDownloader:
    """Download and validate discovered fonts behind one asynchronous interface."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        concurrency: int = 8,
        retries: int = 2,
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be at least 1")
        self._client = client
        self._semaphore = asyncio.Semaphore(concurrency)
        self._retry_policy = RetryPolicy(retries=retries)

    async def download(
        self,
        fonts: list[FontLink],
        destination: Path,
    ) -> DownloadReport:
        destination_root = destination.resolve()
        results = await asyncio.gather(
            *(self._download_one(font, destination_root) for font in sorted(fonts, key=_font_key))
        )
        return DownloadReport(destination=str(destination_root), results=list(results))

    async def _download_one(self, font: FontLink, destination: Path) -> DownloadResult:
        try:
            local_path = _font_destination(font.path, destination)
        except ValueError as exc:
            return DownloadResult(
                path=font.path,
                url=font.canonical_url,
                local_path=None,
                status="failed",
                error=str(exc),
            )

        if _is_valid_font(local_path):
            return DownloadResult(
                path=font.path,
                url=font.canonical_url,
                local_path=str(local_path),
                status="skipped",
                size=local_path.stat().st_size,
            )

        local_path.parent.mkdir(parents=True, exist_ok=True)
        partial_path = local_path.with_name(f".{local_path.name}.{uuid4().hex}.part")
        headers = {
            "Accept": "font/woff2,font/woff,font/ttf,application/octet-stream,*/*;q=0.1",
            "Referer": _font_referer(font),
            "User-Agent": APPLE_USER_AGENT,
        }

        try:
            async with self._semaphore:
                for attempt in self._retry_policy.attempts():
                    outcome = await self._download_attempt(
                        font,
                        local_path,
                        partial_path,
                        headers,
                    )
                    if not outcome.retryable or not self._retry_policy.can_retry(attempt):
                        return outcome.result
                    await self._retry_policy.wait(attempt)
                raise RuntimeError("retry policy produced no attempts")
        finally:
            partial_path.unlink(missing_ok=True)

    async def _download_attempt(
        self,
        font: FontLink,
        local_path: Path,
        partial_path: Path,
        headers: dict[str, str],
    ) -> _DownloadAttempt:
        partial_path.unlink(missing_ok=True)
        try:
            async with self._client.stream(
                "GET",
                font.canonical_url,
                headers=headers,
            ) as response:
                if response.status_code != 200:
                    return _DownloadAttempt(
                        result=DownloadResult(
                            path=font.path,
                            url=font.canonical_url,
                            local_path=str(local_path),
                            status="failed",
                            content_type=response.headers.get("content-type"),
                            error=f"HTTP {response.status_code}",
                        ),
                        retryable=self._retry_policy.should_retry_status(response.status_code),
                    )
                with partial_path.open("wb") as output:
                    async for chunk in response.aiter_bytes():
                        output.write(chunk)
                content_type = response.headers.get("content-type")
                etag = response.headers.get("etag")
                last_modified = response.headers.get("last-modified")
        except httpx.HTTPError as exc:
            return _DownloadAttempt(
                result=DownloadResult(
                    path=font.path,
                    url=font.canonical_url,
                    local_path=str(local_path),
                    status="failed",
                    error=f"{type(exc).__name__}: {exc}",
                ),
                retryable=self._retry_policy.should_retry_exception(exc),
            )

        if not _is_valid_font(partial_path, expected_suffix=local_path.suffix):
            return _DownloadAttempt(
                result=DownloadResult(
                    path=font.path,
                    url=font.canonical_url,
                    local_path=str(local_path),
                    status="failed",
                    size=partial_path.stat().st_size,
                    content_type=content_type,
                    etag=etag,
                    last_modified=last_modified,
                    error=f"invalid {local_path.suffix.lower()} font signature",
                )
            )

        partial_path.replace(local_path)
        return _DownloadAttempt(
            result=DownloadResult(
                path=font.path,
                url=font.canonical_url,
                local_path=str(local_path),
                status="downloaded",
                size=local_path.stat().st_size,
                content_type=content_type,
                etag=etag,
                last_modified=last_modified,
            )
        )


def _font_key(font: FontLink) -> str:
    return font.path


def _font_destination(font_path: str, destination: Path) -> Path:
    decoded = PurePosixPath(unquote(font_path))
    try:
        relative = decoded.relative_to(PurePosixPath("/wss/fonts"))
    except ValueError as exc:
        raise ValueError(f"not a WSS font path: {font_path}") from exc
    if len(relative.parts) < 3 or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError(f"unsafe WSS font path: {font_path}")

    extension = PurePosixPath(relative.name).suffix.lower()
    if extension not in _FONT_SIGNATURES:
        raise ValueError(f"unsupported font format: {extension or '(none)'}")

    local_path = destination.joinpath(
        *relative.parts[:-1],
        extension.removeprefix("."),
        relative.name,
    )
    if not local_path.parent.resolve().is_relative_to(destination):
        raise ValueError(f"unsafe local font path: {font_path}")
    return local_path


def _font_referer(font: FontLink) -> str:
    sources = sorted(font.css_sources)
    for source in sources:
        parsed = urlsplit(source)
        if parsed.hostname == "www.apple.com" and parsed.path == "/wss/fonts":
            return source
    return sources[0] if sources else "https://www.apple.com/"


def _is_valid_font(path: Path, *, expected_suffix: str | None = None) -> bool:
    if not path.is_file() or path.stat().st_size < 4:
        return False
    suffix = (expected_suffix or path.suffix).lower()
    signatures = _FONT_SIGNATURES.get(suffix)
    if signatures is None:
        return False
    with path.open("rb") as font_file:
        signature = font_file.read(4)
    return signature in signatures
