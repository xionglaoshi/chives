"""Disk-backed, allowlisted distribution routes; one writer per upstream object."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time
from urllib.parse import unquote, quote

CACHE = Path('/var/lib/chives-install/assets')
TENCENT = 'https://mirrors.cloud.tencent.com'
PROXY = 'http://127.0.0.1:17897'
SLOTS = threading.BoundedSemaphore(10)
TARGET = r'(?:aarch64|x86_64)-(?:apple-darwin|unknown-linux-(?:gnu|musl)|pc-windows-msvc)'
UV = rf'uv/[0-9]+\.[0-9]+\.[0-9]+/uv-{TARGET}\.(?:tar\.gz|zip)(?:\.sha256)?'
PYTHON = r'python/[0-9]{8}/cpython-3\.12\.[0-9]+\+[0-9]{8}-[A-Za-z0-9_.-]+\.tar\.(?:gz|zst)'
SAFE = r'[a-zA-Z0-9_.+@~/-]+'
RULES = [
    (r'uv-version', 'https://api.github.com/repos/astral-sh/uv/releases/latest', 180),
    (UV, 'https://github.com/astral-sh/uv/releases/download/', 0),
    (PYTHON, 'https://github.com/astral-sh/python-build-standalone/releases/download/', 0),
    (r'node/v[0-9.]+/(?:SHASUMS256.txt|node-v[0-9.]+-(?:darwin|linux|win)-(?:arm64|x64)\.(?:tar\.gz|zip))', TENCENT+'/nodejs-release/', 0),
    (r'pypi/simple/[a-zA-Z0-9_.-]+/?', TENCENT+'/pypi/', 60),
    (r'pypi/packages/'+SAFE, TENCENT+'/pypi/', 0),
    (r'npm/(?:@[\w.-]+/)?[\w.-]+/?', 'https://registry.npmjs.org/', 600),
    (r'npm/(?:@[\w.-]+/)?[\w.-]+/-/[\w.+-]+\.tgz', 'https://registry.npmjs.org/', 0),
    (r'browser/builds/'+SAFE+r'\.zip', 'https://cdn.playwright.dev/', 0),
    (r'apt/(?:debian|debian-security|ubuntu|ubuntu-ports)/(?:pool|dists)/'+SAFE, TENCENT+'/', 120),
]

def route(raw):
    path = unquote(raw)
    if len(path) > 520 or any(x in {'.', '..'} for x in path.split('/')) or '//' in path:
        raise ValueError('非法资源路径')
    for regex, base, ttl in RULES:
        if re.fullmatch(regex, path):
            suffix = path.partition('/')[2]
            if path.startswith('npm/@') and '/-/' not in path:
                suffix = suffix.replace('/', '%2f')
            url = base + quote(suffix, safe='/@%+.-~')
            if path.startswith('apt/') and ('/pool/' in path or '/by-hash/' in path):
                ttl = 0
            return path, url, ttl
    raise ValueError('不支持此资源')

def cached(raw):
    path, url, ttl = route(raw)
    key = hashlib.sha256(url.encode()).hexdigest()
    folder = CACHE / key[:2]
    folder.mkdir(parents=True, exist_ok=True)
    file = folder / key
    with file.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if file.exists() and (not ttl or time.time()-file.stat().st_mtime < ttl):
            return file, 'hit'
        with SLOTS, tempfile.NamedTemporaryFile(dir=folder, delete=False) as temp:
            temp.close()
            try:
                if shutil.disk_usage(folder).free < 2 * 1024**3:
                    raise OSError('缓存盘可用空间不足')
                cmd = ['curl','-q','-fsSL','--proto','=https','--proto-redir','=https','--retry','2',
                       '--connect-timeout','12','--max-time','480','--max-filesize','1073741824',
                       '--noproxy', '*' if url.startswith(TENCENT+'/') else '',
                       '--proxy', '' if url.startswith(TENCENT+'/') else PROXY,
                       '--output',temp.name,'--write-out','%{http_code}',url]
                if path.startswith('npm/') and '/-/' not in path:
                    cmd[2:2] = ['-H', 'Accept: application/vnd.npm.install-v1+json']
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode:
                    if result.stdout in {'404','410'}:
                        raise FileNotFoundError(path)
                    raise OSError(f'上游下载失败 HTTP {result.stdout}')
                if path == 'uv-version':
                    version = json.loads(Path(temp.name).read_bytes())['tag_name']
                    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
                        raise ValueError('无效 uv 版本')
                    Path(temp.name).write_text(version)
                os.replace(temp.name, file)
                file.with_suffix('.asset').write_text(path+'\n',encoding='utf-8')
            finally:
                Path(temp.name).unlink(missing_ok=True)
    return file, 'fill'

def serve(handler, raw, head=False):
    try:
        file, status = cached(raw)
    except ValueError:
        return handler.reply(404,b'Unsupported asset')
    except FileNotFoundError:
        return handler.reply(404,b'Upstream asset not found')
    except (OSError, KeyError, subprocess.SubprocessError):
        return handler.reply(502,b'Asset cache could not fetch upstream')
    with file.open('rb') as source:
        if not handler.enabled():
            return handler.reply(503,'安装分发已停用'.encode())
        size = os.fstat(source.fileno()).st_size
        first, end = 0, size
        partial = None
        if raw.startswith("pypi/packages/"):
            partial = re.fullmatch(r"bytes=(\d*)-(\d*)",handler.headers.get("Range",""))
        if partial:
            left,right = partial.groups()
            if left:
                first = int(left)
                if right:
                    end = min(end,int(right)+1)
            elif right:
                first = max(0,size-int(right))
            if not (left or right) or not 0 <= first < end:
                handler.send_response(416)
                handler.send_header("Content-Range",f"bytes */{size}")
                handler.end_headers()
                return
        handler.send_response(206 if partial else 200)
        if raw.startswith("pypi/packages/"):
            handler.send_header("Accept-Ranges","bytes")
        if partial:
            handler.send_header("Content-Range",f"bytes {first}-{end-1}/{size}")
        kind = ('text/html' if raw.startswith('pypi/simple/') else
                'application/json' if raw.startswith('npm/') and '/-/' not in raw else 'application/octet-stream')
        handler.send_header('Content-Type',kind)
        handler.send_header('X-Chives-Cache',status)
        handler.send_header('Content-Length',str(end-first))
        handler.end_headers()
        if not head:
            source.seek(first)
            remaining = end-first
            while remaining:
                block = source.read(min(remaining,256*1024))
                if not block:
                    break
                handler.wfile.write(block)
                remaining -= len(block)
