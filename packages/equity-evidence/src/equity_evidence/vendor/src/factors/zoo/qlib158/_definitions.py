"""Versioned factor definitions shared by the individual compatibility modules.

Catalogue adapted from microsoft/qlib@d5379c520f66a39953bad76234a7019a72796fd0,
qlib/contrib/data/handler.py and loader.py (Apache-2.0). Copyright (c) Microsoft Corporation.
Metadata and Chinese descriptions from the Vibe-Trading distribution (MIT).
Chives consolidated the definitions here and replaced the numerical implementation.
See NOTICE, LICENSE.md, Apache-2.0.txt, and MIT.txt in this directory.
"""
from ._measure import candle, rolling_measure

# Each entry gives the research themes, required input columns and published formula.
DEFINITIONS = {
    # 中文名称: Beta系数 N日
    # 简要说明: Slope(close, N) / close，收盘价对时间的N日线性回归斜率，按最新收盘价归一化。
    # 典型用途: 衡量N日价格趋势的速度和方向，正值表示上涨趋势。
    'beta': ('momentum', 'close',
        r"\\mathrm{Slope}(\\mathrm{close}, {window}) / \\mathrm{close}"),
    # 中文名称: 涨跌天数差 N日
    # 简要说明: CNTP_N - CNTN_N，N日内上涨天数与下跌天数之差。
    # 典型用途: 综合衡量N日内的涨跌方向，正值表示多头天数占优。
    'cntd': ('reversal', 'close',
        r"\\mathrm{CNTP}_{window} - \\mathrm{CNTN}_{window}"),
    # 中文名称: 下跌天数计数 N日
    # 简要说明: rolling_mean(1[close<close_prev], N)，N日内下跌天数占比。
    # 典型用途: 衡量N日内下跌频率，值高表示持续下跌行情。
    'cntn': ('reversal', 'close',
        r"\\mathrm{rolling\\_mean}(\\mathrm{1}[\\mathrm{close}<\\mathrm{close}_{{-1}}], {window})"),
    # 中文名称: 上涨天数计数 N日
    # 简要说明: rolling_mean(1[close>close_prev], N)，N日内上涨天数占比。
    # 典型用途: 衡量N日内上涨频率，值高表示持续上涨行情。
    'cntp': ('reversal', 'close',
        r"\\mathrm{rolling\\_mean}(\\mathrm{1}[\\mathrm{close}>\\mathrm{close}_{{-1}}], {window})"),
    # 中文名称: 收益率-量变化相关性 N日
    # 简要说明: ts_corr(close/close_prev, log(v/v_prev + 1), N)，N日价格变化与对数量变比的相关系数。
    # 典型用途: 衡量N日价格变动与成交量变动的相关性，反映量价配合程度。
    'cord': ('volume microstructure', 'close volume',
        r"\\mathrm{ts\\_corr}(\\mathrm{close}/\\mathrm{close}_{{-1}}, \\log(\\mathrm{volume}/\\mathrm{volume}_{{-1}} + 1), {window})"),
    # 中文名称: 价量相关性 N日
    # 简要说明: ts_corr(close, log(volume+1), N)，N日收盘价与成交量的相关系数。
    # 典型用途: 衡量N日价格与成交量的同步性，正相关表示价涨量增的健康走势。
    'corr': ('volume microstructure', 'close volume',
        r"\\mathrm{ts\\_corr}(\\mathrm{close}, \\log(\\mathrm{volume}+1), {window})"),
    # 中文名称: 最高价位置 N日
    # 简要说明: ts_argmax(high, N) / N，N日内最高价出现位置的归一化指标。
    # 典型用途: 值接近0表示最高价出现在近期，接近1表示出现在较早期。
    'imax': ('momentum', 'high',
        r"\\mathrm{ts\\_argmax}(\\mathrm{high}, {window}) / {window}"),
    # 中文名称: 最低价位置 N日
    # 简要说明: ts_argmin(low, N) / N，N日内最低价出现位置的归一化指标。
    # 典型用途: 值接近0表示最低价出现在近期，接近1表示出现在较早期。
    'imin': ('momentum', 'low',
        r"\\mathrm{ts\\_argmin}(\\mathrm{low}, {window}) / {window}"),
    # 中文名称: 极值跨度 N日
    # 简要说明: (ts_argmax(high, N) - ts_argmin(low, N)) / N，最高与最低出现位置的时间差。
    # 典型用途: 衡量N日内从最低点到最高点所需的时间，反映趋势持续性。
    'imxd': ('momentum', 'high low',
        r"(\\mathrm{ts\\_argmax}(\\mathrm{high}, {window}) - \\mathrm{ts\\_argmin}(\\mathrm{low}, {window})) / {window}"),
    # 中文名称: K线长度
    # 简要说明: (high - low) / open，衡量当日K线实体振幅相对于开盘价的比率。
    # 典型用途: 用于识别日内波动幅度较大的股票，结合其他因子判断异常交易行为。
    'klen': ('microstructure', 'open high low',
        r"(\\mathrm{high} - \\mathrm{low}) / \\mathrm{open}"),
    # 中文名称: 下影线比率
    # 简要说明: (min(open,close) - low) / open，衡量下影线长度相对于开盘价的比率。
    # 典型用途: 反映日内买方支撑力度，下影线较长意味着低位有买盘承接。
    'klow': ('microstructure', 'open low close',
        r"(\\min(\\mathrm{open}, \\mathrm{close}) - \\mathrm{low}) / \\mathrm{open}"),
    # 中文名称: 下影线相对比率
    # 简要说明: (min(open,close) - low) / (high - low)，衡量下影线在整根K线中的占比。
    # 典型用途: 用于识别探底回升形态，下影线占比高表明下方支撑强劲。
    'klow2': ('microstructure', 'open high low close',
        r"(\\min(\\mathrm{open}, \\mathrm{close}) - \\mathrm{low}) / (\\mathrm{high} - \\mathrm{low})"),
    # 中文名称: 涨跌幅
    # 简要说明: (close - open) / open，即当日收盘相对于开盘的简单收益率。
    # 典型用途: 日内动量因子，正值为多头占优，负值为空头占优。
    'kmid': ('microstructure', 'open close',
        r"(\\mathrm{close} - \\mathrm{open}) / \\mathrm{open}"),
    # 中文名称: K线中部相对位置
    # 简要说明: (close - open) / (high - low)，收盘价在当日振幅中的相对位置。
    # 典型用途: 衡量收盘强度，值接近1表示收盘接近最高点，多方主导。
    'kmid2': ('microstructure', 'open high low close',
        r"(\\mathrm{close} - \\mathrm{open}) / (\\mathrm{high} - \\mathrm{low})"),
    # 中文名称: K线偏移(标准化开盘价)
    # 简要说明: (2*close - high - low) / open，衡量收盘价偏离日内中心的程度。
    # 典型用途: K线形态识别，正偏移表明收盘偏向高价位区间。
    'ksft': ('microstructure', 'open high low close',
        r"(2\\,\\mathrm{close} - \\mathrm{high} - \\mathrm{low}) / \\mathrm{open}"),
    # 中文名称: K线偏移(标准化振幅)
    # 简要说明: (2*close - high - low) / (high - low)，收盘在日内振幅中的偏移比率。
    # 典型用途: 范围在[-1,1]之间，接近1表示强势收盘，接近-1表示弱势收盘。
    'ksft2': ('microstructure', 'open high low close',
        r"(2\\,\\mathrm{close} - \\mathrm{high} - \\mathrm{low}) / (\\mathrm{high} - \\mathrm{low})"),
    # 中文名称: 上影线比率
    # 简要说明: (high - max(open,close)) / open，衡量上影线长度相对于开盘价的比率。
    # 典型用途: 反映日内卖出压力，上影线较长意味着高位有抛压。
    'kup': ('microstructure', 'open high close',
        r"(\\mathrm{high} - \\max(\\mathrm{open}, \\mathrm{close})) / \\mathrm{open}"),
    # 中文名称: 上影线相对比率
    # 简要说明: (high - max(open,close)) / (high - low)，衡量上影线在整根K线中的占比。
    # 典型用途: 用于识别冲高回落形态，上影线占比高表明上方阻力较大。
    'kup2': ('microstructure', 'open high low close',
        r"(\\mathrm{high} - \\max(\\mathrm{open}, \\mathrm{close})) / (\\mathrm{high} - \\mathrm{low})"),
    # 中文名称: 移动均线比 N日
    # 简要说明: ts_mean(close, N) / close，N日简单移动平均与收盘价的比率。
    # 典型用途: 价格相对于均线的位置，大于1表示收盘价在均线下方，用于趋势判断。
    'ma': ('momentum', 'close',
        r"\\mathrm{ts\\_mean}(\\mathrm{close}, {window}) / \\mathrm{close}"),
    # 中文名称: 最大价 N日
    # 简要说明: ts_max(high, N) / close，N日最高价与当前收盘价的比率。
    # 典型用途: 衡量当前价格相对于N日最高点的位置，接近1表示接近近期高点。
    'max': ('momentum', 'high close',
        r"\\mathrm{ts\\_max}(\\mathrm{high}, {window}) / \\mathrm{close}"),
    # 中文名称: 最小价 N日
    # 简要说明: ts_min(low, N) / close，N日最低价与当前收盘价的比率。
    # 典型用途: 衡量当前价格相对于N日最低点的位置，接近1表示接近近期低点。
    'min': ('momentum', 'low close',
        r"\\mathrm{ts\\_min}(\\mathrm{low}, {window}) / \\mathrm{close}"),
    # 中文名称: 下分位数 N日
    # 简要说明: quantile_0.2(close, N) / close，N日20%分位价格与当前收盘价的比率。
    # 典型用途: 衡量当前价格相对于N日低分位的位置，值大表示价格在近期低位以上。
    'qtld': ('momentum', 'close',
        r"\\mathrm{quantile}_{{0.2}}(\\mathrm{close}, {window}) / \\mathrm{close}"),
    # 中文名称: 上分位数 N日
    # 简要说明: quantile_0.8(close, N) / close，N日80%分位价格与当前收盘价的比率。
    # 典型用途: 衡量当前价格相对于N日高分位的位置，值小表示价格在近期高位以下。
    'qtlu': ('momentum', 'close',
        r"\\mathrm{quantile}_{{0.8}}(\\mathrm{close}, {window}) / \\mathrm{close}"),
    # 中文名称: 时间序列排名 N日
    # 简要说明: ts_rank(close, N)，当前收盘价在N日窗口内的百分位排名。
    # 典型用途: 衡量当前价格在过去N日中的相对位置，高排名表示处于近期高位。
    'rank': ('momentum', 'close',
        r"\\mathrm{ts\\_rank}(\\mathrm{close}, {window})"),
    # 中文名称: 残差 N日
    # 简要说明: Resi(close, N) / close，最新收盘价相对N日线性回归拟合值的残差。
    # 典型用途: 衡量价格偏离趋势线的程度，用于均值回复策略。
    'resi': ('momentum', 'close',
        r"\\mathrm{Resi}(\\mathrm{close}, {window}) / \\mathrm{close}"),
    # 中文名称: 变动率 N日
    # 简要说明: close_{t-N} / close_t，N日前收盘价除以最新收盘价。
    # 典型用途: 用于与 Qlib Alpha158 对齐的N日价格变化分析，不是常规收益率。
    'roc': ('momentum', 'close',
        r"\\mathrm{close}_{{t-{window}}} / \\mathrm{close}_t"),
    # 中文名称: R平方 N日
    # 简要说明: ts_corr(close, t, N)^2，收盘价对时间的N日线性回归拟合度。
    # 典型用途: 衡量N日价格趋势的线性强度，值高表示趋势明确。
    'rsqr': ('momentum', 'close',
        r"\\mathrm{ts\\_corr}(\\mathrm{close}, t, {window})^2"),
    # 中文名称: 未成熟随机值 N日
    # 简要说明: (close - ts_min(low, N)) / (ts_max(high, N) - ts_min(low, N))，KDJ指标中的RSV值。
    # 典型用途: 衡量收盘价在N日高低区间中的位置，用于超买超卖判断(>80超买，<20超卖)。
    'rsv': ('momentum', 'high low close',
        r"(\\mathrm{close} - \\mathrm{ts\\_min}(\\mathrm{low}, {window})) / (\\mathrm{ts\\_max}(\\mathrm{high}, {window}) - \\mathrm{ts\\_min}(\\mathrm{low}, {window}))"),
    # 中文名称: 价格标准差比 N日
    # 简要说明: ts_std(close, N) / close，N日收盘价标准差与收盘价的比率（变异系数）。
    # 典型用途: 衡量N日价格波动幅度相对于价格水平的比率，用于波动率排序。
    'std': ('momentum', 'close',
        r"\\mathrm{ts\\_std}(\\mathrm{close}, {window}) / \\mathrm{close}"),
    # 中文名称: 涨跌差 N日
    # 简要说明: SUMP_N - SUMN_N，N日内上涨强度与下跌强度的差值。
    # 典型用途: 判断N日内的整体涨跌倾向，正值表示上涨动量占优。
    'sumd': ('reversal', 'close',
        r"\\mathrm{SUMP}_w - \\mathrm{SUMN}_w"),
    # 中文名称: 下跌强度 N日
    # 简要说明: sum(max(-delta_close, 0)) / sum(|delta_close|)，N日内负收益占比。
    # 典型用途: 衡量N日下跌日的比例强度，值接近1表示连续下跌。
    'sumn': ('reversal', 'close',
        r"\\sum \\max(-\\Delta\\mathrm{close}, 0) / \\sum |\\Delta\\mathrm{close}|"),
    # 中文名称: 上涨强度 N日
    # 简要说明: sum(max(delta_close, 0)) / sum(|delta_close|)，N日内正收益占比。
    # 典型用途: 衡量N日上涨日的比例强度，值接近1表示连续上涨。
    'sump': ('reversal', 'close',
        r"\\sum \\max(\\Delta\\mathrm{close}, 0) / \\sum |\\Delta\\mathrm{close}|"),
    # 中文名称: 成交量均线比 N日
    # 简要说明: ts_mean(volume, N) / volume，N日平均成交量与当日成交量的比率。
    # 典型用途: 判断当日成交量的相对大小，大于1表示缩量，小于1表示放量。
    'vma': ('volume volatility', 'volume',
        r"\\mathrm{ts\\_mean}(\\mathrm{volume}, {window}) / \\mathrm{volume}"),
    # 中文名称: 成交量标准差比 N日
    # 简要说明: ts_std(volume, N) / volume，N日成交量变异系数。
    # 典型用途: 衡量N日成交量的波动稳定性，值低表示成交量稳定。
    'vstd': ('volume volatility', 'volume',
        r"\\mathrm{ts\\_std}(\\mathrm{volume}, {window}) / \\mathrm{volume}"),
    # 中文名称: 成交量涨跌差 N日
    # 简要说明: VSUMP_N - VSUMN_N，N日内成交量加权的上涨与下跌强度差。
    # 典型用途: 结合成交量判断N日内的趋势可信度，量价配合时信号更强。
    'vsumd': ('volume volatility', 'volume',
        r"\\mathrm{VSUMP}_w - \\mathrm{VSUMN}_w"),
    # 中文名称: 成交量下跌强度 N日
    # 简要说明: sum(max(-delta_v, 0)) / sum(|delta_v|)，N日内负成交量变化占比。
    # 典型用途: 衡量N日内成交量缩小日的比例，反映卖盘衰竭程度。
    'vsumn': ('volume volatility', 'volume',
        r"\\sum \\max(-\\Delta v, 0) / \\sum |\\Delta v|"),
    # 中文名称: 成交量上涨强度 N日
    # 简要说明: sum(max(delta_v, 0)) / sum(|delta_v|)，N日内正成交量变化占比。
    # 典型用途: 衡量N日内成交量放大日的比例，反映买盘活跃程度。
    'vsump': ('volume volatility', 'volume',
        r"\\sum \\max(\\Delta v, 0) / \\sum |\\Delta v|"),
    # 中文名称: 成交量加权波动 N日
    # 简要说明: ts_std(|ret|*v, N) / ts_mean(|ret|*v, N)，成交量加权的价格波动归一化指标。
    # 典型用途: 衡量成交量调整后的价格波动性，值越高表示相对于成交量的价格波动越大。
    'wvma': ('volume volatility', 'close volume',
        r"\\mathrm{ts\\_std}(|\\mathrm{ret}|\\cdot v, {window}) / \\mathrm{ts\\_mean}(|\\mathrm{ret}|\\cdot v, {window})"),
}


def bind_factor(family, window=None):
    themes, fields, formula = DEFINITIONS[family]
    name = family if window is None else f"{family}{window}"
    horizon = window or 1
    metadata = {
        "id": f"qlib158_{name}",
        "theme": themes.split(),
        "formula_latex": formula.replace("{window}", str(horizon)),
        "columns_required": fields.split(),
        "universe": ["equity_us", "equity_cn", "equity_hk", "equity_in", "equity_kr"],
        "frequency": ["1d"],
        "decay_horizon": horizon,
        "min_warmup_bars": horizon,
    }
    if family in ("cntp", "cntn", "cntd"):
        threshold = {5: 40, 10: 30, 20: 15, 30: 10, 60: 5}[window]
        metadata["notes"] = (
            "A missing close leaves window+1 rolling rows NaN; on sparse panels this "
            f"can trigger the >95% NaN registry guard (from ~{threshold}% missing bars)."
        )

    def compute(panel):
        if window is None:
            return candle(panel, family)
        return rolling_measure(panel, family, window)

    return metadata, compute
