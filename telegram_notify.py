"""Telegram delivery with persistent outbox. Secrets never appear in diagnostics."""
import json,time
from datetime import datetime,timezone,timedelta
from urllib.request import Request,build_opener
from urllib.error import HTTPError,URLError
from gmgn_api import ROOT,NoRedirect
from gmgn_scan import num


def config():
    values={}
    for line in (ROOT/'.env').read_text(encoding='utf-8-sig').splitlines():
        k,sep,v=line.partition('=')
        if sep:values[k.strip()]=v.strip().strip('\"').strip("'")
    return values

class TelegramError(RuntimeError):pass

def telegram(method,data):
    if method not in ('sendMessage','getUpdates','getMe'):raise ValueError('Unsupported Telegram method')
    token=config().get('TELEGRAM_BOT_TOKEN')
    if not token:raise TelegramError('Telegram token missing')
    request=Request('https://api.telegram.org/bot'+token+'/'+method,data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})
    try:
        with build_opener(NoRedirect()).open(request,timeout=25) as response:out=json.load(response)
    except HTTPError as e:raise TelegramError('Telegram HTTP '+str(e.code)) from None
    except (URLError,TimeoutError,OSError,ValueError):raise TelegramError('Telegram connection or response error') from None
    if not out.get('ok'):raise TelegramError('Telegram rejected request')
    return out['result']


def number(value,suffix='',precision=2):
    n=num(value)
    return 'нет данных' if n is None else f'{n:,.{precision}f}'.replace(',', ' ').replace('.', ',')+suffix


def duration(value):
    n=num(value)
    if n is None:return 'нет данных'
    if n<60:return number(n,' с')
    if n<3600:return number(n/60,' мин')
    return number(n/3600,' ч')


def report(e):
    s7=e.get('stats_7d') or {};s30=e.get('stats_30d') or {}
    p=s30.get('pnl_stat') or {};c=s30.get('common') or {}
    h=e.get('history_metrics') or {};r=e.get('ai_review')
    address=e['wallet'];blocks=[]
    if r:
        from ai_review import VERDICTS
        icon={'reject':'🔴','watch':'🟡','paper_only':'🟠'}[r['verdict']]
        blocks.append(icon+' '+VERDICTS[r['verdict']].upper()+'\nРучной разбор кошелька · Solana')
    else:blocks.append('КОШЕЛЁК · SOLANA\nОжидает ручного разбора')
    blocks.append('АДРЕС\n'+address+'\nhttps://gmgn.ai/sol/address/'+address)
    if e.get('checked_at'):
        try:stamp=datetime.fromisoformat(e['checked_at']).astimezone(timezone(timedelta(hours=4))).strftime('%d.%m.%Y %H:%M')+' · Самара (UTC+4)'
        except (ValueError,TypeError):stamp=str(e['checked_at'])
        blocks.append('Снимок данных: '+stamp)
    if r:blocks.append('ВЫВОД\n'+r['summary'])
    def period(label,stats):
        wr=num((stats.get('pnl_stat') or {}).get('winrate'))
        return label+'\n• Реализованная прибыль: '+number(stats.get('realized_profit'),' USD')+'\n• Винрейт: '+number(wr*100 if wr is not None else None,'%')
    blocks.append('СТАТИСТИКА GMGN\n'+period('За 7 дней',s7)+'\n\n'+period('За 30 дней',s30))
    blocks.append('ЗАКРЫТЫЕ ПОЗИЦИИ · НАША ВЫБОРКА\n'
        +'• Позиций в расчёте: '+str(h.get('closed_cycles',0))
        +'\n• Средний результат: '+number(h.get('mean_multiple'),'×',3)
        +'\n• Медианный результат: '+number(h.get('median_multiple'),'×',3)
        +'\n• Медианное удержание: '+duration(h.get('median_hold_seconds'))
        +'\n\n1× — возврат затрат; 2× — удвоение. Медиана — середина выборки. Это не доходность всего портфеля.')
    blocks.append('АКТИВНОСТЬ ЗА 30 ДНЕЙ · GMGN\n'
        +'• Покупок / продаж: '+str(s30.get('buy','нет данных'))+' / '+str(s30.get('sell','нет данных'))
        +'\n• Токенов: '+str(p.get('token_num','нет данных'))
        +'\n• Среднее удержание: '+duration(p.get('avg_holding_period')))
    if r:
        for title,key in [('СИЛЬНЫЕ СТОРОНЫ','strengths'),('РИСКИ КОПИРОВАНИЯ','risks'),('СЛЕДУЮЩИЕ ПРОВЕРКИ','missing_checks')]:
            if r.get(key):blocks.append(title+'\n'+'\n'.join('• '+item for item in r[key]))
    created=num(c.get('created_at'));created_text='нет данных'
    if created and 0<created<time.time():created_text=datetime.fromtimestamp(float(created),timezone.utc).strftime('%d.%m.%Y %H:%M UTC')
    pump=sum(o.get('source')=='pumpfun_new_creation' for o in e.get('observations',[]))
    blocks.append('КАК НАЙДЕН\n• Прибыльных токенов подтверждено суммарно: '+str(e.get('realized_token_hits',0))
        +'\n• Через закрытые позиции истории: '+str(e.get('history_token_hits',0))
        +'\n• Токенов через Pump.fun: '+str(pump)
        +'\n• Метки GMGN: '+(', '.join(e.get('tags',[])) or 'нет известных')
        +'\n• Первая отметка GMGN: '+created_text+' (не подтверждённая дата создания)')
    blocks.append('ГРАНИЦЫ АНАЛИЗА\nИстория ограничена: '+str(h.get('activity_records',0))+' событий; исключено токенов: '+str(h.get('excluded_tokens',0))+'. '
        +'Полнота истории и результат подписчика не подтверждены. Точное время раннего входа не сверено.')
    return '\n\n'.join(blocks)


