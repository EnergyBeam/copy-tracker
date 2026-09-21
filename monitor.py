"""Single-instance persistent local wallet monitor. Stop using monitor.stop."""
import argparse,json,time,os,logging,re
from logging.handlers import RotatingFileHandler
from contextlib import closing
from datetime import datetime,timezone
from gmgn_api import ROOT,Client,GMGNError
from gmgn_scan import scan,unwrap
from gmgn_review import review
from tracker import connect
from telegram_notify import enqueue,flush,schema as outbox_schema
from history_metrics import closed_metrics
from pump_discovery import scan_pump
from ai_review import prepare, schema as review_schema


def lock_process():
    f=open(ROOT/'monitor.lock','a+b');f.seek(0)
    if os.name=='nt':
        import msvcrt
        if not f.read(1):f.write(b'0');f.flush()
        f.seek(0)
        try:msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:f.close();return None
    else:
        import fcntl
        try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:f.close();return None
    return f


def enrich(db,client):
    from dossier_refresh import refresh
    review_schema(db)
    rows=db.execute("SELECT wallet FROM gmgn_candidates WHERE state='history_review' AND wallet NOT IN (SELECT wallet FROM telegram_outbox) AND wallet NOT IN (SELECT wallet FROM ai_reviews WHERE state IN ('pending','completed')) LIMIT 2").fetchall()
    for row in rows:refresh(db,client,row['wallet'])


def refresh_pending_history(db,client):
    from dossier_refresh import refresh,is_fresh
    rows=db.execute("SELECT c.wallet,c.evidence FROM gmgn_candidates c JOIN ai_reviews a ON c.wallet=a.wallet WHERE a.state='pending' AND c.state='history_review' ORDER BY COALESCE(json_extract(c.evidence,'$.snapshot_started_at'),c.last_checked)").fetchall()
    for row in rows:
        if not is_fresh(json.loads(row['evidence'])):
            refresh(db,client,row['wallet']);break


def status(phase,**extra):
    data={'pid':os.getpid(),'updated_at':datetime.now(timezone.utc).isoformat(),'phase':phase,**extra}
    p=ROOT/'monitor-status.json';temp=p.with_suffix('.tmp');temp.write_text(json.dumps(data),encoding='utf-8');temp.replace(p)


def safe_error(error):
    value=str(error)
    allowed={'GMGN network connection failed','GMGN returned invalid JSON','Unexpected stats schema','GMGN nested response failed','Unexpected response nesting','Unexpected rank schema','Unexpected traders schema','Unexpected trenches schema'}
    if value in allowed:return value
    if re.fullmatch(r'GMGN network (dns|certificate|tls|timeout|connection|transport)( errno=-?[0-9]+)?',value):return value
    if re.fullmatch(r'GMGN HTTP [0-9]{3}',value):return value
    if re.fullmatch(r'GMGN API rejected request; code=-?[0-9]+',value):return value
    return type(error).__name__


def retry_delay(error,failures):
    cap=120 if safe_error(error).startswith('GMGN network ') else 900
    return min(cap,30*2**min(failures,5))


def workload(pending):
    if pending>=1000:return {'pump_interval':900,'scan_interval':1800,'batch':5}
    if pending>=200:return {'pump_interval':300,'scan_interval':1200,'batch':5}
    return {'pump_interval':60,'scan_interval':900,'batch':3}


def run(once=False):
    lock=lock_process()
    if lock is None:return
    logger=logging.getLogger('monitor');logger.setLevel(logging.INFO)
    handler=RotatingFileHandler(ROOT/'monitor.log',maxBytes=1000000,backupCount=3,encoding='utf-8');handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'));logger.addHandler(handler)
    try:
        client=Client();next_scan=0;next_pump=0;failures=0
        with closing(connect(ROOT/'tracker.sqlite3')) as db:
            outbox_schema(db)
            while not (ROOT/'monitor.stop').exists():
                try:
                    pending=db.execute("SELECT COUNT(*) FROM gmgn_candidates WHERE state='pending_profile'").fetchone()[0]
                    policy=workload(pending)
                    status('discovering' if time.time()>=next_scan else 'profiling')
                    if time.time()>=next_scan:
                        summary=scan(db,client,token_limit=5,trader_limit=20,wallet_limit=0)
                        next_scan=time.time()+policy['scan_interval']
                        logger.info('Scan wallets=%s errors=%s',summary['wallets_observed'],len(summary['errors']))
                    if time.time()>=next_pump:
                        status('pumpfun_discovery')
                        pump=scan_pump(db,client)
                        next_pump=time.time()+policy['pump_interval']
                        logger.info('Pump.fun listed=%s checked=%s wallets=%s',pump['listed'],pump['tokens_checked'],pump['wallets_found'])
                    status('profiling')
                    outcome=review(db,client,limit=policy['batch'])
                    if outcome['error']:raise GMGNError(outcome['error'])
                    status('preparing_alerts');enrich(db,client)
                    refresh_pending_history(db,client)
                    sent=flush(db);failures=0
                    status('idle',pending=outcome['pending'],telegram_sent=sent,workload=policy)
                    logger.info('Cycle reviewed=%s pending=%s sent=%s',outcome['reviewed'],outcome['pending'],sent)
                    delay=1
                except Exception as e:
                    failures+=1;delay=retry_delay(e,failures)
                    client=Client()
                    # Never serialize exception messages or request objects containing credentials.
                    reason=safe_error(e)
                    logger.error('Cycle failed type=%s reason=%s retry_seconds=%s',type(e).__name__,reason,delay)
                    status('retry_wait',error_type=type(e).__name__,reason=reason,retry_seconds=delay)
                if once:break
                until=time.time()+delay
                while time.time()<until and not (ROOT/'monitor.stop').exists():time.sleep(1)
            status('stopped')
    finally:lock.close();handler.close();logger.removeHandler(handler)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--once',action='store_true');a=p.parse_args();run(a.once)
