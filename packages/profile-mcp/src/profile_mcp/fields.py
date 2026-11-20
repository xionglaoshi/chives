"""Whitelisted profile fields, value validation and free-text sanitising."""

from __future__ import annotations

import re
from typing import Any

PROFILE_VERSION = 1

ENUM_FIELDS: dict[str, tuple[str, ...]] = {
    "investor_type": ("practitioner", "active_retail", "long_term", "beginner"),
    "risk_level": ("conservative", "balanced", "aggressive"),
    "horizon": ("intraday", "days", "weeks", "months", "years"),
    "capital_range": ("lt_100k", "100k_1m", "1m_10m", "gt_10m"),
    "research_depth": ("light", "adaptive", "thorough"),
    "language": ("zh", "en"),
}

INT_FIELDS: dict[str, tuple[int, int]] = {"experience_years": (0, 60)}

ENUM_LIST_FIELDS: dict[str, tuple[tuple[str, ...], int]] = {
    "markets": (("cn", "us", "hk"), 3),
    "output_format": (("chart", "file", "text"), 3),
}

TEXT_LIST_FIELDS: dict[str, tuple[int, int]] = {
    "sectors": (30, 10),
    "styles": (30, 10),
    "asset_classes": (30, 10),
    "constraints": (60, 8),
}

TEXT_FIELDS: dict[str, int] = {"agent_preference": 300}

FIELD_ORDER: tuple[str, ...] = (
    "investor_type",
    "experience_years",
    "risk_level",
    "horizon",
    "capital_range",
    "markets",
    "sectors",
    "styles",
    "asset_classes",
    "constraints",
    "research_depth",
    "output_format",
    "language",
    "agent_preference",
)

FIELD_LABELS: dict[str, str] = {
    "investor_type": "投资者类型",
    "experience_years": "投资经验（年）",
    "risk_level": "风险偏好",
    "horizon": "持有周期",
    "capital_range": "资金档位（人民币）",
    "markets": "关注市场",
    "sectors": "关注行业",
    "styles": "投资风格",
    "asset_classes": "资产类别",
    "constraints": "硬性约束",
    "research_depth": "研究深度",
    "output_format": "输出偏好（按优先级）",
    "language": "语言",
    "agent_preference": "补充偏好（用户原话）",
}

MAX_FIELD_TEXT = 300
MAX_BLOCK_BYTES = 2000  # strictly inside 2 KiB even if a checker uses 2048 or 2000

# Instruction-like fragments. Matched case-insensitively against free text.
# Chinese entries allow a short run of separators between a verb and its object so
# variants such as "绕过 所有 安全 限制" are caught; English entries allow a little
# whitespace/punctuation between words.
_EN_GAP = r"[\s,;:.!?'\"()\-]{0,3}"

SUSPICIOUS_PATTERNS: tuple[str, ...] = (
    # 忽略/无视/忽视/绕过/突破/越过 + 规则/限制/指令/安全 …
    r"(?:忽略|无视|忽视|绕过|突破|越过|规避|撇开)[^，,。.;；!！?？\n]{0,10}"
    r"(?:规则|限制|指令|安全|约束|设定|提示|要求|政策|审查|过滤|监管)",
    # 不要/不必/无需 + 遵守/遵循/服从/理会
    r"(?:不要|不必|不需|无需|不用|不准|禁止|拒绝|别)[^，,。.;；!！?？\n]{0,4}"
    r"(?:遵守|遵循|服从|理会)",
    # 违反/违背 + 规则/限制/安全 …
    r"(?:违反|违背|对抗)[^，,。.;；!！?？\n]{0,8}"
    r"(?:规则|限制|指令|安全|规定|约束|政策|要求)",
    # 指令式开场
    r"从现在(?:起|开始)",
    r"今后你",
    r"你现在(?:是|扮演)",
    r"扮演",
    # 其它中文模式
    r"忽略(?:以上|之前|前面|上述|上面|此前|指令|规则)",
    r"(?:无视|不要理会|不要遵循)之前",
    r"忘记(?:之前|以上|前面|所有)",
    r"系统(?:提示|指令|消息)",
    r"(?:新指令|跳过限制|解除限制|无限制模式|越狱模式|覆盖以上)",
    # 英文
    r"\b(?:ignore|disregard|override|bypass|jailbreak|pretend)\b",
    rf"\bact{_EN_GAP}as\b",
    rf"\byou{_EN_GAP}are{_EN_GAP}now\b",
    r"\byou\s+must\b",
    rf"\bfrom{_EN_GAP}now{_EN_GAP}on\b",
    r"\bsystem\s+(?:prompt|message)\b",
    r"\bdeveloper\s+mode\b",
    r"\bdo\s+not\s+follow\b",
    r"\bforget\s+(?:all\s+)?(?:previous|prior|everything\s+above)\b",
    r"\bnew\s+instructions\b",
    r"\bskip\s+(?:the\s+)?(?:rules|restrictions|limits)\b",
)

SUSPICIOUS_REGEXES: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE) for pattern in SUSPICIOUS_PATTERNS
)

# Credential- and identity-shaped fragments; never stored, never echoed back.
SENSITIVE_PATTERNS: tuple[str, ...] = (
    "sk-",
    "api_key",
    "apikey",
    "api key",
    "api-key",
    "access_key",
    "access key",
    "password",
    "passwd",
    "密码",
    "token",
    "secret",
    "cookie",
    "ghp_",
    "xoxb-",
    "akia",
    "bearer ",
    "-----begin",
    "private key",
    "begin rsa",
    "begin openssh",
    "私钥",
)

