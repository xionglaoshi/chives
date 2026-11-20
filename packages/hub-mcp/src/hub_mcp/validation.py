"""Argument validation for the hub tools.

Free-text cleaning mirrors profile-mcp / portfolio-mcp: flatten and de-fang the
text, reject instruction-like payloads, secrets and account-shaped digit runs.
"""

from __future__ import annotations

import math
import re
from typing import Any

from hub_mcp.errors import ToolError

PLAN_KINDS = {"entry", "giveup", "watch", "exit"}
CONDITION_TYPES = {"price_cross", "price_in_range", "pct_change"}
MAX_RATIONALE_CHARS = 200
MAX_PLAN_DAYS = 30

_CODE_RE = re.compile(
    r"^(?:(?P<prefix>SH|SZ|BJ))?(?P<digits>\d{1,6})(?:\.(?P<suffix>SH|SZ|BJ|SS))?$"
)
_SH_PREFIXES = ("6", "5")  # 5xxxxx: Shanghai-listed ETF/LOF
_SZ_PREFIXES = ("0", "3", "159", "16")  # 159xxx / 16xxxx: Shenzhen-listed funds
_BJ_PREFIXES = ("92", "43", "83", "87", "88")

_CONTROL_RE = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f"
    "\u200b-\u200f\u2028-\u202e\u2060-\u2064\ufeff]"
)
_MARKUP_RE = re.compile(r"[<>`]")
_SPACE_RE = re.compile(r"\s+")

_EN_GAP = r"[\s,;:.!?'\"()\-]{0,3}"

SUSPICIOUS_PATTERNS: tuple[str, ...] = (
    r"(?:忽略|无视|忽视|绕过|突破|越过|规避|撇开|忘记)[^，,。.;；!！?？\n]{0,12}"
    r"(?:规则|限制|指令|安全|约束|设定|提示|要求|政策|审查|过滤|监管|之前|以上|前面)",
    r"(?:不要|不必|不需|无需|不用|不准|禁止|拒绝|别)[^，,。.;；!！?？\n]{0,4}"
    r"(?:遵守|遵循|服从|理会)",
    r"(?:违反|违背|对抗)[^，,。.;；!！?？\n]{0,8}"
    r"(?:规则|限制|指令|安全|规定|约束|政策|要求)",
    r"从现在(?:起|开始)",
    r"今后你",
    r"你现在(?:是|扮演)",
    r"扮演",
    r"忽略(?:以上|之前|前面|上述|上面|此前|所有|全部)",
    r"(?:无视|不要理会|不要遵循)之前",
    r"忘记(?:之前|以上|前面|所有)",
    r"系统(?:提示|指令|消息)",
    r"(?:新指令|跳过限制|解除限制|无限制模式|越狱模式|覆盖以上)",
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
    "资金账号",
    "资金账户",
    "股东账号",
    "股东账户",
)

SENSITIVE_REGEXES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\d{11,}"),  # phone numbers, ID numbers, account numbers
    re.compile(r"1[3-9]\d[ -]\d{4}[ -]\d{4}"),  # mainland mobile with separators
    re.compile(r"\d{4}(?:[ -]\d{4}){2,}"),  # bank card grouped in fours
    re.compile(r"\d{17}[\dXx]"),  # 18-character mainland ID number
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),  # e-mail
)


def clean_text(value: str) -> str:
    text = value.replace("\r\n", " ").replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = _CONTROL_RE.sub("", text)
    text = _MARKUP_RE.sub("", text)
    return _SPACE_RE.sub(" ", text).strip()


def clean_free_text(
    value: Any,
    field: str,
    max_chars: int,
    *,
    allow_empty: bool = False,
) -> str:
    """Flatten and de-fang one free-text field; reject instructions and secrets."""
    if not isinstance(value, str):
        raise ToolError("invalid_value", f"{field} 必须是字符串", field=field)
    text = clean_text(value)
    for pattern in SUSPICIOUS_REGEXES:
        if pattern.search(text):
            raise ToolError(
                "suspicious_text",
                f"{field} 看起来像在给智能体下指令；请改写为普通说明",
                field=field,
            )
    lowered = text.casefold()
    for pattern in SENSITIVE_PATTERNS:
        if pattern in lowered:
            raise ToolError(
                "sensitive_text",
                f"{field} 含疑似密钥、账号或个人信息；不要提交",
                field=field,
            )
    for regex in SENSITIVE_REGEXES:
        if regex.search(text):
            raise ToolError(
                "sensitive_text",
                f"{field} 含疑似密钥、账号或个人信息；不要提交",
                field=field,
            )
    if not text and not allow_empty:
        raise ToolError("invalid_value", f"{field} 不能为空", field=field)
    if len(text) > max_chars:
        raise ToolError("invalid_value", f"{field} 最多 {max_chars} 字", field=field)
    return text


def clean_body(value: Any, *, max_chars: int = 20000) -> str:
    """Keep markdown structure, drop control bytes; never account-reject a body."""
    if not isinstance(value, str):
        raise ToolError("invalid_value", "body_markdown 必须是字符串", field="body_markdown")
    if len(value) > max_chars:
        raise ToolError("too_large", f"body_markdown 不得超过 {max_chars} 字符", field="body_markdown")
    kept = "".join(
        char
        for char in value
        if char in {"\n", "\t"} or (ord(char) >= 32 and char not in {"\x7f"})
    )
    return kept.replace("\r\n", "\n").replace("\r", "\n")


def clean_rationale(value: Any, *, max_chars: int = MAX_RATIONALE_CHARS) -> str:
    return clean_free_text(value, "rationale", max_chars)


