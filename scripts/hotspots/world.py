"""Sector ETF share creation and market trading activity, using issuer observations."""
import csv
from datetime import datetime
from io import StringIO
from statistics import mean
from lxml import etree
from bs4 import BeautifulSoup
from sources import TODAY, board, get, parallel, num

JP='食品 能源资源 建筑建材 原料化工 医药 汽车及运输设备 钢铁有色 机械 电气及精密设备 信息服务 电力燃气 运输物流 商贸批发 零售 银行 非银金融 房地产'.split()
US=[('SOXX','半导体',239705),('IBB','生物科技',239699),('IHI','医疗器械',239516),('IYT','运输',239501)]
HK='https://www.globalxetfs.com.hk/funds/global-x-china-semiconductor-etf/'

def world(hk_history):
    universe=[(str(1617+i)+'.T','日本',name,1617+i) for i,name in enumerate(JP)]
    universe += [(ticker,'美国',name,key) for ticker,name,key in US]+[('3191.HK','香港','中国半导体',3191)]
    def observe(item):
        ticker,market,name,key=item
        if market=='日本':
            link=f'https://nextfunds.jp/lineup/{key}/'
            data=get(f'https://www.nomura-am.co.jp/fund/etf/history/ETF_{key}.csv',overseas=True).content.decode('cp932')
            hist=[(datetime.strptime(r[0],'%Y%m%d').date().isoformat(),float(r[2])) for r in csv.reader(StringIO(data)) if len(r)>3 and len(r[0])==8 and r[0].isdigit() and num(r[2])]
        elif market=='美国':
            link=f'https://www.ishares.com/us/products/{key}/'
            url='https://www.blackrock.com/varnish-api/blk-one01-product-data/product-data/api/v1/get-fund-document'
            xml=get(url,dict(appType='PRODUCT_PAGE',appSubType='ISHARES',targetSite='us-ishares',locale='en_US',portfolioId=key,component='fundDownload',userType='individual'),overseas=True).content
            root=etree.fromstring(xml,etree.XMLParser(recover=True,resolve_entities=False,no_network=True))
            ns={'s':'urn:schemas-microsoft-com:office:spreadsheet'}
            rows=root.xpath('//s:Worksheet[@s:Name="Historical"]/s:Table/s:Row[position()<30]',namespaces=ns)
            hist=[]
            for r in rows[1:]:
                v=r.xpath('s:Cell/s:Data/text()',namespaces=ns)
                if len(v)>=4 and num(v[3]):hist.append((datetime.strptime(v[0],'%b %d, %Y').date().isoformat(),float(v[3])))
        else:
            link=HK
            page=BeautifulSoup(get(link,overseas=True).content,'html.parser')
            obs=page.select_one('[data-zrcheck="daily-nav-asofdate"]').get_text(strip=True)
            day=datetime.strptime(obs.removeprefix('As of '),'%d %b %Y').date().isoformat()
            hk_history[day]=float(page.select_one('[data-zrcheck="hkd-outstandingunits"]').get_text(strip=True).replace(',',''))
            hist=list(hk_history.items())
        hist.sort()
        asof=hist[-1][0]
        chart=get('https://query1.finance.yahoo.com/v8/finance/chart/'+ticker,dict(range='3mo',interval='1d'),overseas=True).json()['chart']['result'][0]
        vol=[v for v in chart['indicators']['quote'][0]['volume'] if v is not None]
        if len(vol)<25 or not sum(vol[-25:-5]):raise ValueError('成交窗口不足')
        rel=mean(vol[-5:])/mean(vol[-25:-5])
        activity=round(100*rel**3/(1+rel**3))
        growth=None
        if len(hist)>=6 and (datetime.fromisoformat(asof)-datetime.fromisoformat(hist[-6][0])).days<=12:
            growth=100*(hist[-1][1]/hist[-6][1]-1)
        fund=None if growth is None else round(100*max(0,growth)/(1+max(0,growth)))
        score=round(.6*(fund or 0)+.4*activity,1)
        return dict(name=name,code=ticker,metric=f'{score:g} 分',why=f'{market} · 基金热度 {fund if fund is not None else "待积累"} · 交易热度 {activity}',url=link,
                    score=score,market=market,shareChange=growth,volumeRatio=round(rel,2),date=asof)
    def safe(item):
        try:return observe(item)
        except Exception as exc:print('world',item[0],type(exc).__name__,flush=True)
    items=[v for v in parallel(safe,universe,4) if v and v["shareChange"] is not None]
    if len(items)<20:raise ValueError('海外ETF样本不足')
    coverage='、'.join(f'{m}{sum(r["market"]==m for r in items)}只' for m in ['美国','香港','日本'])
    return board('全球热门板块榜',f'{coverage}行业ETF。基金热度按五日份额增长，交易热度按五日均量相对此前20日放量；成交活跃仅代理公众关注。六四加权，只排名两个指标齐全的样本。','https://nextfunds.jp/',sorted(items,key=lambda r:-r['score']),max(r['date'] for r in items))
