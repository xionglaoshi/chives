"""Verify candidate file and actual Chives table cells before publishing."""
import hashlib
import json
import math
import os
import re
import sys
from decimal import Decimal, ROUND_HALF_UP
from sources import ROOT

PATTERNS = {
    'emerging': r'\+\d+位', 'private': r'\+\d+\.\d%',
    'in': r'\+\d+\.\d{2}%', 'out': r'-\d+\.\d{2}%',
    'rating': r'\d+家', 'popular': r'\d+ 天上榜',
    'authors': r'\d+贴', 'global': r'\d+(?:\.\d+)? 分',
}

def expected_tables(snapshot, columns):
    boards = snapshot['boards']
    if list(boards) != list(columns):
        raise ValueError('榜单数量或顺序错误')
    tables = []
    for key, labels in columns.items():
        board = boards[key]
        rows = board['rows']
        if board['columns'] != list(labels) or len(rows) != 20 or len({r['code'] for r in rows}) != 20:
            raise ValueError(f'{key} 表头、行数或唯一代码检查失败')
        field = 'shareChange' if key == 'global' else 'r5' if labels[1] == '五日涨幅' else 'r30'
        expected = []
        for row in rows:
            primary = row.get('metric')
            value = row.get(field)
            if not isinstance(primary,str) or not re.fullmatch(PATTERNS[key],primary):
                raise ValueError(f'{key}/{row["code"]} {labels[0]} 无效')
            if type(value) not in (int,float) or not math.isfinite(value):
                raise ValueError(f'{key}/{row["code"]} {labels[1]} 无效')
            amount = Decimal.from_float(float(value or 0)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
            secondary = ('+' if value>0 else '') + f'{amount:.2f}%'
            expected.append([row['name'],row['code'],primary,secondary])
        tables.append((board['title'],list(labels),expected))
    return tables

def check_candidate(path, columns):
    bindings = ROOT / 'runtime/ms-playwright/python'
    if bindings.is_dir() and str(bindings) not in sys.path:
        sys.path.insert(0, str(bindings))
    from playwright.sync_api import sync_playwright

    raw = path.read_bytes()
    snapshot = json.loads(raw)
    tables = expected_tables(snapshot, columns)
    os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(ROOT/'runtime/ms-playwright/browsers'))
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={'width':1626,'height':894})
        page.route('**/api/settings/desk/hotspots',lambda route: route.fulfill(json={'snapshot':snapshot,'status':{'state':'ready'}}))
        page.goto('http://127.0.0.1:8888/#/workspace/trends',wait_until='domcontentloaded')
        panels = page.locator('.hs-panel')
        panels.first.wait_for(timeout=20000)
        if panels.count()!=len(tables):raise ValueError('网页榜单数量不符')
        for i,(title,labels,rows) in enumerate(tables):
            panel = panels.nth(i)
            if panel.locator('h2').inner_text()!=title or panel.locator('th').all_inner_texts()[1:]!=labels:
                raise ValueError(f'{title} 网页表头不符')
            actual = panel.locator('tbody tr').evaluate_all("""rs=>rs.map(r=>{
                const [identity,...cells]=r.cells;
                const visible=c=>c && c.checkVisibility({checkOpacity:true,checkVisibilityCSS:true}) && c.getBoundingClientRect().width>0;
                return [identity.firstElementChild,identity.querySelector('small'),...cells].map(c=>visible(c)?c.innerText:null);
            })""")
            links = panel.locator('tbody tr').evaluate_all("rs => rs.map(r => r.querySelector('a')?.href ?? null)")
            for (_, code, _, _), link in zip(rows, links, strict=True):
                exchange = 'sh' if code.startswith('6') else 'bj' if code.startswith(('4','8','9')) else 'sz'
                expected_link = None if list(columns)[i] == 'global' else f'https://quote.eastmoney.com/{exchange}{code}.html'
                if link != expected_link:
                    raise ValueError(f'{title}/{code} 行情链接错误')
            if actual!=rows:
                index=next((j for j,(a,b) in enumerate(zip(actual,rows),1) if a!=b),min(len(actual),len(rows))+1)
                raise ValueError(f'{title} 第{index}行网页与文件不一致或不可见')
        browser.close()
    row_count=sum(len(rows) for _,_,rows in tables)
    return dict(boards=len(tables),rows=row_count,values=row_count*2,sha256=hashlib.sha256(raw).hexdigest())
