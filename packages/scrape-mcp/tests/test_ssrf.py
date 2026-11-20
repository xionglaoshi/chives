from __future__ import annotations

from typing import Sequence

import pytest

from scrape_mcp.ssrf import UrlError, parse_target

PUBLIC_V4 = "93.184.216.34"

INVALID_URLS = [
    "",
    "example.com",
    "ftp://example.com/file",
    "file:///etc/passwd",
    "javascript:alert(1)",
    "http://user:pass@example.com/",
    "http://example.com:99999/",
    "http://exa mple.com/",
    "http://example.com/\\@127.0.0.1/",
    "http://" + "a" * 2100 + ".com/",
    "//example.com/path",
    "http:///path",
]

BLOCKED_URLS = [
    "http://127.0.0.1/",
    "http://127.0.0.2:8080/",
    "http://127.1/",
    "http://2130706433/",
    "http://1498927914/",
    "http://0x7f000001/",
    "http://017700000001/",
    "http://0177.0.0.1/",
    "http://0.0.0.0/",
    "http://0/",
    "http://localhost/",
    "http://localhost./",
    "http://foo.localhost/",
    "http://[::1]/",
    "http://[::ffff:127.0.0.1]/",
    "http://[0:0:0:0:0:ffff:127.0.0.1]/",
    "http://10.0.0.1/",
    "http://192.168.1.1/",
    "http://172.16.0.1/",
    "http://172.31.255.255/",
    "http://169.254.169.254/latest/meta-data/",
    "http://169.254.170.2/v2/credentials",
    "http://100.100.100.200/",
    "http://100.64.0.1/",
    "http://[fe80::1]/",
    "http://[fc00::1]/",
    "http://[fd12:3456::1]/",
    "http://[::]/",
    "http://[2002:7f00:1::]/",
    "http://[2001::1]/",
    "http://[64:ff9b::7f00:1]/",
    "http://224.0.0.1/",
    "http://255.255.255.255/",
    "http://198.51.100.1/",
    "http://metadata.google.internal/",
    "http://localhost.localdomain/",
    "http://instance-data/",
    "http://printer.local/",
]


def _resolver(mapping: dict[str, Sequence[str]]):
    def resolve(host: str, port: int) -> tuple[str, ...]:
        if host not in mapping:
            raise UrlError("fetch_failed", f"DNS resolution failed for {host}")
        return tuple(mapping[host])

    return resolve


@pytest.mark.parametrize("url", INVALID_URLS)
def test_invalid_url_forms(url: str) -> None:
    with pytest.raises(UrlError) as excinfo:
        parse_target(url)
    assert excinfo.value.code == "invalid_url"


@pytest.mark.parametrize("url", BLOCKED_URLS)
def test_ssrf_matrix(url: str) -> None:
    with pytest.raises(UrlError) as excinfo:
        parse_target(url)
    assert excinfo.value.code == "ssrf_blocked", url


def test_public_literal_is_allowed() -> None:
    target = parse_target(f"https://{PUBLIC_V4}/a?b=1")
    assert target.ips == (PUBLIC_V4,)
    assert target.host_header == PUBLIC_V4
    assert target.request_path == "/a?b=1"


def test_public_hostname_is_resolved_and_kept_in_host_header() -> None:
    target = parse_target(
        "https://example.com:8443/a?b=1",
        resolver=_resolver({"example.com": [PUBLIC_V4]}),
    )
    assert target.ips == (PUBLIC_V4,)
    assert target.host_header == "example.com:8443"
    assert target.origin == "https://example.com:8443"


def test_default_port_is_not_echoed_in_host_header() -> None:
    target = parse_target(
        "https://example.com/a", resolver=_resolver({"example.com": [PUBLIC_V4]})
    )
    assert target.host_header == "example.com"


def test_ipv6_host_header_is_bracketed() -> None:
    target = parse_target("http://[2606:2800:220:1:248:1893:25c8:1946]/x")
    assert target.host_header == "[2606:2800:220:1:248:1893:25c8:1946]"
    assert target.port == 80


def test_dns_private_answer_is_blocked() -> None:
    with pytest.raises(UrlError) as excinfo:
        parse_target("http://internal.example/", resolver=_resolver({"internal.example": ["10.0.0.5"]}))
    assert excinfo.value.code == "ssrf_blocked"


def test_dns_metadata_answer_is_blocked() -> None:
    with pytest.raises(UrlError) as excinfo:
        parse_target(
            "http://metadata.example/latest",
            resolver=_resolver({"metadata.example": ["169.254.169.254"]}),
        )
    assert excinfo.value.code == "ssrf_blocked"


