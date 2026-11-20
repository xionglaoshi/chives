"""URL validation and SSRF protection.

A URL is validated structurally first, then its host is resolved and every
returned address is checked against the non-public ranges.  Callers connect to
the validated IP literal instead of the hostname (see ``fetch_http``), so a
second DNS answer cannot move the socket to a private address.

Redirect targets are not special: ``fetch_http`` calls this module again for
every hop.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import httpx
from dataclasses import dataclass
from typing import Callable, Sequence
from urllib.parse import urlsplit

MAX_URL_LENGTH = 2048

_IPv4Address = ipaddress.IPv4Address
_IPv6Address = ipaddress.IPv6Address
_IPv4Network = ipaddress.IPv4Network
_IPv6Network = ipaddress.IPv6Network

_CGNAT = _IPv4Network("100.64.0.0/10")
_THIS_NETWORK = _IPv4Network("0.0.0.0/8")
_V6_ULA = _IPv6Network("fc00::/7")
_V6_6TO4 = _IPv6Network("2002::/16")
_V6_TEREDO = _IPv6Network("2001::/32")
_V6_NAT64 = _IPv6Network("64:ff9b::/96")

_METADATA_V4 = frozenset(
    {
        "169.254.169.254",  # AWS / GCP / Azure / OpenStack metadata
        "169.254.169.253",  # Azure WireServer DNS
        "169.254.170.2",  # AWS ECS task metadata
        "169.254.170.23",  # AWS EKS pod identity
        "100.100.100.200",  # Alibaba Cloud metadata
        "192.0.0.192",  # Oracle Cloud metadata
        "168.63.129.16",  # Azure platform endpoint
    }
)

_NUMERIC_LABEL = re.compile(r"^(?:0[xX][0-9a-fA-F]+|[0-9]+)$")

# Host names that must never be resolved: cloud metadata endpoints and
# reserved local-use suffixes.  Rejecting before DNS also keeps the offline
# test suite offline when it checks these names.
_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "metadata",
        "instance-data",
        "metadata.google.internal",
        "metadata.goog",
        "metadata.azure.com",
        "metadata.tencentyun.com",
        "metadata.oraclecloud.com",
    }
)
_BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".localdomain", ".internal", ".home.arpa")

Resolver = Callable[[str, int], Sequence[str]]


class UrlError(ValueError):
    """A URL was rejected.  ``code`` is an MCP error code (invalid_url/ssrf_blocked...)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Target:
    """A validated URL plus the addresses it is allowed to connect to."""

    url: str
    scheme: str
    host: str
    port: int
    ips: tuple[str, ...]
    host_header: str
    request_path: str

    @property
    def origin(self) -> str:
        return f"{self.scheme}://{self.host_header}"


def default_resolver(host: str, port: int) -> tuple[str, ...]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, OSError) as exc:
        raise UrlError("fetch_failed", f"DNS resolution failed for {host}") from exc
    addresses: list[str] = []
    for info in infos:
        address = str(info[4][0])
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise UrlError("fetch_failed", f"DNS resolution returned no address for {host}")
    # Clash Fake-IP is a routing placeholder. Ask for real A records and then
    # run them through the usual public-address checks before opening a socket.
    if addresses and all(ipaddress.ip_address(a) in ipaddress.ip_network("198.18.0.0/15") for a in addresses):
        try:
            response = httpx.get("https://dns.alidns.com/resolve", params={"name": host, "type": "A"},
                                 timeout=4, follow_redirects=False, trust_env=False)
            response.raise_for_status()
            answers = response.json().get("Answer", [])
            addresses = [str(ipaddress.IPv4Address(a["data"])) for a in answers if a.get("type") == 1]
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
            raise UrlError("fetch_failed", f"DNS lookup failed for {host}") from exc
        if not addresses:
            raise UrlError("fetch_failed", f"no public DNS answer for {host}")
    return tuple(addresses)


def _split(url: str) -> tuple[str, int]:
    if not isinstance(url, str):
        raise UrlError("invalid_url", "url must be a string")
    if not url:
        raise UrlError("invalid_url", "url must not be empty")
    if len(url) > MAX_URL_LENGTH:
        raise UrlError("invalid_url", f"url must be at most {MAX_URL_LENGTH} characters")
    if any(ch.isspace() for ch in url):
        raise UrlError("invalid_url", "url must not contain whitespace")
    if "\\" in url:
        raise UrlError("invalid_url", "url must not contain backslashes")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in url):
        raise UrlError("invalid_url", "url must not contain control characters")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise UrlError("invalid_url", "url is malformed") from exc
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise UrlError("invalid_url", "only http and https URLs are supported")
    if parts.username is not None or parts.password is not None:
        raise UrlError("invalid_url", "url must not contain a username or password")
    if not parts.hostname:
        raise UrlError("invalid_url", "url must contain a hostname")
    if port is None:
        port = 443 if scheme == "https" else 80
    return scheme, port


def _ascii_host(host: str) -> str:
    if host.isascii():
        return host.lower()
    try:
        return host.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise UrlError("invalid_url", "hostname is not valid IDNA") from exc


def _looks_numeric(host: str) -> bool:
    labels = host.split(".")
    return bool(labels) and all(_NUMERIC_LABEL.match(label) for label in labels)