SENSITIVE_REGEXES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\d{11,}"),  # phone numbers, ID numbers, account numbers
    re.compile(r"1[3-9]\d[ -]\d{4}[ -]\d{4}"),  # mainland mobile with separators
    re.compile(r"\d{4}(?:[ -]\d{4}){2,}"),  # bank card grouped in fours
    re.compile(r"\d{17}[\dXx]"),  # 18-character mainland ID number
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),  # e-mail
)

_CONTROL_RE = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f"
    "\u200b-\u200f\u2028-\u202e\u2060-\u2064\ufeff]"
)
_MARKUP_RE = re.compile(r"[<>`]")
_HEADING_RE = re.compile(r"^[#>\s\-*+]+")
_SPACE_RE = re.compile(r"\s+")


class ProfileError(Exception):
    """A rejected tool request; the code is stable and machine-readable."""

    def __init__(self, code: str, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field


def _as_text(value: Any, *, field: str, max_chars: int) -> str:
    if not isinstance(value, str):
        raise ProfileError("invalid_value", f"{field} must be a string", field=field)
    text = clean_text(value)
    for pattern in SUSPICIOUS_REGEXES:
        if pattern.search(text):
            raise ProfileError(
                "suspicious_text",
                f"{field} looks like an instruction to the agent; rewrite it as a plain preference",
                field=field,
            )
    lowered = text.casefold()
    for pattern in SENSITIVE_PATTERNS:
        if pattern in lowered:
            raise ProfileError(
                "sensitive_text",
                f"{field} looks like it contains a secret or personal identifier; do not store it",
                field=field,
            )
    for regex in SENSITIVE_REGEXES:
        if regex.search(text):
            raise ProfileError(
                "sensitive_text",
                f"{field} looks like it contains a secret or personal identifier; do not store it",
                field=field,
            )
    if len(text) > max_chars:
        raise ProfileError("invalid_value", f"{field} must be at most {max_chars} characters", field=field)
    return text


def clean_text(value: str) -> str:
    """Flatten and de-fang user text before it can reach an instruction file."""
    text = value.replace("\r\n", " ").replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = _CONTROL_RE.sub("", text)
    text = _MARKUP_RE.sub("", text)
    text = _SPACE_RE.sub(" ", text).strip()
    text = _HEADING_RE.sub("", text).strip()
    return text


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_enum(field: str, value: Any, allowed: tuple[str, ...]) -> str:
    if not isinstance(value, str):
        raise ProfileError("invalid_value", f"{field} must be a string", field=field)
    if value not in allowed:
        raise ProfileError(
            "invalid_value",
            f"{field} must be one of: {', '.join(allowed)}",
            field=field,
        )
    return value


def _check_enum_list(field: str, value: Any, allowed: tuple[str, ...], max_items: int) -> list[str]:
    if not isinstance(value, list):
        raise ProfileError("invalid_value", f"{field} must be a list", field=field)
    if len(value) > max_items:
        raise ProfileError("invalid_value", f"{field} must have at most {max_items} items", field=field)
    ordered: list[str] = []
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            raise ProfileError(
                "invalid_value",
                f"{field} items must be one of: {', '.join(allowed)}",
                field=field,
            )
        if item not in ordered:
            ordered.append(item)
    return ordered


def _check_text_list(field: str, value: Any, max_chars: int, max_items: int) -> list[str]:
    if not isinstance(value, list):
        raise ProfileError("invalid_value", f"{field} must be a list", field=field)
    if len(value) > max_items:
        raise ProfileError("invalid_value", f"{field} must have at most {max_items} items", field=field)
    items: list[str] = []
    for item in value:
        text = _as_text(item, field=field, max_chars=max_chars)
        if not text:
            raise ProfileError("invalid_value", f"{field} items must not be empty", field=field)
        if text not in items:
            items.append(text)
    return items


def validate_fields(raw: Any) -> dict[str, Any]:
    """Validate an update payload; unknown keys and bad values raise ProfileError."""
    if not isinstance(raw, dict):
        raise ProfileError("invalid_argument", "fields must be a JSON object of field -> value")
    unknown = sorted(key for key in raw if key not in FIELD_ORDER)
    if unknown:
        raise ProfileError(
            "unknown_field",
            "unknown field(s): "
            + ", ".join(unknown)
            + "; allowed: "
            + ", ".join(FIELD_ORDER),
        )
    cleaned: dict[str, Any] = {}
    for field, value in raw.items():
        if field in ENUM_FIELDS:
            cleaned[field] = _check_enum(field, value, ENUM_FIELDS[field])
        elif field in INT_FIELDS:
            low, high = INT_FIELDS[field]
            if not _is_int(value) or not low <= value <= high:
                raise ProfileError(
                    "invalid_value",
                    f"{field} must be an integer between {low} and {high}",
                    field=field,
                )
            cleaned[field] = value
        elif field in ENUM_LIST_FIELDS:
            allowed, max_items = ENUM_LIST_FIELDS[field]
            cleaned[field] = _check_enum_list(field, value, allowed, max_items)
        elif field in TEXT_LIST_FIELDS:
            max_chars, max_items = TEXT_LIST_FIELDS[field]
            cleaned[field] = _check_text_list(field, value, max_chars, max_items)
        elif field in TEXT_FIELDS:
            cleaned[field] = _as_text(value, field=field, max_chars=TEXT_FIELDS[field])
    return cleaned


def validate_field_names(names: Any) -> list[str]:
    """Validate the field list passed to profile_clear."""
    if not isinstance(names, list):
        raise ProfileError("invalid_argument", "fields must be a list of field names or null")
    unknown = sorted({name for name in names if not isinstance(name, str) or name not in FIELD_ORDER})
    if unknown:
        raise ProfileError(
            "unknown_field",
            "unknown field(s): " + ", ".join(str(name) for name in unknown),
        )
    ordered: list[str] = []
    for name in names:
        if name not in ordered:
            ordered.append(name)
    return ordered
