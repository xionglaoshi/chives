"""Pre-registered exit optimization v1 (docs/strategy/zhushenglang-exit-v1.md)."""
import csv, json, sys, statistics as st, itertools
import pullback as P   # reuses calendar, limit prices, cost formula, market series
SLS=[None,0.05,0.08,0.12]; TRS=[None,(0.05,0.04),(0.10,0.07),(0.0,0.08)]; TS=[2,3,5,10,20]
COMBOS=list(itertools.product(SLS,TRS,TS))
def label(c):
    sl,tr,n=c
    return f"SL={'无' if sl is None else f'{sl:.0%}'} TR={'无' if tr is None else f'({tr[0]:.0%},{tr[1]:.0%})'} T={n}"
def load_trades(scheme):
    rows=[r for r in csv.DictReader(open(f'{scheme}_20200102_20261117/trades.csv')) if r['status']=='ok']
    out=[]
    for r in rows:
        b=P.db.execute("select date,open,high,low,close,volume,adj_factor from bars where code=? and date>=? order by date limit 26",(r['code'],r['buy_date'])).fetchall()
        if len(b)<3: continue
        out.append((r,b))
    return out
def exit_ret(r,b,combo):
    sl,tr,n=combo; bo=b[0][1]; fb=b[0][6]; peak=None
    for i in range(len(b)):
        rel=b[i][4]*b[i][6]/(bo*fb); peak=rel if peak is None else max(peak,rel); h=i+1
        hit = (sl is not None and rel<=1-sl) or (tr is not None and peak-1>=tr[0] and rel<=peak*(1-tr[1])) or h>=n
        if hit:
            j=i+1
            while j<len(b) and b[j][1] <= P.lim(b[j-1][4], P.ratio(r['code'],b[j][0]), up=False)+1e-9: j+=1
            if j>=len(b): return None
            ret=P.costs_return(bo,fb,b[j][1],b[j][6],b[j][0])
            return ret, ret-P.mkt_ret(b[0][0],b[j][0]), j
    return None
def orig(r):
    return float(r['return_pct'])/100 if r['unclosed']=='False' else None
def evaluate(trades, combo):
    res=[x for x in (exit_ret(r,b,combo) for r,b in trades) if x]
    rets=[x[0] for x in res]
    return {'n':len(rets),'mean':st.mean(rets),'median':st.median(rets),'win':sum(1 for x in rets if x>0)/len(rets),
            'worst':min(rets),'excess':st.mean(x[1] for x in res),'hold':st.mean(x[2] for x in res)}
if __name__=='__main__':
    mode=sys.argv[1]; schemes=sys.argv[2].split(',')
    for sc in schemes:
        allt=load_trades(sc)
        design=[t for t in allt if t[0]['signal_date']<='2023-12-31']
        test=[t for t in allt if t[0]['signal_date']>='2024-01-01']
        if mode=='design':
            o=[x for x in (orig(r) for r,_ in design) if x is not None]
            print(f'== {sc} design n={len(design)}  原规则 平均 {st.mean(o)*100:+.2f}% 中位 {st.median(o)*100:+.2f}%')
            scored=sorted(((evaluate(design,c),c) for c in COMBOS), key=lambda x:-x[0]['mean'])
            means=[s['mean'] for s,_ in scored]
            print(f'   80 组平均：最好 {means[0]*100:+.2f}%  前10%分位 {means[7]*100:+.2f}%  中位 {st.median(means)*100:+.2f}%  最差 {means[-1]*100:+.2f}%')
            for s,c in scored[:5]:
                print(f"   {label(c):34s} 平均 {s['mean']*100:+.2f}% 中位 {s['median']*100:+.2f}% 胜率 {s['win']*100:.1f}% 最差 {s['worst']*100:+.1f}% 超额 {s['excess']*100:+.2f}% 持有 {s['hold']:.1f}")
            json.dump({'scheme':sc,'best':list(scored[0][1][:1])+[scored[0][1][1] and list(scored[0][1][1])]+[scored[0][1][2]]},open(f'best_{sc}.json','w'))
        else:
            bj=json.load(open(f'best_{sc}.json'))['best']; c=(bj[0], tuple(bj[1]) if bj[1] else None, bj[2])
            s=evaluate(test,c); o=[x for x in (orig(r) for r,_ in test) if x is not None]
            print(f"== {sc} test n={s['n']}  选中 {label(c)}  平均 {s['mean']*100:+.2f}% 中位 {s['median']*100:+.2f}% 胜率 {s['win']*100:.1f}% 最差 {s['worst']*100:+.1f}% 超额 {s['excess']*100:+.2f}% 持有 {s['hold']:.1f}  | 原规则平均 {st.mean(o)*100:+.2f}%")
