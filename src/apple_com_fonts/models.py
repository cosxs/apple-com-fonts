from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal


@dataclass(slots=True)
class RegionDirectoryResult:
    url: str
    source: Literal["official"]
    status: int | None
    homepages_discovered: int
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "source": self.source,
            "status": self.status,
            "homepages_discovered": self.homepages_discovered,
            "error": self.error,
        }


@dataclass(slots=True)
class HomepageResult:
    url: str
    status: int | None
    regions: set[str] = field(default_factory=set[str])
    css_urls: list[str] = field(default_factory=list[str])
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "status": self.status,
            "regions": sorted(self.regions),
            "css_urls": sorted(self.css_urls),
            "error": self.error,
        }


@dataclass(slots=True)
class StylesheetResult:
    url: str
    sources: set[str] = field(default_factory=set[str])
    status: int | None = None
    content_type: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    font_count: int = 0
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "sources": sorted(self.sources),
            "status": self.status,
            "content_type": self.content_type,
            "etag": self.etag,
            "last_modified": self.last_modified,
            "font_count": self.font_count,
            "error": self.error,
        }


@dataclass(slots=True)
class FontLink:
    path: str
    canonical_url: str
    observed_urls: set[str] = field(default_factory=set[str])
    css_sources: set[str] = field(default_factory=set[str])

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "url": self.canonical_url,
            "observed_urls": sorted(self.observed_urls),
            "css_sources": sorted(self.css_sources),
        }


@dataclass(slots=True)
class DiscoveryReport:
    region_directory: RegionDirectoryResult
    homepages: list[HomepageResult]
    stylesheets: list[StylesheetResult]
    fonts: list[FontLink]
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def as_dict(self) -> dict[str, Any]:
        successful_homepages = sum(page.status == 200 for page in self.homepages)
        successful_css = sum(css.status == 200 for css in self.stylesheets)
        return {
            "schema_version": 4,
            "generated_at": self.generated_at,
            "scope": "Apple global homepage WSS font links",
            "strategy": "official-region-homepages-and-family-version-probes",
            "summary": {
                "homepages_requested": len(self.homepages),
                "homepages_successful": successful_homepages,
                "stylesheets_requested": len(self.stylesheets),
                "stylesheets_successful": successful_css,
                "unique_font_urls": len(self.fonts),
            },
            "region_directory": self.region_directory.as_dict(),
            "homepages": [
                page.as_dict() for page in sorted(self.homepages, key=lambda item: item.url)
            ],
            "stylesheets": [
                css.as_dict() for css in sorted(self.stylesheets, key=lambda item: item.url)
            ],
            "fonts": [font.as_dict() for font in sorted(self.fonts, key=lambda item: item.path)],
        }
