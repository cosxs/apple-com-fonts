# Apple.com Fonts

English | [简体中文](README.zh-CN.md)

Discover, validate, and archive the web fonts exposed by Apple’s public global homepages.

The project starts from Apple’s live country and region directory on every run. It does not use
local fonts, generated manifests, historical snapshots, Apple Developer downloads, or operating
system fonts as discovery inputs.

## What it does

- Discovers Apple’s current country and region homepages from the official directory.
- Extracts `/wss/fonts` stylesheets referenced by those homepages.
- Probes the versions of font families observed from Apple’s own pages.
- Produces a canonical URL list and an auditable discovery manifest.
- Downloads fonts concurrently, validates their signatures, and organizes them deterministically.
- Synchronizes the validated font set and publishes a reproducible monthly archive with GitHub
  Actions.

## Discovery scope

Apple does not expose a public directory index for `/wss/fonts`. In this project, the current font
set means every unique font URL discovered from:

1. Apple’s [country and region directory](https://www.apple.com/choose-country-region/).
2. The unique global homepages listed by that directory.
3. Successful version probes for font families referenced by those homepages.

This scope does not claim to cover unlinked files or fonts used only by inner pages, Apple
Developer packages, or Apple operating systems. Every run is built from live Apple sources; stored
artifacts are outputs, never discovery seeds.

## Requirements

- Python 3.14 or newer
- Git LFS when cloning or committing the repository font archive

On macOS, install Git LFS and initialize it for this repository:

```bash
brew install git-lfs
git lfs install --local
```

## Quick start

Create an isolated environment and install the project with development tools:

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

Discover the current font links without downloading font files:

```bash
.venv/bin/apple-com-fonts discover
```

Discover, download, validate, and organize the current font set:

```bash
.venv/bin/apple-com-fonts download
```

## Commands

### `discover`

Writes a new timestamped snapshot containing:

- `font-urls.txt` — canonical, deduplicated Apple font URLs.
- `manifest.json` — homepage coverage, stylesheet requests, version probes, HTTP metadata,
  failures, observed URLs, and provenance.

```bash
.venv/bin/apple-com-fonts discover \
  --output snapshots/manual-discovery \
  --concurrency 16
```

### `download`

Runs discovery first, then downloads the resulting font set. Existing valid files are skipped.
Missing or invalid files are replaced only after a complete response passes signature validation;
temporary downloads are moved into place atomically.

```bash
.venv/bin/apple-com-fonts download \
  --fonts-dir fonts \
  --output snapshots/manual-download
```

The destination layout is derived from Apple’s URL paths:

```text
fonts/<family>/<version>/<format>/<file>
```

In addition to the discovery artifacts, `download` writes `downloads.json` with per-file status,
local paths, sizes, HTTP metadata, and errors.

### Common options

| Option | Purpose |
| --- | --- |
| `--output PATH` | Write reports to a new directory instead of a timestamped snapshot. |
| `--proxy MODE` | Select `auto`, `env`, `none`, or an explicit proxy URL. |
| `--timeout SECONDS` | Set the request timeout. |
| `--concurrency COUNT` | Set concurrent discovery and download requests. |
| `--retries COUNT` | Set retry attempts for transient failures. |
| `--fonts-dir PATH` | Select the font destination for `download`. |

The default `auto` proxy mode checks the active macOS system proxy before standard proxy
environment variables. Proxy addresses are never written to generated manifests.

```bash
.venv/bin/apple-com-fonts discover --proxy 'http://127.0.0.1:PORT'
```

## Reliability model

- Failure to fetch or parse Apple’s official region directory stops discovery.
- Individual homepage and stylesheet failures are recorded so local runs can finish with an
  auditable partial result.
- A manual download does not delete files that are absent from its latest discovery result.
- Font files are written atomically only after their signatures have been validated.
- WSS stylesheet requests use the matching Apple origin as their `Referer`.
- The automated release requires complete homepage, stylesheet, and font-download validation
  before it is allowed to mirror the repository archive.

## Automated release

The [Release workflow](.github/workflows/release.yml) runs at `00:00 UTC` on the first day of every
month and supports manual dispatch.

After a fully successful discovery and download, the workflow:

1. Mirrors the validated set into `fonts/`, including removal of files no longer discovered.
2. Verifies that every repository font is tracked by Git LFS.
3. Commits and pushes only when the font set changed.
4. Builds a reproducible archive and SHA-256 checksum.
5. Creates or updates the monthly `fonts-YYYY-MM` GitHub Release.

The custom Release assets are:

```text
apple-com-fonts-YYYY-MM.tar.gz
apple-com-fonts-YYYY-MM.tar.gz.sha256
```

The archive contains `fonts/`, discovery and download metadata, `LICENSE`, `NOTICE`, and both
README files. GitHub separately provides source archives for the tagged repository state.

The workflow uses the repository’s standard `GITHUB_TOKEN` with `contents: write`. Repository
rules must allow GitHub Actions to push its font synchronization commit to the default branch.

## Project layout

```text
.
├── .github/workflows/             # CI, monthly synchronization, and Release
├── fonts/                         # current Git LFS font archive
├── snapshots/                     # generated local reports; ignored by Git
├── src/apple_com_fonts/           # discovery, networking, and download implementation
├── tests/                         # automated tests
├── LICENSE
├── NOTICE
├── README.md
├── README.zh-CN.md
└── pyproject.toml
```

## Development

Run the complete quality gate from the project environment:

```bash
.venv/bin/pyright
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check .
actionlint .github/workflows/release.yml
```

Pyright runs in strict mode across `src` and `tests`.

The [CI workflow](.github/workflows/ci.yml) runs dependency checks, Ruff, Pyright, and the test
suite with enforced branch coverage for every push and pull request.

## License and third-party content

Copyright (c) 2026 cosxs.

The original source code, tests, configuration, and automation are licensed under the
[MIT License](LICENSE). Font files discovered through Apple’s public `/wss/fonts` URLs are not
covered by this project’s MIT License. See [NOTICE](NOTICE) for source, affiliation, and
third-party rights information.
