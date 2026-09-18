"""Discover previously unknown wallets from a market-wide normalized event feed."""
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import json
from profiler import calculate, utc


def schema(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS candidates(chain TEXT,address TEXT,first_detected TEXT,last_evaluated TEXT,state TEXT,evidence TEXT,PRIMARY KEY(chain,address));
    CREATE TABLE IF NOT EXISTS candidate_changes(id INTEGER PRIMARY KEY,chain TEXT,address TEXT,ts TEXT,old_state TEXT,new_state TEXT,evidence TEXT);
    CREATE TABLE IF NOT EXISTS candidate_signals(chain TEXT,tx_id TEXT,event_index INTEGER,wallet TEXT,ts TEXT,side TEXT,token TEXT,candidate_state TEXT,PRIMARY KEY(chain,tx_id,event_index));
    ''')


def discover(db, as_of=None, lookback_days=30, early_minutes=30, min_multiple=2, min_hits=2):
    """Ranks opportunities for investigation, never authorizes copying.

    Early means relative to first BUY in this dataset, not token creation.
    Price multiple is observed trade price, not executable follower return.
    """
    if lookback_days<=0 or early_minutes<=0 or min_multiple<=1 or min_hits<1:
        raise ValueError('Invalid discovery thresholds')
    schema(db)
    now = utc(as_of) if as_of else datetime.now(timezone.utc)
    stamp=now.isoformat()
    previous=db.execute('SELECT MAX(last_evaluated) FROM candidates').fetchone()[0]
    if previous and utc(previous)>now:
        raise ValueError('Discovery cannot rewind persisted state; use a separate replay database')
    since=now-timedelta(days=lookback_days)
    all_rows=[dict(r) for r in db.execute('SELECT * FROM events ORDER BY ts,tx_id,event_index') if utc(r['ts'])<=now]
    tokens=defaultdict(list)
    for r in all_rows:
        tokens[(r['chain'],r['token'])].append(r)
    evidence=defaultdict(list)
    for (chain,token),rows in tokens.items():
        buys=[r for r in rows if r['side']=='BUY']
        if not buys: continue
        first=utc(buys[0]['ts'])
        if first<since: continue
        first_by_wallet={}
        for r in buys:
            first_by_wallet.setdefault(r['wallet'],r)
        for address,buy in first_by_wallet.items():
            if utc(buy['ts'])>first+timedelta(minutes=early_minutes): continue
            later=[r for r in rows if utc(r['ts'])>utc(buy['ts'])]
            if not later: continue
            latest=later[-1]
            multiple=Decimal(latest['price_usd'])/Decimal(buy['price_usd'])
            if multiple<Decimal(str(min_multiple)): continue
            evidence[(chain,address)].append({'token':token,'entry_ts':buy['ts'],
                'entry_tx':buy['tx_id'],'observed_multiple':str(multiple),
                'price_ts':latest['ts'],'basis':'first observed buy; not launch time'})
    current={(r['chain'],r['address']):dict(r) for r in db.execute('SELECT * FROM candidates')}
    changes=[]
    with db:
        for key in sorted(set(evidence)|set(current)):
            chain,address=key
            hits=evidence.get(key,[])
            p=calculate(db,chain,address,stamp)
            w=p['windows']['30']
            profitable_hits=[h for h in hits if Decimal(w['realized_by_token_usd'].get(h['token'],'0'))>0]
            reasons=[]
            if len(profitable_hits)<min_hits: reasons.append('INSUFFICIENT_REALIZED_MULTI_HIT')
            if len(hits)<min_hits: reasons.append('INSUFFICIENT_DISTINCT_TOKEN_HITS')
            if Decimal(w['known_realized_pnl_usd'])<=0: reasons.append('NO_POSITIVE_REALIZED_RESULT')
            if w['closed_cycles']<min_hits: reasons.append('TOO_FEW_CLOSED_CYCLES')
            if w['median_hold_seconds'] is None or w['median_hold_seconds']<60: reasons.append('HOLD_TOO_SHORT_OR_UNKNOWN')
            if w['top1_profit_pct'] is None or w['top1_profit_pct']>70: reasons.append('CONCENTRATED_OR_UNKNOWN')
            if p['last_active'] is None or utc(p['last_active'])<now-timedelta(days=7): reasons.append('INACTIVE')
            for flag in p['data_quality']:
                if flag!='HISTORY_NOT_VERIFIED': reasons.append(flag)
            state='research_candidate' if not reasons else 'observing'
            if 'UNKNOWN_INVENTORY' in reasons or 'EXPECTANCY_DECAY' in reasons: state='quarantine'
            details={'hits':hits,'reasons':reasons,'metrics_30d':w,
                     'copy_eligible':False,'limitations':['MARKET_COVERAGE_UNVERIFIED','HISTORY_NOT_VERIFIED','FOLLOWER_BACKTEST_REQUIRED']}
            encoded=json.dumps(details,sort_keys=True)
            old=current.get(key)
            first_detected=old['first_detected'] if old else stamp
            db.execute('INSERT INTO candidates VALUES(?,?,?,?,?,?) ON CONFLICT(chain,address) DO UPDATE SET last_evaluated=excluded.last_evaluated,state=excluded.state,evidence=excluded.evidence',
                       (chain,address,first_detected,stamp,state,encoded))
            if old is None or old['state']!=state:
                db.execute('INSERT INTO candidate_changes(chain,address,ts,old_state,new_state,evidence) VALUES(?,?,?,?,?,?)',
                           (chain,address,stamp,old['state'] if old else None,state,encoded))
                changes.append({'chain':chain,'address':address,'state':state,'reasons':reasons})
    return {'as_of':stamp,'observed_wallets':len({(r['chain'],r['wallet']) for r in all_rows}),
            'observed_tokens':len(tokens),'changes':changes,'new_candidates':sum(k not in current for k in evidence),
            'mode':'offline_market_feed','copy_eligible':False}


def candidates(db):
    schema(db)
    return [dict(r, evidence=json.loads(r['evidence'])) for r in db.execute('SELECT * FROM candidates ORDER BY state,address')]


def record_signals(db, events):
    """Only record new events observed AFTER qualification; do not replay old buys."""
    schema(db)
    from tracker import normalize
    added=0
    with db:
        for raw in events:
            e=normalize(raw)
            c=db.execute('SELECT * FROM candidates WHERE chain=? AND address=?',(e['chain'],e['wallet'])).fetchone()
            if not c or c['state']!='research_candidate' or utc(e['ts'])<=utc(c['last_evaluated']): continue
            cursor=db.execute('INSERT OR IGNORE INTO candidate_signals VALUES(?,?,?,?,?,?,?,?)',
                (e['chain'],e['tx_id'],e['event_index'],e['wallet'],e['ts'],e['side'],e['token'],c['state']))
            added+=cursor.rowcount
    return added
