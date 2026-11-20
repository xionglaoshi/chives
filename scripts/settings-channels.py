"""Chives-owned channel profiles. Provider secrets and polling tokens stay on the Mac."""
import asyncio
import base64
import contextlib
import io
import json
import logging
import os
from pathlib import Path
import re
import sys
import tempfile
import time

os.umask(0o077)
DATA=Path(sys.argv[1])
STORE=DATA/'secrets'/'channels'
STORE.mkdir(parents=True,exist_ok=True,mode=0o700)
import channel_onboarding as channel
CHANNELS=('weixin','wecom','feishu','slack','discord','telegram')
QR_CHANNELS=('weixin','wecom','feishu','telegram')
logging.disable(logging.CRITICAL)

def read(path):
    return json.loads(path.read_text()) if path.exists() else {}

def save(path,obj):
    with tempfile.NamedTemporaryFile(mode='w',dir=STORE,delete=False) as f:
        json.dump(obj,f); tmp=f.name
    os.replace(tmp,path)

def qr_image(url):
    import qrcode
    buf=io.BytesIO()
    qrcode.make(url).save(buf,format='PNG')
    return 'data:image/png;base64,'+base64.b64encode(buf.getvalue()).decode()

def pair(kind,status):
    def show(url):
        if not isinstance(url,str) or not url.startswith(('https://','tg://')):raise ValueError('invalid QR')
        save(status,{'state':'waiting','image':qr_image(url),'at':time.time()})
    with contextlib.redirect_stdout(io.StringIO()):
        if kind=='telegram':
            from channel_onboarding import create_pairing,poll_for_setup_result
            p=create_pairing(bot_name='Chives')
            if not p:raise ValueError('pairing unavailable')
            show(p.qr_payload); result=poll_for_setup_result(None,p,timeout=240)
            if not result:raise ValueError('timeout')
            return {'key':result.token,'target':str(result.owner_user_id or '')}
        if kind=='weixin':
            return channel.pair_weixin(show)
        if kind=='feishu':
            import channel_onboarding as adapter
            adapter._init_registration('feishu'); b=adapter._begin_registration('feishu');show(b['qr_url'])
            r=adapter._poll_registration(device_code=b['device_code'],interval=b['interval'],expire_in=min(240,b['expire_in']),domain='feishu')
            if r:return {'key':r['app_secret'],'account':r['app_id'],'target':r.get('open_id') or ''}
        if kind=='wecom':
            return channel.pair_wecom(show)
    raise ValueError('pairing expired')

def connect(kind,cfg,message=None):
    import httpx
    from urllib.parse import quote
    token=cfg.get('key',''); target=cfg.get('target',''); account=cfg.get('account','')
    if not token or len(token)>4096 or (message and not target):raise ValueError('missing credentials or recipient')
    def api(url,body=None,headers=None):
        with httpx.Client(timeout=15,follow_redirects=False) as client:
            r=client.get(url,headers=headers) if body is None else client.post(url,json=body,headers=headers)
            r.raise_for_status();return r.json()
    if kind=='telegram':
        if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]+',token):raise ValueError('token')
        res=api('https://api.telegram.org/bot'+token+('/sendMessage' if message else '/getMe'),{'chat_id':target,'text':message} if message else None)
        if not res.get('ok'):raise ValueError('telegram')
    elif kind=='discord':
        hdr={'Authorization':'Bot '+token}
        result=api('https://discord.com/api/v10/users/@me',headers=hdr)
        if not result.get('bot'):raise ValueError('bot required')
        if target:api('https://discord.com/api/v10/channels/'+quote(target,safe=''),headers=hdr)
        if message:api('https://discord.com/api/v10/channels/'+quote(target,safe='')+'/messages',{'content':message,'allowed_mentions':{'parse':[]}},hdr)
    elif kind=='slack':
        res=api('https://slack.com/api/'+('chat.postMessage' if message else 'auth.test'),{'channel':target,'text':message} if message else {},{'Authorization':'Bearer '+token})
        if not res.get('ok'):raise ValueError('slack')
    elif kind=='feishu':
        r=api('https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',{'app_id':account,'app_secret':token})
        if not r.get('tenant_access_token'):raise ValueError('feishu')
        if message:
            typ='open_id' if target.startswith('ou_') else 'chat_id'
            r=api('https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type='+typ,{'receive_id':target,'msg_type':'text','content':json.dumps({'text':message})},{'Authorization':'Bearer '+r['tenant_access_token']})
            if r.get('code')!=0:raise ValueError('feishu')
    elif kind=='wecom':
        channel.connect_wecom(cfg,message)
    elif kind=='weixin':
        if message:
            if not re.fullmatch(r'[\w.@-]+',account):raise ValueError('account')
            folder=STORE/'hermes/weixin/accounts'
            context=read(folder/(account+'.context-tokens.json')).get(target)
            channel.send_weixin(cfg,message,context)
        elif not cfg.get('paired'):raise ValueError('请先扫码验证微信账号')

def main():
    op=sys.argv[2]
    cfgin=json.load(sys.stdin) if op!='pair' else {}
    kind=sys.argv[3] if op=='pair' else cfgin.get('id','')
    if op=='list':
        out=[]
        for n in CHANNELS:
            c=read(STORE/(n+'.json')); q=read(STORE/(n+'.pair'))
            if time.time()-q.get('at',0)>300:q={}
            out.append({'id':n,'configured':bool(c),'verified':bool(c.get('verified')),'enabled':bool(c.get('enabled')),'target':c.get('target',''),'account':c.get('account',''),'pair':q,'qr':n in QR_CHANNELS,'last':c.get('last','')})
        return out
    if kind not in CHANNELS:raise ValueError('channel')
    file=STORE/(kind+'.json'); status=STORE/(kind+'.pair'); config=read(file)
    if op=='pair':
        try:
            save(status,{'state':'starting','at':time.time()}); c=pair(kind,status)
            save(file,{**c,'paired':True,'verified':True,'enabled':False})
            save(status,{'state':'done','at':time.time()})
        except Exception:save(status,{'state':'failed','at':time.time()})
    elif op=='save':
        c={**config,**{k:str(cfgin.get(k,'')).strip() for k in ('account','target')}}
        if cfgin.get('key'):c.update(key=cfgin['key'],paired=False)
        connect(kind,c)
        if cfgin.get('enabled') and not c['target']:raise ValueError('recipient')
        save(file,{**c,'verified':True,'enabled':bool(cfgin.get('enabled'))})
    elif op=='delete':
        file.unlink(missing_ok=True);status.unlink(missing_ok=True)
    elif op=='send' and config.get('enabled'):
        try:connect(kind,config,cfgin['message']);config['last']='投递成功'
        except Exception:config['last']='投递失败，请核对权限和接收会话'
        save(file,config)
    return {'ok':True}

if __name__=='__main__':
    try:print(json.dumps(main(),ensure_ascii=False))
    except Exception:print(json.dumps({'error':'平台未确认连接，请检查凭证、目标会话和网络。微信请先扫码授权。'},ensure_ascii=False));sys.exit(1)
