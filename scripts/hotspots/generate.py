"""Publish one version atomically. Both launchd and the UI enter through this lock."""
import argparse
import fcntl
import gzip
import hashlib
import json
import os
import tempfile
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta
from pathlib import Path
import sources
from analytics import emerging,enrich
from world import world
from quality import check_candidate

COLUMNS={
    'emerging':('热度上升','五日涨幅'), 'private':('仓位增持比','30日涨幅'),
    'in':('净流入占市值','五日涨幅'), 'out':('净流出占市值','五日涨幅'),
    'rating':('荐买券商数','30日涨幅'), 'popular':('百强天数','五日涨幅'),
    'authors':('热议贴数','30日涨幅'), 'global':('本周热度','份额增幅')
}
ORDER=tuple(COLUMNS)
def now():return datetime.now(sources.ZONE)
def load(path,default):
    try:return json.loads(path.read_bytes())
    except FileNotFoundError:return default
def compact(obj):return json.dumps(obj,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
def write(path,data):
    with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as f:
        try:
            f.write(data);f.flush();os.fsync(f.fileno())
            os.replace(f.name,path)
        finally:
            if os.path.exists(f.name):os.unlink(f.name)

def generate(folder,due):
    folder.mkdir(parents=True,exist_ok=True)
    with (folder/'update.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        stat=folder/'status.json'; latest=folder/'latest.json'
        old=load(latest,None);previous=load(stat,{})
        start=now(); today=start.replace(hour=8,minute=30,second=0,microsecond=0)
        target=today if start>=today else today-timedelta(days=1)
        if due and previous.get('startedAt','')>=target.isoformat() and previous.get('finishedAt'):
            if previous.get('state')=='ready' or (start-datetime.fromisoformat(previous['finishedAt'])).total_seconds()<3600:return
        def status(state,**values):
            write(stat,compact(dict(state=state,startedAt=start.isoformat(),pid=os.getpid(),**values)))
        status('running')
        try:
            hk=load(folder/'hk-units.json',{})
            jobs={'flow':sources.flows,'rating':sources.ratings,'popular':sources.popular,'authors':sources.authors,'private':sources.private,'global':lambda:world(hk)}
            result={};issues={}
            with ThreadPoolExecutor(5) as executor:
                pending={k:executor.submit(fn) for k,fn in jobs.items()}
                for key,future in pending.items():
                    try:result[key]=future.result()
                    except Exception as exc:
                        issues[key]=type(exc).__name__;traceback.print_exc()
            boards={}
            if 'flow' in result:boards['in'],boards['out'],pool=result['flow']
            if 'popular' in result:boards['popular'],pop=result['popular']
            if 'rating' in result:boards['rating'],broker=result['rating']
            if all(k in result for k in ('flow','rating','popular')):
                boards['emerging']=emerging(pool,pop,broker,boards['in']['asOf'])
            for k in ('authors','private','global'):
                if k in result:boards[k]=result[k]
            if hk:write(folder/'hk-units.json',compact(dict(sorted(hk.items())[-30:])))
            boards={k:v for k,v in boards.items() if len(v['rows'])==20}
            for k,b in boards.items():b['columns']=list(COLUMNS[k])
            if not boards:raise ValueError('所有来源暂不可用')
            enrich(boards.values())
            # Never replace a board with a snapshot missing its price column.
            for k,b in list(boards.items()):
                if k=='global':continue
                field='r5' if COLUMNS[k][1]=='五日涨幅' else 'r30'
                if any(r.get(field) is None for r in b['rows']):del boards[k]
            oldboards=(old or {}).get('boards',{})
            missing=[k for k in ORDER if k not in boards]
            for k in missing:
                if k in oldboards and oldboards[k].get('columns')==list(COLUMNS[k]):boards[k]=oldboards[k]
                else:raise ValueError('等待完整的新版榜单：'+k)
            stamp=now().isoformat(timespec='seconds')
            ordered={k:boards[k] for k in ORDER if k in boards}
            changed=old is None or ordered!=oldboards or missing!=old.get('retained',[])
            candidate=dict(schema=2,publishedAt=stamp,boards=ordered,retained=missing) if changed else old
            staged=folder/'candidate.tmp'
            try:
                write(staged,compact(candidate))
                quality=check_candidate(staged,COLUMNS)
                if changed:
                    if old:
                        raw=compact(old);archive=folder/'archive';archive.mkdir(exist_ok=True)
                        archivefile=archive/(old['publishedAt'][:19].replace(':','')+'-'+hashlib.sha256(raw).hexdigest()[:10]+'.json.gz')
                        if not archivefile.exists():write(archivefile,gzip.compress(raw,mtime=0))
                    os.replace(staged,latest)
            finally:
                staged.unlink(missing_ok=True)
            status('partial' if missing else 'ready',finishedAt=now().isoformat(),missing=missing,quality=quality)
        except BaseException as exc:
            status('error',finishedAt=now().isoformat(),reason=str(exc)[:500])
            raise

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--data',type=Path,default=sources.ROOT/'data/hotspots')
    parser.add_argument('--due',action='store_true')
    args=parser.parse_args();generate(args.data,args.due)
