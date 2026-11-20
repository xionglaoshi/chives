"""Cash conversion and trade receivables. All amounts are in yuan."""

import re


MONEY = re.compile(r"(?<![\d.])[-−]?\d[\d,]*\.\d{2}(?!\d)")
HEADING = re.compile(
    r"(?:[（(]?[0-9一二三四五六七八九十]+[)）、.．])?(合并|母公司)(?:年初到报告期末)?(资产负债表|现金流量表|利润表)$"
)
FIELDS = {
    "利润表": {
        "revenue": r"^(?:一、|其中[：:])营业收入",
        "profit": r"^[四五]、净利润[（(]",
    },
    "现金流量表": {
        "cash": r"^经营活动产生的现金流量净额",
        "receipts": r"^销售商品、提供劳务收到的现金",
        "other_cash": r"^收到其他与经营活动有关的现金",
        "payments": r"^经营活动现金流出小计",
    },
    "资产负债表": {
        "net_ar": r"^应收账款",
        "bills": r"^应收票据",
        "advances": r"^合同负债",
    },
}
UNITS = {"元": 1, "万元": 10000, "千元": 1000, "亿元": 100000000}


def compact(value):
    return re.sub(r"\s+", "", value)


def amounts(line):
    return [float(v.replace(",", "").replace("−", "-")) for v in MONEY.findall(line)]


def unit(text):
    hits = re.findall(
        r"(?:金额单位|单位)[：:]?(?:人民币)?(亿元|万元|千元|元)", compact(text)
    )
    return UNITS[hits[-1]] if hits else None


def statements(pages):
    out = {"合并": {}, "母公司": {}}
    section = None
    for page_no, page in enumerate(pages, 1):
        lines = page.splitlines()
        for i, line in enumerate(lines):
            s = compact(line)
            h = HEADING.fullmatch(s)
            if h:
                section = h.groups()
                scale = unit(" ".join(lines[i : i + 12]))
                continue
            if not section:
                continue
            if (
                "公司负责人：" in s
                or "法定代表人：" in s
                or re.fullmatch(r".*所有者权益变动表", s)
            ):
                section = None
                continue
            owner, kind = section
            # Only compare rows with both period columns populated. No shifting blank cells.
            for key, pattern in FIELDS[kind].items():
                label = compact(MONEY.split(line, 1)[0])
                for following in lines[i + 1 : i + 4]:
                    tail = compact(following)
                    if re.fullmatch(r"[一二三四五六七八九十]+、[0-9]+", tail):
                        continue
                    if tail in ("的现金", "流量净额"):
                        label += tail
                    break
                if key in out[owner] or not re.match(pattern, label) or not scale:
                    continue
                vals = amounts(line)
                if len(vals) == 2:
                    out[owner][key] = dict(
                        now=vals[0] * scale,
                        prior=vals[1] * scale,
                        page=page_no,
                        line=line.strip(),
                    )
    return out


def ar_sections(pages):
    section = []
    for pg, page in enumerate(pages, 1):
        for line in page.splitlines():
            s = compact(line)
            if re.search(r"母公司财务报表(?:主要)?项目注释", s) and "…" not in s:
                if section:
                    yield section
                return
            if re.fullmatch(r"\d+[、.．]应收账款", s):
                if section:
                    yield section
                section = [(pg, line)]
            elif section and re.match(r"^\d+[、.．][\u4e00-\u9fff]", s):
                yield section
                section = []
            elif section:
                section.append((pg, line))
    if section:
        yield section


def aging(section):
    # Select the raw closing/opening balance table, separate from provisioning tables.
    for start, (_, line) in enumerate(section):
        head = compact(line)
        if "期末账面余额" not in head or "期初账面余额" not in head:
            continue
        rows = []
        for pg, l in section[start + 1 : start + 55]:
            vals = amounts(l)
            name = compact(MONEY.split(l, 1)[0])
            if name in ("合计", "小计") and len(vals) == 2 and rows:
                if (
                    abs(sum(x["now"] for x in rows) - vals[0]) < 0.03
                    and abs(sum(x["prior"] for x in rows) - vals[1]) < 0.03
                ):
                    return dict(
                        rows=rows, gross=vals[0], prior=vals[1], page=pg, line=l.strip()
                    )
                break
            if "小计" in name or not vals:
                continue
            matched = re.fullmatch(
                r"(\d+)年?(?:以内(?:[（(]含\d+年[)）])?|[-－至~—]\d+年|年以上)", name
            )
            if matched and len(vals) == 2:
                if "以内" in name and any(
                    "以内" in x["label"]
                    and x["now"] == vals[0]
                    and x["prior"] == vals[1]
                    for x in rows
                ):
                    continue
                rows.append(
                    dict(
                        label=name,
                        start=0 if "以内" in name else int(matched[1]),
                        now=vals[0],
                        prior=vals[1],
                        page=pg,
                        line=l.strip(),
                    )
                )
    return None


