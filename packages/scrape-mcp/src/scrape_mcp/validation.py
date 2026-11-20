"""Argument validation shared by both tools."""

from __future__ import annotations

from typing import Any

MODES = ("fast", "browser")
UNSUPPORTED_MODES = ("stealth", "solve_cloudflare")
EXTRACTIONS = ("markdown", "text", "html")
MIN_TIMEOUT = 1.0
MAX_TIMEOUT = 60.0
MAX_BATCH_URLS = 10
UNSUPPORTED_KEYS = ("stealth", "solve_cloudflare")


class ValidationError(ValueError):
    """A tool argument failed validation; no request is made."""

    code = "invalid_argument"


def _mode(value: Any) -> str:
    if value is None:
        return "fast"
    if not isinstance(value, str):
        raise ValidationError("mode must be 'fast' or 'browser'")
    normalized = value.strip().lower()
    if normalized in MODES:
        return normalized
    if normalized in UNSUPPORTED_MODES:
        raise ValidationError(
            f"mode '{normalized}' is not supported: this tool does not bypass bot protection, "
            "CAPTCHAs, Cloudflare challenges or paywalls; use an official API or a search tool instead"
        )
    raise ValidationError("mode must be 'fast' or 'browser'")


def _extraction(value: Any) -> str:
    if value is None:
        return "markdown"
    if not isinstance(value, str) or value.strip().lower() not in EXTRACTIONS:
        raise ValidationError("extraction must be 'markdown', 'text' or 'html'")
    return value.strip().lower()


def _timeout(value: Any) -> float:
    if value is None:
        return 30.0
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError("timeout must be a number of seconds between 1 and 60")
    timeout = float(value)
    if not MIN_TIMEOUT <= timeout <= MAX_TIMEOUT:
        raise ValidationError("timeout must be between 1 and 60 seconds")
    return timeout


def _url(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValidationError("url must be a non-empty string")
    return value


def _reject_unsupported_keys(args: dict[str, Any]) -> None:
    for key in UNSUPPORTED_KEYS:
        if key in args:
            raise ValidationError(
                f"'{key}' is not supported: this tool does not bypass bot protection, "
                "CAPTCHAs, Cloudflare challenges or paywalls; use an official API or a search tool instead"
            )


def _common(args: dict[str, Any]) -> dict[str, Any]:
    _reject_unsupported_keys(args)
    return {
        "mode": _mode(args.get("mode")),
        "extraction": _extraction(args.get("extraction")),
        "timeout": _timeout(args.get("timeout")),
    }


def validate_page_args(args: Any) -> dict[str, Any]:
    if not isinstance(args, dict):
        raise ValidationError("arguments must be an object")
    params = _common(args)
    params["url"] = _url(args.get("url"))
    return params


def validate_pages_args(args: Any) -> dict[str, Any]:
    if not isinstance(args, dict):
        raise ValidationError("arguments must be an object")
    urls = args.get("urls")
    if not isinstance(urls, list) or not urls:
        raise ValidationError("urls must be a non-empty list")
    if len(urls) > MAX_BATCH_URLS:
        raise ValidationError(f"urls must contain at most {MAX_BATCH_URLS} URLs")
    normalized: list[str] = []
    for item in urls:
        if not isinstance(item, str) or not item:
            raise ValidationError("urls must contain non-empty strings")
        normalized.append(item)
    params = _common(args)
    params["urls"] = normalized
    return params
