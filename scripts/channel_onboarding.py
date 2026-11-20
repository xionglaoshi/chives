"""Provider onboarding clients; see THIRD_PARTY_NOTICES.md for source notices."""
from __future__ import annotations
from dataclasses import dataclass
import base64
import json
import logging
import os
import re
import secrets
import time
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request,urlopen
from uuid import uuid4
import httpx

logger=logging.getLogger(__name__)

DEFAULT_API_URL = "https://setup.hermes-agent.nousresearch.com"

TELEGRAM_ONBOARDING_URL_ENV = "TELEGRAM_ONBOARDING_URL"

DEFAULT_BOT_NAME = "Hermes Agent"

DEFAULT_POLL_TIMEOUT = 180

POLL_INTERVAL = 2

_TELEGRAM_BOT_TOKEN_RE = re.compile(r"^\d+:[A-Za-z0-9_-]{30,}$")

@dataclass(frozen=True)
class TelegramPairing:
    """Pairing record returned by the Telegram onboarding service."""
    pairing_id: str
    poll_token: str
    suggested_username: str
    deep_link: str
    qr_payload: str
    expires_at: str | None = None

@dataclass(frozen=True)
class TelegramBotSetupResult:
    """Successful Telegram onboarding result returned by the setup service."""
    token: str
    bot_username: str | None = None
    owner_user_id: int | None = None

def _api_url(api_url: str | None = None) -> str:
    """Resolve the onboarding API URL, honoring the PoC env override."""
    return (api_url or os.environ.get(TELEGRAM_ONBOARDING_URL_ENV) or DEFAULT_API_URL).rstrip("/")

def is_valid_telegram_bot_token(token: object) -> bool:
    """Return True when *token* has Telegram's bot-token shape."""
    return isinstance(token, str) and bool(_TELEGRAM_BOT_TOKEN_RE.match(token))

