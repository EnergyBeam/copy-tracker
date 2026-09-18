"""Bounded live GMGN token -> trader -> wallet discovery. No trading."""
import argparse,json,time
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
from pathlib import Path
from gmgn_api import Client,GMGNError,RateLimited,ROOT,snapshot
from tracker import connect


def unwrap(value):
    for _ in range(4):
        if isinstance(value,dict) and 'code' in value:
            if value['code']!=0: raise GMGNError('GMGN nested response failed')
            value=value.get('data')
        else: return value
    raise GMGNError('Unexpected response nesting')


def num(value):
    if value is None or isinstance(value,bool): return None
    try:
        d=Decimal(str(value))
        return d if d.is_finite() else None
    except InvalidOperation: return None


def assess(observations,stats7,stats30,history_tokens=()):
    reasons=[]
    tags=set()
    for o in observations:
        tags.update(o.get('tags') or [])
        tags.update(o.get('maker_token_tags') or [])
        if o.get('is_suspicious'): reasons.append('SUSPICIOUS_PROVIDER_FLAG')
    common=stats30.get('common') or {}
    tags.update(common.get('tags') or [])
    blocked=tags & {'dev','sniper','rat_trader','bundler','dex_bot','arbitrager'}
    if blocked: reasons.append('NON_REPLICABLE_TAGS:'+','.join(sorted(blocked)))
    if (num(common.get('created_token_count')) or 0)>0: reasons.append('TOKEN_CREATOR')
    hits={o['token_address'] for o in observations if (num(o.get('realized_profit')) or 0)>0}
    observation_hits=len(hits)
    hits.update(history_tokens)
    if len(hits)<2: reasons.append('REALIZED_MULTI_HIT_NOT_CONFIRMED')
    for period,stats in [('7d',stats7),('30d',stats30)]:
        pnl=num(stats.get('realized_profit'))
        if pnl is None: reasons.append('MISSING_PNL_'+period)
        elif pnl<=0: reasons.append('NON_POSITIVE_PNL_'+period)
    hold=num((stats30.get('pnl_stat') or {}).get('avg_holding_period'))
    if hold is None: reasons.append('HOLD_UNKNOWN')
    elif hold<60: reasons.append('HOLD_TOO_SHORT')
    # Average is not the median required by the full copyability gate.
    state='history_review' if not reasons else 'observing'
    if blocked or 'TOKEN_CREATOR' in reasons or 'SUSPICIOUS_PROVIDER_FLAG' in reasons: state='signal_only'
    return {'state':state,'reasons':reasons,'tags':sorted(tags),'realized_token_hits':len(hits),'observation_token_hits':observation_hits,'history_token_hits':len(set(history_tokens)),
            'copy_eligible':False,'pending':['FULL_HISTORY','MEDIAN_HOLD','CONCENTRATION','INDEPENDENCE','FOLLOWER_SIMULATION']}


