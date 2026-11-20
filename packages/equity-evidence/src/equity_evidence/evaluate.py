def evaluate(snapshot):
    statements = (snapshot["financial"].get("data") or {}).get("periods") or []
    f = statements[0] if statements else {}

    def item(label, key, check):
        value = f.get(key)
        return {
            "dimension": label,
            "field": key,
            "value": value,
            "status": "缺项" if value is None else "符合" if check(value) else "待复核",
            "source": "financial.data.periods[0]",
        }

    return {
        "period": f.get("report_date"),
        "quality_value": [
            item("经营现金流为正", "operating_cash_flow_yuan", lambda x: x > 0),
            item("毛利率为正", "gross_margin_pct", lambda x: x > 0),
            item("净资产收益率为正", "roe_pct", lambda x: x > 0),
        ],
        "growth": [
            item("收入同比增长", "revenue_yoy_pct", lambda x: x > 0),
            item("扣非盈利同比增长", "net_profit_deducted_yoy_pct", lambda x: x > 0),
        ],
        "risk": [item("扣非净利润为正", "net_profit_deducted_yuan", lambda x: x > 0)],
        "review_questions": [
            "业务优势能否带来持续的资本回报？",
            "增长是否依赖并购或非经常性损益？",
            "利润与经营现金流的方向是否一致？",
        ],
    }
