"""Read-only public observations. All stock codes are resolved against the local A-share directory."""
import math
import os
import re
import json
import subprocess
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, date
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[2]
ZONE = ZoneInfo('Asia/Shanghai')
TODAY = datetime.now(ZONE).date()
START = TODAY - timedelta(days=29)
NAMES = {k[:6]:v for k,v in json.loads((ROOT/'apps/web/public/holdings-securities.json').read_text()).items()
         if re.fullmatch(r'(?:[036]\d{5}\.(?:SH|SZ)|[489]\d{5}\.BJ)',k)}
EM = 'https://data.eastmoney.com'
POPULAR = 'https://guba.eastmoney.com/rank/'
RATING = EM+'/report/stock.jshtml'
PRIVATE = EM+'/gdfx/HoldingAnalyse.html'
FLOW = 'https://vip.stock.finance.sina.com.cn/mkt/'
AGENT = {'User-Agent':'Mozilla/5.0 (compatible; Chives local market research)','Referer':'https://data.eastmoney.com/'}

def get(url, params=None, *, payload=None, overseas=False):
    opts = dict(headers=AGENT,timeout=(6,18))
    if overseas:
        opts.update(proxies={'https':os.getenv('CHIVES_OVERSEAS_PROXY','http://127.0.0.1:7897')})
    for attempt in range(2):
        try:
            r=requests.post(url,json=payload,**opts) if payload else requests.get(url,params=params,**opts)
            r.raise_for_status()
            return r
        except requests.RequestException:
            if attempt: raise

def parallel(fn,items,workers=4):
    with ThreadPoolExecutor(workers) as pool:
        return list(pool.map(fn,items))

def num(value):
    try:
        n=float(value)
        return n if math.isfinite(n) else None
    except (TypeError,ValueError):
        return None

def row(code,metric,why,link,**details):
    return dict(code=code,name=NAMES[code],metric=metric,why=why,url=link,**details)

def board(title,note,link,rows,asof=None):
    return dict(title=title,note=note,url=link,asOf=asof or TODAY.isoformat(),rows=rows[:20])

def flows():
    base='https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.'
    def page(key):
        side,index=key
        return get(base+'ssl_bkzj_ssggzj',dict(page=index,num=50,sort='r0_net',asc=side,bankuai='',shichang='')).json()
    symbols=sorted({r['symbol'] for group in parallel(page,[(s,i) for s in (0,1) for i in range(1,9)]) for r in group if r['symbol'][2:] in NAMES})
    caps={}
    for i in range(0,len(symbols),55):
        quotes=get('https://qt.gtimg.cn/q='+','.join(symbols[i:i+55])).content.decode('gbk',errors='replace')
        for line in quotes.splitlines():
            fields=line.split('~')
            if len(fields)>45 and num(fields[45]):caps[fields[2]]=(float(fields[45])*1e8,fields[30][:8])
    def history(symbol):
        c=symbol[2:]
        if c not in caps:return None
        rs=get(base+'ssl_qsfx_zjlrqs',dict(daima=symbol,page=1,num=5,sort='opendate',asc=0)).json()
        if not rs or len(rs)!=5:return None
        cap,day=caps[c]
        if rs[0]['opendate'].replace('-','')!=day:return None
        net=sum(float(x['r0_net']) for x in rs)
        amounts=[float(x['r0_net'])/float(x['r0_ratio']) for x in rs if num(x['r0_ratio'])]
        if len(amounts)!=5 or min(amounts)<=0 or cap<=0:return None
        return c,rs[0]['opendate'],(net,100*net/cap,100*net/sum(amounts),float(rs[0]['r0_net']),None)
    observed=[r for r in parallel(history,symbols,5) if r]
    latest=max(date.fromisoformat(r[1]) for r in observed)
    pool={c:data for c,d,data in observed if d==str(latest)}
    if len(pool)<100:raise ValueError('资金样本覆盖不足')
    out=[]
    for sign,label in [(1,'流入'),(-1,'流出')]:
        side=[c for c in pool if pool[c][0]*sign>0]
        scores=defaultdict(float)
        for idx,weight in [(1,.6),(2,.4)]:
            for pos,c in enumerate(sorted(side,key=lambda k:sign*pool[k][idx])):
                scores[c]+=weight*pos/max(1,len(side)-1)
        items=[]
        for c in sorted(side,key=scores.get,reverse=True)[:20]:
            n,ratio,share,_,change=pool[c]
            items.append(row(c,f'{ratio:+.2f}%',f'占总市值 {ratio:+.2f}% · 占成交额 {share:+.2f}%',FLOW,
                             net=round(n),capRatio=round(ratio,3),r5=change))
        out.append(board('资金'+label+'榜',f'近5个交易日 · {len(pool)}只有效股票 · 样本取新浪当日大单净额两端各400名并剔除基金。按净额/期末总市值与净额/成交额的同向百分位六四加权。',FLOW,items,latest.isoformat()))
    return (*out,pool)

