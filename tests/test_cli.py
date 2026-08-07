import json
from argparse import Namespace
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

import apple_com_fonts.cli as cli


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("--concurrency", "0"),
        ("--retries", "-1"),
        ("--timeout", "0"),
    ],
)
def test_parser_rejects_invalid_numeric_options(option: str, value: str) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.build_parser().parse_args(["discover", option, value])

    assert exit_info.value.code == 2


def test_parser_accepts_explicit_runtime_options() -> None:
    args = cli.build_parser().parse_args(
        [
            "download",
            "--timeout",
            "12.5",
            "--concurrency",
            "4",
            "--retries",
            "0",
            "--fonts-dir",
            "archive",
        ]
    )

    assert args.timeout == 12.5
    assert args.concurrency == 4
    assert args.retries == 0
    assert args.fonts_dir == Path("archive")


def test_output_writers_are_atomic_and_reject_nonempty_directories(tmp_path: Path) -> None:
    output = tmp_path / "snapshot"
    cli.prepare_output(output)
    cli.write_json(output / "manifest.json", {"ok": True})
    cli.write_text(output / "font-urls.txt", "https://www.apple.com/font.woff2\n")

    assert json.loads((output / "manifest.json").read_text(encoding="utf-8")) == {"ok": True}
    assert (output / "font-urls.txt").read_text(encoding="utf-8").endswith("\n")
    assert not list(output.glob(".*.tmp"))

    with pytest.raises(SystemExit) as exit_info:
        cli.prepare_output(output)
    assert exit_info.value.code == 2


@pytest.mark.parametrize(
    ("command", "function_name"),
    [("discover", "_run_discover"), ("download", "_run_download")],
)
def test_main_dispatches_to_selected_command(
    command: str,
    function_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run(_: Namespace) -> int:
        return 7

    function: Callable[[Namespace], Awaitable[int]] = run
    monkeypatch.setattr(cli, function_name, function)

    with pytest.raises(SystemExit) as exit_info:
        cli.main([command])
    assert exit_info.value.code == 7


def test_default_output_uses_project_prefix() -> None:
    output = cli.default_output()

    assert output.parent == Path("snapshots")
    assert output.name.startswith("apple-com-fonts-")
