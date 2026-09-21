"""Coherent profile/history snapshots; publication is atomic after all reads succeed."""
import json,hashlib
from datetime import datetime,timezone
from gmgn_api import GMGNError
from gmgn_scan import unwrap,assess
from history_metrics import fetch_history
from ai_review import schema,packet

MAX_AGE_SECONDS=6*3600

def is_fresh(e,now=None):
    try:
        if e.get('snapshot_version')!=1:return False
        start=datetime.fromisoformat(e['snapshot_started_at'])
        if start.tzinfo is None:return False
        age=((now or datetime.now(timezone.utc))-start).total_seconds()
        return 0<=age<=MAX_AGE_SECONDS
    except (KeyError,ValueError,TypeError):return False

def refresh(db,client,wallet):
    schema(db)
    old=db.execute('SELECT evidence FROM gmgn_candidates WHERE wallet=?',(wallet,)).fetchone()
    if not old:raise ValueError('Unknown candidate')
    original=old['evidence']
    started=datetime.now(timezone.utc).isoformat()
    stats={}
    for period in ('30d','7d'):
        data=unwrap(client.get('stats',chain='sol',wallet_address=wallet,period=period))
        if not isinstance(data,dict) or 'realized_profit' not in data:raise GMGNError('Unexpected stats schema')
        stats[period]=data
    history=fetch_history(client,wallet,db)
    observations=[json.loads(r[0]) for r in db.execute("SELECT payload FROM gmgn_observations WHERE wallet=? AND julianday(observed_at)>=julianday('now')-7",(wallet,))]
    result=assess(observations,stats['7d'],stats['30d'],history.get('profitable_token_addresses',[]))
    e={'wallet':wallet,**result,'stats_7d':stats['7d'],'stats_30d':stats['30d'],'history_metrics':history,'observations':observations,'checked_at':started,'snapshot_started_at':started,'snapshot_completed_at':datetime.now(timezone.utc).isoformat(),'snapshot_version':1,'repeatability_source':'observations_and_closed_history','profile_stage':'full'}
    encoded=json.dumps(packet(e),ensure_ascii=False,sort_keys=True)
    if len(encoded)>24000:raise ValueError('Review packet too large')
    digest=hashlib.sha256(encoded.encode()).hexdigest()
    with db:
        current=db.execute('SELECT evidence FROM gmgn_candidates WHERE wallet=?',(wallet,)).fetchone()
        review=db.execute('SELECT state FROM ai_reviews WHERE wallet=?',(wallet,)).fetchone()
        if current['evidence']!=original or (review and review['state']=='completed'):raise ValueError('Candidate changed during refresh')
        db.execute('UPDATE gmgn_candidates SET evidence=?,state=?,last_checked=? WHERE wallet=?',(json.dumps(e),e['state'],started,wallet))
        state='pending' if e['state']=='history_review' else 'withdrawn'
        db.execute("INSERT INTO ai_reviews(wallet,evidence_hash,packet,state) VALUES(?,?,?,?) ON CONFLICT(wallet) DO UPDATE SET evidence_hash=excluded.evidence_hash,packet=excluded.packet,state=excluded.state,result=NULL,reviewed_at=NULL",(wallet,digest,encoded,state))
    return e