def _parse_owner_user_id(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.isdecimal():
        value = int(value)
    return value if isinstance(value, int) and value > 0 else None

def create_pairing(
    api_url: str | None = None, bot_name: str = DEFAULT_BOT_NAME, timeout: float = 10.0
) -> TelegramPairing | None:
    """POST a pairing; the returned poll token is only used as a bearer credential while polling."""
    try:
        resp = httpx.post(f"{_api_url(api_url)}/v1/telegram/pairings", json={"bot_name": bot_name}, timeout=timeout)
        if resp.status_code not in (200, 201):
            return None
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return None
    required = ("pairing_id", "poll_token", "suggested_username", "deep_link")
    if not all(isinstance(data.get(key), str) and data.get(key) for key in required):
        return None
    qr_payload = data.get("qr_payload") or data["deep_link"]
    if not isinstance(qr_payload, str):
        return None
    expires_at = data.get("expires_at")
    return TelegramPairing(*(data[key] for key in required), qr_payload=qr_payload,
                           expires_at=expires_at if isinstance(expires_at, str) else None)

def poll_pairing_result_once(
    api_url: str | None, pairing: TelegramPairing, timeout: float = 10.0
) -> TelegramBotSetupResult | None:
    """Poll the onboarding service once. Returns setup metadata when ready."""
    resp = httpx.get(f"{_api_url(api_url)}/v1/telegram/pairings/{pairing.pairing_id}",
                     headers={"Authorization": f"Bearer {pairing.poll_token}"}, timeout=timeout)
    if resp.status_code != 200:
        return None
    data = resp.json()
    token = data.get("token")
    if data.get("status") != "ready" or not is_valid_telegram_bot_token(token):
        return None
    bot_username = data.get("bot_username")
    return TelegramBotSetupResult(
        token, bot_username if isinstance(bot_username, str) and bot_username else None,
        _parse_owner_user_id(data.get("owner_user_id")))

def poll_for_setup_result(
    api_url: str | None, pairing: TelegramPairing, timeout: float = DEFAULT_POLL_TIMEOUT,
    interval: float = POLL_INTERVAL, on_tick=None) -> Optional[TelegramBotSetupResult]:
    """Poll the pairing API until setup metadata is available or timeout. ``on_tick(elapsed_s)``
    runs before each attempt (progress display)."""
    start = time.monotonic()
    deadline = start + timeout
    while time.monotonic() < deadline:
        if on_tick:
            on_tick(time.monotonic() - start)
        try:  # transport/JSON errors count as 'not ready yet'
            if result := poll_pairing_result_once(api_url, pairing):
                return result
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(interval)
    return None

_ONBOARD_ACCOUNTS_URLS = {
    "feishu": "https://accounts.feishu.cn",
    "lark": "https://accounts.larksuite.com",
}

_REGISTRATION_PATH = "/oauth/v1/app/registration"

_ONBOARD_REQUEST_TIMEOUT_S = 10

def _accounts_base_url(domain: str) -> str:
    return _ONBOARD_ACCOUNTS_URLS.get(domain, _ONBOARD_ACCOUNTS_URLS["feishu"])

def _post_registration(base_url: str, body: dict[str, str]) -> dict:
    """POST form data to the registration endpoint; parse JSON even on 4xx (poll's pending is a 400)."""
    req = Request(
        f"{base_url}{_REGISTRATION_PATH}", data=urlencode(body).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urlopen(req, timeout=_ONBOARD_REQUEST_TIMEOUT_S) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        body_bytes = exc.read()
        if body_bytes:
            try:
                return json.loads(body_bytes.decode("utf-8"))
            except (ValueError, json.JSONDecodeError):
                raise exc from None
        raise

def _init_registration(domain: str = "feishu") -> None:
    """Raise RuntimeError unless the registration environment supports client_secret auth."""
    res = _post_registration(_accounts_base_url(domain), {"action": "init"})
    methods = res.get("supported_auth_methods") or []
    if "client_secret" not in methods:
        raise RuntimeError(
            f"Feishu / Lark registration environment does not support client_secret auth. "
            f"Supported: {methods}"
        )

def _begin_registration(domain: str = "feishu") -> dict:
    """Start the device-code flow. Returns device_code, qr_url, user_code, interval, expire_in."""
    res = _post_registration(_accounts_base_url(domain), {
        "action": "begin", "archetype": "PersonalAgent", "auth_method": "client_secret", "request_user_info": "open_id",
    })
    device_code = res.get("device_code")
    if not device_code:
        raise RuntimeError("Feishu / Lark registration did not return a device_code")
    qr_url = res.get("verification_uri_complete", "")
    qr_url += ("&" if "?" in qr_url else "?") + "from=hermes&tp=hermes"
    return {
        "device_code": device_code, "qr_url": qr_url, "user_code": res.get("user_code", ""),
        "interval": res.get("interval") or 5, "expire_in": res.get("expire_in") or 600,
    }

def _poll_registration(*, device_code: str, interval: int, expire_in: int, domain: str = "feishu") -> Optional[dict]:
    """Poll until scan (→ {app_id, app_secret, domain, open_id}), or None on denial/timeout."""
    deadline = time.monotonic() + expire_in
    current_domain = domain
    domain_switched = False
    poll_count = 0

    while time.monotonic() < deadline:
        try:
            body = {"action": "poll", "device_code": device_code, "tp": "ob_app"}
            res = _post_registration(_accounts_base_url(current_domain), body)
        except (URLError, OSError, json.JSONDecodeError):
            time.sleep(interval)
            continue

        poll_count += 1
        if poll_count == 1:
            print("  Fetching configuration results...", end="", flush=True)
        elif poll_count % 6 == 0:
            print(".", end="", flush=True)

        # Domain auto-detection; fall through — this same response may carry credentials.
        user_info = res.get("user_info") or {}
        if user_info.get("tenant_brand") == "lark" and not domain_switched:
            current_domain = "lark"
            domain_switched = True
        if res.get("client_id") and res.get("client_secret"):
            if poll_count > 0:
                print()  # newline after "Fetching configuration results..." dots
            return {
                "app_id": res["client_id"], "app_secret": res["client_secret"], "domain": current_domain,
                "open_id": user_info.get("open_id"),
            }

        error = res.get("error", "")
        if error in {"access_denied", "expired_token"}:
            if poll_count > 0:
                print()
            logger.warning("[Feishu onboard] Registration %s", error)
            return None
        time.sleep(interval)  # authorization_pending or unknown — keep polling

    if poll_count > 0:
        print()
    logger.warning("[Feishu onboard] Poll timed out after %ds", expire_in)
    return None

WX_BASE='https://ilinkai.weixin.qq.com'
WX_HEADERS={'iLink-App-Id':'bot','iLink-App-ClientVersion':str((2<<16)|(2<<8))}
def wx_base(url):
    parsed=urlsplit(url)
    if parsed.scheme!='https' or not (parsed.hostname or '').endswith('.weixin.qq.com') or parsed.username or parsed.password:
        raise ValueError('invalid Weixin service')
    return 'https://'+parsed.netloc

def pair_weixin(show):
    until=time.monotonic()+240
    with httpx.Client(timeout=35,headers=WX_HEADERS) as client:
        for _ in range(4):
            qr=client.get(WX_BASE+'/ilink/bot/get_bot_qrcode',params={'bot_type':3}).raise_for_status().json()
            show(qr['qrcode_img_content'])
            base=WX_BASE
            while time.monotonic()<until:
                try:
                    state=client.get(base+'/ilink/bot/get_qrcode_status',params={'qrcode':qr['qrcode']}).raise_for_status().json()
                except httpx.TimeoutException:
                    continue
                status=state.get('status')
                if status=='confirmed' and state.get('bot_token') and state.get('ilink_bot_id'):
                    return dict(key=state['bot_token'],account=state['ilink_bot_id'],target=state.get('ilink_user_id',''),base_url=wx_base(state.get('baseurl') or base))
                if status=='expired':break
                if status=='scaned_but_redirect':base=wx_base('https://'+state['redirect_host'])
                time.sleep(1)
            if time.monotonic()>=until:break
    raise ValueError('pairing expired')

def send_weixin(cfg,text,context):
    target,token=cfg['target'],cfg['key']
    with httpx.Client(timeout=20,headers=WX_HEADERS) as client:
        for start in range(0,len(text),2000):
            msg={'from_user_id':'','to_user_id':target,'client_id':uuid4().hex,'message_type':2,'message_state':2,
                 'item_list':[{'type':1,'text_item':{'text':text[start:start+2000]}}]}
            if context:msg['context_token']=context
            for attempt in range(2):
                data={'msg':msg,'base_info':{'channel_version':'2.2.0'}}
                headers={'AuthorizationType':'ilink_bot_token','Authorization':'Bearer '+token,
                         'X-WECHAT-UIN':base64.b64encode(str(secrets.randbits(32)).encode()).decode()}
                response=client.post(wx_base(cfg.get('base_url') or WX_BASE)+'/ilink/bot/sendmessage',headers=headers,json=data).raise_for_status().json()
                codes=(response.get('ret',0),response.get('errcode',0))
                if all(v==0 for v in codes):break
                stale=-14 in codes or (-2 in codes and response.get('errmsg','').lower() in ('unknown error','prepare failed'))
                if not attempt and context and stale:
                    msg.pop('context_token',None);context=None;continue
                raise ValueError('Weixin did not accept message')

def pair_wecom(show):
    with httpx.Client(base_url='https://work.weixin.qq.com',timeout=15) as client:
        qr=client.get('/ai/qc/generate',params={'source':'hermes'}).raise_for_status().json()['data']
        show(qr['auth_url'])
        deadline=time.monotonic()+240
        while time.monotonic()<deadline:
            time.sleep(3)
            data=client.get('/ai/qc/query_result',params={'scode':qr['scode']}).raise_for_status().json()['data']
            if str(data.get('status')).lower()=='success':
                bot=data['bot_info']
                return {'account':bot.get('botid') or bot['bot_id'],'key':bot['secret'],'target':''}
    raise ValueError('pairing expired')

def connect_wecom(cfg,text=None):
    from websockets.sync.client import connect
    def request(ws,cmd,body):
        tag=uuid4().hex
        ws.send(json.dumps({'cmd':cmd,'headers':{'req_id':tag},'body':body}))
        deadline=time.monotonic()+12
        while time.monotonic()<deadline:
            reply=json.loads(ws.recv(timeout=max(.1,deadline-time.monotonic())))
            if reply.get('headers',{}).get('req_id')==tag:
                if reply.get('errcode',0)!=0:raise ValueError('WeCom declined request')
                return
        raise TimeoutError('WeCom acknowledgment')
    with connect('wss://openws.work.weixin.qq.com',open_timeout=10,close_timeout=2) as ws:
        request(ws,'aibot_subscribe',{'bot_id':cfg['account'],'secret':cfg['key'],'device_id':uuid4().hex})
        if text:
            for start in range(0,len(text),2000):
                request(ws,'aibot_send_msg',{'chatid':cfg['target'],'msgtype':'markdown','markdown':{'content':text[start:start+2000]}})
