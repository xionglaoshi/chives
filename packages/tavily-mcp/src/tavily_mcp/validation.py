"""Strict validation for the two read-only tool inputs."""

from __future__ import annotations

import ipaddress
import re
from typing import Any
from urllib.parse import urlsplit

MAX_QUERY_CHARS = 400
MAX_RESULTS = 10
MAX_DOMAINS = 10
MAX_EXTRACT_URLS = 5
SEARCH_DEPTHS = ("basic", "advanced")
TOPICS = ("general", "news", "finance")
TIME_RANGES = ("day", "week", "month", "year")
DOMAIN_RE = re.compile(r"^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


class ValidationError(ValueError):
    """A tool argument failed validation; no upstream request is made."""


def _domain_list(value: Any, field: str) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValidationError(f"{field} must be a list of domains")
    if len(value) > MAX_DOMAINS:
        raise ValidationError(f"{field} must contain at most {MAX_DOMAINS} domains")
    domains: list[str] = []
    for item in value:
        if not isinstance(item, str) or not DOMAIN_RE.fullmatch(item):
            raise ValidationError(f"{field} contains an invalid domain")
        domains.append(item)
    return domains


def validate_search(args: Any) -> dict[str, Any]:
    if not isinstance(args, dict):
        raise ValidationError("arguments must be an object")
    query = args.get("query")
    if not isinstance(query, str) or not query.strip() or len(query) > MAX_QUERY_CHARS:
        raise ValidationError(f"query must be a non-empty string of at most {MAX_QUERY_CHARS} characters")

    max_results = args.get("max_results", 5)
    if isinstance(max_results, bool) or not isinstance(max_results, int) or not 1 <= max_results <= MAX_RESULTS:
        raise ValidationError(f"max_results must be an integer between 1 and {MAX_RESULTS}")

    search_depth = args.get("search_depth", "basic")
    if search_depth not in SEARCH_DEPTHS:
        raise ValidationError("search_depth must be basic or advanced")

    topic = args.get("topic", "general")
    if topic not in TOPICS:
        raise ValidationError("topic must be general, news or finance")

    time_range = args.get("time_range")
    if time_range is not None and time_range not in TIME_RANGES:
        raise ValidationError("time_range must be day, week, month, year or null")

    include_domains = _domain_list(args.get("include_domains"), "include_domains")
    exclude_domains = _domain_list(args.get("exclude_domains"), "exclude_domains")

    normalized: dict[str, Any] = {
        "query": query,
        "max_results": max_results,
        "search_depth": search_depth,
        "topic": topic,
        "time_range": time_range,
    }
    if include_domains is not None:
        normalized["include_domains"] = include_domains
    if exclude_domains is not None:
        normalized["exclude_domains"] = exclude_domains
    return normalized


def _reject_host(host: str) -> None:
    name = host.lower().rstrip(".")
    if not name:
        raise ValidationError("urls must contain a hostname")
    if name == "localhost" or name.endswith(".localhost"):
        raise ValidationError("urls must not point at localhost")
    if name.startswith("127.") or name.startswith("10.") or name.startswith("192.168.") or name.startswith("169.254."):
        raise ValidationError("urls must not point at a loopback, private or link-local address")
    if name.startswith("172."):
        second = name.split(".", 2)[1] if name.count(".") >= 1 else ""
        if second.isdigit() and 16 <= int(second) <= 31:
            raise ValidationError("urls must not point at a private address")
    if name.isdigit():
        raise ValidationError("urls must not use a numeric host")
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        return
    if address.is_loopback or address.is_private or address.is_link_local or address.is_unspecified:
        raise ValidationError("urls must not point at a loopback, private or link-local address")


def validate_extract(args: Any) -> dict[str, Any]:
    if not isinstance(args, dict):
        raise ValidationError("arguments must be an object")
    urls = args.get("urls")
    if not isinstance(urls, list) or not 1 <= len(urls) <= MAX_EXTRACT_URLS:
        raise ValidationError(f"urls must be a list of 1 to {MAX_EXTRACT_URLS} URLs")
    normalized: list[str] = []
    for url in urls:
        if not isinstance(url, str) or not url.strip():
            raise ValidationError("urls must contain non-empty strings")
        if any(char.isspace() for char in url):
            raise ValidationError("urls must not contain whitespace")
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https"):
            raise ValidationError("urls must use http or https")
        if not parsed.hostname:
            raise ValidationError("urls must contain a hostname")
        if parsed.username is not None or parsed.password is not None:
            raise ValidationError("urls must not contain credentials")
        try:
            parsed.port
        except ValueError as exc:
            raise ValidationError("urls must contain a valid port") from exc
        _reject_host(parsed.hostname)
        normalized.append(url)
    return {"urls": normalized}
