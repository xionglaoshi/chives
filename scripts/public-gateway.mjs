import http from 'node:http';
import {promises as fs, createReadStream} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {join} from 'node:path';
import {homedir} from 'node:os';
import {randomBytes, scrypt, timingSafeEqual} from 'node:crypto';
import {promisify} from 'node:util';
import {createGzip} from 'node:zlib';
import {pipeline} from 'node:stream';
const root=fileURLToPath(new URL('../',import.meta.url));
const assets=join(root,'deploy/public');
const workbench={hostname:'127.0.0.1',port:8888};
const port=Number(process.env.CHIVES_PUBLIC_PORT ?? 25829);
const build=join(root,'runtime/public-dist');
const credentials=JSON.parse(await fs.readFile(process.env.CHIVES_ENTRY_CREDENTIALS ?? join(homedir(),'.agents/credentials/chives-public-entry.json'),'utf8'));
const salt=Buffer.from(credentials.salt,'hex'), digest=Buffer.from(credentials.digest,'hex');
if(salt.length!==16 || digest.length!==32) throw Error('Invalid gateway credentials');
const derive=promisify(scrypt);
const origin='https://150.158.11.154';
const sessionCookie='__Secure-chives';
const scope='; Path=/chives/; HttpOnly; Secure; SameSite=Strict';
const sessions=new Map(), attempts=new Map();
const types={html:'text/html; charset=utf-8',css:'text/css; charset=utf-8',js:'text/javascript; charset=utf-8',svg:'image/svg+xml',png:'image/png',jpg:'image/jpeg',jpeg:'image/jpeg',webp:'image/webp',woff2:'font/woff2',json:'application/json'};
const publicFiles=new Map(['login.css','chart.js','offline-reconnect.js'].map(name=>['/chives/entry/'+name,join(assets,name)]));

