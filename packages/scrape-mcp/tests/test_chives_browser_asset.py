"""Exercise the expert MCP service, against a temporary research page."""
import json
import os
from pathlib import Path
import subprocess
import sys

from scrape_mcp.private_browser import RUNTIME, browser_api, chromium_binary

ROOT = Path(__file__).resolve().parents[3]


def test_private_paths_override_other_installations(monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path / "unrelated-browser"))
    monkeypatch.setenv("PLAYWRIGHT_NODEJS_PATH", str(tmp_path / "unrelated-node"))
    api = browser_api()
    assert Path(api.__file__).resolve().is_relative_to(RUNTIME / "python")
    with api.sync_playwright() as driver:
        binary = chromium_binary(driver.chromium)
        assert Path(binary).is_relative_to(RUNTIME / "browsers")
        browser = driver.chromium.launch(executable_path=binary, chromium_sandbox=True)
        try:
            processes = subprocess.check_output(["ps", "-axo", "command="], text=True)
            assert binary + " --" in processes
            assert os.environ["PLAYWRIGHT_NODEJS_PATH"] + " " in processes
        finally:
            browser.close()


def test_expert_tool_actions_and_permissions(tmp_path):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    class ResearchPage(BaseHTTPRequestHandler):
        def do_GET(self):
            data = b'User-agent: *\nAllow: /' if self.path == '/robots.txt' else b'''<title>Research</title>
              <input id="code"><select id="year"><option>2024</option><option>2025</option></select>
              <button id="query" onclick="setTimeout(()=>document.querySelector('output').textContent=document.querySelector('input').value+'-'+document.querySelector('select').value,100)">Query</button><output></output>'''
            self.send_response(200)
            self.send_header('Content-Type','text/plain' if self.path=='/robots.txt' else 'text/html')
            self.end_headers()
            self.wfile.write(data)
        def log_message(self,*args):
            pass
    bot_dir = tmp_path / 'bots/qa/profile'
    bot_dir.mkdir(parents=True)
    profile = bot_dir / 'resources.json'
    import asyncio
    sys.path.insert(0,str(ROOT/'scripts'))
    from research_bridge import ResearchBridge
    def call(tool='', arguments=None, write=True):
        bridge=ResearchBridge([{'name':'bot_assets','command':sys.executable,
            'args':[str(ROOT/'scripts/bot-assets.py'),str(tmp_path),'qa'],
            'env':[{'name':'SCRAPE_TEST_ALLOW_LOOPBACK','value':'1'},
                   {'name':'CHIVES_ASSET_POLICY','value':json.dumps({'workspaceWrite':write})}]}])
        async def invoke():
            async with bridge.connect('bot_assets') as session:
                if not tool:return [t.name for t in (await session.list_tools()).tools]
                return (await session.call_tool(tool,arguments or {})).model_dump(exclude_none=True)
        return asyncio.run(invoke())
    httpd=ThreadingHTTPServer(('127.0.0.1',0),ResearchPage)
    thread=Thread(target=httpd.serve_forever,daemon=True)
    thread.start()
    try:
        profile.write_text('{"tools":[]}')
        assert 'browser_research' not in call()
        profile.write_text('{"tools":["browser_research"]}')
        assert 'browser_research' in call()
        url=f'http://127.0.0.1:{httpd.server_port}/'
        args={'url':url,'screenshot':True,'steps':[
            {'action':'fill','selector':'#code','value':'688588'},
            {'action':'select','selector':'#year','value':'2025'},
            {'action':'click','selector':'#query'},
            {'action':'wait','selector':'text=688588-2025'},
            {'action':'read','selector':'output'}]}
        result=call('browser_research',args)
        assert not result.get('isError'),result
        data=result.get('structuredContent') or json.loads(result['content'][0]['text'])
        assert data['url']==url and data['title']=='Research'
        assert data['readings'][0]['text']=='688588-2025'
        image=tmp_path/'bots/qa/workspace'/data['screenshot']
        assert image.read_bytes().startswith(b'\x89PNG')
        assert call('browser_research',args,write=False)['isError']
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()
