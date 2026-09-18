"""Metrics on completely closed positions in a bounded GMGN activity sample."""
from collections import defaultdict
from decimal import Decimal
from statistics import median
from gmgn_scan import num


def closed_metrics(activities,complete=False):
    tokens=defaultdict(list)
    seen=set()
    for r in activities:
        token=(r.get('token') or {}).get('address')
        if not token:continue
        identity=(r.get('tx_hash'),r.get('event_type'),token,str(r.get('token_amount')),r.get('timestamp'))
        if identity in seen:continue
        seen.add(identity);tokens[token].append(r)
    multiples=[];holds=[];excluded=[];profits={}
    for token,rows in tokens.items():
        rows.sort(key=lambda r:(r.get('timestamp',0),r.get('tx_hash','')))
        qty=Decimal(0);spent=Decimal(0);income=Decimal(0);start=None;local=[];bad=False
        stamps={}
        for r in rows:
            t=r.get('timestamp');tx=r.get('tx_hash')
            if t in stamps and stamps[t]!=tx:bad=True
            stamps[t]=tx
            if r.get('event_type') not in ('buy','sell'):bad=True;break
            q=num(r.get('token_amount'));price=num(r.get('price_usd'))
            gas=num(r.get('gas_usd'));dex=num(r.get('dex_usd'))
            if any(v is None for v in (q,price,gas,dex)) or q<=0 or price<=0 or gas<0 or dex<0:bad=True;break
            if r['event_type']=='buy':
                if qty==0:start=t;spent=Decimal(0);income=Decimal(0)
                qty+=q;spent+=q*price+gas+dex
            else:
                if q>qty:bad=True;break
                qty-=q;income+=q*price-gas-dex
                if qty==0 and spent>0:
                    local.append((income/spent,t-start,income-spent))
        if bad:excluded.append(token);continue
        for multiple,hold,profit in local:multiples.append(multiple);holds.append(hold)
        if local:profits[token]=sum(x[2] for x in local)
    return {'profitable_token_addresses':sorted(t for t,p in profits.items() if p>0),'closed_token_pnl':{t:str(p) for t,p in profits.items()},'closed_cycles':len(multiples),'mean_multiple':str(sum(multiples)/len(multiples)) if multiples else None,
            'median_multiple':str(median(multiples)) if multiples else None,
            'median_hold_seconds':median(holds) if holds else None,'excluded_tokens':len(excluded),
            'history_complete':complete,'activity_records':len(seen),'basis':'closed position proceeds / acquisition cost; gas_usd + dex_usd; bounded sample'}


def event_key(row):
    import hashlib,json
    # Match the metric dedup identity; avoid counting repeated pages as trades.
    fields=(row.get('tx_hash'),row.get('event_type'),(row.get('token') or {}).get('address'),str(row.get('token_amount')),row.get('timestamp'))
    return hashlib.sha256(json.dumps(fields,sort_keys=True).encode()).hexdigest()


def fetch_history(client,wallet,db=None):
    import json
    from datetime import datetime,timezone
    from gmgn_scan import unwrap
    from gmgn_api import GMGNError
    saved_cursor=None
    if db is not None:
        db.execute('CREATE TABLE IF NOT EXISTS wallet_history_cursor(wallet TEXT PRIMARY KEY,cursor TEXT)')
        old=db.execute('SELECT cursor FROM wallet_history_cursor WHERE wallet=?',(wallet,)).fetchone()
        saved_cursor=old[0] if old else None
        db.execute('CREATE TABLE IF NOT EXISTS wallet_activity_cache(wallet TEXT,event_key TEXT,payload TEXT,PRIMARY KEY(wallet,event_key))')
        db.commit()
    items=[];cursor=None;seen=set();pages=set();stop='page_limit';count=0
    for _ in range(3):
        params={'chain':'sol','wallet_address':wallet,'limit':100}
        if cursor:params['cursor']=cursor
        data=unwrap(client.get('activity',**params))
        if not isinstance(data,dict) or not isinstance(data.get('activities'),list):raise GMGNError('Unexpected activity schema')
        rows=data['activities'];count+=1
        fingerprint=tuple(sorted(event_key(r) for r in rows))
        if rows and fingerprint in pages:stop='repeated_page';break
        pages.add(fingerprint);items.extend(rows)
        # Commit each successful page: later network failures do not lose it.
        if db is not None:
            with db:
                for r in rows:
                    db.execute('INSERT INTO wallet_activity_cache VALUES(?,?,?) ON CONFLICT(wallet,event_key) DO UPDATE SET payload=excluded.payload',(wallet,event_key(r),json.dumps(r)))
        cursor=data.get('next')
        if count==1 and saved_cursor:
            cursor=saved_cursor
        if db is not None:
            with db:db.execute('INSERT INTO wallet_history_cursor VALUES(?,?) ON CONFLICT(wallet) DO UPDATE SET cursor=excluded.cursor',(wallet,cursor))
        if not cursor:stop='provider_exhausted';break
        if cursor in seen:stop='repeated_cursor';break
        seen.add(cursor)
    downloaded=len({event_key(r) for r in items})
    if db is not None:
        items=[json.loads(r[0]) for r in db.execute('SELECT payload FROM wallet_activity_cache WHERE wallet=?',(wallet,))]
    metrics=closed_metrics(items,False)
    times=[r['timestamp'] for r in items if isinstance(r.get('timestamp'),(int,float))]
    metrics.update(history_fetched_at=datetime.now(timezone.utc).isoformat(),history_storage='sqlite' if db is not None else 'request',pages_fetched=count,downloaded_records=downloaded,pagination_stop=stop,provider_exhausted=stop=='provider_exhausted',oldest_event_at=min(times) if times else None,newest_event_at=max(times) if times else None)
    return metrics