publicFiles.set('/chives/entry/logo.svg',join(root,'apps/web/public/chives.svg'));
const login=await fs.readFile(join(assets,'login.html'),'utf8');
const offlinePanel=await fs.readFile(join(assets,'offline-panel.html'),'utf8');
const loginPanel=await fs.readFile(join(assets,'login-panel.html'),'utf8');
const loginPolicy="default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'";
setInterval(()=>{
  const now=Date.now();
  for(const [k,t] of sessions) if(t<=now) sessions.delete(k);
  for(const [k,a] of attempts) if(a.expiry<=now) attempts.delete(k);
},60000).unref();
function finish(res,status,body=''){res.statusCode=status;res.end(body);}
function showLogin(res,status=200,message='',panel=loginPanel){
  res.setHeader('Content-Type',types.html);
  res.setHeader('Content-Security-Policy',loginPolicy);
  finish(res,status,login.replace('{{PANEL}}',panel).replace('{{ERROR}}',message));
}
async function streamFile(req,res,path,{compress=false}={}){
  let stat;
  try {stat=await fs.stat(path);} catch {return finish(res,404);}
  if(!stat.isFile())return finish(res,404);
  res.setHeader('Content-Type',types[path.split('.').pop()] ?? 'application/octet-stream');
  if(compress)res.setHeader('Vary','Accept-Encoding');
  const gzip=compress && /(?:^|,)\s*gzip\s*(?:;\s*q=(?:1(?:\.0+)?|0\.\d*[1-9]\d*))?\s*(?:,|$)/i.test(req.headers['accept-encoding']??'');
  if(gzip)res.setHeader('Content-Encoding','gzip');
  else res.setHeader('Content-Length',stat.size);
  if(req.method==='HEAD')return res.end();
  if(gzip)return pipeline(createReadStream(path),createGzip(),res,()=>{});
  const stream=createReadStream(path);
  stream.on('error',()=>res.destroy());res.on('close',()=>stream.destroy());stream.pipe(res);
}
async function workbenchOnline() {
  return new Promise(resolve => {
    const req=http.get({...workbench, path:'/api/health', headers:{host:'127.0.0.1:8888'}, signal:AbortSignal.timeout(3000)}, up => {
      let body='';
      up.setEncoding('utf8');
      up.on('data', chunk => {
        body+=chunk;
        if(body.length>1024) req.destroy(new Error('invalid health response'));
      });
      up.on('error', () => resolve(false));
      up.on('end', () => {
        try {resolve(up.statusCode===200 && JSON.parse(body).ok===true);}
        catch {resolve(false);}
      });
    });
    req.on('error', () => resolve(false));
  });
}
function api(req,res,path){
  const headers={host:'127.0.0.1:8888'};
  for(const name of ['accept','content-type','content-length','last-event-id','range','if-none-match',
    'x-chives-kernel-manager','sec-fetch-site','x-file-name']) {
    if(req.headers[name]) headers[name]=req.headers[name];
  }
  // The gateway authenticates the public session and validates the origin before proxying.
  if(req.headers.origin) headers.origin=req.headers.origin===origin?'http://127.0.0.1:8888':req.headers.origin;
  const remote=http.request({...workbench,method:req.method,path,headers},up=>{
    for(const key of ['content-type','content-disposition','content-length','content-range','etag']) {
      if(up.headers[key])res.setHeader(key,up.headers[key]);
    }
    // Files produced by a bot may contain HTML or SVG. Give them an opaque origin.
    res.setHeader('Content-Security-Policy',"sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:; frame-ancestors 'self'");
    res.writeHead(up.statusCode);res.flushHeaders();up.on('error',()=>res.destroy());up.pipe(res);
    res.on('close',()=>up.destroy());
  });
  remote.on('error',()=>res.headersSent?res.destroy():finish(res,503,'工作台暂时离线'));
  res.on('close',()=>remote.destroy());req.pipe(remote);
}
async function handle(req,res){
  res.setHeader('Cache-Control','no-store');res.setHeader('X-Content-Type-Options','nosniff');
  res.setHeader('Referrer-Policy','same-origin');
  const {pathname:p,search}=new URL(req.url,'http://localhost');
  const read=['GET','HEAD'].includes(req.method);
  if(p==='/chives' && read){res.setHeader('Location','/chives/');return finish(res,308);}
  if(!p.startsWith('/chives/'))return finish(res,404);
  if(!read && (req.headers.origin!==origin || req.headers['sec-fetch-site']==='cross-site'))return finish(res,403);
  if(read && p==='/chives/entry/csi300.json'){
    const [hasLegacy, hasUserData] = await Promise.all(
      ['data', 'user-data'].map(name => fs.stat(join(root, name)).then(stat => stat.isDirectory(), () => false)),
    );
    let cache = 'public-data/mechanical-cache';
    if (hasLegacy && !hasUserData) {
      const runtime = join(root, 'runtime');
      const batches = (await fs.readdir(runtime).catch(() => [])).filter(name => name.startsWith('data-migration-'));
      const receipts = await Promise.all(batches.map(name => fs.stat(join(runtime, name, 'active')).then(stat => stat.isFile(), () => false)));
      if (!receipts.some(Boolean)) cache = 'data';
    }
    return streamFile(req, res, join(root, cache, 'market/login-chart/csi300.json'));
  }
  if(read && publicFiles.has(p))return streamFile(req,res,publicFiles.get(p));
  const token=(req.headers.cookie??'').split(';').map(v=>v.trim()).find(v=>v.startsWith(sessionCookie+'='))?.slice(sessionCookie.length+1);
  if(p==='/chives/login' && req.method==='POST'){
    if(req.headers['content-type']?.split(';')[0] !== 'application/x-www-form-urlencoded')return finish(res,415);
    const ip=req.headers['x-chives-client']??'loopback';
    let attempt=attempts.get(ip);
    if(!attempt || attempt.expiry<=Date.now()){attempt={count:0,expiry:Date.now()+300000};attempts.set(ip,attempt);}
    if(attempt.count>=10){res.setHeader('Retry-After',Math.max(1,Math.ceil((attempt.expiry-Date.now())/1000)));return showLogin(res,429,'尝试次数过多，请稍后再试。');}
    let size=0,chunks=[];for await(const chunk of req){size+=chunk.length;if(size>4096)return finish(res,413);chunks.push(chunk);}
    const password=new URLSearchParams(Buffer.concat(chunks).toString()).get('password')??'';
    attempt.count++;
    if(!password || password.length>256 || !timingSafeEqual(await derive(password,salt,32),digest))return showLogin(res,401,'密码有误，请再试一次。');
    attempts.delete(ip);sessions.delete(token);
    const key=randomBytes(32).toString('base64url');
    sessions.set(key,Date.now()+12*3600000);res.setHeader('Set-Cookie',sessionCookie+'='+key+scope+'; Max-Age=43200');
    res.setHeader('Location','/chives/');return finish(res,303);
  }
  if(p==='/chives/logout' && req.method==='POST'){
    sessions.delete(token);res.setHeader('Set-Cookie',sessionCookie+'='+scope+'; Max-Age=0');res.setHeader('Location','/chives/');return finish(res,303);
  }
  if(!(sessions.get(token)>Date.now()))return p==='/chives/' && read?showLogin(res):finish(res,401);
  if(p.startsWith('/chives/api/')){
    const portrait=read && /^\/chives\/api\/internal\/style-portraits\/[a-z0-9-]+\.jpg$/.test(p);
    if(p.startsWith('/chives/api/internal/') && !portrait)return finish(res,403);
    return api(req,res,p.slice('/chives'.length)+search);
  }
  if(!read)return finish(res,405);
  res.setHeader('Content-Security-Policy',"frame-ancestors 'none'; base-uri 'self'; object-src 'none'");
  if(p==='/chives/'){
    if(!await workbenchOnline()){
      res.setHeader('Retry-After','10');
      return showLogin(res,503,'',offlinePanel);
    }
    return streamFile(req,res,join(build,'index.html'));
  }
  if(p==='/chives/market-news.json'){
    const news = join(root,'public-data/mechanical-cache/market/market-news.json');
    const path = await fs.access(news).then(()=>news,()=>join(root,'apps/web/public/market-news.json'));
    return streamFile(req,res,path,{compress:true});
  }
  if(p==='/chives/holdings-securities.json')
    return streamFile(req,res,join(root,'apps/web/public/holdings-securities.json'),{compress:true});
  if(p==='/chives/chives.svg')return streamFile(req,res,join(build,'chives.svg'));
  if(/^\/chives\/assets\/[\w.-]+\.(?:js|css|svg|png|jpe?g|webp|woff2)$/.test(p))return streamFile(req,res,join(build,p.slice('/chives/'.length)));
  return finish(res,404);
}
http.createServer((req,res)=>handle(req,res).catch(()=>res.headersSent?res.destroy():finish(res,500))).listen(port,'127.0.0.1');
