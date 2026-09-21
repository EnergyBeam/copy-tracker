"""Manual review inbox. Results are authored in Codex, never synthesized by a rule."""
import argparse,hashlib,json
from datetime import datetime,timezone
from pathlib import Path
from ai_review import schema,packet,validate,prepare
from gmgn_api import ROOT
from tracker import connect
from dossier_refresh import is_fresh,refresh
from telegram_notify import enqueue,flush


def inbox(db):
    schema(db)
    return [{'wallet':r['wallet'],'evidence_hash':r['evidence_hash'],'state':r['state'],'needs_refresh':not is_fresh(json.loads(r['packet'])),'dossier':json.loads(r['packet'])} for r in db.execute("SELECT * FROM ai_reviews WHERE state='pending'")]


def submit(db,wallet,expected_hash,result):
    schema(db);validate(result)
    r=db.execute('SELECT * FROM ai_reviews WHERE wallet=?',(wallet,)).fetchone()
    if not r or r['state']!='pending' or r['evidence_hash']!=expected_hash:raise ValueError('Review missing, already completed or stale')
    current=db.execute('SELECT state,evidence FROM gmgn_candidates WHERE wallet=?',(wallet,)).fetchone()
    if not current or current['state']!='history_review':raise ValueError('Candidate no longer qualified')
    e=json.loads(current['evidence'])
    if not is_fresh(e):raise ValueError('Dossier expired or incoherent; refresh before reviewing')
    digest=hashlib.sha256(json.dumps(packet(e),ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    if digest!=expected_hash:
        prepare(db,e)
        raise ValueError('Evidence changed; review refreshed dossier first')
    completed={**result,'model':'manual_codex_review','reviewed_at':datetime.now(timezone.utc).isoformat(),'evidence_hash':digest}
    e['ai_review']=completed
    with db:
        db.execute("UPDATE ai_reviews SET state='completed',result=?,model=?,reviewed_at=? WHERE wallet=?",(json.dumps(completed),'manual_codex_review',completed['reviewed_at'],wallet))
        db.execute('UPDATE gmgn_candidates SET evidence=? WHERE wallet=?',(json.dumps(e),wallet))
    enqueue(db,e)
    return {'review_saved':True,'sent':flush(db)}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--result-file');p.add_argument('--refresh-wallet');a=p.parse_args()
    with connect(ROOT/'tracker.sqlite3') as db:
        if a.refresh_wallet:
            from gmgn_api import Client
            refresh(db,Client(),a.refresh_wallet);out=inbox(db)
        elif a.result_file:
            r=json.loads(Path(a.result_file).read_text(encoding='utf-8-sig'))
            out=submit(db,r['wallet'],r['evidence_hash'],r['analysis'])
        else:out=inbox(db)
    print(json.dumps(out,ensure_ascii=False,indent=2))
