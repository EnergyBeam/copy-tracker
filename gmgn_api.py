"""Read-only official GMGN OpenAPI; protocol verified against gmgn-cli 1.6.2."""
import json, os, time, uuid, sqlite3, socket, ssl
from pathlib import Path
from contextlib import closing
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError

ROOT=Path(__file__).resolve().parent
ROUTES={'trending':'/v1/market/rank','traders':'/v1/market/token_top_traders',
        'stats':'/v1/user/wallet_stats','activity':'/v1/user/wallet_activity',
        'security':'/v1/token/security','trenches':'/v1/trenches'}

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None

class GMGNError(RuntimeError): pass
class RateLimited(GMGNError): pass

def network_reason(error):
    reason=error.reason if isinstance(error,URLError) else error
    if isinstance(reason,socket.gaierror):kind='dns'
    elif isinstance(reason,ssl.SSLCertVerificationError):kind='certificate'
    elif isinstance(reason,ssl.SSLError):kind='tls'
    elif isinstance(reason,TimeoutError):kind='timeout'
    elif isinstance(reason,ConnectionError):kind='connection'
    else:kind='transport'
    code=getattr(reason,'winerror',None) or getattr(reason,'errno',None)
    return 'GMGN network '+kind+(' errno='+str(code) if isinstance(code,int) else '')


def read_key():
    value=os.environ.get('GMGN_API_KEY','').strip()
    if not value:
        p=ROOT/'.env'
        if p.exists():
            for line in p.read_text(encoding='utf-8-sig').splitlines():
                k,sep,v=line.partition('=')
                if sep and k.strip()=='GMGN_API_KEY': value=v.strip().strip('\"').strip("'")
    if not value: raise GMGNError('GMGN_API_KEY is missing in local .env')
    return value

class Pacer:
    """Serialize request starts across tracker processes; default 10 requests/minute."""
    def __init__(self,path=None,interval=6):
        self.path=path or ROOT/'gmgn-rate.sqlite3'
        self.interval=interval
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS pace(id INTEGER PRIMARY KEY,next_at REAL)')
            db.execute('INSERT OR IGNORE INTO pace VALUES(1,0)')
    def wait(self):
        while True:
            with closing(sqlite3.connect(self.path,timeout=10)) as db, db:
                db.execute('BEGIN IMMEDIATE')
                deadline=db.execute('SELECT next_at FROM pace WHERE id=1').fetchone()[0]
                now=time.time()
                if deadline<=now:
                    db.execute('UPDATE pace SET next_at=? WHERE id=1',(now+self.interval,))
                    return
            time.sleep(min(deadline-now,1))
    def cooldown(self,until):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE pace SET next_at=MAX(next_at,?) WHERE id=1',(until,))

class Client:
    def __init__(self):
        self.key=read_key()
        self.opener=build_opener(NoRedirect())
        self.pacer=Pacer()
        self.request_count=0
        self.rate_limit_count=0
    def get(self,route,**params):
        return self._request(route,params,None)
    def trenches(self):
        section={"filters":["offchain","onchain"],"launchpad_platform_v2":True,"launchpad_platform":["Pump.fun"],"limit":80}
        return self._request("trenches",{"chain":"sol"},{"version":"v2","new_creation":section})
    def _request(self,route,params,body):
        if route not in ROUTES: raise ValueError('Route not permitted')
        for attempt in range(3):
            self.pacer.wait()
            self.request_count+=1
            q={**params,'timestamp':int(time.time()),'client_id':str(uuid.uuid4())}
            request=Request('https://openapi.gmgn.ai'+ROUTES[route]+'?'+urlencode(q,doseq=True),
                            data=json.dumps(body).encode() if body is not None else None,
                            headers={'X-APIKEY':self.key,'User-Agent':'wallet-tracker/0.1','Accept':'application/json','Content-Type':'application/json'})
            try:
                with self.opener.open(request,timeout=20) as response: payload=json.load(response)
            except HTTPError as e:
                if e.code==429:
                    self.rate_limit_count+=1
                    try: info=json.load(e)
                    except (ValueError,TypeError): info={}
                    try: reset=float(info.get('reset_at') or e.headers.get('X-RateLimit-Reset') or 0)
                    except (ValueError,TypeError): reset=0
                    try: retry=float(e.headers.get('Retry-After') or 0)
                    except (ValueError,TypeError): retry=0
                    until=max(reset+2,time.time()+retry+2,time.time()+60 if not reset and not retry else 0)
                    self.pacer.cooldown(until)
                    safe={'status':429,'reset_at':until,'route':route}
                    (ROOT/'gmgn-limit.json').write_text(json.dumps(safe),encoding='utf-8')
                    raise RateLimited('GMGN rate limit; retry after '+str(int(until))) from None
                if e.code in (500,502,503,504) and attempt<2:
                    time.sleep(1+attempt*2); continue
                raise GMGNError('GMGN HTTP '+str(e.code)) from None
            except (URLError,TimeoutError,OSError) as e:
                # Re-read OS proxy settings after network/VPN changes.
                self.opener=build_opener(NoRedirect())
                if attempt<2:
                    time.sleep(1+attempt*2);continue
                raise GMGNError(network_reason(e)) from None
            except (ValueError,TypeError):
                raise GMGNError('GMGN returned invalid JSON') from None
            if not isinstance(payload,dict) or payload.get('code')!=0:
                code=payload.get('code') if isinstance(payload,dict) else None
                raise GMGNError('GMGN API rejected request; code='+str(code)[:30])
            return payload.get('data')

def snapshot(label,data):
    folder=ROOT/'gmgn-snapshots'; folder.mkdir(exist_ok=True)
    p=folder/(str(time.time_ns())+'-'+label+'.json')
    p.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    return p

if __name__=='__main__':
    try:
        data=Client().get('trending',chain='sol',interval='1h',limit=3)
        p=snapshot('connection-test',data)
        print(json.dumps({'connected':True,'snapshot':p.name,'type':type(data).__name__,'fields':list(data)[:15] if isinstance(data,dict) else None}))
    except GMGNError as e: raise SystemExit(str(e))
