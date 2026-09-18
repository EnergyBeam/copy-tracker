"""Resume profiling queued GMGN wallets without repeating token discovery."""
import argparse,json
from datetime import datetime,timezone
from gmgn_api import Client,GMGNError,RateLimited,ROOT
from gmgn_scan import unwrap,assess
from tracker import connect
from history_metrics import fetch_history

def select_queue(db,limit):
    db.execute('CREATE TABLE IF NOT EXISTS profile_scheduler(id INTEGER PRIMARY KEY,completed INTEGER NOT NULL)')
    db.execute('INSERT OR IGNORE INTO profile_scheduler VALUES(1,0)');db.commit()
    turn=db.execute('SELECT completed FROM profile_scheduler WHERE id=1').fetchone()[0]
    observations={}
    for row in db.execute("SELECT wallet,payload FROM gmgn_observations WHERE julianday(observed_at)>=julianday('now')-7"):
        observations.setdefault(row['wallet'],[]).append(json.loads(row['payload']))
    rows=db.execute("SELECT wallet,state,first_seen,last_checked FROM gmgn_candidates WHERE state='pending_profile' OR (state IN ('observing','signal_only') AND julianday(last_checked)<julianday('now')-0.25)").fetchall()
    neutral={'realized_profit':1,'pnl_stat':{'avg_holding_period':60}}
    def priority(row):
        a=assess(observations.get(row['wallet'],[]),neutral,neutral)
        return (a['state']=='signal_only',-a['realized_token_hits'],row['first_seen'] or '',row['wallet'])
    new=sorted([r for r in rows if r['state']=='pending_profile'],key=priority)
    due=sorted([r for r in rows if r['state']!='pending_profile'],key=lambda r:(r['last_checked'] or '',r['wallet']))
    selected=[]
    for i in range(limit):
        # One in five slots reserved for overdue profiles; one for oldest new entry.
        if (turn+i)%5==4 and due:row=due.pop(0)
        elif new:
            row=min(new,key=lambda r:(r['first_seen'] or '',r['wallet'])) if (turn+i)%5==3 else new[0]
            new.remove(row)
        elif due:row=due.pop(0)
        else:break
        selected.append(row)
    return selected


def review(db,client,limit=1):
    rows=select_queue(db,limit)
    completed=0;error=None
    for row in rows:
        wallet=row['wallet']
        try:
            s30=unwrap(client.get('stats',chain='sol',wallet_address=wallet,period='30d'))
            if not isinstance(s30,dict) or 'realized_profit' not in s30:raise GMGNError('Unexpected stats schema')
            ts=datetime.now(timezone.utc).isoformat()
            observations=[json.loads(r['payload']) for r in db.execute('SELECT payload FROM gmgn_observations WHERE wallet=? AND julianday(observed_at)>=julianday(?)-7',(wallet,ts))]
            preliminary=assess(observations,{},s30)
            # Sparse discovery evidence is not a trading failure: allow 7D,
            # then fetch wallet history only if all financial/risk gates pass.
            s7={}
            if not [r for r in preliminary['reasons'] if r not in ('MISSING_PNL_7d','REALIZED_MULTI_HIT_NOT_CONFIRMED')]:
                s7=unwrap(client.get('stats',chain='sol',wallet_address=wallet,period='7d'))
                if not isinstance(s7,dict) or 'realized_profit' not in s7:raise GMGNError('Unexpected stats schema')
            history=None
            current=assess(observations,s7,s30)
            if current['reasons']==['REALIZED_MULTI_HIT_NOT_CONFIRMED']:
                history=fetch_history(client,wallet,db)
                current=assess(observations,s7,s30,history['profitable_token_addresses'])
                if current['state']=='observing':
                    current['reasons']=['HISTORY_REPEATABILITY_INSUFFICIENT']
            result={'wallet':wallet,**current,'stats_7d':s7,'stats_30d':s30,'checked_at':ts,'observations':observations,'profile_stage':'full' if s7 else '30d_only','skipped_7d':not bool(s7)}
            if history is not None:
                result['history_metrics']=history
                result['repeatability_source']='observations_and_closed_history'
            with db:
                db.execute('UPDATE gmgn_candidates SET last_checked=?,state=?,evidence=? WHERE wallet=?',(ts,result['state'],json.dumps(result),wallet))
                db.execute('UPDATE profile_scheduler SET completed=completed+1 WHERE id=1')
            completed+=1
            print(json.dumps({'progress':completed,'wallet':wallet,'state':result['state']}),flush=True)
        except GMGNError as e:
            error=str(e);break
    from gmgn_report import export
    export(db)
    return {'reviewed':completed,'pending':db.execute("SELECT COUNT(*) FROM gmgn_candidates WHERE state='pending_profile'").fetchone()[0],'error':error,'requests':getattr(client,'request_count',None),'http_429':getattr(client,'rate_limit_count',None)}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--limit',type=int,default=1);a=p.parse_args()
    if not 1<=a.limit<=20: p.error('limit must be 1..20')
    try:
        with connect(ROOT/'tracker.sqlite3') as db: print(json.dumps(review(db,Client(),a.limit),indent=2))
    except GMGNError as e: raise SystemExit(str(e))
