"""Fixed gateway limits, hosts and cache lifetimes (design §7)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone

CN_TZ = timezone(timedelta(hours=8))

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8868


@dataclass(frozen=True)
class HostPolicy:
    host: str
    rate_bucket: str
    max_per_minute: int
    max_concurrency: int
    min_interval: float
    timeout: float = 8.0


# Only hosts used by the gateway tools are whitelisted.  Any host whose name
# contains the forbidden marker is rejected before this table is consulted.
HOST_POLICIES: dict[str, HostPolicy] = {
    "qt.gtimg.cn": HostPolicy("qt.gtimg.cn", "tencent", 120, 4, 0.0),
    "web.ifzq.gtimg.cn": HostPolicy("web.ifzq.gtimg.cn", "tencent", 120, 2, 0.0),
    "hq.sinajs.cn": HostPolicy("hq.sinajs.cn", "sina", 30, 2, 0.5),
    "quotes.sina.cn": HostPolicy("quotes.sina.cn", "sina", 30, 2, 1.0, 20.0),
    "finance.sina.com.cn": HostPolicy("finance.sina.com.cn", "sina", 30, 1, 1.0, 20.0),
    "vip.stock.finance.sina.com.cn": HostPolicy(
        "vip.stock.finance.sina.com.cn", "sina", 30, 2, 0.5, 15.0
    ),
    "money.finance.sina.com.cn": HostPolicy(
        "money.finance.sina.com.cn", "sina", 30, 1, 0.5, 15.0
    ),
    "datacenter.eastmoney.com": HostPolicy(
        "datacenter.eastmoney.com", "eastmoney_data", 30, 1, 1.0, 20.0
    ),
    "datacenter-web.eastmoney.com": HostPolicy(
        "datacenter-web.eastmoney.com", "eastmoney_data", 30, 1, 1.0, 20.0
    ),
    "legulegu.com": HostPolicy("legulegu.com", "legu", 6, 1, 10.0, 20.0),
    "data.10jqka.com.cn": HostPolicy("data.10jqka.com.cn", "ths", 20, 1, 1.0, 15.0),
    "basic.10jqka.com.cn": HostPolicy("basic.10jqka.com.cn", "ths", 20, 1, 1.0, 15.0),
    "q.10jqka.com.cn": HostPolicy("q.10jqka.com.cn", "ths", 20, 1, 1.0, 15.0),
    "stock.finance.sina.com.cn": HostPolicy(
        "stock.finance.sina.com.cn", "sina", 30, 1, 1.0, 20.0
    ),
    "reportapi.eastmoney.com": HostPolicy(
        "reportapi.eastmoney.com", "eastmoney_data", 30, 1, 1.0, 20.0
    ),
    "emweb.securities.eastmoney.com": HostPolicy(
        "emweb.securities.eastmoney.com", "eastmoney_data", 30, 1, 1.0, 20.0
    ),
    "searchapi.eastmoney.com": HostPolicy(
        "searchapi.eastmoney.com", "eastmoney_data", 30, 2, 1.0, 15.0
    ),
    "search-api-web.eastmoney.com": HostPolicy(
        "search-api-web.eastmoney.com", "eastmoney_data", 30, 1, 1.0, 20.0
    ),
    "np-weblist.eastmoney.com": HostPolicy(
        "np-weblist.eastmoney.com", "eastmoney_data", 30, 1, 1.0, 20.0
    ),
    "www.cls.cn": HostPolicy("www.cls.cn", "cls", 30, 1, 1.0, 20.0),
    "finance.pae.baidu.com": HostPolicy("finance.pae.baidu.com", "baidu", 20, 1, 1.0, 20.0),
    "finance.baidu.com": HostPolicy("finance.baidu.com", "baidu", 20, 1, 1.0, 20.0),
    "hm.baidu.com": HostPolicy("hm.baidu.com", "baidu", 20, 1, 1.0, 20.0),
    "irm.cninfo.com.cn": HostPolicy("irm.cninfo.com.cn", "cninfo", 20, 1, 1.0, 20.0),
    "www.cninfo.com.cn": HostPolicy("www.cninfo.com.cn", "cninfo", 20, 1, 1.0, 20.0),
    "static.cninfo.com.cn": HostPolicy("static.cninfo.com.cn", "cninfo", 20, 1, 1.0, 25.0),
    "webapi.cninfo.com.cn": HostPolicy("webapi.cninfo.com.cn", "cninfo", 20, 1, 1.0, 20.0),
    "oss-ch.csindex.com.cn": HostPolicy(
        "oss-ch.csindex.com.cn", "csindex", 20, 1, 1.0, 20.0
    ),
    "gushitong.baidu.com": HostPolicy("gushitong.baidu.com", "baidu", 20, 1, 1.0, 20.0),
    "www.hkex.com.hk": HostPolicy("www.hkex.com.hk", "hkex", 10, 1, 1.0, 15.0),
    "www3.hkexnews.hk": HostPolicy("www3.hkexnews.hk", "hkexnews", 6, 1, 1.0, 25.0),
}
ALLOWED_HOSTS = frozenset(HOST_POLICIES)
_FORBIDDEN_HOST_MARKERS = ("push" + str(2),)

HOST_TIMEOUT = 8.0
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
HTTP_RETRIES = 1
AKSHARE_TIMEOUT = 20.0
AKSHARE_WORKERS = 4

# cache: (fresh ttl seconds, stale fallback seconds)
QUOTE_TTL = 3.0
QUOTE_FALLBACK = 60.0
MINUTE_TTL = 30.0
MINUTE_FALLBACK = 300.0
INTRADAY_TTL = 30.0
INTRADAY_FALLBACK = 300.0
DAILY_TRADING_TTL = 60.0
DAILY_CLOSED_TTL = 18 * 3600.0
DAILY_FALLBACK = 24 * 3600.0
GLOBAL_TTL = 30.0
GLOBAL_FALLBACK = 60.0
RATES_TTL = 1800.0
RATES_FALLBACK = 24 * 3600.0
OVERVIEW_TTL = 15.0
OVERVIEW_FALLBACK = 120.0
MOVERS_TTL = 15.0
MOVERS_FALLBACK = 120.0
POOL_TTL = 30.0
POOL_FALLBACK = 600.0
SECTOR_TTL = 60.0
SECTOR_FALLBACK = 600.0
FLOW_TTL = 20.0
FLOW_FALLBACK = 300.0
ACTIVITY_TTL = 1800.0
ACTIVITY_FALLBACK = 6 * 3600.0
NORTHBOUND_FALLBACK = 24 * 3600.0
HOLDINGS_TTL = 24 * 3600.0
HOLDINGS_FALLBACK = 48 * 3600.0

# company/research cache lifetimes (design §7: whole-market tables >= 30 min, single stock >= 10 min)
COMPANY_SEARCH_TTL = 1800.0
COMPANY_SEARCH_FALLBACK = 6 * 3600.0
COMPANY_NAMES_TTL = 6 * 3600.0
COMPANY_NAMES_FALLBACK = 7 * 24 * 3600.0
COMPANY_FINANCIALS_TTL = 6 * 3600.0
COMPANY_FINANCIALS_FALLBACK = 7 * 24 * 3600.0
COMPANY_VALUATION_TTL = 600.0
COMPANY_VALUATION_FALLBACK = 24 * 3600.0
COMPANY_CONSENSUS_TTL = 1800.0
COMPANY_CONSENSUS_FALLBACK = 6 * 3600.0
COMPANY_STOCK_TTL = 600.0
COMPANY_STOCK_FALLBACK = 24 * 3600.0
COMPANY_EARNINGS_TTL = 1800.0
COMPANY_EARNINGS_FALLBACK = 6 * 3600.0
COMPANY_PROFILE_TTL = 1800.0
COMPANY_PROFILE_FALLBACK = 24 * 3600.0

# news / announcement / convertible-bond cache lifetimes (design §7: news 5 min, flash 30 s)
NEWS_STOCK_TTL = 300.0
NEWS_STOCK_FALLBACK = 6 * 3600.0
NEWS_FLASH_TTL = 30.0
NEWS_FLASH_FALLBACK = 600.0
NEWS_IRM_TTL = 300.0
NEWS_IRM_FALLBACK = 6 * 3600.0
NEWS_CALENDAR_TTL = 600.0
NEWS_CALENDAR_FALLBACK = 6 * 3600.0
NEWS_SUSPENSIONS_TTL = 600.0
NEWS_SUSPENSIONS_FALLBACK = 6 * 3600.0
ANNOUNCEMENTS_TTL = 300.0
ANNOUNCEMENTS_FALLBACK = 24 * 3600.0
LOCKUP_MARKET_TTL = 1800.0
LOCKUP_MARKET_FALLBACK = 24 * 3600.0
CB_LIST_TTL = 1800.0
CB_LIST_FALLBACK = 24 * 3600.0
CB_QUOTE_TTL = 30.0
CB_QUOTE_FALLBACK = 300.0

DEFAULT_NEWS_LIMIT = 10
DEFAULT_FLASH_LIMIT = 20
MAX_NEWS_LIMIT = 50
MAX_ANNOUNCEMENTS_LIMIT = 100
MAX_CB_LIST_LIMIT = 500
DEFAULT_CB_LIST_LIMIT = 50
MAX_CB_CODES = 20
NEWS_SUMMARY_MAX = 300
NEWS_BODY_MAX = 400
NEWS_QUESTION_MAX = 300
NEWS_ANSWER_MAX = 500
SUSPENSION_NAME_MAX = 100
SUSPENSION_REASON_MAX = 500

MAX_SEARCH_LIMIT = 20
DEFAULT_SEARCH_LIMIT = 10
MAX_FINANCIAL_PERIODS = 40
DEFAULT_FINANCIAL_PERIODS = 8
MAX_RATING_LIMIT = 50
DEFAULT_RATING_LIMIT = 20
MAX_EVENT_LIMIT = 200
DEFAULT_EVENT_LIMIT = 50
MAX_HOLDER_LIMIT = 50
DEFAULT_HOLDER_LIMIT = 20
MAX_HOLDER_PERIODS = 24
MAX_LOCKUP_LIMIT = 500
DEFAULT_LOCKUP_LIMIT = 100
MAX_LOCKUP_MARKET_LIMIT = 200
DEFAULT_LOCKUP_MARKET_LIMIT = 50
DEFAULT_LOCKUP_WINDOW_DAYS = 30
MAX_LOCKUP_WINDOW_DAYS = 90
MAX_ANNOUNCEMENT_OFFSET = 10000
MAX_INDUSTRY_LIMIT = 200
DEFAULT_INDUSTRY_LIMIT = 40
MAX_INDEX_CONS_LIMIT = 1000
DEFAULT_INDEX_CONS_LIMIT = 500
MAX_VALUATION_YEARS = 10
DEFAULT_VALUATION_YEARS = 3
MIN_PERCENTILE_SAMPLES = 60
MAX_SERIES_POINTS = 160
CONSENSUS_DISAGREE = 0.05

MAX_CODES = 20
MAX_OVERSEAS_SYMBOLS = 10
MAX_LIMIT = 1000
DEFAULT_LIMIT = 250
MAX_POOL_LIMIT = 500
DEFAULT_POOL_LIMIT = 50
MAX_MOVER_LIMIT = 200
MAX_SECTOR_LIMIT = 100
MAX_FLOW_LIMIT = 100

CIRCUIT_FAILURE_THRESHOLD = 3
CIRCUIT_OPEN_SECONDS = 300.0
RECENT_EVENTS = 50
#: How long a duplicate request waits for the identical one already running. Waiting
#: happens on a background thread (callers have their own CALL_BUDGET_SECONDS), so it
#: can outlast slow upstreams such as the quarterly holdings pages.
MAX_COALESCE_WAIT = 300.0
#: Longest a tool call waits for data before answering "being prepared" (dsh caps MCP calls at 60 s).
CALL_BUDGET_SECONDS = 40.0

FORBIDDEN_OUTPUT = (
    "tencent",
    "gtimg",
    "sina",
    "eastmoney",
    "akshare",
    "legu",
    "legulegu",
    "cninfo",
    "hkex",
    "hkexnews",
    "10jqka",
    "ths",
    "http",
    "fallback",
    "circuit_open",
    "circuit breaker",
    "熔断",
    "traceback",
)

#: Source names and implementation words that must never appear in text the gateway
#: itself writes (basis notes, missing reasons, messages, tool descriptions). Third-party
#: data (stock/concept/company names, news) is not checked against this list: a concept
#: may legitimately be called "腾讯概念".
FORBIDDEN_AUTHORED = FORBIDDEN_OUTPUT + (
    "新浪",
    "东财",
    "东方财富",
    "腾讯",
    "同花顺",
    "乐咕",
    "巨潮",
    "财联社",
    "百度",
    "港交所",
    "披露易",
    "直连",
    "备用",
    "主源",
    "第三方",
    "引擎",
)


def is_forbidden_host(host: str) -> bool:
    lowered = host.lower()
    return any(marker in lowered for marker in _FORBIDDEN_HOST_MARKERS)


def daily_ttl(now: datetime) -> float:
    """60 s while the market is open, otherwise keep until the next 09:30 open."""
    local = now.astimezone(CN_TZ)
    if local.weekday() >= 5:
        return DAILY_CLOSED_TTL
    current = local.time()
    if time(9, 15) <= current <= time(15, 5):
        return DAILY_TRADING_TTL
    if current < time(9, 30):
        return max(60.0, (datetime.combine(local.date(), time(9, 30), CN_TZ) - local).total_seconds())
    next_open = datetime.combine(local.date() + timedelta(days=1), time(9, 30), CN_TZ)
    while next_open.weekday() >= 5:
        next_open += timedelta(days=1)
    return max(60.0, (next_open - local).total_seconds())
