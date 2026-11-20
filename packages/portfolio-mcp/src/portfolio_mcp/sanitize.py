"""Text cleaning plus instruction / credential rejection.

Reused in spirit from profile-mcp: every free-text field is flattened and de-fanged,
and text that looks like an instruction to the agent or like a secret / account
number is rejected instead of stored.
"""

from __future__ import annotations

import re

from portfolio_mcp.errors import PortfolioError

MAX_TEXT_CHARS = 200_000

_CONTROL_RE = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f"
    "\u200b-\u200f\u2028-\u202e\u2060-\u2064\ufeff]"
)
_MARKUP_RE = re.compile(r"[<>`]")
_SPACE_RE = re.compile(r"\s+")
_DIGIT_RUN_RE = re.compile(r"\d{11,}")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_ID_RE = re.compile(r"\d{17}[\dXx]")
_BANK_GROUPED_RE = re.compile(r"\d{4}(?:[ -]\d{4}){2,}")
_MOBILE_RE = re.compile(r"1[3-9]\d[ -]\d{4}[ -]\d{4}")

_EN_GAP = r"[\s,;:.!?'\"()\-]{0,3}"

# Instruction-like fragments; matched case-insensitively against free text.
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
    # English
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

# Credential / personal-identifier fragments; never stored, never echoed back.
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
    _DIGIT_RUN_RE,
    _MOBILE_RE,
    _BANK_GROUPED_RE,
    _ID_RE,
    _EMAIL_RE,
)


def clean_text(value: str) -> str:
    """Flatten and de-fang user text before it can reach storage or a prompt."""
    text = value.replace("\r\n", " ").replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = _CONTROL_RE.sub("", text)
    text = _MARKUP_RE.sub("", text)
    return _SPACE_RE.sub(" ", text).strip()


def check_text_payload(text: object) -> str:
    """Reject instruction-like or sensitive whole payloads; keep row/column structure intact."""
    if not isinstance(text, str):
        raise PortfolioError("invalid_argument", "text must be a string", field="text")
    if len(text) > MAX_TEXT_CHARS:
        raise PortfolioError(
            "text_too_large",
            f"text must be at most {MAX_TEXT_CHARS} characters",
            field="text",
        )
    # Keep the row/column structure (tabs, newlines) but drop other control bytes and markup.
    sample = _MARKUP_RE.sub("", _CONTROL_RE.sub("", text))
    for regex in SUSPICIOUS_REGEXES:
        if regex.search(sample):
            raise PortfolioError(
                "suspicious_text",
                "text looks like an instruction to the agent; paste only the holdings table",
                field="text",
            )
    lowered = sample.casefold()
    for pattern in SENSITIVE_PATTERNS:
        if pattern in lowered:
            raise PortfolioError(
                "sensitive_text",
                "text looks like it contains a secret, account number or personal identifier; "
                "remove those columns and paste only code/name/quantity/cost",
                field="text",
            )
    for regex in SENSITIVE_REGEXES:
        if regex.search(sample):
            raise PortfolioError(
                "sensitive_text",
                "text looks like it contains a secret, account number or personal identifier; "
                "remove those columns and paste only code/name/quantity/cost",
                field="text",
            )
    return sample


def clean_free_text(value: object, *, field: str, max_chars: int, allow_empty: bool = False) -> str:
    """Clean one short text field, then apply the same rejection rules."""
    if not isinstance(value, str):
        raise PortfolioError("invalid_value", f"{field} must be a string", field=field)
    text = clean_text(value)
    for regex in SUSPICIOUS_REGEXES:
        if regex.search(text):
            raise PortfolioError(
                "suspicious_text",
                f"{field} looks like an instruction to the agent; rewrite it as plain data",
                field=field,
            )
    lowered = text.casefold()
    for pattern in SENSITIVE_PATTERNS:
        if pattern in lowered:
            raise PortfolioError(
                "sensitive_text",
                f"{field} looks like a secret or personal identifier; do not store it",
                field=field,
            )
    for regex in SENSITIVE_REGEXES:
        if regex.search(text):
            raise PortfolioError(
                "sensitive_text",
                f"{field} looks like a secret or personal identifier; do not store it",
                field=field,
            )
    if not text and not allow_empty:
        raise PortfolioError("invalid_value", f"{field} must not be empty", field=field)
    if len(text) > max_chars:
        raise PortfolioError(
            "invalid_value",
            f"{field} must be at most {max_chars} characters",
            field=field,
        )
    return text
