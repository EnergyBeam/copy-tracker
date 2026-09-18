import json
from pathlib import Path
from telegram_notify import telegram,config
from gmgn_api import ROOT

if __name__=='__main__':
    me=telegram('getMe',{})
    updates=telegram('getUpdates',{'timeout':0,'allowed_updates':['message']})
    chats={}
    for u in updates:
        m=u.get('message') or {};c=m.get('chat') or {}
        if c.get('type')=='private' and (m.get('text') or '').split()[0:1]==['/start']:
            chats[str(c['id'])]=c
    current=config().get('TELEGRAM_CHAT_ID')
    if current:print(json.dumps({'bot':me.get('username'),'chat_configured':True}))
    elif len(chats)==1:
        chat=next(iter(chats));p=ROOT/'.env';lines=p.read_text(encoding='utf-8-sig').splitlines()
        lines=[('TELEGRAM_CHAT_ID='+chat) if l.partition('=')[0].strip()=='TELEGRAM_CHAT_ID' else l for l in lines]
        p.write_text('\n'.join(lines)+'\n',encoding='utf-8')
        print(json.dumps({'bot':me.get('username'),'chat_configured':True,'source':'unique private /start'}))
    else:print(json.dumps({'bot':me.get('username'),'chat_configured':False,'matching_private_chats':len(chats)}))
