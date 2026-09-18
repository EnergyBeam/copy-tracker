"""Pump.fun discovery from GMGN new_creation; bounded polling, not a full stream."""
import json,time
from datetime import datetime,timezone
from gmgn_scan import unwrap,num
from gmgn_api import GMGNError


def eligible(token,now):
    created=num(token.get('created_timestamp'))
    return (token.get('launchpad_platform')=='Pump.fun' and token.get('chain')=='sol'
            and not token.get('offchain') and created is not None and 0<=now-float(created)<=900
            and (num(token.get('buys_24h')) or 0)>=3)


def scan_pump(db,client):
    db.execute('CREATE TABLE IF NOT EXISTS pump_tokens(address TEXT PRIMARY KEY,created_at REAL,first_seen REAL,last_checked REAL,payload TEXT)');db.commit()
    data=unwrap(client.trenches())
    if not isinstance(data,dict) or not isinstance(data.get('new_creation'),list):raise GMGNError('Unexpected trenches schema')
    now=time.time();ts=datetime.now(timezone.utc).isoformat()
    choices=[]
    with db:
        for t in data['new_creation']:
            if not eligible(t,now):continue
            address=t['address'];old=db.execute('SELECT last_checked FROM pump_tokens WHERE address=?',(address,)).fetchone()
            db.execute('INSERT INTO pump_tokens VALUES(?,?,?,?,?) ON CONFLICT(address) DO UPDATE SET payload=excluded.payload',
                       (address,t['created_timestamp'],now,0,json.dumps({k:v for k,v in t.items() if k!='logo_small_base64'})))
            if old is None or old['last_checked']==0:choices.append(t)
    # Prioritize most active fresh launches, not profits of already famous wallets.
    choices.sort(key=lambda t:-(num(t.get('buys_24h')) or 0))
    found=set();checked=0
    for t in choices[:2]:
        payload=unwrap(client.get('traders',chain='sol',address=t['address'],limit=30,order_by='buy_volume_cur',direction='desc'))
        if not isinstance(payload,dict) or not isinstance(payload.get('list'),list):raise GMGNError('Unexpected traders schema')
        with db:
            for r in payload['list']:
                wallet=r.get('address')
                if not wallet or r.get('exchange') or wallet==t.get('creator') or (num(r.get('buy_tx_count_cur')) or 0)<=0:continue
                entry=num(r.get('start_holding_at'));created=num(t['created_timestamp'])
                lag=float(entry-created) if entry is not None and 0<=entry-created<=900 else None
                enriched={**r,'token_address':t['address'],'token_symbol':t.get('symbol'),'token_liquidity':t.get('liquidity'),
                          'observed_at':ts,'source':'pumpfun_new_creation','token_created_at':t['created_timestamp'],
                          'token_age_at_observation_seconds':round(time.time()-float(created)),
                          'holding_start_lag_seconds':lag,'entry_timing_verified':False}
                db.execute('INSERT INTO gmgn_observations VALUES(?,?,?,?) ON CONFLICT(wallet,token) DO UPDATE SET observed_at=excluded.observed_at,payload=excluded.payload',
                           (wallet,t['address'],ts,json.dumps(enriched)))
                db.execute('INSERT OR IGNORE INTO wallets(chain,address,role,source) VALUES(?,?,?,?)',('solana',wallet,'Pump.fun discovery','GMGN Trenches'))
                db.execute('INSERT OR IGNORE INTO gmgn_candidates VALUES(?,?,?,?,?)',(wallet,ts,ts,'pending_profile',json.dumps({'wallet':wallet,'source':'pumpfun_new_creation','copy_eligible':False})))
                found.add(wallet)
            db.execute('UPDATE pump_tokens SET last_checked=? WHERE address=?',(time.time(),t['address']))
        checked+=1
    return {'listed':len(data['new_creation']),'tokens_checked':checked,'wallets_found':len(found)}
