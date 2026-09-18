"""FIFO profiling of imported swaps. USD amounts remain Decimal strings."""
from collections import defaultdict, deque
from datetime import datetime, timezone, timedelta
from decimal import Decimal, localcontext
from statistics import median


def utc(text):
    value = datetime.fromisoformat(text.replace('Z', '+00:00'))
    if value.tzinfo is None:
        raise ValueError('Timezone required')
    return value.astimezone(timezone.utc)


def calculate(db, chain, address, as_of=None):
    # Fixed precision independent of the caller's Decimal context.
    with localcontext() as context:
        context.prec = 50
        return _calculate(db, chain, address, as_of)


def _calculate(db, chain, address, as_of):
    now = utc(as_of) if as_of else datetime.now(timezone.utc)
    if chain == 'robinhood':
        address = address.lower()
    wallet = db.execute('SELECT * FROM wallets WHERE chain=? AND address=?', (chain,address)).fetchone()
    if wallet is None:
        raise ValueError('Wallet not found')
    rows = [dict(r) for r in db.execute('SELECT * FROM events WHERE chain=? AND wallet=? ORDER BY ts,tx_id,event_index', (chain,address))]
    rows = [r for r in rows if utc(r['ts']) <= now]
    inventory = defaultdict(deque)
    cycle = {}
    closed, realized, issues = [], [], []
    timestamps = defaultdict(set)
    for r in rows:
        timestamps[(r['token'],r['ts'])].add(r['tx_id'])
    if any(len(txs)>1 for txs in timestamps.values()):
        issues.append('AMBIGUOUS_SAME_TIMESTAMP_ORDER')
    for r in rows:
        token, ts = r['token'], utc(r['ts'])
        quantity, price, fee = (Decimal(r[k]) for k in ('quantity','price_usd','fee_usd'))
        if r['side'] == 'BUY':
            if not inventory[token]:
                cycle[token] = {'start':ts,'pnl':Decimal(0),'cost':Decimal(0)}
            cost = quantity*price+fee
            inventory[token].append({'quantity':quantity,'cost':cost,'ts':ts})
            cycle[token]['cost'] += cost
            continue
        remaining, event_pnl, known = quantity, Decimal(0), Decimal(0)
        while remaining and inventory[token]:
            lot = inventory[token][0]
            matched = min(remaining,lot['quantity'])
            # Allocate remaining cost, avoiding cost loss after partial sales.
            cost = lot['cost'] if matched == lot['quantity'] else lot['cost']*matched/lot['quantity']
            pnl = matched*price-fee*matched/quantity-cost
            event_pnl += pnl
            known += matched
            lot['quantity'] -= matched
            lot['cost'] -= cost
            remaining -= matched
            if lot['quantity'] == 0:
                inventory[token].popleft()
        if known:
            realized.append({'token':token,'ts':ts,'pnl':event_pnl})
            cycle[token]['pnl'] += event_pnl
        if remaining:
            issues.append('UNKNOWN_INVENTORY')
        if not inventory[token] and token in cycle:
            c = cycle.pop(token)
            if not remaining:
                closed.append({'token':token,'ts':ts,'pnl':c['pnl'],'hold':(ts-c['start']).total_seconds(),'cost':c['cost']})
    windows = {}
    for days in (7,30,90):
        since = now-timedelta(days=days)
        sales = [r for r in realized if r['ts']>=since]
        cycles = [c for c in closed if c['ts']>=since]
        gains = sum((c['pnl'] for c in cycles if c['pnl']>0),Decimal(0))
        losses = -sum((c['pnl'] for c in cycles if c['pnl']<0),Decimal(0))
        net = sum((c['pnl'] for c in cycles),Decimal(0))
        by_token = defaultdict(Decimal)
        for sale in sales:
            by_token[sale['token']] += sale['pnl']
        positive = [v for v in by_token.values() if v>0]
        windows[str(days)] = {
            'known_realized_pnl_usd':str(sum((r['pnl'] for r in sales),Decimal(0))),
            'closed_cycles':len(cycles),
            'realized_by_token_usd':{k:str(v) for k,v in by_token.items()},
            'win_rate_pct':100*sum(c['pnl']>0 for c in cycles)/len(cycles) if cycles else None,
            'expectancy_usd':str(net/len(cycles)) if cycles else None,
            'profit_factor':str(gains/losses) if losses else None,
            'profit_factor_status':'defined' if losses else ('no_losses' if cycles else 'no_cycles'),
            'median_hold_seconds':median(c['hold'] for c in cycles) if cycles else None,
            'top1_profit_pct':float(max(positive)/sum(positive)*100) if positive else None,
        }
    flags = ['HISTORY_NOT_VERIFIED']+sorted(set(issues))
    e7,e30 = (windows[k]['expectancy_usd'] for k in ('7','30'))
    if e7 is not None and e30 is not None and Decimal(e7)<0 and Decimal(e7)<Decimal(e30):
        flags.append('EXPECTANCY_DECAY')
    from tracker import screen
    w = windows['30']
    metrics = {k:w[k] for k in ('closed_cycles','median_hold_seconds','top1_profit_pct')}
    metrics['history_verified'] = False
    assessment = screen(metrics)
    assessment['reasons'] = sorted(set(assessment['reasons']+flags))
    return {
        'chain':chain,'address':address,'as_of':now.isoformat(),
        'source':wallet['source'],'event_count':len(rows),
        'last_active':rows[-1]['ts'] if rows else None,
        'data_quality':flags,'windows':windows,'assessment':assessment,
        'open_positions':[{'token':token,'known_quantity':str(sum((l['quantity'] for l in lots),Decimal(0))),
                           'remaining_cost_usd':str(sum((l['cost'] for l in lots),Decimal(0))),
                           'unrealized_pnl_usd':None} for token,lots in inventory.items() if lots],
        'follower_pnl_usd':None,
    }