def ratings():
    since=TODAY-timedelta(days=179)
    roster=json.loads(Path(__file__).with_name('brokers.json').read_text())
    licensed={name.strip().replace('（','(').replace('）',')') for name in roster['names']}
    def page(i):
        d=get('https://reportapi.eastmoney.com/report/list',dict(pageSize=100,pageNo=i,p=i,pageNumber=i,pageNum=i,qType=0,beginTime=str(since),endTime=str(TODAY))).json()
        return d['data'],int(d['TotalPage'])
    first,n=page(1)
    groups=defaultdict(dict)
    for r in first+[r for rows,_ in parallel(page,range(2,n+1)) for r in rows]:
        c=r['stockCode']; inst=(r.get('orgName') or '').strip().replace('（','(').replace('）',')')
        day=r['publishDate'][:10]
        if c not in NAMES or inst not in licensed or not str(since)<=day<=str(TODAY) or not r.get('emRatingName'):continue
        previous=groups[c].get(inst)
        if previous is None or (r['publishDate'],r['infoCode'])>(previous['publishDate'],previous['infoCode']):groups[c][inst]=r
    ranked=[]
    for c,ratings_by_broker in groups.items():
        positive=[r for r in ratings_by_broker.values() if r['emRatingName'] in {'买入','增持','推荐','强推'}]
        if not positive:continue
        last=max(positive,key=lambda r:r['publishDate'])
        ranked.append(((len(positive),last['publishDate'],c),row(c,f'{len(positive)}家',f'{last["orgSName"]} · {last["emRatingName"]}',
            'https://data.eastmoney.com/report/info/'+last['infoCode']+'.html',recommendingBrokers=sorted(r['orgSName'] for r in positive),
            recent=sum(r['publishDate'][:10]>=str(TODAY-timedelta(days=6)) for r in positive))))
    items=[r for _,r in sorted(ranked,key=lambda x:x[0],reverse=True)]
    note=f"近180天公开个股研报，每家券商每股只取最后一份有评级的报告，统计买入、增持、推荐、强推。匹配证监会{roster['asOf']}名录。"
    return board('券商荐买榜',note,RATING,items),{r['code']:r for r in items}

def private():
    for d in sorted([date(y,m,day) for y in (TODAY.year-1,TODAY.year) for m,day in [(3,31),(6,30),(9,30),(12,31)] if date(y,m,day)<TODAY],reverse=True):
        def page(i):
            filt=f"(END_DATE='{d}')(HOLDER_TYPE=\"私募基金\")(HOLDNUM_CHANGE_NAME=\"增加\")"
            result=get('https://datacenter-web.eastmoney.com/api/data/v1/get',dict(reportName='RPT_F10_EH_FREEHOLDERS',columns='ALL',pageSize=500,pageNumber=i,filter=filt,sortColumns='SECURITY_CODE,HOLDER_RANK',sortTypes='1,1')).json()
            if not result.get('success') and result.get('code') not in (9201,):raise ValueError(str(result.get('message','披露查询失败')))
            data=result.get('result') or {}
            return data.get('data',[]),int(data.get('pages',0))
        rows,n=page(1)
        if not rows:continue
        rows += [r for rs,_ in parallel(page,range(2,n+1)) for r in rs]
        by=defaultdict(dict)
        for r in rows:
            c=r['SECURITY_CODE']; delta=num(r.get('XZCHANGE') or r.get('HOLD_NUM_CHANGE'));holder=r['HOLDER_NAME']
            if c in NAMES and delta and delta>0 and r['UPDATE_DATE'][:10]<=str(TODAY):
                by[c][holder]=(delta,num(r['HOLD_NUM']),r['UPDATE_DATE'][:10])
        items=[]
        for c,holders in by.items():
            qty=sum(x[0] for x in holders.values())
            prev=sum((x[1] or x[0])-x[0] for x in holders.values())
            rate=qty/prev*100 if prev>0 else 0
            items.append(((len(holders),rate),row(c,f'{rate:+.1f}%',f'可比增持 {qty/10000:,.1f} 万股 · 合计持股增幅 {rate:.1f}%',PRIVATE,
                increasePct=round(rate,3),example=next(iter(holders)),disclosed=max(x[2] for x in holders.values()))))
        return board('私募增持榜','十大流通股东中有可比增量的私募产品，按产品数、合计持股增幅排序；新进前十单独口径，不计入。',PRIVATE,[r for _,r in sorted(items,key=lambda x:x[0],reverse=True)],str(d))
    raise ValueError('尚无可比较私募披露')

