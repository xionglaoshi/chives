from sources import *

def emerging(pool,pop,broker,asof):
    ranked=[]
    for c in set(pool)|set(pop)|set(broker):
        net,ratio,_,last,_=pool.get(c,(0,0,0,0,0))
        shift=pop.get(c,{}).get('baselineGain') or 0
        recent=broker.get(c,{}).get('recent',0)
        signals=[]
        if net>0 and last and last>max(0,(net-last)/4):signals.append('大单流入加速')
        if shift>=10:signals.append(f'人气较基准升{shift}位')
        if recent:signals.append(f'近7日{recent}家正面评级')
        if shift>0 and signals:
            ranked.append(((len(signals),min(shift,100)/100+min(recent,5)/5+max(0,min(ratio,5))/5),
                 row(c,f'+{shift}位',' · '.join(signals),'https://quote.eastmoney.com/'+('sh' if c.startswith('6') else 'bj' if c[0] in '489' else 'sz')+c+'.html',rankGain=shift)))
    return board('新晋热点榜','资金加速、人气跃升、近期券商正面评级，仅列人气排名上升的股票，多项信号优先。人气比较当前排名与此前第6至30天均值，至少15天有效记录。按信号数及强度排序。',POPULAR,[r for _,r in sorted(ranked,key=lambda x:x[0],reverse=True)],asof)

def enrich(boards):
    def stock(c):
        sym=('sh' if c.startswith('6') else 'bj' if c[0] in '489' else 'sz')+c
        try:
            result=get('https://web.ifzq.gtimg.cn/appstock/app/fqkline/get',dict(param=f'{sym},day,,,40,qfq')).json()['data'][sym]
            days=result.get('qfqday') or result['day']
            qt=result['qt'][sym]
            # Estimate period turnover against latest tradable shares; historical denominator may vary.
            shares=float(qt[44])*1e8/float(qt[3])
            out={'priceDate':days[-1][0]}
            for n in (5,30):
                if len(days)>n:
                    out['r'+str(n)]=round(100*(float(days[-1][2])/float(days[-n-1][2])-1),2)
                    out['t'+str(n)]=round(100*sum(float(d[5])*100 for d in days[-n:])/shares,2)
            return c,out
        except (ValueError,TypeError,KeyError,IndexError,ZeroDivisionError,requests.RequestException):
            pass
        # Compute price performance independently of the optional turnover feed.
        try:
            suffix='SS' if sym.startswith('sh') else 'SZ'
            if not sym.startswith('bj'):
                chart=get('https://query1.finance.yahoo.com/v8/finance/chart/'+c+'.'+suffix,dict(range='3mo',interval='1d'),overseas=True).json()['chart']['result'][0]
                obs=[(ts,float(v)) for ts,v in zip(chart['timestamp'],chart['indicators']['adjclose'][0]['adjclose']) if num(v) and float(v)>0]
                if len(obs)>30 and (TODAY-datetime.fromtimestamp(obs[-1][0],ZONE).date()).days<=7:
                    return c,{'priceDate':datetime.fromtimestamp(obs[-1][0],ZONE).date().isoformat(),'priceSource':'Yahoo adjusted close',
                              **{'r'+str(n):round(100*(obs[-1][1]/obs[-n-1][1]-1),2) for n in (5,30)}}
        except (ValueError,TypeError,KeyError,IndexError,requests.RequestException):
            pass
        try:
            days=get('https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssl_qsfx_zjlrqs',dict(daima=sym,page=1,num=35,sort='opendate',asc=0)).json()
            if not days or (TODAY-date.fromisoformat(days[0]['opendate'])).days>7:return c,{}
            return c,{'priceDate':days[0]['opendate'],'priceSource':'新浪日涨跌幅连乘',
                      **{'r'+str(n):round(100*(math.prod(1+float(d['changeratio']) for d in days[:n])-1),2) for n in (5,30) if len(days)>=n}}
        except (ValueError,TypeError,KeyError,IndexError,requests.RequestException):
            return c,{}
    data=dict(parallel(stock,{r['code'] for b in boards for r in b['rows'] if r['code'] in NAMES},5))
    for b in boards:
        for r in b['rows']:r.update(data.get(r['code'],{}))
