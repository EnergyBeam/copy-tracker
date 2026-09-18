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


def fetch_history(client,wallet):
    from gmgn_scan import unwrap
    from gmgn_api import GMGNError
    items=[];cursor=None;seen=set();complete=False
    for _ in range(3):
        params={'chain':'sol','wallet_address':wallet,'limit':100}
        if cursor:params['cursor']=cursor
        data=unwrap(client.get('activity',**params))
        if not isinstance(data,dict) or not isinstance(data.get('activities'),list):raise GMGNError('Unexpected activity schema')
        items.extend(data['activities']);cursor=data.get('next')
        if not cursor:complete=True;break
        if cursor in seen:break
        seen.add(cursor)
    return closed_metrics(items,complete)
