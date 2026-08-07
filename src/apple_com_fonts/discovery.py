from __future__ import annotations

import asyncio
from collections.abc import Mapping
from urllib.parse import urlsplit

import httpx

from apple_com_fonts.models import (
    DiscoveryReport,
    FontLink,
    HomepageResult,
    RegionDirectoryResult,
    StylesheetResult,
)
from apple_com_fonts.network import APPLE_USER_AGENT, RetryPolicy
from apple_com_fonts.parsing import (
    WssFamilyVersion,
    build_wss_stylesheet_url,
    canonical_font_path,
    canonical_font_url,
    extract_font_urls,
    extract_region_pages,
    extract_wss_family_versions,
    extract_wss_stylesheets,
)

REGION_DIRECTORY_URL = "https://www.apple.com/choose-country-region/"
_MAX_WSS_VERSION = 20


class RegionDirectoryError(RuntimeError):
    """Raised when Apple cannot provide the official global homepage directory."""


class WssDiscovery:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        concurrency: int = 16,
        retries: int = 2,
        region_directory_url: str = REGION_DIRECTORY_URL,
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be at least 1")
        self._client = client
        self._semaphore = asyncio.Semaphore(concurrency)
        self._retry_policy = RetryPolicy(retries=retries)
        self._region_directory_url = region_directory_url

    async def discover(self) -> DiscoveryReport:
        directory_result, region_homepages = await self._discover_region_directory()
        homepage_regions: dict[str, set[str]] = {}
        for region, homepage_url in region_homepages.items():
            homepage_regions.setdefault(homepage_url, set()).add(region)
        homepage_results = await self._discover_homepages(homepage_regions)

        css_sources: dict[str, set[str]] = {}
        for homepage in homepage_results:
            for css_url in homepage.css_urls:
                css_sources.setdefault(css_url, set()).add(homepage.url)

        stylesheet_results, direct_fonts = await self._discover_stylesheets(css_sources)
        discovered_families = {
            family
            for stylesheet_url in css_sources
            for family in extract_wss_family_versions(stylesheet_url)
        }
        probe_results, probe_fonts = await self._probe_family_versions(
            discovered_families,
            stylesheet_results,
        )
        stylesheet_results.extend(probe_results)
        discovered_fonts = self._merge_fonts(direct_fonts, probe_fonts)
        return DiscoveryReport(
            region_directory=directory_result,
            homepages=homepage_results,
            stylesheets=stylesheet_results,
            fonts=discovered_fonts,
        )

    async def _discover_region_directory(
        self,
    ) -> tuple[RegionDirectoryResult, dict[str, str]]:
        response, error = await self._get(
            self._region_directory_url,
            accept="text/html,application/xhtml+xml",
        )
        if response is None:
            raise RegionDirectoryError(
                f"failed to fetch official region directory: {error or 'request failed'}"
            )
        if response.status_code != 200:
            raise RegionDirectoryError(
                f"official region directory returned HTTP {response.status_code}"
            )

        try:
            pages = extract_region_pages(response.text, str(response.url))
        except ValueError as exc:
            raise RegionDirectoryError(f"invalid official region directory: {exc}") from exc
        if not pages:
            raise RegionDirectoryError("official region directory contained no regional homepages")

        return (
            RegionDirectoryResult(
                url=str(response.url),
                source="official",
                status=response.status_code,
                homepages_discovered=len(pages),
            ),
            pages,
        )

    async def _probe_family_versions(
        self,
        families: set[WssFamilyVersion],
        known_results: list[StylesheetResult],
    ) -> tuple[list[StylesheetResult], list[FontLink]]:
        states = {
            item.family: {
                "observed": item.version,
                "next": 1,
                "misses": 0,
            }
            for item in sorted(families)
        }
        for item in families:
            states[item.family]["observed"] = max(states[item.family]["observed"], item.version)

        all_results: list[StylesheetResult] = []
        font_batches: list[list[FontLink]] = []
        by_url = {result.url: result for result in known_results}
        while states:
            probes = {
                build_wss_stylesheet_url(family, state["next"]): {
                    f"version-probe:{family},v{state['next']}"
                }
                for family, state in states.items()
                if build_wss_stylesheet_url(family, state["next"]) not in by_url
            }
            if probes:
                results, fonts = await self._discover_stylesheets(probes)
                all_results.extend(results)
                font_batches.append(fonts)
                by_url.update({result.url: result for result in results})
            completed: set[str] = set()
            for family, state in states.items():
                version = state["next"]
                url = build_wss_stylesheet_url(family, version)
                result = by_url.get(url)
                successful = result is not None and result.status == 200 and result.font_count > 0
                if version > state["observed"]:
                    state["misses"] = 0 if successful else state["misses"] + 1
                state["next"] += 1
                if state["misses"] >= 2 or state["next"] > _MAX_WSS_VERSION:
                    completed.add(family)
            for family in completed:
                del states[family]

        return all_results, self._merge_fonts(*font_batches)

    @staticmethod
    def _merge_fonts(*groups: list[FontLink]) -> list[FontLink]:
        merged: dict[str, FontLink] = {}
        for group in groups:
            for font in group:
                target = merged.setdefault(
                    font.path,
                    FontLink(path=font.path, canonical_url=font.canonical_url),
                )
                target.observed_urls.update(font.observed_urls)
                target.css_sources.update(font.css_sources)
        return list(merged.values())

    async def _discover_homepages(
        self,
        homepage_regions: Mapping[str, set[str]],
    ) -> list[HomepageResult]:
        return list(
            await asyncio.gather(
                *(
                    self._discover_homepage(url, regions)
                    for url, regions in sorted(homepage_regions.items())
                )
            )
        )

    async def _discover_homepage(self, url: str, regions: set[str]) -> HomepageResult:
        response, error = await self._get(url, accept="text/html,application/xhtml+xml")
        if response is None:
            return HomepageResult(url=url, status=None, regions=set(regions), error=error)
        if response.status_code != 200:
            return HomepageResult(
                url=str(response.url),
                status=response.status_code,
                regions=set(regions),
                error=f"HTTP {response.status_code}",
            )
        return HomepageResult(
            url=str(response.url),
            status=response.status_code,
            regions=set(regions),
            css_urls=extract_wss_stylesheets(response.text, str(response.url)),
        )

    async def _discover_stylesheets(
        self,
        css_sources: Mapping[str, set[str]],
    ) -> tuple[list[StylesheetResult], list[FontLink]]:
        tasks = [self._discover_stylesheet(url, sources) for url, sources in css_sources.items()]
        results = await asyncio.gather(*tasks)

        fonts_by_path: dict[str, FontLink] = {}
        stylesheet_results: list[StylesheetResult] = []
        for stylesheet, font_urls in results:
            stylesheet_results.append(stylesheet)
            for observed_url in font_urls:
                path = canonical_font_path(observed_url)
                font = fonts_by_path.setdefault(
                    path,
                    FontLink(path=path, canonical_url=canonical_font_url(observed_url)),
                )
                font.observed_urls.add(observed_url)
                font.css_sources.add(stylesheet.url)

        return stylesheet_results, list(fonts_by_path.values())

    async def _discover_stylesheet(
        self,
        url: str,
        sources: set[str],
    ) -> tuple[StylesheetResult, list[str]]:
        result = StylesheetResult(url=url, sources=set(sources))
        parsed_url = urlsplit(url)
        referer = f"{parsed_url.scheme}://{parsed_url.netloc}/"
        response, error = await self._get(
            url,
            accept="text/css,*/*;q=0.1",
            referer=referer,
        )
        if response is None:
            result.error = error
            return result, []

        result.url = str(response.url)
        result.status = response.status_code
        result.content_type = response.headers.get("content-type")
        result.etag = response.headers.get("etag")
        result.last_modified = response.headers.get("last-modified")
        if response.status_code != 200:
            result.error = f"HTTP {response.status_code}"
            return result, []

        font_urls = extract_font_urls(response.text, str(response.url))
        result.font_count = len(font_urls)
        return result, font_urls

    async def _get(
        self,
        url: str,
        *,
        accept: str,
        referer: str | None = None,
    ) -> tuple[httpx.Response | None, str | None]:
        headers = {"Accept": accept, "User-Agent": APPLE_USER_AGENT}
        if referer:
            headers["Referer"] = referer
        async with self._semaphore:
            for attempt in self._retry_policy.attempts():
                try:
                    response = await self._client.get(
                        url,
                        headers=headers,
                    )
                except httpx.HTTPError as exc:
                    if not self._retry_policy.should_retry_exception(
                        exc
                    ) or not self._retry_policy.can_retry(attempt):
                        return None, f"{type(exc).__name__}: {exc}"
                else:
                    if not self._retry_policy.should_retry_status(response.status_code):
                        return response, None
                    if not self._retry_policy.can_retry(attempt):
                        return response, None
                await self._retry_policy.wait(attempt)
        return None, "request failed"
