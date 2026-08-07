from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn

import httpx

from apple_com_fonts.discovery import RegionDirectoryError, WssDiscovery
from apple_com_fonts.downloader import DownloadReport, FontDownloader
from apple_com_fonts.models import DiscoveryReport
from apple_com_fonts.network import build_http_client


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("cannot be negative")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="apple-com-fonts",
        description="Discover and download Apple global-homepage WSS fonts.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    discover = subparsers.add_parser(
        "discover",
        help="discover WSS links from Apple's official global homepages",
    )
    _add_run_arguments(discover)

    download = subparsers.add_parser(
        "download",
        help="discover, validate, download, and organize all current font files",
    )
    _add_run_arguments(download)
    download.add_argument(
        "--fonts-dir",
        type=Path,
        default=Path("fonts"),
        help="font destination root (default: fonts)",
    )
    return parser


def _add_run_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--output",
        type=Path,
        help="new output directory (default: snapshots/apple-com-fonts-TIMESTAMP)",
    )
    parser.add_argument(
        "--proxy",
        default="auto",
        help=(
            "proxy mode or URL: auto (macOS/system or environment), env, none, "
            "or an explicit HTTP(S) proxy URL"
        ),
    )
    parser.add_argument("--timeout", type=_positive_float, default=30.0)
    parser.add_argument("--concurrency", type=_positive_int, default=16)
    parser.add_argument("--retries", type=_nonnegative_int, default=2)


def _fail(message: str, *, code: int = 2) -> NoReturn:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(code)


def default_output() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path("snapshots") / f"apple-com-fonts-{stamp}"


def prepare_output(output: Path) -> None:
    if output.exists() and any(output.iterdir()):
        _fail(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_text(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _write_discovery_report(report: DiscoveryReport, output: Path) -> tuple[Path, Path]:
    manifest_path = output / "manifest.json"
    urls_path = output / "font-urls.txt"
    write_json(manifest_path, report.as_dict())
    write_text(
        urls_path,
        "".join(f"{font.canonical_url}\n" for font in sorted(report.fonts, key=lambda x: x.path)),
    )
    return manifest_path, urls_path


def _write_download_report(report: DownloadReport, output: Path) -> Path:
    path = output / "downloads.json"
    write_json(path, report.as_dict())
    return path


async def _discover(client: httpx.AsyncClient, args: argparse.Namespace) -> DiscoveryReport:
    discovery = WssDiscovery(
        client,
        concurrency=args.concurrency,
        retries=args.retries,
    )
    try:
        return await discovery.discover()
    except RegionDirectoryError as exc:
        _fail(str(exc))


def _print_discovery(report: DiscoveryReport, manifest_path: Path, urls_path: Path) -> None:
    summary = report.as_dict()["summary"]
    print(
        f"Discovered {summary['unique_font_urls']} unique font URLs from "
        f"{summary['stylesheets_successful']}/{summary['stylesheets_requested']} stylesheets "
        f"across {summary['homepages_successful']}/{summary['homepages_requested']} "
        "global homepages."
    )
    print(f"URLs: {urls_path}")
    print(f"Manifest: {manifest_path}")


def _empty_report_error() -> int:
    print(
        "No font links were found. If Apple returns 404 on this network path, "
        "configure the system proxy, HTTPS_PROXY, or pass --proxy.",
        file=sys.stderr,
    )
    return 1


async def _run_discover(args: argparse.Namespace) -> int:
    output = args.output or default_output()
    prepare_output(output)
    async with build_http_client(timeout=args.timeout, proxy=args.proxy) as client:
        report = await _discover(client, args)

    manifest_path, urls_path = _write_discovery_report(report, output)
    _print_discovery(report, manifest_path, urls_path)
    return 0 if report.fonts else _empty_report_error()


async def _run_download(args: argparse.Namespace) -> int:
    output = args.output or default_output()
    prepare_output(output)
    async with build_http_client(timeout=args.timeout, proxy=args.proxy) as client:
        discovery_report = await _discover(client, args)
        manifest_path, urls_path = _write_discovery_report(discovery_report, output)
        _print_discovery(discovery_report, manifest_path, urls_path)
        if not discovery_report.fonts:
            return _empty_report_error()

        downloader = FontDownloader(
            client,
            concurrency=args.concurrency,
            retries=args.retries,
        )
        download_report = await downloader.download(discovery_report.fonts, args.fonts_dir)

    downloads_path = _write_download_report(download_report, output)
    summary = download_report.as_dict()["summary"]
    print(
        f"Downloaded {summary['files_downloaded']}, skipped {summary['files_skipped']}, "
        f"failed {summary['files_failed']} into {download_report.destination}."
    )
    print(f"Downloads: {downloads_path}")
    return 1 if summary["files_failed"] else 0


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.command == "discover":
        raise SystemExit(asyncio.run(_run_discover(args)))
    if args.command == "download":
        raise SystemExit(asyncio.run(_run_download(args)))
    _fail(f"unsupported command: {args.command}")
