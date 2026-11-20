# cn-daily-store

全 A 日线库（T154），是主升浪规则引擎（T155）的唯一数据来源。Python ≥3.11，运行时只用标准库
（`sqlite3` + `urllib`），不新增第三方依赖。

## 安装与运行

```bash
cd packages/cn-daily-store
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e '.[test]'

.venv/bin/cn-daily-store init
.venv/bin/cn-daily-store backfill --limit 50
.venv/bin/cn-daily-store backfill                  # 可中断，按代码续跑
.venv/bin/cn-daily-store update                    # 交易日 15:30 之后
.venv/bin/cn-daily-store check --pool-days 15
.venv/bin/cn-daily-store stats
```

默认数据库 `runtime/marketdata/daily.sqlite`（已在 `.gitignore` 范围内），用 `--db` 覆盖，或设
`CN_DAILY_STORE_DB`。`--db` 可放在子命令前或后。

## 数据源（只读）

| 数据 | 来源 | 说明 |
|---|---|---|
| 日线 OHLC/量/额（未复权） | 腾讯 `web.ifzq.gtimg.cn/appstock/app/newfqkline/get` | 单只串行；全局 ≤3 次/秒；失败指数退避；不含 `push2*` 主机 |
| 复权因子 | 新浪 `finance.sina.com.cn/realstock/company/<symbol>/qfq.js`；备用腾讯 qfq | 腾讯单次 qfq 最多 640 根，长历史用新浪完整因子；`qfq = raw / f`，存 `1/f` |
| 证券清单、名称、上市/退市日 | 上交所 `query.sse.com.cn`、深交所 `www.szse.cn` 公开列表 | 上交所含已退市；深交所 A 股列表仅当前上市 |
| 交易日历 | 腾讯上证指数 `sh000001` 日线日期 | 2018-01-01 起；日线存在即交易日 |
| 涨停池交叉核对 | 网关 `http://127.0.0.1:8768/v1/call` 的 `market_limit_pool(kind=zt)` | 只读、串行、低频 |

单位换算：腾讯 K 线成交量对主板/创业板为手（入库 ×100 为股），科创板 688/689 直接为股（不再乘 100）；
第 9 个字段为成交额（万元），入库 ×10000 为元。
`adj_factor = 前复权收盘 / 未复权收盘`，前复权价按
`close × adj_factor / 该股最新 adj_factor` 计算，不存第二份价格。腾讯 qfq 接口单次只返回 640 根，
因此长历史优先用新浪 qfq 因子文件（`qfq = raw / f`，存 `1/f`）；新浪取不到时回退到腾讯 qfq，
并按 640 根一段向前补齐。

## 表

- `calendar(date PRIMARY KEY)`
- `securities(code PRIMARY KEY, name, board, list_date, delist_date, updated_at)`，
  `board ∈ {sh_main, sz_main, chinext, star}`；北交所、B 股、基金不入库。
- `names(code, start_date, name, PRIMARY KEY(code, start_date))`：当前简称及能取到的历史简称。
- `bars(code, date, open, high, low, close, volume, amount, adj_factor, PRIMARY KEY(code,date))`：
  未复权 OHLC、成交量（股）、成交额（元）、复权因子。停牌不插空行。
- `meta(key, value)`：版本、数据源、最后更新日、每只股票的抓取进度。

代码格式统一为 `600519.SH` / `000528.SZ`。

## Python API

```python
from cn_daily_store import DailyStore

store = DailyStore("runtime/marketdata/daily.sqlite")   # 默认只读，可多进程并发读
store.calendar("2024-01-01", "2024-12-31")              # list[date]
store.universe("2024-06-28")                            # list[str]，按规格第 0 节股票池
store.bars("600519.SH", "2024-01-01", "2024-12-31", adjust="qfq")  # list[Bar]
store.bars_on("2024-06-28", codes=None, adjust="qfq")   # dict[code, Bar]
store.is_limit_up("600519.SH", "2024-06-28")            # bool
store.limit_ratio("600519.SH", "2024-06-28")            # Decimal | None
store.limit_up_price("600519.SH", "2024-06-28")         # float | None
store.name_on("600519.SH", "2024-06-28")                # str | None
store.is_st("600519.SH", "2024-06-28")                  # bool
store.close()
```

`Bar` 是 frozen dataclass：`code, date, open, high, low, close, volume, amount, adj_factor`。
`adjust="qfq"` 时 OHLC 为前复权价（保留 3 位小数），`adj_factor` 仍为原始因子。

## 涨跌停规则

- 主板 10%，ST/*ST 5%；创业板 2020-08-24 起 20%（含 ST），之前 10%（ST 5%）；科创板 20%。
- `limit_up_price = round_half_up(上一根有效未复权收盘 × (1+p), 2)`；`is_limit_up` 用未复权收盘精确到分比较。
- 上市前 5 个交易日不判定；`universe()` 排除上市不足 60 个交易日、ST、退市整理期名称（`退市…`/`退…`）。

## 已知限制

- 交易所列表只给当前简称，历史 ST 期间无法精确重建；`names` 目前每只股票只有一条当前名称。
  近期涨停池核对不受影响（当前名称准确），历史回测的 ST 过滤是近似值。
- `limit_up_price` 按任务书字面口径使用上一根未复权收盘，未按除权参考价调整；除权日的涨停价可能偏差。
- 深交所公开列表没有已退市股票；已退市样本主要来自上交所列表。
- `check` 的相邻日涨跌幅阈值按当前 ST 状态近似历史 ST；除权日再用复权价复核。
- 每日 `update` 对每只股票各请求一次未复权与前复权日线（约 5000 只，受 3 次/秒限制），全量增量约 1 小时。

## 测试

全部离线（HTTP 传输注入假实现）：

```bash
.venv/bin/python -m pytest -q
```
