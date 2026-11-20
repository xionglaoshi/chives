"""Publish a compact reading list from publisher public front pages."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
import tempfile
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
import requests

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'apps/web/public/market-news.json'
SHANGHAI = ZoneInfo('Asia/Shanghai')
DOMESTIC = {
    '证券时报': ('https://www.stcn.com/', r'/article/detail/\d+\.html'),
    '中国证券报': ('https://www.cs.com.cn/', r'/[^?]+/detail_\d+\.html'),
    '上海证券报': ('https://www.cnstock.com/', r'/commonDetail/\d+'),
    '第一财经': ('https://www.yicai.com/', r'/news/\d+\.html'),
    '东方财富': ('https://stock.eastmoney.com/', r'/a/\d+\.html'),
    '每日经济新闻': ('https://www.nbd.com.cn/', r'/articles/\d{4}-\d{2}-\d{2}/\d+\.html'),
}
GLOBAL = {**DOMESTIC, '东方财富': ('https://global.eastmoney.com/', DOMESTIC['东方财富'][1])}
CHINESE = re.compile(r'[㐀-鿿]')
OVERSEAS = re.compile(r'全球(?:股市|市场)|美股|港股|恒生|中概股|纳斯达克|标普|道指|华尔街|美联储|联储|欧洲股市|欧股|日经|日本股市|韩股|韩国股市|亚太股市|印度股市|英伟达|(?i:Anthropic|Nvidia)')
MARKET = re.compile(r'A股|沪指|深证|沪深|创业板|科创板|股市|股票|上市公司|ETF|券商|并购|回购|增持|减持|财报|业绩|证监会|涨停|跌停|股价|股东|指数|(?i:\bstocks?\b|\bshares?\b|equities|earnings|nasdaq|wall street|\bs&p\b|\bipo\b|\bmarkets?\b|nikkei|hang seng|stoxx|investors|monetary policy|fomc|fed rate|federal reserve)')
IMPACT = re.compile(r'财报|业绩|证监会|并购|回购|降息|加息|披露|(?i:earnings|guidance|\bipo\b|fomc|rate cut|rate hike|merger|monetary policy)')
REGIONS = (
    ('港股', r'香港股市|港股|恒指|Hang Seng|Hong Kong stocks'),
    ('日本', r'日经|日本股市|Nikkei|Japan(?:ese)? (?:stock|share|market)'),
    ('欧洲', r'欧洲股市|Stoxx|FTSE|DAX|European (?:stock|share|market)'),
    ('美股', r'美股|纳斯达克|Nasdaq|Wall Street|S&P 500|Dow Jones|Federal Reserve|美国联储'),
)


def fetch(source, config):
    url, rule = config
    response = requests.get(url, timeout=(5, 10))
    response.raise_for_status()
    items = []
    page = BeautifulSoup(response.content, 'html.parser')
    for tag in page.select('a[href]'):
        heading = tag.select_one('h1,h2,h3,h4,[class*=title]')
        title = ' '.join((tag.get('title') or (heading or tag).get_text(' ', strip=True)).split())
        link = urlsplit(urljoin(url, tag['href']))
        domain = urlsplit(url).hostname.split('.', 1)[1]
        if link.scheme != 'https' or not host_matches(link.hostname, domain) or not re.fullmatch(rule, link.path):
            continue
        date = re.search(r'20\d{2}[-/]?\d{2}[-/]?\d{2}', link.path)
        try:
            day = datetime.strptime(re.sub(r'[^0-9]', '', date[0]), '%Y%m%d').date().isoformat() if date else None
        except ValueError:
            day = None
        items.append(item(source, title, link, day=day))
    return items


def host_matches(host, domain):
    return host == domain or bool(host and host.endswith('.' + domain))


def item(source, title, link, published=None, day=None):
    return dict(source=source, title=title, url=link._replace(query='', fragment='').geturl(),
                publishedAt=published, day=day)


def select(candidates, now, global_news=False):
    earliest = now - timedelta(hours=36)
    ranked = []
    for order, row in enumerate(candidates):
        title = row['title']
        if global_news and (len(CHINESE.findall(title)) < 4 or not OVERSEAS.search(title)):
            continue
        signals = MARKET.findall(title)
        if (not signals and not global_news) or not 7 <= len(title) <= 220:
            continue
        if row['publishedAt']:
            published = datetime.fromisoformat(row['publishedAt'])
            if published < earliest or published > now + timedelta(minutes=5):
                continue
            freshness = max(0, 7 - (now - published).total_seconds() / 3600 / 4)
        elif row['day']:
            if row['day'] < earliest.date().isoformat() or row['day'] > now.date().isoformat():
                continue
            freshness = 4 if row['day'] == now.date().isoformat() else 1
        else:
            freshness = 0
        score = 3 * min(3, len(signals)) + 4 * bool(IMPACT.search(title)) + freshness
        ranked.append((score - order / 1000, row))
    selected, urls, signatures = [], set(), []
    sources = Counter()
    regions = Counter()
    topics = Counter()
    for _, row in sorted(ranked, key=lambda pair: pair[0], reverse=True):
        title = re.sub(r'[^\w\u4e00-\u9fff]', '', row['title'].casefold())
        grams = {title[i:i + 3] for i in range(len(title) - 2)}
        if row['url'] in urls or any(len(grams & prev) / len(grams | prev) >= .48 for prev in signatures):
            continue
        region = next((label for label, terms in REGIONS if re.search(terms, row['title'], re.I)), '')
        # Limit repeated market themes without excluding distinct events entirely.
        topic = next((word for word in ('回购', '增持', 'IPO', '利率', 'earnings') if word.casefold() in row['title'].casefold()), '')
        if sources[row['source']] >= 6 or (region and regions[region] >= 10) or (topic and topics[topic] >= 4):
            continue
        selected.append({**row, 'region': region})
        sources[row['source']] += 1
        regions[region] += 1
        topics[topic] += 1
        urls.add(row['url'])
        signatures.append(grams)
        if len(selected) == 20:
            break
    return selected


def main():
    now = datetime.now(SHANGHAI)
    previous = json.loads(OUTPUT.read_text()) if OUTPUT.exists() else {}
    snapshot = {}
    with ThreadPoolExecutor(max_workers=12) as pool:
        pending = {
            key: {name: pool.submit(fetch, name, cfg) for name, cfg in sources.items()}
            for key, sources in [('domestic', DOMESTIC), ('global', GLOBAL)]
        }
        for key, feeds in pending.items():
            candidates, available = [], []
            for source, job in feeds.items():
                try:
                    items = job.result()
                    if items:
                        available.append(source)
                        candidates.extend(items)
                except (requests.RequestException, ValueError) as exc:
                    print(f'{source}: {exc}', flush=True)
            entries = select(candidates, now, global_news=key == 'global')
            if len(available) >= 2 and entries:
                snapshot[key] = dict(updatedAt=now.isoformat(timespec='seconds'), sources=available, entries=entries)
            else:
                retained = previous.get(key)
                if key == 'global' and retained:
                    entries = [row for row in retained['entries'] if len(CHINESE.findall(row['title'])) >= 4]
                    retained = {**retained, 'entries': entries} if entries else None
                snapshot[key] = retained
            print(f'{key}: {len(available)} sources; {len(entries)} selected', flush=True)
    if not any(snapshot.values()):
        raise SystemExit('No usable news snapshot')
    if snapshot == previous:
        return
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=OUTPUT.parent, delete=False) as handle:
        json.dump(snapshot, handle, ensure_ascii=False, separators=(',', ':'))
        pending_file = Path(handle.name)
    pending_file.replace(OUTPUT)


if __name__ == '__main__':
    main()
