from pathlib import Path

import httpx
import pytest

from apple_com_fonts import __version__
from apple_com_fonts.downloader import FontDownloader
from apple_com_fonts.models import FontLink


def font_link(path: str, *, css_source: str = "https://www.apple.com/wss/fonts?families=Test,v1"):
    return FontLink(
        path=path,
        canonical_url=f"https://www.apple.com{path}",
        css_sources={css_source},
    )


@pytest.mark.asyncio
async def test_downloader_rejects_invalid_retry_and_concurrency_limits() -> None:
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="concurrency must be at least 1"):
            FontDownloader(client, concurrency=0)
        with pytest.raises(ValueError, match="retries cannot be negative"):
            FontDownloader(client, retries=-1)


@pytest.mark.asyncio
async def test_downloader_organizes_and_validates_font_files(tmp_path: Path) -> None:
    font = font_link("/wss/fonts/SF-Pro-SC/v1/PingFangSC-Regular.woff2")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["referer"] == next(iter(font.css_sources))
        assert f"apple-com-fonts/{__version__}" in request.headers["user-agent"]
        return httpx.Response(
            200,
            content=b"wOF2font-data",
            headers={"content-type": "font/woff2", "etag": 'W/"font"'},
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        report = await FontDownloader(client, concurrency=2, retries=0).download(
            [font],
            tmp_path / "fonts",
        )

    expected = tmp_path / "fonts/SF-Pro-SC/v1/woff2/PingFangSC-Regular.woff2"
    assert expected.read_bytes() == b"wOF2font-data"
    assert report.as_dict()["summary"] == {
        "files_requested": 1,
        "files_downloaded": 1,
        "files_skipped": 0,
        "files_failed": 0,
        "bytes_downloaded": 13,
        "bytes_stored": 13,
    }
    assert report.results[0].local_path == str(expected)
    assert report.results[0].content_type == "font/woff2"


@pytest.mark.asyncio
async def test_downloader_skips_existing_valid_fonts_without_requesting(tmp_path: Path) -> None:
    font = font_link("/wss/fonts/SF-Pro/v4/SFPro.ttf")
    existing = tmp_path / "fonts/SF-Pro/v4/ttf/SFPro.ttf"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"\x00\x01\x00\x00existing")

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"Unexpected request: {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        report = await FontDownloader(client, retries=0).download([font], tmp_path / "fonts")

    assert report.results[0].status == "skipped"
    assert existing.read_bytes() == b"\x00\x01\x00\x00existing"


@pytest.mark.asyncio
async def test_downloader_replaces_invalid_files_only_after_valid_response(tmp_path: Path) -> None:
    font = font_link("/wss/fonts/SF-Pro/v4/SFPro.woff")
    existing = tmp_path / "fonts/SF-Pro/v4/woff/SFPro.woff"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"broken")

    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, request=request)
        return httpx.Response(200, content=b"wOFFreplacement", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        report = await FontDownloader(client, retries=1).download([font], tmp_path / "fonts")

    assert attempts == 2
    assert report.results[0].status == "downloaded"
    assert existing.read_bytes() == b"wOFFreplacement"
    assert not list((tmp_path / "fonts").rglob("*.part"))


@pytest.mark.asyncio
async def test_downloader_records_failures_and_preserves_invalid_file(
    tmp_path: Path,
) -> None:
    good = font_link("/wss/fonts/SF-Pro/v4/SFPro.woff2")
    bad = font_link("/wss/fonts/SF-Pro/v4/SFProItalic.ttf")
    existing = tmp_path / "fonts/SF-Pro/v4/ttf/SFProItalic.ttf"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"broken")

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("SFPro.woff2"):
            return httpx.Response(200, content=b"wOF2valid", request=request)
        return httpx.Response(200, content=b"not-a-font", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        report = await FontDownloader(client, concurrency=2, retries=0).download(
            [good, bad],
            tmp_path / "fonts",
        )

    results = {result.path: result for result in report.results}
    assert results[good.path].status == "downloaded"
    assert results[bad.path].status == "failed"
    assert results[bad.path].error == "invalid .ttf font signature"
    assert existing.read_bytes() == b"broken"


@pytest.mark.asyncio
async def test_downloader_rejects_unsafe_or_unsupported_paths(tmp_path: Path) -> None:
    unsafe = font_link("/wss/fonts/../escape.ttf")
    unsupported = font_link("/wss/fonts/SF-Pro/v4/font.eot")

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"Unexpected request: {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        report = await FontDownloader(client, retries=0).download(
            [unsafe, unsupported],
            tmp_path / "fonts",
        )

    assert [result.status for result in report.results] == ["failed", "failed"]
    assert any("unsafe WSS font path" in (result.error or "") for result in report.results)
    assert any("unsupported font format: .eot" in (result.error or "") for result in report.results)
