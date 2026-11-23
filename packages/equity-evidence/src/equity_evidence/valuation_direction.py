"""As-of 20-session outlook and purged, non-overlapping walk-forward diagnostics."""

import math
from statistics import mean, median, pstdev
from .valuation_data import number


HORIZON = 20
FLAT = 0.02


def direction(change):
    return int(change > FLAT) - int(change < -FLAT)


def trend_date(stock_moves, market_moves, end, book_ratios):
    # All offsets are trading sessions in the common market calendar. A missing
    # stock quote is never filled with a zero return through a suspension.
    own = stock_moves[max(0, end - 59) : end + 1]
    broad = market_moves[max(0, end - 19) : end + 1]
    if len(own) < 20 or len(broad) < 20 or None in own[-20:] or None in broad:
        return None
    short = sum(own[-20:])
    sigma = max(0.005, pstdev(own[-20:])) * math.sqrt(20)
    deep = len(own) == 60 and None not in own
    slow = sum(own) / 3 if deep else short
    relative = short - sum(broad)
    features = tuple(max(-3.0, min(3.0, v / sigma)) for v in (short, slow, relative))
    # Median resists a single extreme indicator. Score units represent trend strength.
    strength = median(features)
    score = (
        0
        if abs(strength) < 0.30
        else min(5, 1 + int((abs(strength) - 0.30) / 0.55))
        * (1 if strength > 0 else -1)
    )
    # Date-matched PB ranks provide a slow valuation context independent of price momentum.
    series = [v for v in book_ratios[max(0, end - 251) : end] if v is not None]
    book = book_ratios[end]
    rank = (
        sum(v <= book for v in series) / len(series)
        if book is not None and len(series) >= 60
        else None
    )
    return dict(
        book_percentile=rank,
        features=features,
        trend=score,
        sessions=60 if deep else 20,
        return_20=math.expm1(short),
        market_return_20=math.expm1(sum(broad)),
        volatility_20=sigma,
    )


def sign(score):
    return (score > 0) - (score < 0)


def dominant(counts, tie):
    return max((-1, 0, 1), key=lambda side: (counts[side], side == tie, side == 0))


def analog(signal, training):
    if len(training) < 12:
        return None

    def distance(row):
        diff = sum((v - w) ** 2 for v, w in zip(signal["features"], row["features"]))
        p, q = signal["book_percentile"], row["book_percentile"]
        return diff + (2 * (p - q)) ** 2 if p is not None and q is not None else diff

    neighbors = sorted(training, key=distance)[
        : max(10, round(1.5 * math.sqrt(len(training))))
    ]
    counts = {
        side: sum(direction(r["outcome"]) == side for r in neighbors)
        for side in (-1, 0, 1)
    }
    move = median(r["outcome"] for r in neighbors)
    return dict(
        side=dominant(counts, direction(move)),
        count=len(neighbors),
        median_return=move,
        frequencies={str(k): v for k, v in counts.items()},
    )


def select(signal, training, finished):
    trend = sign(signal["trend"])
    counts = {
        side: sum(direction(r["outcome"]) == side for r in training)
        for side in (-1, 0, 1)
    }
    history = dominant(counts, 0)
    neighbors = analog(signal, training)
    # Compare simple rules on completed periods only. Constant rules share a single prior vote.
    rules = {
        "趋势": trend,
        "反转": -trend,
        "历史多数": history,
        "看涨基准": 1,
        "看跌基准": -1,
        "中性基准": 0,
    }
    if neighbors:
        rules["相似行情"] = neighbors["side"]
    sample = finished[-48:]
    votes = {side: 0.0 for side in (-1, 0, 1)}
    weights = {}
    for name, side in rules.items():
        seen = [r for r in sample if name in r["rules"]]
        advantage = sum(int(r["rules"][name] == r["actual"]) - 1 / 3 for r in seen)
        learning_rate = math.sqrt(2 * math.log(len(rules)) / max(12, len(seen)))
        weight = math.exp(learning_rate * advantage)
        if name.endswith("基准"):
            weight /= 3
        weights[name] = weight
        votes[side] += weight
    total = sum(votes.values())
    support = {k: v / total for k, v in votes.items()}
    leader = dominant(votes, history)
    # A more complex rule can displace the security's own base rate only on paired,
    # already resolved predictions. Use the prespecified one-sided exact sign test.
    wins = sum(r["ensemble"] == r["actual"] != r["base"] for r in sample)
    losses = sum(r["base"] == r["actual"] != r["ensemble"] for r in sample)
    discordant = wins + losses
    tail = (
        sum(math.comb(discordant, k) for k in range(wins, discordant + 1))
        / 2**discordant
    )
    if len(sample) < 6:
        score = max(-1, min(1, signal["trend"]))
        model = "短历史趋势观察"
    elif len(sample) >= 24 and discordant >= 8 and tail <= 0.10:
        ordered = sorted(support.values(), reverse=True)
        score = leader * min(5, 1 + int(5 * (ordered[0] - ordered[1])))
        model = "滚动历史投票"
    else:
        score, model = history, "个股历史基准"
    # The challenger failed the separate issuer cohort. Keep its frozen prediction
    # for prospective evaluation; publish the historical base when labels exist.
    candidate_score, candidate_method = score, model
    if training:
        score, model = history, "个股历史基准"
    return dict(
        score=score,
        candidate_score=candidate_score,
        candidate_method=candidate_method,
        label={1: "偏涨", -1: "偏跌", 0: "中性"}[sign(score)],
        method=model,
        historical_counts={str(k): v for k, v in counts.items()},
        ensemble=leader,
        validation=dict(
            paired_wins=wins,
            paired_losses=losses,
            one_sided_p=tail,
            windows=len(sample),
        ),
        rules=rules,
        rule_weights=weights,
        vote_share={str(k): v for k, v in support.items()},
        analog_comparison=neighbors,
        history_windows=len(training),
        observations=signal,
    )


