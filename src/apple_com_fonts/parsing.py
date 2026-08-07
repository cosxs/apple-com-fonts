from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote, quote_plus, unquote, urljoin, urlsplit, urlunsplit

_CSS_URL_PATTERN = re.compile(
    r"""url\(\s*(?P<quote>['\"]?)(?P<url>[^'\")\s]+)(?P=quote)\s*\)""",
    re.IGNORECASE,
)
_WSS_FAMILY_PATTERN = re.compile(r"^(?P<family>.+),v(?P<version>\d+)(?::.*)?$", re.IGNORECASE)


class _StylesheetLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "link":
            return

        attributes = {name.casefold(): value or "" for name, value in attrs}
        relations = {part.casefold() for part in attributes.get("rel", "").split()}
        href = attributes.get("href", "").strip()
        if "stylesheet" in relations and "/wss/fonts" in href:
            self.hrefs.append(href)


class _RegionLinkParser(HTMLParser):
    """Extract only country links from Apple's region directory."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "a":
            return

        attributes = {name.casefold(): value or "" for name, value in attrs}
        classes = {part.casefold() for part in attributes.get("class", "").split()}
        href = attributes.get("href", "").strip()
        if "block" in classes and attributes.get("data-analytics-title") and href:
            self.hrefs.append(href)


@dataclass(frozen=True, order=True, slots=True)
class WssFamilyVersion:
    family: str
    version: int


def extract_wss_stylesheets(html: str, page_url: str) -> list[str]:
    parser = _StylesheetLinkParser()
    parser.feed(html)
    return sorted({urljoin(page_url, href) for href in parser.hrefs})


def extract_wss_family_versions(stylesheet_url: str) -> set[WssFamilyVersion]:
    query = parse_qs(urlsplit(stylesheet_url).query)
    discovered: set[WssFamilyVersion] = set()

    for value in query.get("families", []):
        for item in value.split("|"):
            match = _WSS_FAMILY_PATTERN.fullmatch(item.strip())
            if match:
                discovered.add(
                    WssFamilyVersion(
                        family=match.group("family").strip(),
                        version=int(match.group("version")),
                    )
                )

    versions = query.get("v", [])
    if versions and versions[0].isdigit():
        for family in query.get("family", []):
            if family.strip():
                discovered.add(WssFamilyVersion(family=family.strip(), version=int(versions[0])))

    return discovered


def build_wss_stylesheet_url(family: str, version: int) -> str:
    query = f"families={quote_plus(family)},v{version}"
    return urlunsplit(("https", "www.apple.com", "/wss/fonts", query, ""))


def region_id_from_url(url: str) -> str:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").casefold()
    parts = [part.casefold() for part in parsed.path.split("/") if part]

    if host == "www.apple.com.cn":
        return "cn" if not parts else "cn-" + "-".join(parts)
    if host != "www.apple.com":
        raise ValueError(f"Not an Apple regional page: {url}")
    return "us" if not parts else "-".join(parts)


def extract_region_pages(html: str, directory_url: str) -> dict[str, str]:
    parser = _RegionLinkParser()
    parser.feed(html)

    pages: dict[str, str] = {}
    seen_urls: set[str] = set()
    for href in parser.hrefs:
        observed_url = urljoin(directory_url, href)
        parsed = urlsplit(observed_url)
        host = (parsed.hostname or "").casefold()
        if parsed.scheme.casefold() not in {"http", "https"}:
            continue
        if host not in {"www.apple.com", "www.apple.com.cn"}:
            continue

        path = parsed.path or "/"
        if not path.endswith("/"):
            path += "/"
        canonical_url = urlunsplit(("https", host, path, "", ""))
        if canonical_url in seen_urls:
            continue

        region = region_id_from_url(canonical_url)
        existing = pages.get(region)
        if existing is not None and existing != canonical_url:
            message = f"Region identifier collision for {region}: {existing}, {canonical_url}"
            raise ValueError(message)
        pages[region] = canonical_url
        seen_urls.add(canonical_url)

    return dict(sorted(pages.items()))


def extract_font_urls(css: str, stylesheet_url: str) -> list[str]:
    urls: set[str] = set()
    for match in _CSS_URL_PATTERN.finditer(css):
        candidate = urljoin(stylesheet_url, match.group("url"))
        path = urlsplit(candidate).path
        if path.startswith("/wss/fonts/"):
            urls.add(candidate)
    return sorted(urls)


def canonical_font_path(url: str) -> str:
    raw_path = unquote(urlsplit(url).path)
    normalized = posixpath.normpath(raw_path)
    if not normalized.startswith("/wss/fonts/") or "/../" in f"{normalized}/":
        raise ValueError(f"Not a safe WSS font URL: {url}")
    return quote(normalized, safe="/-._~")


def canonical_font_url(url: str) -> str:
    path = canonical_font_path(url)
    return urlunsplit(("https", "www.apple.com", path, "", ""))