def optional_text(value: Any, field: str, max_chars: int) -> str | None:
    if value is None:
        return None
    text = clean_free_text(value, field, max_chars, allow_empty=True)
    return text or None


def only_fields(raw: dict[str, Any], allowed: set[str], *, field: str = "payload") -> None:
    extra = sorted(set(raw) - allowed)
    if extra:
        raise ToolError(
            "unexpected_field",
            f"{field} 不支持的字段: " + ", ".join(extra),
            field=field,
        )


def finite_number(value: Any, field: str, *, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ToolError("invalid_value", f"{field} 必须是数字", field=field)
    number = float(value)
    if not math.isfinite(number):
        raise ToolError("invalid_value", f"{field} 必须是有限数字", field=field)
    if minimum is not None and number < minimum:
        raise ToolError("bad_value", f"{field} 不得小于 {minimum:g}", field=field)
    if maximum is not None and number > maximum:
        raise ToolError("bad_value", f"{field} 不得大于 {maximum:g}", field=field)
    return number


def safe_date(value: Any, field: str = "date") -> str:
    from datetime import date as _date

    if not isinstance(value, str) or len(value.strip()) != 10:
        raise ToolError("invalid_date", f"{field} 必须是 YYYY-MM-DD", field=field)
    text = value.strip()
    try:
        _date.fromisoformat(text)
    except ValueError as exc:
        raise ToolError("invalid_date", f"{field} 必须是 YYYY-MM-DD", field=field) from exc
    return text


def _infer_exchange(digits: str) -> str | None:
    if digits.startswith(_SH_PREFIXES):
        return "SH"
    if digits.startswith(_SZ_PREFIXES):
        return "SZ"
    if digits.startswith(_BJ_PREFIXES):
        return "BJ"
    return None


def normalize_code(value: Any) -> str:
    """Return ``NNNNNN.SH/SZ/BJ`` for A-share stocks and listed funds."""
    if not isinstance(value, str):
        raise ToolError("invalid_code", "code 必须是字符串", field="code")
    text = value.strip().upper()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    match = _CODE_RE.match(text)
    if match is None:
        raise ToolError(
            "invalid_code",
            "只支持 A 股股票与基金：NNNNNN.SH/.SZ/.BJ 或 6 位数字代码",
            field="code",
        )
    digits = match.group("digits").zfill(6)
    inferred = _infer_exchange(digits)
    if inferred is None:
        raise ToolError("invalid_code", "不是沪深北 A 股代码", field="code")
    explicit = match.group("prefix") or match.group("suffix")
    if explicit == "SS":
        explicit = "SH"
    if explicit is not None and explicit != inferred:
        raise ToolError("invalid_code", "交易所后缀与代码前缀不一致", field="code")
    return f"{digits}.{inferred}"


def validate_kind(value: Any) -> str:
    if not isinstance(value, str) or value not in PLAN_KINDS:
        raise ToolError("invalid_kind", "kind 只接受 entry/giveup/watch/exit", field="kind")
    return value


def _number(value: Any, field: str, *, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ToolError("invalid_condition", f"{field} 必须是数字", field=field)
    number = float(value)
    if not math.isfinite(number):
        raise ToolError("invalid_condition", f"{field} 必须是有限数字", field=field)
    if number <= 0:
        raise ToolError("invalid_condition", f"{field} 必须为正数", field=field)
    if maximum is not None and number > maximum:
        raise ToolError("invalid_condition", f"{field} 不得大于 {maximum}", field=field)
    return number


def _only(raw: dict[str, Any], allowed: set[str]) -> None:
    extra = sorted(set(raw) - allowed)
    if extra:
        raise ToolError("invalid_condition", "condition 不支持的字段: " + ", ".join(extra), field="condition")


def validate_condition(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ToolError("invalid_condition", "condition 必须是对象", field="condition")
    cond_type = value.get("type")
    if cond_type == "price_cross":
        _only(value, {"type", "direction", "level"})
        direction = value.get("direction")
        if direction not in {"up", "down"}:
            raise ToolError("invalid_condition", "price_cross.direction 只接受 up/down", field="condition")
        return {
            "type": "price_cross",
            "direction": direction,
            "level": _number(value.get("level"), "condition.level"),
        }
    if cond_type == "price_in_range":
        _only(value, {"type", "lo", "hi"})
        lo = _number(value.get("lo"), "condition.lo")
        hi = _number(value.get("hi"), "condition.hi")
        if lo >= hi:
            raise ToolError("invalid_condition", "price_in_range 要求 lo < hi", field="condition")
        return {"type": "price_in_range", "lo": lo, "hi": hi}
    if cond_type == "pct_change":
        _only(value, {"type", "direction", "threshold_pct"})
        direction = value.get("direction")
        if direction not in {"up", "down"}:
            raise ToolError("invalid_condition", "pct_change.direction 只接受 up/down", field="condition")
        return {
            "type": "pct_change",
            "direction": direction,
            "threshold_pct": _number(
                value.get("threshold_pct"), "condition.threshold_pct", maximum=100.0
            ),
        }
    raise ToolError(
        "invalid_condition",
        "condition.type 只接受 price_cross/price_in_range/pct_change",
        field="condition",
    )


def validate_expires_in_days(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError("invalid_value", "expires_in_days 必须是整数", field="expires_in_days")
    if not 1 <= value <= MAX_PLAN_DAYS:
        raise ToolError("invalid_value", "expires_in_days 必须在 1..30", field="expires_in_days")
    return value


def validate_stop(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ToolError("invalid_value", "stop 必须是数字或 null", field="stop")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ToolError("invalid_value", "stop 必须为正数", field="stop")
    return number


def validate_analysis_id(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ToolError("invalid_value", "analysis_id 必须是非负整数或 null", field="analysis_id")
    return value