def test_dns_mixed_answers_are_blocked_if_any_is_private() -> None:
    with pytest.raises(UrlError) as excinfo:
        parse_target(
            "http://mixed.example/",
            resolver=_resolver({"mixed.example": [PUBLIC_V4, "10.0.0.1"]}),
        )
    assert excinfo.value.code == "ssrf_blocked"


def test_dns_rebinding_sequence_is_rechecked() -> None:
    answers = {"rebind.example": [PUBLIC_V4, "127.0.0.1"]}
    calls = {"count": 0}

    def resolver(host: str, port: int) -> tuple[str, ...]:
        index = min(calls["count"], len(answers[host]) - 1)
        calls["count"] += 1
        return (answers[host][index],)

    first = parse_target("http://rebind.example/", resolver=resolver)
    assert first.ips == (PUBLIC_V4,)
    with pytest.raises(UrlError) as excinfo:
        parse_target("http://rebind.example/", resolver=resolver)
    assert excinfo.value.code == "ssrf_blocked"
    assert calls["count"] == 2


def test_dns_ipv6_private_answer_is_blocked() -> None:
    with pytest.raises(UrlError) as excinfo:
        parse_target("http://v6.example/", resolver=_resolver({"v6.example": ["fd00::1"]}))
    assert excinfo.value.code == "ssrf_blocked"


def test_dns_ipv4_mapped_answer_is_blocked() -> None:
    with pytest.raises(UrlError) as excinfo:
        parse_target(
            "http://mapped.example/", resolver=_resolver({"mapped.example": ["::ffff:127.0.0.1"]})
        )
    assert excinfo.value.code == "ssrf_blocked"


def test_empty_dns_answer_is_a_fetch_failure() -> None:
    with pytest.raises(UrlError) as excinfo:
        parse_target("http://empty.example/", resolver=_resolver({"empty.example": []}))
    assert excinfo.value.code == "fetch_failed"


def test_dns_failure_is_a_fetch_failure() -> None:
    with pytest.raises(UrlError) as excinfo:
        parse_target("http://nxdomain.example/", resolver=_resolver({}))
    assert excinfo.value.code == "fetch_failed"


def test_loopback_test_switch_allows_only_loopback() -> None:
    target = parse_target("http://127.0.0.1:8000/", allow_loopback=True)
    assert target.port == 8000
    with pytest.raises(UrlError) as excinfo:
        parse_target("http://127.0.0.2/", allow_loopback=True)
    assert excinfo.value.code == "ssrf_blocked"
    with pytest.raises(UrlError) as excinfo:
        parse_target("http://10.0.0.1/", allow_loopback=True)
    assert excinfo.value.code == "ssrf_blocked"
    with pytest.raises(UrlError) as excinfo:
        parse_target("http://[::ffff:127.0.0.1]/", allow_loopback=True)
    assert excinfo.value.code == "ssrf_blocked"
    with pytest.raises(UrlError) as excinfo:
        parse_target("http://localhost/", allow_loopback=True)
    assert excinfo.value.code == "ssrf_blocked"
    with pytest.raises(UrlError) as excinfo:
        parse_target("http://0.0.0.0/", allow_loopback=True)
    assert excinfo.value.code == "ssrf_blocked"


def test_allow_hosts_exact_and_subdomain() -> None:
    resolver = _resolver({"api.example.com": [PUBLIC_V4]})
    target = parse_target(
        "https://api.example.com/x",
        resolver=resolver,
        allow_hosts=("example.com",),
    )
    assert target.ips == (PUBLIC_V4,)
    for url in ("https://example.org/", "https://notexample.com/"):
        with pytest.raises(UrlError) as excinfo:
            parse_target(url, resolver=resolver, allow_hosts=("example.com",))
        assert excinfo.value.code == "ssrf_blocked"


def test_allow_hosts_blocks_before_dns() -> None:
    calls = {"count": 0}

    def resolver(host: str, port: int) -> tuple[str, ...]:
        calls["count"] += 1
        return (PUBLIC_V4,)

    with pytest.raises(UrlError):
        parse_target("https://other.example/", resolver=resolver, allow_hosts=("example.com",))
    assert calls["count"] == 0



@pytest.mark.parametrize(
    "url",
    [
        "http://metadata.google.internal/",
        "http://localhost.localdomain/",
        "http://instance-data.ec2.internal/",
    ],
)
def test_reserved_hostnames_are_blocked_before_dns(url: str) -> None:
    calls = {"count": 0}

    def resolver(host: str, port: int) -> tuple[str, ...]:
        calls["count"] += 1
        return ("169.254.169.254",)

    with pytest.raises(UrlError) as excinfo:
        parse_target(url, resolver=resolver)
    assert excinfo.value.code == "ssrf_blocked"
    assert calls["count"] == 0