def message_parts(text,limit=3500):
    # Split at paragraph/line/word boundaries, never silently discard content.
    parts=[]
    while len(text.encode('utf-16-le'))//2>limit:
        end=min(len(text),limit)
        while len(text[:end].encode('utf-16-le'))//2>limit:end-=1
        cut=text.rfind('\n\n',0,end+1)
        if cut<end//2:cut=text.rfind('\n',0,end+1)
        if cut<end//2:cut=text.rfind(' ',0,end+1)
        if cut<=0:cut=end
        parts.append(text[:cut]);text=text[cut:].lstrip()
    if text:parts.append(text)
    return parts


def schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS telegram_outbox(wallet TEXT PRIMARY KEY,text TEXT,state TEXT DEFAULT 'pending',attempts INTEGER DEFAULT 0,next_attempt REAL DEFAULT 0,message_id INTEGER)''')
    if 'sent_parts' not in {r[1] for r in db.execute('PRAGMA table_info(telegram_outbox)')}:
        db.execute('ALTER TABLE telegram_outbox ADD COLUMN sent_parts INTEGER DEFAULT 0')
    db.commit()


def enqueue(db,e):
    schema(db)
    if e.get('state')!='history_review' or not e.get('ai_review'):return
    with db:db.execute('INSERT OR IGNORE INTO telegram_outbox(wallet,text) VALUES(?,?)',(e['wallet'],report(e)))


def flush(db):
    schema(db);chat=config().get('TELEGRAM_CHAT_ID')
    if not chat:return 0
    sent=0
    rows=db.execute("SELECT * FROM telegram_outbox WHERE state='pending' AND next_attempt<=? LIMIT 3",(time.time(),)).fetchall()
    for r in rows:
        current=db.execute('SELECT state,evidence FROM gmgn_candidates WHERE wallet=?',(r['wallet'],)).fetchone()
        if not current or current['state']!='history_review':
            with db:db.execute("DELETE FROM telegram_outbox WHERE wallet=?",(r['wallet'],))
            continue
        if 'evidence' in current.keys() and not json.loads(current['evidence']).get('ai_review'):continue
        try:
            parts=message_parts(r['text'])
            for index in range(r['sent_parts'],len(parts)):
                heading=('ОТЧЁТ '+r['wallet'][:8]+'… · '+str(index+1)+'/'+str(len(parts))+'\n\n') if len(parts)>1 else ''
                message=telegram('sendMessage',{'chat_id':chat,'text':heading+parts[index],'link_preview_options':{'is_disabled':True}})
                with db:db.execute('UPDATE telegram_outbox SET sent_parts=?,message_id=? WHERE wallet=?',(index+1,message['message_id'],r['wallet']))
            with db:db.execute("UPDATE telegram_outbox SET state='sent',message_id=? WHERE wallet=?",(message['message_id'] if r['sent_parts']<len(parts) else r['message_id'],r['wallet']))
            sent+=1
        except TelegramError:
            with db:db.execute('UPDATE telegram_outbox SET attempts=attempts+1,next_attempt=? WHERE wallet=?',(time.time()+min(3600,60*2**min(r['attempts'],6)),r['wallet']))
            break
    return sent
