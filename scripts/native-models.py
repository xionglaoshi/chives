"""Ask the signed-in Chives CLI for its catalog or a minimal inference."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def run():
    binary, provider, action, model = sys.argv[1:]
    with tempfile.TemporaryDirectory() as working:
        if provider == 'codex':
            if action == 'discover':
                args = ['debug', 'models']
            else:
                args = ['-c','features.shell_tool=false','-c','features.unified_exec=false',
                        'exec','--ephemeral','--skip-git-repo-check','--sandbox','read-only']
                if model: args += ['--model',model]
                args += ['Reply with the single word OK. Do not use tools.']
            payload = None
        else:
            args = ['-p','--tools','','--no-session-persistence','--strict-mcp-config',
                    '--mcp-config','{"mcpServers":{}}']
            if action == 'discover':
                args += ['--verbose','--input-format','stream-json','--output-format','stream-json']
                payload = json.dumps({'type':'control_request','request_id':'chives','request':{'subtype':'initialize'}})+'\n'
            else:
                args += ['--output-format','json']
                if model and model != 'default': args += ['--model',model]
                payload = 'Reply with the single word OK.'
        result = subprocess.run([binary,*args],input=payload or '',capture_output=True,text=True,
                                cwd=working,timeout=60,check=True)
        if action == 'probe':
            value=json.loads(result.stdout)['result'] if provider=='claude' else result.stdout
            if 'OK' not in value.upper():raise ValueError('no reply')
            return {'message':'所选模型已完成最小推理请求'}
        if provider=='codex':
            raw=json.loads(result.stdout)
            ids=[entry['slug'] for entry in raw['models'] if entry.get('visibility')!='hide']
        else:
            data=next(x['response']['response'] for x in map(json.loads,result.stdout.splitlines()) if x.get('type')=='control_response')
            ids=[entry['value'] for entry in data['models']]
        if not ids:raise ValueError('no models')
        return {'models':ids,'message':'已读取官方 CLI 返回的模型清单，验证可确认当前账号的使用权限'}


if __name__=='__main__':
    try: print(json.dumps(run(),ensure_ascii=False))
    except Exception: sys.exit(1)