def assess_direction(history, indices, as_of):
    calendar = sorted(d for d, r in indices.items() if d <= as_of and len(r) == 2)
    own = {}
    book = {}
    for r in history:
        traded = r["TRADE_DATE"][:10]
        pb = number(r.get("PB_MRQ"))
        book[traded] = pb if pb and pb > 0 else None
        rate = number(r.get("CHANGE_RATE"))
        if rate is not None and rate > -100:
            own[r["TRADE_DATE"][:10]] = math.log1p(rate / 100)
    changes = [own.get(d) for d in calendar]
    book_ratios = [book.get(d) for d in calendar]
    market = [None] + [
        mean(
            math.log(indices[d][index] / indices[prior][index])
            for index in ("000001", "399001")
        )
        for prior, d in zip(calendar, calendar[1:])
    ]
    if not calendar or calendar[-1] != as_of:
        return None, {"reason": "缺少与个股同日的宽基收盘数据"}
    signal = trend_date(changes, market, len(changes) - 1, book_ratios)
    if signal is None:
        return None, {"reason": "缺少最近20个连续交易日的有效涨跌幅"}

    training, finished = [], []
    for origin in range(19, len(calendar) - HORIZON, HORIZON):
        prior = trend_date(changes, market, origin, book_ratios)
        forward = changes[origin + 1 : origin + HORIZON + 1]
        if prior is None or None in forward:
            continue
        pick = select(prior, training, finished)
        path, total = [], 0.0
        for move in forward:
            total += move
            path.append(math.expm1(total))
        realized = median(path)
        truth = direction(realized)
        base = pick["rules"]["历史多数"]
        peer = pick["analog_comparison"]
        finished.append(
            dict(
                date=calendar[origin],
                end=calendar[origin + HORIZON],
                actual=truth,
                realized_return=realized,
                predicted=sign(pick["score"]),
                method=pick["method"],
                ensemble=pick["ensemble"],
                candidate=sign(pick["candidate_score"]),
                trend=sign(prior["trend"]),
                base=base,
                rules=pick["rules"],
                analog=peer["side"] if peer else None,
            )
        )
        training.append(
            dict(
                features=prior["features"],
                book_percentile=prior["book_percentile"],
                outcome=realized,
            )
        )
    current = select(signal, training, finished)
    current.update(
        as_of=as_of,
        horizon=HORIZON,
        neutral_threshold=FLAT,
        target="未来20个交易日收盘价中位数相对估值日收盘价，涨跌超过2%分为涨跌，其余为中性",
    )
    return current, {"windows": finished}


def summarize_windows(windows):
    """Expose compact actually-resolved outcomes; store full audit trail outside prompt context."""
    return dict(
        count=len(windows),
        start=windows[0]["date"] if windows else None,
        end=windows[-1]["end"] if windows else None,
        correct=sum(w["predicted"] == w["actual"] for w in windows),
        trend_correct=sum(w["trend"] == w["actual"] for w in windows),
        candidate_correct=sum(w["candidate"] == w["actual"] for w in windows),
        prior_correct=sum(w["base"] == w["actual"] for w in windows),
        flat_correct=sum(w["actual"] == 0 for w in windows),
        up_correct=sum(w["actual"] == 1 for w in windows),
        down_correct=sum(w["actual"] == -1 for w in windows),
    )
