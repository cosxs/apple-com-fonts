import pytest

from apple_com_fonts.parsing import (
    WssFamilyVersion,
    build_wss_stylesheet_url,
    canonical_font_path,
    canonical_font_url,
    extract_font_urls,
    extract_region_pages,
    extract_wss_family_versions,
    extract_wss_stylesheets,
    region_id_from_url,
)


def test_extract_wss_stylesheets_resolves_and_deduplicates() -> None:
    html = """
    <link rel="stylesheet" href="/wss/fonts?families=SF+Pro,v3">
    <link rel="stylesheet preload" href="/wss/fonts?families=SF+Pro,v3">
    <link rel="stylesheet" href="/assets/site.css">
    """

    assert extract_wss_stylesheets(html, "https://www.apple.com/jp/") == [
        "https://www.apple.com/wss/fonts?families=SF+Pro,v3"
    ]


def test_extract_region_pages_uses_country_links_and_deduplicates_shared_sites() -> None:
    html = """
    <a class="globalnav-link" data-analytics-title="mac" href="/mac/">Mac</a>
    <main>
      <a class="block" data-analytics-title="australia" href="/au/">Australia</a>
      <a class="block" data-analytics-title="china" href="https://www.apple.com.cn/">
        China mainland
      </a>
      <a class="block" data-analytics-title="canada-french" href="/ca/fr">Canada</a>
      <a class="block" data-analytics-title="anguilla" href="/lae/">Anguilla</a>
      <a class="block" data-analytics-title="barbados" href="/lae/">Barbados</a>
      <a class="block" data-analytics-title="united-states" href="/">United States</a>
      <a class="block" data-analytics-title="invalid" href="https://example.com/xx/">Bad</a>
    </main>
    """

    assert extract_region_pages(html, "https://www.apple.com/choose-country-region/") == {
        "au": "https://www.apple.com/au/",
        "ca-fr": "https://www.apple.com/ca/fr/",
        "cn": "https://www.apple.com.cn/",
        "lae": "https://www.apple.com/lae/",
        "us": "https://www.apple.com/",
    }


def test_region_id_is_stable_for_localized_homepages() -> None:
    assert region_id_from_url("https://www.apple.com/hk/en/") == "hk-en"
    assert region_id_from_url("https://www.apple.com/bh-ar/") == "bh-ar"


def test_wss_family_versions_are_extracted_and_rebuilt() -> None:
    combined = (
        "https://www.apple.com/wss/fonts?"
        "families=SF+Pro,v3:200,400,600|SF+Pro+Icons,v3|SF+Pro+AR+Text,v2"
    )
    assert extract_wss_family_versions(combined) == {
        WssFamilyVersion("SF Pro", 3),
        WssFamilyVersion("SF Pro AR Text", 2),
        WssFamilyVersion("SF Pro Icons", 3),
    }
    assert extract_wss_family_versions(
        "https://www.apple.com/wss/fonts?family=SF+Pro+HK&weights=400,600&v=1"
    ) == {WssFamilyVersion("SF Pro HK", 1)}
    assert build_wss_stylesheet_url("SF Pro AR", 2) == (
        "https://www.apple.com/wss/fonts?families=SF+Pro+AR,v2"
    )


def test_extract_font_urls_accepts_quoted_and_unquoted_css_urls() -> None:
    css = """
    @font-face {
      src: url('/wss/fonts/SF-Pro/v4/SFPro.woff2') format('woff2'),
           url(\"/wss/fonts/SF-Pro/v4/SFPro.ttf\") format('truetype'),
           url(/assets/not-a-font.svg);
    }
    """

    assert extract_font_urls(css, "https://www.apple.com/wss/fonts?families=SF+Pro,v4") == [
        "https://www.apple.com/wss/fonts/SF-Pro/v4/SFPro.ttf",
        "https://www.apple.com/wss/fonts/SF-Pro/v4/SFPro.woff2",
    ]


def test_canonical_font_url_normalizes_apple_host() -> None:
    observed = "https://www.apple.com.cn/wss/fonts/SF-Pro-SC/v1/PingFangSC-Regular.woff2"

    assert canonical_font_path(observed) == ("/wss/fonts/SF-Pro-SC/v1/PingFangSC-Regular.woff2")
    assert canonical_font_url(observed) == (
        "https://www.apple.com/wss/fonts/SF-Pro-SC/v1/PingFangSC-Regular.woff2"
    )


def test_canonical_font_path_rejects_non_font_paths() -> None:
    with pytest.raises(ValueError, match="safe WSS"):
        canonical_font_path("https://www.apple.com/wss/fonts/../private.txt")