def note_details(section):
    result = {}
    within_top = False
    # The first numeric row in a ranked table is the largest debtor.
    for i, (pg, l) in enumerate(section):
        s = compact(l)
        if re.search(r"应收账款金额前5名|欠款方归集的期末余额前[五5]名", s):
            within_top = True
        vals = amounts(l)
        if within_top and len(vals) in (3, 4) and 0 < vals[-2] <= 100 and vals[0] > 0:
            label = compact(MONEY.split(l, 1)[0])
            if label in ("合计", "小计"):
                result["top5"] = dict(
                    amount=vals[0],
                    pct=vals[-2],
                    allowance=vals[-1],
                    page=pg,
                    line=l.strip(),
                )
                within_top = False
            elif "largest" not in result:
                next_line = section[i + 1][1].strip() if i + 1 < len(section) else ""
                if re.fullmatch(r"[\u3000-\u30ff\u4e00-\u9fff]{1,8}", next_line):
                    label += next_line
                result["largest"] = dict(
                    name=label, amount=vals[0], pct=vals[-2], page=pg, line=l.strip()
                )
        if s.startswith("实际核销的应收账款") and len(vals) == 1:
            result["writeoff"] = dict(amount=vals[0], page=pg, line=l.strip())
        if "本期实际核销的应收账款情况" in s and any(
            "□适用√不适用" in compact(x[1]) for x in section[i + 1 : i + 4]
        ):
            result["writeoff_na"] = dict(page=pg, line=l.strip())
        if (
            "账龄组" in s
            and len(vals) == 10
            and vals[0] > 0
            and abs(vals[0] - vals[2] - vals[4]) < 0.02
        ):
            result.setdefault("groups", []).append(
                dict(
                    label=compact(MONEY.split(l, 1)[0]).rstrip("组") + "组合",
                    amount=vals[0],
                    rate=vals[3],
                    page=pg,
                    line=l.strip(),
                )
            )
    return result


def notes(pages, statement):
    for section in ar_sections(pages):
        a = aging(section)
        if not a:
            continue
        # Notes often inherit yuan from the financial statements rather than repeat units.
        text = "\n".join(l for _, l in section)
        factor = unit(text)
        if factor not in (None, 1):
            continue
        net = statement["合并"].get("net_ar")
        if (
            not net
            or net["now"] > a["gross"]
            or not any(
                abs(v - net["now"]) < 0.02 for _, line in section for v in amounts(line)
            )
        ):
            continue
        allowance = round(a["gross"] - net["now"], 2)
        # Prove same unit and scope by matching all three amounts in the note.
        combined = [
            (pg, line)
            for pg, line in section
            if all(
                any(abs(v - target) < 0.02 for v in amounts(line))
                for target in (a["gross"], net["now"], allowance)
            )
        ]
        if not combined:
            continue
        a.update(
            net=net["now"],
            allowance=allowance,
            allowance_page=combined[0][0],
            **note_details(section),
        )
        return a
    return None


RECEIPT = re.compile(
    r"(?:期后|报告期后|截至.{0,18}日).{0,18}(?:回款|收回|收款|到账)|(?:回款|收回)(?:金额|比例).{0,8}期后"
)
PAID = re.compile(
    r"(?:期后|报告期后|截至.{0,18}日).{0,12}(?:已(?:累计)?|实际|累计)?(?:回款|收回|到账|收到回款)(?:金额|合计|人民币|为|了|约|货款|应收账款|达|共|计|：|:)*([\d,]+(?:\.\d+)?)\s*(亿元|万元|千元|元)"
)


