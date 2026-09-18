"""Read-only GMGN CLI adapter. Stores source responses without inventing mappings."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parent

def query(node,cli,args):
    permitted={('market','trending'),('token','traders'),('portfolio','activity'),('portfolio','stats')}
    if tuple(args[:2]) not in permitted:
        raise ValueError('Read-only command not permitted')
    if not os.environ.get('GMGN_API_KEY'):
        raise ValueError('Set GMGN_API_KEY locally before running')
    result=subprocess.run([str(node),str(cli),*args,'--raw'],capture_output=True,text=True,encoding='utf-8',timeout=45)
    if result.returncode:
        # CLI diagnostics may contain credentials; never echo raw stderr.
        raise RuntimeError('GMGN query failed; check credentials, quota and network')
    return json.loads(result.stdout)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--node',default='node')
    p.add_argument('--cli',required=True,help='Path to installed gmgn-cli JS entry')
    s=p.add_subparsers(dest='command',required=True)
    s.add_parser('trending')
    s.add_parser('traders').add_argument('address')
    s.add_parser('activity').add_argument('address')
    s.add_parser('stats').add_argument('address')
    a=p.parse_args()
    commands={'trending':['market','trending','--chain','sol','--interval','1h','--limit','20'],
              'traders':['token','traders','--chain','sol','--address',getattr(a,'address',''),'--limit','100'],
              'activity':['portfolio','activity','--chain','sol','--wallet',getattr(a,'address',''),'--limit','100'],
              'stats':['portfolio','stats','--chain','sol','--wallet',getattr(a,'address','')]}
    data=query(a.node,a.cli,commands[a.command])
    folder=ROOT/'gmgn-snapshots';folder.mkdir(exist_ok=True)
    ts=datetime.now(timezone.utc)
    target=folder/(ts.strftime('%Y%m%dT%H%M%S%f')+'-'+a.command+'.json')
    target.write_text(json.dumps({'source':'gmgn','fetched_at':ts.isoformat(),'command':a.command,'address':getattr(a,'address',None),'data':data},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'snapshot':str(target),'normalized':False,'history_complete':False}))

if __name__=='__main__': main()