def scan(db,client,token_limit=5,trader_limit=20,wallet_limit=10):
    if not 1<=token_limit<=30 or not 1<=trader_limit<=100 or not 0<=wallet_limit<=100: raise ValueError('Limits out of range')
    db.executescript('''
    CREATE TABLE IF NOT EXISTS gmgn_observations(wallet TEXT,token TEXT,observed_at TEXT,payload TEXT,PRIMARY KEY(wallet,token));
    CREATE TABLE IF NOT EXISTS gmgn_candidates(wallet TEXT PRIMARY KEY,first_seen TEXT,last_checked TEXT,state TEXT,evidence TEXT);
    CREATE TABLE IF NOT EXISTS gmgn_runs(id INTEGER PRIMARY KEY,ts TEXT,summary TEXT);
    ''')
    ts=datetime.now(timezone.utc).isoformat()
    rank=unwrap(client.get('trending',chain='sol',interval='1h',limit=token_limit,order_by='volume',direction='desc'))
    if not isinstance(rank,dict) or not isinstance(rank.get('rank'),list): raise GMGNError('Unexpected rank schema')
    snapshot('rank',rank)
    observed=set(); errors=[]; skipped=0; rate_limited=False
    for token in rank['rank'][:token_limit]:
        address=token.get('address')
        if not address: continue
        try:
            payload=unwrap(client.get('traders',chain='sol',address=address,limit=trader_limit,order_by='profit',direction='desc'))
            if not isinstance(payload,dict) or not isinstance(payload.get('list'),list): raise GMGNError('Unexpected trader schema')
            snapshot('traders',{'token':address,'data':payload})
            with db:
                for row in payload['list']:
                    wallet=row.get('address')
                    # Pool/exchange addresses and non-buyers are not traders to copy.
                    if not wallet or row.get('exchange') or (num(row.get('buy_tx_count_cur')) or 0)<=0:
                        skipped+=1;continue
                    observed.add(wallet)
                    enriched={**row,'token_address':address,'token_symbol':token.get('symbol'),'token_liquidity':token.get('liquidity'),'observed_at':ts}
                    db.execute('INSERT INTO gmgn_observations VALUES(?,?,?,?) ON CONFLICT(wallet,token) DO UPDATE SET observed_at=excluded.observed_at,payload=excluded.payload',
                               (wallet,address,ts,json.dumps(enriched)))
                    db.execute('INSERT OR IGNORE INTO wallets(chain,address,role,source) VALUES(?,?,?,?)',('solana',wallet,'discovered via token traders','GMGN OpenAPI'))
        except RateLimited as e:
            errors.append({'token':address,'error':str(e)}); rate_limited=True; break
        except GMGNError as e: errors.append({'token':address,'error':str(e)})
        time.sleep(.15)
    # Prioritize repetition before volume/PnL; only fresh evidence (7 days) counts.
    grouped={}
    for wallet in observed:
        grouped[wallet]=[json.loads(r['payload']) for r in db.execute("SELECT payload FROM gmgn_observations WHERE wallet=? AND julianday(observed_at)>=julianday(?)-7",(wallet,ts))]
    with db:
        for wallet in observed:
            db.execute('INSERT OR IGNORE INTO gmgn_candidates VALUES(?,?,?,?,?)',(wallet,ts,ts,'pending_profile',json.dumps({'wallet':wallet,'copy_eligible':False,'reasons':['PROFILE_PENDING']})))
    selected=sorted(observed,key=lambda w:(-len(grouped[w]),w))[:wallet_limit]
    result=[]; new=0
    for wallet in selected:
        if rate_limited: break
        try:
            s7=unwrap(client.get('stats',chain='sol',wallet_address=wallet,period='7d'))
            s30=unwrap(client.get('stats',chain='sol',wallet_address=wallet,period='30d'))
            if not isinstance(s7,dict) or not isinstance(s30,dict) or 'realized_profit' not in s30: raise GMGNError('Unexpected stats schema')
            a=assess(grouped[wallet],s7,s30)
            old=db.execute('SELECT first_seen FROM gmgn_candidates WHERE wallet=?',(wallet,)).fetchone()
            if not old:new+=1
            record={'wallet':wallet,**a,'stats_7d':s7,'stats_30d':s30,'observations':grouped[wallet],'checked_at':ts}
            with db:
                db.execute('INSERT INTO gmgn_candidates VALUES(?,?,?,?,?) ON CONFLICT(wallet) DO UPDATE SET last_checked=excluded.last_checked,state=excluded.state,evidence=excluded.evidence',
                    (wallet,old['first_seen'] if old else ts,ts,a['state'],json.dumps(record)))
            result.append(record)
        except RateLimited as e:
            errors.append({'wallet':wallet,'error':str(e)}); rate_limited=True; break
        except GMGNError as e: errors.append({'wallet':wallet,'error':str(e)})
        time.sleep(.15)
    summary={'as_of':ts,'tokens_scanned':len(rank['rank'][:token_limit]),'wallets_observed':len(observed),'wallets_profiled':len(result),'new_profiled':new,'excluded_pool_or_nonbuyer':skipped,'errors':errors,'copy_eligible':False,'rate_limited':rate_limited}
    with db: db.execute('INSERT INTO gmgn_runs(ts,summary) VALUES(?,?)',(ts,json.dumps(summary)))
    report=['# Кошельки из живого сканирования GMGN','',f'Срез: {ts}', '',
            'Источник: трейдеры токенов из часового рейтинга объёма GMGN. Это ограниченная выборка, не вся сеть. Новые означает впервые найденные нашим трекером, не недавно созданные адреса. Все адреса требуют проверки копируемости.','',
            '| Кошелёк | Статус | PnL 7D, USD | PnL 30D, USD | Прибыльных токенов в выборке |','|---|---|---:|---:|---:|']
    for r in result:
        address=r['wallet']
        report.append(f"| [{address[:6]}…{address[-4:]}](https://gmgn.ai/sol/address/{address}) | {r['state']} | {r['stats_7d'].get('realized_profit')} | {r['stats_30d'].get('realized_profit')} | {r['realized_token_hits']} |")
    report+=['','history_review — требуется полная проверка; observing — мало подтверждений; signal_only — отмечены признаки плохо копируемой торговли. PnL взят у провайдера, нашим FIFO ещё не сверялся.','',f'Ошибок запросов: {len(errors)}. Подробные причины отбора сохранены в SQLite и JSON.']
    (ROOT/'gmgn-latest.md').write_text('\n'.join(report),encoding='utf-8')
    (ROOT/'gmgn-latest.json').write_text(json.dumps({'summary':summary,'candidates':result},ensure_ascii=False,indent=2),encoding='utf-8')
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tokens',type=int,default=5);p.add_argument('--traders',type=int,default=20);p.add_argument('--wallets',type=int,default=10)
    a=p.parse_args()
    try:
        with connect(ROOT/'tracker.sqlite3') as db: print(json.dumps(scan(db,Client(),a.tokens,a.traders,a.wallets),ensure_ascii=False,indent=2))
    except GMGNError as e: raise SystemExit(str(e))