def subsequent(pages):
    hits = []
    for pg, p in enumerate(pages, 1):
        # Join wrapped narrative, preserve sentence boundaries. Table headings are candidates.
        for sent in re.split(r"[。；;！？]", compact(p)):
            for match in RECEIPT.finditer(sent):
                clip = sent[max(0, match.start() - 55) : match.end() + 80]
                pos = PAID.search(clip)
                if (
                    re.search(
                        "预计|计划|目标|拟回款|假设|未收到|尚未|能否|是否|可能|要求|争取|未回款|未收回",
                        clip,
                    )
                    or not pos
                ):
                    pos = None
                status = (
                    "披露金额"
                    if pos
                    else (
                        "审计程序"
                        if re.search("抽样|检查|审计|核查程序", clip)
                        else "待核线索"
                    )
                )
                hits.append(
                    dict(
                        page=pg,
                        status=status,
                        quote=clip,
                        amount=float(pos[1].replace(",", "")) * UNITS[pos[2]]
                        if pos
                        else None,
                    )
                )
    return hits


def collection_tables(pages):
    """Only read unambiguous single-line table headers and fully populated numeric rows."""
    found = []
    for pg, p in enumerate(pages, 1):
        lines = p.splitlines()
        for i, l in enumerate(lines):
            cols = re.split(r" {2,}", l.strip())
            if len(cols) < 3 or not re.search("客户|欠款方|项目名称|单位名称", cols[0]):
                continue
            indices = [
                j
                for j, c in enumerate(cols)
                if re.fullmatch(
                    r"(?:截至.{4,18}日)?期后(?:累计|实际)?(?:回款|收款|收回)(?:金额)?(?:[（(](?:万|千|亿)?元[）)])?",
                    compact(c),
                )
            ]
            if len(indices) != 1:
                continue
            k = indices[0]
            factor = unit(" ".join(lines[max(i - 7, 0) : i + 1]))
            column_unit = re.search(r"[（(](亿元|万元|千元|元)[)）]", cols[k])
            if column_unit:
                factor = UNITS[column_unit[1]]
            if not factor:
                continue
            for row in lines[i + 1 : i + 32]:
                cells = re.split(r" {2,}", row.strip())
                if not row.strip():
                    continue
                if len(cells) != len(cols) or not re.fullmatch(
                    r"[0-9][0-9,]*(?:\.\d+)?", cells[k]
                ):
                    break
                if compact(cells[0]) in ("合计", "小计", "总计"):
                    break
                if not re.search(r"[A-Za-z\u4e00-\u9fff]", cells[0]):
                    break
                found.append(
                    dict(
                        status="披露金额",
                        page=pg,
                        amount=float(cells[k].replace(",", "")) * factor,
                        quote=l.strip() + " / " + row.strip(),
                    )
                )
    return found


def reconciliation(pages, st):
    totals = st["合并"].get("cash")
    if not totals:
        return []
    for i, p in enumerate(pages):
        if "经营性应收项目的减少" not in p:
            continue
        area = p + "\n" + (pages[i + 1] if i + 1 < len(pages) else "")
        if not any(
            "经营活动产生的现金流量净额" in compact(l)
            and any(abs(v - totals["now"]) < 0.006 for v in amounts(l))
            for l in area.splitlines()
        ):
            continue
        result = []
        lines = p.splitlines()
        for j, l in enumerate(lines):
            for start in (
                "固定资产折旧",
                "财务费用",
                "存货的减少",
                "经营性应收项目的减少",
                "经营性应付项目的增加",
            ):
                if not compact(l).startswith(start):
                    continue
                vals = amounts(l)
                raw = l.strip()
                if len(vals) < 2 and j + 1 < len(lines):
                    tail = lines[j + 1].strip()
                    # A continuation containing only amounts carries no new account label.
                    if tail and not MONEY.sub("", tail).strip():
                        vals += amounts(tail)
                        raw += " / " + tail
                if len(vals) == 2:
                    result.append(
                        dict(label=start, amount=vals[0], page=i + 1, line=raw)
                    )
        return result
    return []


