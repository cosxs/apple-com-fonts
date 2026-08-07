import httpx
import pytest

from apple_com_fonts.discovery import RegionDirectoryError, WssDiscovery

DIRECTORY_URL = "https://www.apple.com/choose-country-region/"


def region_directory(*pages: tuple[str, str]) -> str:
    return "".join(
        f'<a class="block" data-analytics-title="{region}" href="{url}">{region}</a>'
        for region, url in pages
    )


@pytest.mark.asyncio
async def test_discovery_rejects_invalid_retry_and_concurrency_limits() -> None:
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="concurrency must be at least 1"):
            WssDiscovery(client, concurrency=0)
        with pytest.raises(ValueError, match="retries cannot be negative"):
            WssDiscovery(client, retries=-1)


@pytest.mark.asyncio
async def test_discovery_uses_only_global_homepages_then_probes_observed_families() -> None:
    home_css = "https://www.apple.com/wss/fonts?families=SF+Pro,v3:400"
    japan_css = "https://www.apple.com/wss/fonts?family=SF+Pro+JP&weights=400&v=1"

    probe_fonts = {
        "https://www.apple.com/wss/fonts?families=SF+Pro,v1": (
            "/wss/fonts/SF-Pro-Display/v1/regular.woff2"
        ),
        "https://www.apple.com/wss/fonts?families=SF+Pro,v2": (
            "/wss/fonts/SF-Pro-Display/v2/regular.woff2"
        ),
        "https://www.apple.com/wss/fonts?families=SF+Pro,v3": (
            "/wss/fonts/SF-Pro-Display/v3/regular.woff2"
        ),
        "https://www.apple.com/wss/fonts?families=SF+Pro,v4": ("/wss/fonts/SF-Pro/v4/SFPro.woff2"),
        "https://www.apple.com/wss/fonts?families=SF+Pro+JP,v1": (
            "/wss/fonts/SF-Pro-JP/v1/regular.woff2"
        ),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == DIRECTORY_URL:
            return httpx.Response(
                200,
                text=region_directory(
                    ("us", "https://www.apple.com/"),
                    ("jp", "https://www.apple.com/jp/"),
                ),
                request=request,
            )
        if url == "https://www.apple.com/":
            return httpx.Response(
                200,
                text=f'<link rel="stylesheet" href="{home_css}">',
                request=request,
            )
        if url == "https://www.apple.com/jp/":
            return httpx.Response(
                200,
                text=f'<link rel="stylesheet" href="{japan_css}">',
                request=request,
            )
        if url == home_css:
            assert request.headers["referer"] == "https://www.apple.com/"
            return httpx.Response(
                200,
                text="@font-face { src: url('/wss/fonts/SF-Pro-Display/v3/regular.woff2'); }",
                request=request,
            )
        if url == japan_css:
            assert request.headers["referer"] == "https://www.apple.com/"
            return httpx.Response(
                200,
                text="@font-face { src: url('/wss/fonts/SF-Pro-JP/v1/regular.woff2'); }",
                request=request,
            )
        if font_path := probe_fonts.get(url):
            return httpx.Response(
                200,
                text=f"@font-face {{ src: url('{font_path}'); }}",
                request=request,
            )
        if url.startswith("https://www.apple.com/wss/fonts?families="):
            return httpx.Response(400, request=request)
        raise AssertionError(f"Unexpected request: {url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        report = await WssDiscovery(client, concurrency=2, retries=0).discover()

    assert report.region_directory.homepages_discovered == 2
    assert report.as_dict()["summary"] == {
        "homepages_requested": 2,
        "homepages_successful": 2,
        "stylesheets_requested": 11,
        "stylesheets_successful": 7,
        "unique_font_urls": 5,
    }
    assert [font.path for font in sorted(report.fonts, key=lambda item: item.path)] == [
        "/wss/fonts/SF-Pro-Display/v1/regular.woff2",
        "/wss/fonts/SF-Pro-Display/v2/regular.woff2",
        "/wss/fonts/SF-Pro-Display/v3/regular.woff2",
        "/wss/fonts/SF-Pro-JP/v1/regular.woff2",
        "/wss/fonts/SF-Pro/v4/SFPro.woff2",
    ]
    manifest = report.as_dict()
    assert manifest["schema_version"] == 4
    assert "catalog_sources" not in manifest
    assert "pages" not in manifest
    assert {page["url"] for page in manifest["homepages"]} == {
        "https://www.apple.com/",
        "https://www.apple.com/jp/",
    }


@pytest.mark.asyncio
async def test_discovery_requires_the_official_region_directory() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RegionDirectoryError, match="returned HTTP 404"):
            await WssDiscovery(client, retries=0).discover()


@pytest.mark.asyncio
async def test_discovery_records_and_skips_failed_homepages() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == DIRECTORY_URL:
            return httpx.Response(
                200,
                text=region_directory(
                    ("us", "https://www.apple.com/"),
                    ("jp", "https://www.apple.com/jp/"),
                ),
                request=request,
            )
        if url == "https://www.apple.com/":
            return httpx.Response(404, request=request)
        if url == "https://www.apple.com/jp/":
            raise httpx.ConnectError("connection failed", request=request)
        raise AssertionError(f"Unexpected request: {url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        report = await WssDiscovery(client, retries=0).discover()

    assert not report.fonts
    assert [(page.url, page.status) for page in report.homepages] == [
        ("https://www.apple.com/", 404),
        ("https://www.apple.com/jp/", None),
    ]
    assert report.homepages[0].error == "HTTP 404"
    assert report.homepages[1].error == "ConnectError: connection failed"
