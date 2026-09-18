"""Wallet research event store. Offline only; no trade execution."""
import argparse
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal

ROOT = Path(__file__).resolve().parent
FIELDS = ('chain','wallet','tx_id','event_index','token','side','ts','quantity','price_usd','fee_usd')

def connect(path):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript('''
    CREATE TABLE IF NOT EXISTS wallets(chain TEXT,address TEXT,role TEXT,source TEXT,status TEXT DEFAULT 'unverified',PRIMARY KEY(chain,address));
    CREATE TABLE IF NOT EXISTS events(chain TEXT,wallet TEXT,tx_id TEXT,event_index INTEGER,token TEXT,side TEXT,ts TEXT,quantity TEXT,price_usd TEXT,fee_usd TEXT,PRIMARY KEY(chain,tx_id,event_index));
    CREATE INDEX IF NOT EXISTS wallet_events ON events(chain,wallet,ts);
    ''')
    return db

def normalize(raw):
    e = {k: raw[k] for k in FIELDS}
    if e['chain'] not in ('solana','robinhood') or e['side'] not in ('BUY','SELL'):
        raise ValueError('Unsupported chain or side')
    if type(e['event_index']) is not int or e['event_index'] < 0:
        raise ValueError('Invalid event_index')
    for k in ('wallet','tx_id','token'):
        if not isinstance(e[k],str) or not e[k].strip():
            raise ValueError('Missing identifier: '+k)
    if e['chain'] == 'robinhood':
        for k in ('wallet','token','tx_id'):
            e[k] = e[k].lower()
    ts = datetime.fromisoformat(e['ts'].replace('Z','+00:00'))
    if ts.tzinfo is None:
        raise ValueError('Timezone required')
    e['ts'] = ts.astimezone(timezone.utc).isoformat()
    for k in ('quantity','price_usd','fee_usd'):
        v = Decimal(str(e[k]))
        if not v.is_finite() or v < 0 or (k != 'fee_usd' and v == 0):
            raise ValueError('Invalid '+k)
        e[k] = str(v.normalize())
    return e

def ingest(db,events):
    if not isinstance(events,list):
        raise ValueError('Expected JSON array')
    n = 0
    with db:
        for raw in events:
            e = normalize(raw)
            old = db.execute('SELECT * FROM events WHERE chain=? AND tx_id=? AND event_index=?',(e['chain'],e['tx_id'],e['event_index'])).fetchone()
            if old:
                if dict(old) != e:
                    raise ValueError('Conflicting duplicate')
                continue
            db.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?)',tuple(e[k] for k in FIELDS))
            db.execute('INSERT OR IGNORE INTO wallets(chain,address,role,source) VALUES(?,?,?,?)',(e['chain'],e['wallet'],'imported','normalized import'))
            n += 1
    return n

def screen(metrics):
    """Research thresholds, not a calibrated score. Missing data fails closed."""
    rules = [
        ('closed_cycles',lambda v:v>=25,'INSUFFICIENT_CYCLES'),
        ('median_hold_seconds',lambda v:v>=60,'HOLD_TOO_SHORT'),
        ('price_drift_pct',lambda v:abs(v)<=5,'PRICE_DRIFT'),
        ('slippage_pct',lambda v:0<=v<=2,'SLIPPAGE'),
        ('size_pool_pct',lambda v:0<=v<=1,'POOL_IMPACT'),
        ('top1_profit_pct',lambda v:0<=v<=70,'CONCENTRATION'),
    ]
    reasons = []
    for key,ok,reason in rules:
        value = metrics.get(key)
        if value is None:
            reasons.append('MISSING_'+key.upper())
        elif isinstance(value,bool) or not isinstance(value,(int,float)) or not Decimal(str(value)).is_finite():
            reasons.append('INVALID_'+key.upper())
        elif not ok(value):
            reasons.append(reason)
    for key in ('history_verified','token_gate_passed','independence_verified','follower_backtest_passed'):
        if metrics.get(key) is not True:
            reasons.append(key.upper()+'_REQUIRED')
    for key in ('creator_flag','anti_farm_flag'):
        if metrics.get(key) is not False:
            reasons.append(key.upper()+'_OR_UNKNOWN')
    return {'state':'watchlist' if reasons else 'paper_candidate','reasons':reasons,'auto_copy':False}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',default=str(ROOT/'tracker.sqlite3'))
    s = p.add_subparsers(dest='command',required=True)
    s.add_parser('init'); s.add_parser('wallets')
    for name in ('import','screen'):
        s.add_parser(name).add_argument('file')
    profile_parser = s.add_parser('profile')
    profile_parser.add_argument('chain', choices=['solana','robinhood'])
    profile_parser.add_argument('address')
    profile_parser.add_argument('--as-of')
    discovery_parser = s.add_parser('discover')
    discovery_parser.add_argument('--as-of')
    s.add_parser('candidates')
    s.add_parser('signals')
    s.add_parser('import-market').add_argument('file')
    a = p.parse_args()
    with connect(a.db) as db:
        if a.command == 'init':
            seeds=json.loads((ROOT/'seeds.json').read_text(encoding='utf-8-sig'))
            with db:
                db.executemany('INSERT OR IGNORE INTO wallets(chain,address,role,source) VALUES(?,?,?,?)',[(r['chain'],r['address'],r['role'],'Research DOCX 2026-09-07; unverified') for r in seeds])
            out={'seed_count':len(seeds),'mode':'research'}
        elif a.command in ('discover','candidates','signals','import-market'):
            from discovery import discover, candidates, record_signals, schema
            schema(db)
            if a.command == 'discover':
                out = discover(db,a.as_of)
            elif a.command == 'candidates':
                out = candidates(db)
            elif a.command == 'signals':
                out = [dict(r) for r in db.execute('SELECT * FROM candidate_signals ORDER BY ts DESC')]
            else:
                data=json.loads(Path(a.file).read_text(encoding='utf-8-sig'))
                count=ingest(db,data)
                signals=record_signals(db,data)
                out={'inserted':count,'new_signals':signals,'discovery':discover(db)}
        elif a.command == 'profile':
            from profiler import calculate
            out = calculate(db,a.chain,a.address,a.as_of)
        elif a.command == 'wallets':
            out=[dict(r) for r in db.execute('SELECT * FROM wallets ORDER BY chain,address')]
        else:
            data=json.loads(Path(a.file).read_text(encoding='utf-8-sig'))
            out={'inserted':ingest(db,data)} if a.command=='import' else screen(data)
    print(json.dumps(out,ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
