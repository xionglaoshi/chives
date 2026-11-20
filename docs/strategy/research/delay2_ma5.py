"""User-specified: buy 2 trading days later than the original entry (signal+3 open), exit next open after close < MA5."""
import csv, statistics as st
import pullback as P
def run(scheme, delay=2):
    rows=list(csv.DictReader(open(f'{scheme}_20200102_20261117/trades.csv')))
    res={'design':[], 'test':[]}; skip={'limit_up':0,'suspended':0,'open':0}
    for r in rows:
        si=P.CI[r['signal_date']]
        target=P.cal[si+1+delay] if si+1+delay < len(P.cal) else None
        if target is None: continue
        b=P.db.execute("select date,open,high,low,close,volume,adj_factor from bars where code=? and date>=? order by date limit 150",(r['code'],P.cal[si-12])).fetchall()
        k=[i for i,x in enumerate(b) if x[0]>=target]
        if not k: continue
        bi=k[0]
        if P.CI[b[bi][0]]-P.CI[target]>5: skip['suspended']+=1; continue
        if b[bi][1] >= P.lim(b[bi-1][4], P.ratio(r['code'],b[bi][0]))-1e-9: skip['limit_up']+=1; continue
        if bi<4: continue
        q=[x[4]*x[6] for x in b]; out=None
        for i in range(bi,len(b)):
            if q[i] < sum(q[i-4:i+1])/5:
                j=i+1
                while j<len(b) and b[j][1] <= P.lim(b[j-1][4], P.ratio(r['code'],b[j][0]), up=False)+1e-9: j+=1
                if j<len(b): out=j
                break
        if out is None: skip['open']+=1; continue
        ret=P.costs_return(b[bi][1],b[bi][6],b[out][1],b[out][6],b[out][0])
        ex=ret-P.mkt_ret(b[bi][0],b[out][0])
        res['design' if r['signal_date']<='2023-12-31' else 'test'].append((ret,ex,out-bi,b[bi][0],r['code'],b[out][0]))
    return res, skip
names={'p1':'优先级一','p2':'优先级二','start':'启动日','second_board':'二板'}
if __name__=='__main__':
    for sc in ['p1','p2','start','second_board']:
        res,skip=run(sc)
        for seg,lab in (('design','2020–2023'),('test','2024–至今')):
            v=res[seg]; rets=[x[0] for x in v]; wins=[x for x in rets if x>0]; loss=[-x for x in rets if x<=0]
            print(f"{names[sc]:4s} {lab:9s} n={len(v):5d} 平均 {st.mean(rets)*100:+.2f}% 中位 {st.median(rets)*100:+.2f}% 胜率 {len(wins)/len(v)*100:.1f}% 盈亏比 {st.mean(wins)/st.mean(loss):.2f} 持有 {st.mean(x[2] for x in v):.1f}天 最差 {min(rets)*100:+.1f}% 超额 {st.mean(x[1] for x in v)*100:+.2f}%")
        print('   跳过', skip)