def popular():
    base='https://emappdata.eastmoney.com/stockrank/'
    common=dict(appId='appId01',globalId='786e4c21-70dc-435a-93bb-38',marketType='')
    data=get(base+'getAllCurrentList',payload=dict(common,pageNo=1,pageSize=100)).json()['data']
    def history(r):
        c=r['sc'][2:]
        if c not in NAMES:return None
        records=get(base+'getHisList',payload=dict(common,srcSecurityCode=r['sc'],yearType='5')).json().get('data') or []
        hist={str(x['calcTime'])[:10]:int(x['rank']) for x in records if str(START)<=str(x['calcTime'])[:10]<=str(TODAY)}
        hist[str(TODAY)]=int(r['rk'])
        days=sum(v<=100 for v in hist.values())
        rise=int(r.get('hisRc') or 0)
        baseline=[v for d,v in hist.items() if d<str(TODAY-timedelta(days=4))]
        gain=round(sum(baseline)/len(baseline)-int(r['rk'])) if len(baseline)>=15 else None
        score=sum(max(0,101-v) for v in hist.values())
        return score,row(c,f'{days} 天上榜',f'当前第 {r["rk"]} · 较昨日 {rise:+d} 位',POPULAR,shift=rise,baselineGain=gain,sampledDays=len(hist),rank=int(r['rk']))
    result=[v for v in parallel(history,data,4) if v]
    items=[r for _,r in sorted(result,key=lambda x:(x[0],-x[1]['rank']),reverse=True)]
    return board('散户热搜榜','东财当前百强样本 · 近30天每日排名积分，越靠前、持续越久排位越高。',POPULAR,items),{r['code']:r for r in items}

def zh(*args):
    out=subprocess.run(['/opt/homebrew/bin/zhihu-cli',*args],capture_output=True,timeout=45)
    j=json.loads(out.stdout)
    if not j.get('ok'):raise ValueError('知乎读取失败')
    return j['data']

def authors():
    # Public author candidates from investment discussion; require actual profile follower count.
    people=set(['15268154184ai','xiao-jie-29-22-95','wu-min-yong-4','36-14-82-21','nalan-liuli-19-10','38-16-18-13'])
    for q in ['A股 行情 复盘','股票 价值投资','半导体 股票 投资','银行股 投资']:
        for item in zh('search','--query',q,'--questions-only','--answers','3','--limit','4'):
            for a in item.get('answers',[]):
                if a.get('author',{}).get('urlToken'):people.add(a['author']['urlToken'])
    matcher=re.compile('|'.join(re.escape(v) for v in sorted(set(NAMES.values()),key=len,reverse=True) if len(v)>=3))
    codes={v:k for k,v in NAMES.items()}
    stats=defaultdict(dict);qualified=0;seen=set()
    for person in sorted(people):
        try:
            profile=zh('user',person)
            if (profile.get('followerCount') or 0)<1000:continue
            qualified+=1
            for a in zh('user-answers',person,'--limit','30'):
                if a['id'] in seen or datetime.fromtimestamp(a['createdTime'],ZONE).date()<START:continue
                seen.add(a['id'])
                for name in set(matcher.findall(re.sub('<[^>]*>','',' '.join([a.get('questionTitle',''),a.get('excerpt','')])))):
                    stats[codes[name]][a['id']]=(person,a.get('commentCount') or 0,a['url'],profile['name'])
        except (ValueError,KeyError,subprocess.TimeoutExpired):continue
    items=[]
    for c,posts in stats.items():
        authors_n=len({x[0] for x in posts.values()});comments=sum(x[1] for x in posts.values());best=max(posts.values(),key=lambda x:x[1])
        items.append(((comments,authors_n,len(posts)),row(c,f'{comments}贴',f'{len(posts)} 篇回答 · {comments} 条跟帖 · {best[3]}',best[2],comments=comments)))
    return board('大V热议榜',f'知乎投资话题作者样本 · ≥千名关注者 · {qualified}位 · 近30天回答标题及摘要精确匹配。雪球本期未覆盖。','https://www.zhihu.com/',[r for _,r in sorted(items,key=lambda x:x[0],reverse=True)])
