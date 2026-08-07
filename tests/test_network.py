import httpx
import pytest

from apple_com_fonts.network import ProxySettings, RetryPolicy, resolve_proxy_settings


@pytest.mark.parametrize(
    ("mode", "system_proxies", "expected"),
    [
        ("none", {}, ProxySettings(url=None, trust_env=False)),
        ("env", {}, ProxySettings(url=None, trust_env=True)),
        (
            "https://proxy.example:8443",
            {},
            ProxySettings(url="https://proxy.example:8443", trust_env=False),
        ),
        (
            "auto",
            {"https": "http://system-proxy.example:8080"},
            ProxySettings(url="http://system-proxy.example:8080", trust_env=False),
        ),
        ("auto", {}, ProxySettings(url=None, trust_env=True)),
    ],
)
def test_proxy_settings_are_resolved_explicitly(
    mode: str,
    system_proxies: dict[str, str],
    expected: ProxySettings,
) -> None:
    assert resolve_proxy_settings(mode, system_proxies=system_proxies) == expected


def test_retry_policy_validates_configuration_and_classifies_failures() -> None:
    with pytest.raises(ValueError, match="retries cannot be negative"):
        RetryPolicy(retries=-1)
    with pytest.raises(ValueError, match="base_delay cannot be negative"):
        RetryPolicy(base_delay=-0.1)

    policy = RetryPolicy(retries=2, base_delay=0)
    request = httpx.Request("GET", "https://www.apple.com/")
    response = httpx.Response(400, request=request)

    assert list(policy.attempts()) == [0, 1, 2]
    assert policy.can_retry(1)
    assert not policy.can_retry(2)
    assert policy.should_retry_status(503)
    assert not policy.should_retry_status(400)
    assert policy.should_retry_exception(httpx.ConnectError("offline", request=request))
    assert not policy.should_retry_exception(
        httpx.HTTPStatusError("bad response", request=request, response=response)
    )


@pytest.mark.asyncio
async def test_retry_policy_wait_accepts_zero_delay() -> None:
    await RetryPolicy(base_delay=0).wait(0)