def outstanding_bills(pages):
    for n, p in enumerate(pages):
        if "尚未到期的应收票据情况" not in compact(p):
            continue
        tail = p.split("尚未到期的应收票据情况")[-1]
        for pg, area in [(n + 1, tail)] + (
            [(n + 2, pages[n + 1])] if n + 1 < len(pages) else []
        ):
            lines = area.splitlines()
            for j, line in enumerate(lines):
                if not re.match(r"^(银行|商业)承兑汇票\s", line.strip()):
                    continue
                header = compact("".join(lines[max(0, j - 5) : j]))
                if "期末终止" not in header or "期末未终止" not in header:
                    continue
                cells = line.split()
                if (
                    len(cells) == 3
                    and MONEY.fullmatch(cells[-1])
                    and (cells[1] == "-" or MONEY.fullmatch(cells[1]))
                ):
                    return dict(
                        kind=cells[0],
                        amount=amounts(cells[-1])[0],
                        page=pg,
                        section_page=n + 1,
                        line=line.strip(),
                    )
    return None


def supplementary_risk(pages):
    result = []
    for pg, p in enumerate(pages, 1):
        for sentence in re.split(r"[。；]", compact(p)):
            for phrase in ("分年度预算", "票终止确认", "汇票终止确认"):
                if phrase in sentence and len(sentence) < 230:
                    result.append(dict(page=pg, quote=sentence))
                    break
    return result[:8]


def explanations(pages):
    found = []
    for pg, p in enumerate(pages[:25], 1):
        lines = p.splitlines()
        for i, line in enumerate(lines):
            start = line.find("主要系")
            if start < 0:
                continue
            excerpt = line[start:].strip()
            # Wrapped explanatory column in exchange templates. Skip left-hand labels.
            if "。" not in excerpt:
                for following in lines[i + 1 : i + 6]:
                    chunks = re.split(r" {2,}", following.rstrip())
                    tail = chunks[-1].strip()
                    if (
                        len(chunks) > 1
                        and tail
                        and following.find(tail) >= 10
                        and "主要系" not in tail
                        and not re.search(r"[0-9%]|_", tail)
                    ):
                        excerpt += tail
                    if "。" in excerpt or "主要系" in following:
                        break
            if "。" in excerpt and any(
                w in excerpt for w in ("回款", "汇兑", "预收", "现金流", "承兑")
            ):
                quote = excerpt.split("。")[0]
                if len(quote) < 140 and quote not in [x["quote"] for x in found]:
                    found.append(dict(quote=quote, page=pg))
    return found


def attributed_profit(pages, financial):
    """Resolve same-period indicator values only when their named disclosure row agrees."""
    result = {}
    for key, marker in (
        ("parent", "归属于上市公司股东的净利润"),
        ("adjusted", "归属于上市公司股东的扣除非"),
    ):
        target = financial.get(
            {"parent": "net_profit_yuan", "adjusted": "net_profit_deducted_yuan"}[key]
        )
        if target is None:
            continue
        for pg, p in enumerate(pages[:10], 1):
            lines = p.splitlines()
            for i, l in enumerate(lines):
                if not compact(l).startswith(marker):
                    continue
                span = [l]
                if not amounts(l) and i + 1 < len(lines):
                    span.append(lines[i + 1])
                if any(abs(v - target) < 0.006 for row in span for v in amounts(row)):
                    result[key] = dict(
                        amount=target, page=pg, line=" ".join(x.strip() for x in span)
                    )
                    break
            if key in result:
                break
    return result


def parse_cash(docs, errors, scope, financial=None):
    filings = []
    for meta, pages in docs:
        st = statements(pages) if meta["period"] else None
        entry = dict(meta=meta, receipts=subsequent(pages) + collection_tables(pages))
        if not st:
            entry["risk_notes"] = supplementary_risk(pages)
        if st:
            entry["explanations"] = explanations(pages)
            if financial and meta["period"] == financial.get("report_date"):
                entry["attributed"] = attributed_profit(pages, financial)
            entry.update(
                statements=st,
                aging=notes(pages, st),
                bills=outstanding_bills(pages) if "bills" in st["合并"] else None,
                reconciliation=reconciliation(pages, st),
            )
        filings.append(entry)
    scanned = any(f.get("statements", {}).get("合并") for f in filings)
    coverage = dict(
        aging=any(f.get("aging") for f in filings),
        receipt_amount_candidate=any(
            r["amount"] is not None for f in filings for r in f["receipts"]
        ),
        original_pages=bool(filings),
        consolidated_statements=scanned,
    )
    return dict(
        scope=scope,
        filings=filings,
        errors=errors,
        coverage=coverage,
        status="unavailable"
        if not filings
        else "partial"
        if errors or not all(coverage.values())
        else "ok",
    )
