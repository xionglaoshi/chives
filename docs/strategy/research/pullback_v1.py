"""Pre-registered pullback experiment v1 (docs/strategy/zhushenglang-pullback-v1.md)."""
import csv, json, sqlite3, sys, statistics as st
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
db=sqlite3.connect(f'file:{ROOT}/data/marketdata/daily.sqlite?mode=ro',uri=True)
cal=[r[0] for r in db.execute("select date from calendar order by date")]; CI={d:i for i,d in enumerate(cal)}
mkt=json.load(open('mkt.json'))
sec={c:(b,n) for c,b,n in db.execute("select code,board,name from securities")}
flast={c:f for c,f in db.execute("select code, adj_factor from bars b where date=(select max(date) from bars where code=b.code)")}

def ratio(code, day):
    if sec.get(code,('',''))[0]=='chinext' and day>='2020-08-24': return Decimal('0.20')
    if sec.get(code,('',''))[0]=='star': return Decimal('0.20')
    name=sec.get(code,('',''))[1] or ''
    return Decimal('0.05') if ('ST' in name.upper()) else Decimal('0.10')
def lim(prev, r, up=True):
    v=Decimal(str(prev))*(1+r if up else 1-r)
    return float(v.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))

def load(code, start_i, n):
    d0=cal[max(0,start_i)]; return db.execute("select date,open,high,low,close,volume,adj_factor from bars where code=? and date>=? order by date limit ?",(code,d0,n)).fetchall()

def costs_return(bo, fb, so, fs, sell_day):
    buy_exec=bo*1.001; shares=100000/buy_exec; cost=100000+25
    sell_exec=so*0.999; notional=shares*sell_exec
    comm=max(5, notional*0.00025); tax=notional*(0.001 if sell_day<'2023-08-28' else 0.0005)
    net=notional*(fs/fb)-comm-tax
    return (net-cost)/cost

def mkt_ret(d0, d1):
    v=1.0
    for k in range(CI[d0]+1, CI[d1]+1): v*=1+mkt.get(cal[k],0)
    return v-1

starts={}
for r in csv.reader(open(f'{ROOT}/runtime/surge/events.csv')):
    if len(r)>4 and r[4]=='启动':
        v=json.loads(r[5]); starts[(r[1],r[2])]=v
rounds={(r['code'],r['round_id']):r for r in csv.DictReader(open(f'{ROOT}/runtime/surge/rounds.csv'))}

def simulate(code, rid, scheme):
    s=starts[(code,rid)]; ts=s['T_star']; Hb=s['Hb']
    rd=rounds.get((code,rid),{}); out=rd.get('main_out_date') or '9999'
    if ts not in CI: return None
    b=load(code, CI[ts]-15, 15+1+15+40)
    q=lambda x,i: x*b[i][6]/flast[code]   # qfq price
    ti=[i for i,x in enumerate(b) if x[0]==ts]
    if not ti: return None
    ti=ti[0]
    C=[q(x[4],i) for i,x in enumerate(b)]; L=[q(x[3],i) for i,x in enumerate(b)]; O=[q(x[1],i) for i,x in enumerate(b)]
    V=[x[5] for x in b]
    def ma10(i): return sum(C[i-9:i+1])/10 if i>=9 else None
    def v5(i):
        xs=[v for v in V[max(0,i-5):i] if v>0]; return sum(xs)/len(xs) if len(xs)==5 else None
    entry=None
    if scheme=='start':
        entry=(ti, ti)  # buy next open after T*, stop ref = T* low
    else:
        for t in range(ti+2, min(ti+16, len(b))):
            # abandon checks up to t
            if any(C[j] < Hb*0.95 for j in range(ti+1, t+1)) or b[t][0] >= out: break
            p=t-1; vv=v5(p)
            if vv is None: continue
            shrink = V[p] < vv
            stab = C[t] > C[t-1] and C[t] > O[t]
            if not stab: continue
            if scheme=='A':
                ok = L[p] <= Hb*1.02 and C[p] >= Hb*0.97 and shrink
            elif scheme=='B':
                m=ma10(p); m2=ma10(t)
                ok = m is not None and m2 is not None and abs(C[p]/m-1)<=0.02 and shrink and C[t]>m2
            else:
                hmax=max(C[ti:p+1]); ok = C[p] <= hmax*0.92 and C[p] >= Hb*0.95
            if ok: entry=(t, p); break
    if entry is None: return None
    t, p = entry
    # buy at next bar open (suspension: next bar within 5 trading days)
    bi=t+1
    if bi>=len(b) or CI[b[bi][0]]-CI[b[t][0]]>6: return ('skip_suspended',)
    prev_raw=b[bi-1][4]
    if b[bi][1] >= lim(prev_raw, ratio(code,b[bi][0])) - 1e-9: return ('limit_up',)
    buy_q=q(b[bi][1],bi); stop=L[p]*0.99
    peak=C[bi]; exit_i=None; reason=None
    for i in range(bi, len(b)):
        peak=max(peak, C[i]); held=i-bi+1
        if C[i] < stop: reason='stop'
        elif peak/buy_q-1 >= 0.10 and C[i] < peak*0.93: reason='trail'
        elif held>=15: reason='time'
        if reason:
            j=i+1
            while j<len(b) and b[j][1] <= lim(b[j-1][4], ratio(code,b[j][0]), up=False)+1e-9: j+=1
            if j>=len(b): return None
            exit_i=j; break
    if exit_i is None: return None
    r=costs_return(b[bi][1], b[bi][6], b[exit_i][1], b[exit_i][6], b[exit_i][0])
    ex=r - mkt_ret(b[bi][0], b[exit_i][0])
    return ('ok', b[bi][0], r, ex, exit_i-bi, reason, ts)

def run(scheme, lo, hi):
    res=[]; skips={'limit_up':0,'skip_suspended':0}
    for (code,rid),s in starts.items():
        if not (lo <= s['T_star'] <= hi): continue
        if code not in flast: continue
        x=simulate(code,rid,scheme)
        if x is None: continue
        if x[0]!='ok': skips[x[0]]+=1; continue
        res.append(x)
    rets=[x[2] for x in res]; ex=[x[3] for x in res]
    if not rets: return {'n':0, **skips}
    wins=[r for r in rets if r>0]; loss=[-r for r in rets if r<=0]
    pf=(st.mean(wins)/st.mean(loss)) if wins and loss else None
    reasons={k:sum(1 for x in res if x[5]==k) for k in ('stop','trail','time')}
    return {'n':len(rets),'limit_up':skips['limit_up'],'win':len(wins)/len(rets),'mean':st.mean(rets),'median':st.median(rets),
            'payoff':pf,'hold':st.mean(x[4] for x in res),'worst':min(rets),'excess':st.mean(ex),'exits':reasons}

if __name__=='__main__':
    lo,hi=sys.argv[1],sys.argv[2]; schemes=sys.argv[3].split(',')
    for sc in schemes:
        r=run(sc,lo,hi)
        if r['n']==0: print(sc, r); continue
        print(f"{sc:6s} n={r['n']:5d} 买不到={r['limit_up']:4d} 胜率={r['win']*100:5.1f}% 平均={r['mean']*100:+.2f}% 中位={r['median']*100:+.2f}% 盈亏比={r['payoff']:.2f} 持有={r['hold']:.1f} 最差={r['worst']*100:+.1f}% 超额={r['excess']*100:+.2f}% 出场={r['exits']}")
