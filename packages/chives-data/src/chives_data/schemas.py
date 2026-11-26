"""JSON Schemas for the four T140 tools and the static MCP fallback list."""

from __future__ import annotations

from typing import Any

from .company_schemas import COMPANY_TOOLS
from .news_schemas import NEWS_TOOLS

TOOLS: list[dict[str, Any]] = [
    {
        "name": "market_quote",
        "description": (
            "读取 1 到 20 只 A 股、ETF 或指数的实时快照：价格、昨收、涨跌幅、开高低、"
            "成交量（股）、成交额（元）、换手率、量比、市盈率、市净率、涨跌停价与行情时间。"
            "返回 status=ok/partial/unavailable；取不到的标的或字段逐项写入 missing。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "codes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 20,
                    "description": "代码列表，例如 600519、sh600519、600519.SH、000300.SH",
                }
            },
            "required": ["codes"],
            "additionalProperties": False,
        },
    },
    {
        "name": "market_bars",
        "description": (
            "读取 A 股、ETF 或指数的 K 线。interval 取 1m/5m/15m/30m/60m/1d/1w/1M，默认 1d；"
            "adjust 取 none/qfq/hfq；limit 默认 250、最多 1000。日线每行含成交量（股）、"
            "成交额（元）与换手率；周线/月线由日线聚合，时间取该周期最后一个交易日。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "例如 600519、000300.SH"},
                "interval": {
                    "type": "string",
                    "enum": ["1m", "5m", "15m", "30m", "60m", "1d", "1w", "1M"],
                    "default": "1d",
                },
                "start": {"type": ["string", "null"], "description": "YYYY-MM-DD，含当日"},
                "end": {"type": ["string", "null"], "description": "YYYY-MM-DD，含当日"},
                "adjust": {"type": "string", "enum": ["none", "qfq", "hfq"], "default": "none"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 250},
            },
            "required": ["code"],
            "additionalProperties": False,
        },
    },
    {
        "name": "market_intraday",
        "description": (
            "单日盘中汇总：开高低收、最高/最低价首次出现时间、VWAP=sum(amount)/sum(volume)、"
            "收盘相对 VWAP、前 30 分钟成交量占比、最高价那根起到收盘的成交量占比、"
            "数据是否覆盖到 15:00。只接受交易日 YYYY-MM-DD。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "例如 600519、920418.BJ"},
                "date": {"type": "string", "description": "交易日 YYYY-MM-DD"},
            },
            "required": ["code", "date"],
            "additionalProperties": False,
        },
    },
    {
        "name": "market_global",
        "description": (
            "读取外盘：groups 可取 us_index、hk_index、a50、fx、commodity、rates、leaders；"
            "symbols 可给 1 到 10 个海外个股（如 usNVDA、hk00700）。groups 与 symbols 二选一。"
            "返回价格、昨收/昨结算、涨跌幅、行情时间与时区；期货涨跌幅相对昨结算价。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "groups": {
                    "type": ["array", "null"],
                    "items": {
                        "type": "string",
                        "enum": ["us_index", "hk_index", "a50", "fx", "commodity", "rates", "leaders"],
                    },
                },
                "symbols": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 10,
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "market_overview",
        "description": (
            "读取大盘概览：主要指数行情、涨跌家数、涨停/跌停/炸板家数、最大连板、全市场成交额，"
            "并在有市场摘要时附 3–5 条 headline。取不到的字段逐项写入 missing，口径差异写入 basis。"
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "market_movers",
        "description": (
            "读取全 A 榜单：kind 取 gainers（涨幅）/losers（跌幅）/active（成交额），"
            "limit 默认 10、最多 200，include_bj 默认 false。每行含 code、name、price、"
            "change_pct、amount_yuan、turnover_pct。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["gainers", "losers", "active"], "default": "gainers"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 10},
                "include_bj": {"type": "boolean", "default": False},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "market_limit_pool",
        "description": (
            "读取涨停/炸板/跌停池、连板梯队与封板率：kind 取 zt/zb/dt/ladder/stats，"
            "date 为交易日期（默认最近交易日），limit 默认 50、最多 500，"
            "stats 时 days 为 1–30（默认 10）。换源后缺失的字段逐项写入 missing。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["zt", "zb", "dt", "ladder", "stats"], "default": "zt"},
                "date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 50},
                "days": {"type": "integer", "minimum": 10, "maximum": 30, "default": 10},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "market_sectors",
        "description": (
            "读取行业/概念板块：kind 取 industry/concept，sort 取 change/amount，limit 默认 20；"
            "排行含板块内上涨/下跌家数、涨停家数、相对沪深300涨跌幅（百分点）、30分钟排名变化"
            "与成交额占比（百分数）；不同分类口径取不到的字段逐项写入 missing，口径差异写在 basis。"
            "给 code 时返回单个板块详情。行业排行没有代码时，传 industry:行业名称 查询最多五只领涨股及成交额。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["industry", "concept"], "default": "industry"},
                "sort": {"type": "string", "enum": ["change", "amount"], "default": "change"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                "code": {"type": ["string", "null"], "description": "例如 new_kfq、gn_hwhs、industry:半导体"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "market_fund_flow",
        "description": (
            "读取资金流：scope 取 stock（个股，给 code）/sector（板块排行）/rank（个股排行），"
            "kind 取 in/out，limit 默认 10，days 为个股历史天数（默认 20）。"
            "字段为主力净流入；口径与默认主力口径不同时写入 basis。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "scope": {"type": "string", "enum": ["stock", "sector", "rank"], "default": "rank"},
                "kind": {"type": "string", "enum": ["in", "out"], "default": "in"},
                "code": {"type": ["string", "null"], "description": "scope=stock 时必填，例如 600519"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10},
                "days": {"type": "integer", "minimum": 1, "maximum": 120, "default": 20},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "market_trading_activity",
        "description": (
            "读取龙虎榜/大宗交易/融资融券：kind 取 dragon_tiger/block_trades/margin；"
            "龙虎榜用 date（默认今天），给 code 时附买卖席位；大宗交易与两融必须给 code，"
            "days 为回看窗口（大宗默认 30、最多 365；两融默认 30、最多 250）。"
            "金额单位为元，大宗 premium_pct 为百分数。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["dragon_tiger", "block_trades", "margin"]},
                "code": {"type": ["string", "null"]},
                "date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
                "days": {"type": "integer", "minimum": 1, "maximum": 365, "default": 30},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 200},
            },
            "required": ["kind"],
            "additionalProperties": False,
        },
    },
    {
        "name": "market_northbound",
        "description": (
            "读取北向数据：kind 取 daily（每日成交额与笔数；days>1 时一次返回最近 N 个交易日）/top_active（前十活跃股成交额）/"
            "holdings（季度持股：给 code 查单只；不给 code 时沪深两通合并，按 sort 降序取前 limit 只）；date 为交易日或季度末。"
            "本工具不提供也不估算每日净流入；成交额为买卖合计，季度持股变化为本季末减上季末。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["daily", "top_active", "holdings"], "default": "daily"},
                "date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
                "code": {"type": ["string", "null"], "description": "仅 holdings 可选用"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50, "description": "仅 holdings 且不给 code 时"},
                "days": {"type": "integer", "minimum": 1, "maximum": 20, "default": 1, "description": "仅 daily：返回截至 date（默认最近交易日）的最近 N 个交易日，一次调用取一段区间"},
                "sort": {"type": "string", "enum": ["change_shares", "shareholding_pct", "change_pct_points"], "default": "change_shares", "description": "仅 holdings 且不给 code 时：按季度增持股数/持股比例/比例变化降序"},
            },
            "additionalProperties": False,
        },
    },
]


TOOLS.extend(COMPANY_TOOLS)
TOOLS.extend(NEWS_TOOLS)


def static_tools() -> list[dict[str, Any]]:
    return [dict(tool) for tool in TOOLS]
