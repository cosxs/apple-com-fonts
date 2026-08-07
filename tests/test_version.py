from importlib.metadata import version

from apple_com_fonts import __version__
from apple_com_fonts.network import APPLE_USER_AGENT


def test_runtime_version_and_user_agent_use_installed_project_metadata() -> None:
    assert __version__ == version("apple-com-fonts")
    assert f"apple-com-fonts/{__version__}" in APPLE_USER_AGENT
