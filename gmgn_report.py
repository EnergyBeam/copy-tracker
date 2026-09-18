"""Render current GMGN queue and evidence from the database."""
import json
from datetime import datetime,timezone
from gmgn_api import ROOT
from tracker import connect

def export(db):
    rows=[dict(r) for r in db.execute('SELECT * FROM gmgn_candidates ORDER BY state,wallet')]
    lines=['# Кошельки GMGN','',f'Обновлено: {datetime.now(timezone.utc).isoformat()}','',
           'Отбор по трейдерам токенов. Это кандидаты для исследования, не разрешение на копирование. PnL получен от GMGN и пока не сверялся с полной историей.','',
           '| Кошелёк | Статус | PnL 7D, USD | PnL 30D, USD | Причины / ограничения |','|---|---|---:|---:|---|']
    counts={}
    for row in rows:
        e=json.loads(row['evidence']);counts[row['state']]=counts.get(row['state'],0)+1
        a=row['wallet']
        v7=e.get('stats_7d',{}).get('realized_profit','—');v30=e.get('stats_30d',{}).get('realized_profit','—')
        why=', '.join(e.get('reasons',[])).replace('|','/')
        lines.append(f"| [{a[:6]}…{a[-4:]}](https://gmgn.ai/sol/address/{a}) | {row['state']} | {v7} | {v30} | {why} |")
    lines+=['','Скорость клиента: не чаще одного запроса каждые 6 секунд. При 429 соблюдается серверный reset; абсолютной гарантии нет, поскольку квота может быть общей с другими клиентами.','',json.dumps(counts,ensure_ascii=False)]
    (ROOT/'gmgn-latest.md').write_text('\n'.join(lines),encoding='utf-8')
    (ROOT/'gmgn-latest.json').write_text(json.dumps({'counts':counts,'candidates':[dict(r,evidence=json.loads(r['evidence'])) for r in rows]},ensure_ascii=False,indent=2),encoding='utf-8')
    return counts

if __name__=='__main__':
    with connect(ROOT/'tracker.sqlite3') as db:print(json.dumps(export(db)))