def _reject_hostname(host: str) -> None:
    name = host.lower().rstrip(".")
    if name in _BLOCKED_HOSTNAMES or any(name.endswith(suffix) for suffix in _BLOCKED_HOST_SUFFIXES):
        raise UrlError("ssrf_blocked", f"refusing non-public hostname {name}")


def _host_allowed(host: str, allow_hosts: Sequence[str]) -> bool:
    if not allow_hosts:
        return True
    return any(host == allowed or host.endswith("." + allowed) for allowed in allow_hosts)


def _check_address(address: str, *, allow_loopback: bool) -> None:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError as exc:
        raise UrlError("ssrf_blocked", f"refusing to use an unparsable address: {address}") from exc

    if isinstance(ip, _IPv6Address):
        if ip.ipv4_mapped is not None:
            raise UrlError(
                "ssrf_blocked", f"refusing IPv4-mapped IPv6 address {address}"
            )
        if allow_loopback and ip == _IPv6Address("::1"):
            return
        if ip.is_loopback or ip.is_unspecified:
            raise UrlError("ssrf_blocked", f"refusing loopback/unspecified address {address}")
        if ip.is_link_local:
            raise UrlError("ssrf_blocked", f"refusing link-local address {address}")
        if ip.is_multicast:
            raise UrlError("ssrf_blocked", f"refusing multicast address {address}")
        if ip in _V6_ULA or ip.is_site_local or ip.is_private:
            raise UrlError("ssrf_blocked", f"refusing private address {address}")
        if ip in _V6_6TO4 or ip in _V6_TEREDO or ip in _V6_NAT64:
            raise UrlError("ssrf_blocked", f"refusing transition address {address}")
        if ip.is_reserved or not ip.is_global:
            raise UrlError("ssrf_blocked", f"refusing non-public address {address}")
        return

    # The test switch exists for a local fake site on 127.0.0.1 only.
    if allow_loopback and ip == _IPv4Address("127.0.0.1"):
        return
    if ip.is_loopback or ip.is_unspecified:
        raise UrlError("ssrf_blocked", f"refusing loopback/unspecified address {address}")
    if ip.is_link_local:
        raise UrlError("ssrf_blocked", f"refusing link-local address {address}")
    if ip.is_multicast:
        raise UrlError("ssrf_blocked", f"refusing multicast address {address}")
    if ip in _CGNAT:
        raise UrlError("ssrf_blocked", f"refusing carrier-grade NAT address {address}")
    if ip in _THIS_NETWORK:
        raise UrlError("ssrf_blocked", f"refusing 'this network' address {address}")
    if str(ip) in _METADATA_V4:
        raise UrlError("ssrf_blocked", f"refusing cloud metadata address {address}")
    if ip.is_private or ip.is_reserved or not ip.is_global:
        raise UrlError("ssrf_blocked", f"refusing non-public address {address}")


def parse_target(
    url: str,
    *,
    resolver: Resolver = default_resolver,
    allow_hosts: Sequence[str] = (),
    allow_loopback: bool = False,
) -> Target:
    """Validate ``url`` and return a Target whose ``ips`` may be connected to."""

    scheme, port = _split(url)
    parts = urlsplit(url)
    raw_host = parts.hostname or ""
    host = raw_host.rstrip(".")
    if not host:
        raise UrlError("invalid_url", "url must contain a hostname")
    _reject_hostname(host)

    literal_addresses: tuple[str, ...] | None = None
    if ":" in host:
        try:
            literal = _IPv6Address(host)
        except ValueError as exc:
            raise UrlError("invalid_url", "url contains an invalid IPv6 host") from exc
        host = str(literal)
        literal_addresses = (host,)
    else:
        host = _ascii_host(host)
        _reject_hostname(host)
        if _looks_numeric(host):
            labels = host.split(".")
            canonical = len(labels) == 4 and all(
                label.isdigit() and str(int(label)) == label for label in labels
            )
            if not canonical:
                raise UrlError(
                    "ssrf_blocked",
                    "refusing a non-canonical numeric IP host (decimal/octal/hex forms are not allowed)",
                )
            try:
                literal_v4 = _IPv4Address(host)
            except ValueError as exc:
                raise UrlError("invalid_url", "url contains an invalid IPv4 host") from exc
            host = str(literal_v4)
            literal_addresses = (host,)

    # The allow-list is checked before DNS so a blocked host is never resolved.
    if not _host_allowed(host, allow_hosts):
        raise UrlError("ssrf_blocked", f"host {host} is not in SCRAPE_ALLOW_HOSTS")
    addresses = literal_addresses if literal_addresses is not None else tuple(resolver(host, port))
    if not addresses:
        raise UrlError("fetch_failed", f"DNS resolution returned no address for {host}")
    for address in addresses:
        _check_address(address, allow_loopback=allow_loopback)

    path = parts.path or "/"
    if parts.query:
        path = f"{path}?{parts.query}"
    host_for_header = f"[{host}]" if ":" in host else host
    default_port = 443 if scheme == "https" else 80
    host_header = host_for_header if port == default_port else f"{host_for_header}:{port}"
    return Target(
        url=url,
        scheme=scheme,
        host=host,
        port=port,
        ips=addresses,
        host_header=host_header,
        request_path=path,
    )
