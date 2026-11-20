"""Render only dated, page-addressable PDF facts and reproducible differences."""


def wan(v):
    return f"{v / 10000:,.2f}"


def cite(f, pg):
    meta = f["meta"]
    return f"[{meta['title']}第{pg}页]({meta['url']}#page={pg})"


def cash_markdown(code, d):
    scope = d["scope"]
    lines = [
        f"# {scope.get('name') or code}（{code}）利润兑现与回款风险",
        f"研究日 {scope['end']}。金额单位为万元。现金流和净利润默认取合并报表，页码按 PDF 原件从 1 起算。",
    ]
    fs = d["filings"]
    periodic = [
        f for f in fs if f["meta"]["period"] and f.get("statements", {}).get("合并")
    ]
    if periodic:
        latest = max(periodic, key=lambda f: f["meta"]["period"])
        period = latest["meta"]["period"]
        st = latest["statements"]["合并"]
        lines.append(f"## 截至 {period} 的现金表现")

        def ref(key):
            return cite(latest, st[key]["page"])

        if "profit" in st and "cash" in st:
            cash, profit = st["cash"]["now"], st["profit"]["now"]
            msg = f"经营现金流净额 **{wan(cash)}**，合并净利润 **{wan(profit)}**。"
            if profit > 0:
                msg += f"现金利润比为 **{cash / profit:.2f} 倍**，当期经营现金流{'覆盖' if cash >= profit else '未完全覆盖'}当期合并利润。"
                if st["profit"]["prior"] > 2 * profit:
                    msg += "上年同期利润明显较高，本期利润分母缩小会抬高这个比值。"
            else:
                msg += "合并净利润为零或亏损，现金覆盖倍数缺乏经济解释。"
            lines.append(msg + " " + ref("cash") + " · " + ref("profit"))
        items = [
            ("revenue", "营业收入"),
            ("profit", "合并净利润"),
            ("receipts", "销售商品、提供劳务收到的现金"),
            ("other_cash", "其他经营收现"),
            ("payments", "经营活动现金流出"),
            ("cash", "经营现金流净额"),
        ]
        rows = [
            "| 合并指标 | 本年累计 | 上年同期 | 同比 | 公告 |",
            "|---|---:|---:|---:|---|",
        ]
        for key, label in items:
            if key not in st:
                continue
            x = st[key]
            change = (
                f"{(x['now'] / x['prior'] - 1) * 100:+.2f}%"
                if x["prior"] > 0
                else "基数非正"
            )
            rows.append(
                f"| {label} | {wan(x['now'])} | {wan(x['prior'])} | {change} | {ref(key)} |"
            )
        lines.append("\n".join(rows))
        if all(k in st for k in ("receipts", "cash", "payments")):
            a, b, c = (st[k] for k in ("receipts", "cash", "payments"))
            if (
                a["now"] < a["prior"]
                and b["now"] > b["prior"]
                and c["now"] < c["prior"]
            ):
                lines.append(
                    f"销售收现减少 {wan(a['prior'] - a['now'])}，同期经营现金流出减少 {wan(c['prior'] - c['now'])}。净现金增加与付款减少有关，仅凭净额上升无法判断客户付款加快。 "
                    + ref("receipts")
                    + " · "
                    + ref("payments")
                )
        half = next(
            (f for f in periodic if f["meta"]["period"] == period[:4] + "-06-30"), None
        )
        if period.endswith("09-30") and half:
            h = half["statements"]["合并"]
            if all(k in metric for metric in [h, st] for k in ("cash", "profit")):
                cash = st["cash"]["now"] - h["cash"]["now"]
                profit = st["profit"]["now"] - h["profit"]["now"]
                parts = [
                    ref("cash"),
                    cite(half, h["cash"]["page"]),
                    ref("profit"),
                    cite(half, h["profit"]["page"]),
                ]
                msg = f"用前三季度累计数减去半年数，第三季度单季经营现金流 **{wan(cash)}**，单季合并净利润 **{wan(profit)}**。"
                if profit > 0:
                    msg += f"单季现金覆盖率 **{100 * cash / profit:.2f}%**。"
                lines.append(msg + " " + " · ".join(parts))
        bridge = next(
            (
                f
                for f in sorted(
                    periodic, key=lambda f: f["meta"]["period"], reverse=True
                )
                if f.get("reconciliation")
            ),
            None,
        )
        if bridge:
            pieces = [
                v["label"] + " " + wan(v["amount"]) for v in bridge["reconciliation"]
            ]
            lines.append(
                f"{bridge['meta']['period']} 现金流量补充资料列出的调节项（万元，正数提高现金净额，负数降低现金净额）："
                + "，".join(pieces)
                + "。经营性应收包含多种往来，金额不能直接归给某一客户。 "
                + cite(bridge, bridge["reconciliation"][0]["page"])
            )
        attributed = latest.get("attributed", {})
        if "parent" in attributed and "adjusted" in attributed:
            parent, adjusted = attributed["parent"], attributed["adjusted"]
            diff = parent["amount"] - adjusted["amount"]
            share = (
                f"，占归母净利润 {100 * diff / parent['amount']:.2f}%"
                if parent["amount"] > 0
                else ""
            )
            lines.append(
                f"归母净利润 {wan(parent['amount'])}，扣非归母净利润 {wan(adjusted['amount'])}，两者相差 {wan(diff)}{share}。现金利润比采用同范围的合并净利润。 "
                + cite(latest, parent["page"])
                + " · "
                + cite(latest, adjusted["page"])
            )
        par = latest["statements"]["母公司"]
        if "cash" in par and "receipts" in par:
            a, b = par["cash"], par["receipts"]
            lines.append(
                f"母公司单体经营现金流 {wan(a['now'])}，上年同期 {wan(a['prior'])}。销售收现 {wan(b['now'])}，上年同期 {wan(b['prior'])}。集团与母公司可分别评估。 "
                + cite(latest, a["page"])
                + " · "
                + cite(latest, b["page"])
            )
        else:
            lines.append(
                "本次未提取到同期间的母公司单体现金流，无法拆出母公司和各子公司对集团收现的贡献。"
            )
        for item in latest.get("explanations", [])[:8]:
            lines.append(
                "公司对变动的解释（原文节选）：“"
                + item["quote"]
                + "。” "
                + cite(latest, item["page"])
            )
        lines.append("## 应收账款与客户风险")
        if "net_ar" in st:
            x = st["net_ar"]
            lines.append(
                f"截至 {period}，合并应收账款账面净额 **{wan(x['now'])}**，年初 {wan(x['prior'])}。净额已扣坏账准备。 "
                + ref("net_ar")
            )
        if "bills" in st:
            x = st["bills"]
            lines.append(
                f"应收票据期末 {wan(x['now'])}，年初 {wan(x['prior'])}。接受票据与到期收现应分开核对。 "
                + ref("bills")
            )
        ds = sorted(
            (f for f in periodic if f["aging"]),
            key=lambda f: f["meta"]["period"],
            reverse=True,
        )
        if ds:
            note = ds[0]
            a = note["aging"]
            day = note["meta"]["period"]
            lines.append(
                f"最近通过总额勾稽的账龄表截至 **{day}**。应收原值 **{wan(a['gross'])}**，坏账准备 **{wan(a['allowance'])}**，净额 **{wan(a['net'])}**。 "
                + cite(note, a["allowance_page"])
            )
            rows = ["| 账龄 | 期末原值 | 期初原值 | 公告 |", "|---|---:|---:|---|"]
            for r in a["rows"]:
                rows.append(
                    f"| {r['label']} | {wan(r['now'])} | {wan(r['prior'])} | {cite(note, r['page'])} |"
                )
            lines.append("\n".join(rows))
            bill = note.get("bills")
            if bill:
                lines.append(
                    f"{day}，已背书或贴现、尚未到期且未终止确认的{bill['kind']}为 {wan(bill['amount'])}。到期兑付和追索情况需另查。 "
                    + cite(note, bill["section_page"])
                    + " · "
                    + cite(note, bill["page"])
                )
            for years in (1, 3):
                bal = sum(r["now"] for r in a["rows"] if r["start"] >= years)
                if a["gross"] and any(r["start"] == years for r in a["rows"]):
                    lines.append(
                        f"{years} 年及以上合计 **{wan(bal)}**，占原值 **{bal / a['gross'] * 100:.2f}%**。 "
                        + cite(note, a["page"])
                    )
            if day != period and "net_ar" in st:
                change = st["net_ar"]["now"] - a["net"]
                lines.append(
                    f"从 {day} 至 {period} 净额变动 **{wan(change)}**。期间新开票、收款、汇率、计提及核销均可能改变余额，无法从净变动反推出旧账实收额。 "
                    + cite(note, a["allowance_page"])
                    + " · "
                    + ref("net_ar")
                )
            if a.get("top5") and a["top5"]["pct"] >= 50:
                lines.append(
                    f"前五名占到一半以上；追踪这几户的结算进度，比只看全公司应收净额更能辨认集中回款风险。 "
                    + cite(note, a["top5"]["page"])
                )
            for g in a.get("groups", []):
                lines.append(
                    f"{g['label']}应收原值 {wan(g['amount'])}，计提比例 {g['rate']:.2f}%。 "
                    + cite(note, g["page"])
                )
            if len(a.get("groups", [])) > 1:
                highest = max(a["groups"], key=lambda g: g["rate"])
                lowest = min(a["groups"], key=lambda g: g["rate"])
                if highest["rate"] > lowest["rate"]:
                    lines.append(
                        f"按公司已计提比例，{highest['label']}每百元应收承担的损失准备高于{lowest['label']}。这是财报估计，实际损失还要观察逾期和到账。 "
                        + cite(note, highest["page"])
                    )
            if a.get("top5"):
                t = a["top5"]
                lines.append(
                    f"按公司前五名披露口径，余额 **{wan(t['amount'])}**，占 **{t['pct']:.2f}%**，相应坏账准备 {wan(t['allowance'])}。大客户结算时间足以影响单季现金流。 "
                    + cite(note, t["page"])
                )
            if a.get("largest"):
                t = a["largest"]
                lines.append(
                    f"第一大欠款方 **{t['name']}**，应收 **{wan(t['amount'])}**，披露占比 **{t['pct']:.2f}%**。集中度衡量对单户回款的依赖，判断违约仍需要逾期或信用事件证据。 "
                    + cite(note, t["page"])
                )
            if "writeoff" in a:
                w = a["writeoff"]
                lines.append(
                    f"本期实际核销应收账款 {wan(w['amount'])}，这部分余额的减少没有带来现金。 "
                    + cite(note, w["page"])
                )
            elif "writeoff_na" in a:
                lines.append(
                    "公司将“本期实际核销的应收账款情况”勾选为不适用。 "
                    + cite(note, a["writeoff_na"]["page"])
                )
        else:
            lines.append("未找到同时满足分档合计、坏账准备和合并净额校验的账龄表。")
    for f in fs:
        for item in f.get("risk_notes", []):
            lines.append(
                "专项公告披露（按该公告所属期间理解）：“"
                + item["quote"]
                + "”。 "
                + cite(f, item["page"])
            )
    lines.append("## 期后到账证据")
    positive = 0
    for f in fs:
        for r in f["receipts"]:
            if r["status"] == "披露金额":
                positive += 1
            amt = (
                ""
                if r["amount"] is None
                else f" **{wan(r['amount'])} 万元**，仅适用于该段所述对象和期间。"
            )
            lines.append(
                f"{r['status']}。原文节选：“{r['quote']}”。{amt} " + cite(f, r["page"])
            )
    if not positive:
        lines.append(
            "在本次已读取的公告中，未识别出可归属到具体欠款或客户的期后实收金额。期后回款率未知。"
        )
    lines.extend(
        [
            "## 哪些证据仍缺",
            "要判断老账收回多少，需要按同一基准日和客户匹配期末欠款、期后收到的现金、收款截止日，并分列票据、核销和新增销售。审计抽查、已计提准备和账龄较短均不能代替到账证据。",
            f"检索范围 {scope['start']} 至 {scope['end']}，共检索 {scope['count']} 条公告。以下为实际读取的最新定期报告、半年报、年报及相关标题命中的专项公告。页码为 PDF 物理页序。",
        ]
    )
    for f in fs:
        m = f["meta"]
        lines.append(
            f"- [{m['title']}]({m['url']})，披露于 {m['date']}，{m['pages_total']} 页。[工作台原件](./api/research-documents/{m['sha256']})。"
        )
    for error in d["errors"]:
        lines.append("检索限制：" + error)
    return "\n\n".join(lines) + "\n"
