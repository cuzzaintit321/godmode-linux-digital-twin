"""GODMODE central control plane: telemetry, event storage, and read-only diagnostics."""
import os, json, sqlite3, time, secrets
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, WebSocket, WebSocketDisconnect, Depends
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

BASE = Path(__file__).resolve().parents[1]
DB = Path(os.environ.get('GODMODE_DB', str(BASE / 'data' / 'godmode.sqlite')))
TOKEN = os.environ.get('GODMODE_TOKEN', '')
STALE_SECONDS = 45
DB.parent.mkdir(parents=True, exist_ok=True)

def conn():
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL')
    return c

def initialize():
    with conn() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS hosts(id TEXT PRIMARY KEY, hostname TEXT, os TEXT, kernel TEXT, first_seen REAL, last_seen REAL, last_json TEXT);
        CREATE TABLE IF NOT EXISTS samples(id INTEGER PRIMARY KEY AUTOINCREMENT, host_id TEXT NOT NULL, at REAL NOT NULL, cpu REAL, memory REAL, disk REAL, payload TEXT);
        CREATE INDEX IF NOT EXISTS idx_samples_host_time ON samples(host_id,at DESC);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, host_id TEXT, at REAL, level TEXT, category TEXT, message TEXT);
        CREATE INDEX IF NOT EXISTS idx_events_time ON events(at DESC);
        CREATE TABLE IF NOT EXISTS snapshots(id INTEGER PRIMARY KEY AUTOINCREMENT, host_id TEXT, at REAL, payload TEXT);
        ''')

def require(request: Request):
    if not TOKEN:
        if request.client and request.client.host not in ('127.0.0.1','::1','testclient') and os.environ.get('GODMODE_ALLOW_UNAUTH_LAN') != '1':
            raise HTTPException(403, 'Set GODMODE_TOKEN for network access')
    elif not secrets.compare_digest(request.headers.get('x-godmode-token', ''), TOKEN):
        raise HTTPException(401, 'Invalid token')

class Report(BaseModel):
    id: str = Field(min_length=1,max_length=100,pattern=r'^[a-zA-Z0-9_.-]+$')
    hostname: str = Field(max_length=120)
    os: str = Field(max_length=240)
    kernel: str = Field(max_length=180)
    cpu: float = Field(ge=0,le=100)
    memory: float = Field(ge=0,le=100)
    disk: float = Field(ge=0,le=100)
    uptime: float = Field(ge=0)
    processes: list[dict] = Field(default_factory=list,max_length=20)
    services: list[dict] = Field(default_factory=list,max_length=60)
    containers: list[dict] = Field(default_factory=list,max_length=80)
    interfaces: list[dict] = Field(default_factory=list,max_length=40)
    connections: list[dict] = Field(default_factory=list,max_length=50)
    disks: list[dict] = Field(default_factory=list,max_length=30)
    load: list[float] = Field(default_factory=list,max_length=3)

initialize()
app = FastAPI(title='GODMODE Control Plane',version='1.0.0')

@app.get('/')
def index(): return FileResponse(BASE / 'frontend' / 'index.html')

@app.post('/api/report',dependencies=[Depends(require)])
def report(r:Report):
    now=time.time()
    data=r.model_dump()
    with conn() as c:
        before=c.execute('SELECT last_json FROM hosts WHERE id=?',(r.id,)).fetchone()
        prior=json.loads(before['last_json']) if before else None
        c.execute('INSERT INTO hosts VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET hostname=excluded.hostname,os=excluded.os,kernel=excluded.kernel,last_seen=excluded.last_seen,last_json=excluded.last_json', (r.id,r.hostname,r.os,r.kernel,now,now,json.dumps(data)))
        c.execute('INSERT INTO samples(host_id,at,cpu,memory,disk,payload) VALUES(?,?,?,?,?,?)',(r.id,now,r.cpu,r.memory,r.disk,json.dumps({'uptime':r.uptime,'load':r.load})))
        if not prior:
            c.execute('INSERT INTO events(host_id,at,level,category,message) VALUES(?,?,?,?,?)',(r.id,now,'info','discovery','Host joined fleet'))
        else:
            old={x.get('name'):x.get('state') for x in prior.get('containers',[])}
            for x in r.containers:
                name=x.get('name')
                if name in old and old[name]!=x.get('state'):
                    c.execute('INSERT INTO events(host_id,at,level,category,message) VALUES(?,?,?,?,?)',(r.id,now,'warning','container',f'{name}: {old[name]} → {x.get("state")}'))
        for metric,value in [('CPU',r.cpu),('Memory',r.memory),('Disk',r.disk)]:
            prev=float(prior.get(metric.lower(),0)) if prior else 0
            if value>=90 and prev<90:
                c.execute('INSERT INTO events(host_id,at,level,category,message) VALUES(?,?,?,?,?)',(r.id,now,'critical','threshold',f'{metric} utilization reached {value:.1f}%'))
        c.execute('DELETE FROM samples WHERE id NOT IN (SELECT id FROM samples WHERE host_id=? ORDER BY at DESC LIMIT 1440) AND host_id=?',(r.id,r.id))
    return {'ok':True,'received':now}

@app.get('/api/overview',dependencies=[Depends(require)])
def overview():
    with conn() as c:
        hosts=[dict(x) for x in c.execute('SELECT * FROM hosts ORDER BY hostname')]
        events=[dict(x) for x in c.execute('SELECT * FROM events ORDER BY at DESC LIMIT 80')]
    for h in hosts:
        h['online']=time.time()-h['last_seen']<STALE_SECONDS
        h['metrics']=json.loads(h.pop('last_json'))
    return {'hosts':hosts,'events':events,'server_time':time.time()}

@app.get('/api/history/{host_id}',dependencies=[Depends(require)])
def history(host_id:str, hours:int=24):
    if not 1<=hours<=168: raise HTTPException(422,'hours 1–168')
    with conn() as c:
        rows=c.execute('SELECT at,cpu,memory,disk FROM samples WHERE host_id=? AND at>? ORDER BY at DESC LIMIT 1440',(host_id,time.time()-3600*hours)).fetchall()
    return [dict(r) for r in reversed(rows)]

@app.post('/api/snapshots/{host_id}',dependencies=[Depends(require)])
def snapshot(host_id:str):
    with conn() as c:
        host=c.execute('SELECT last_json FROM hosts WHERE id=?',(host_id,)).fetchone()
        if not host: raise HTTPException(404,'Unknown host')
        cur=c.execute('INSERT INTO snapshots(host_id,at,payload) VALUES(?,?,?)',(host_id,time.time(),host['last_json']))
        return {'id':cur.lastrowid}

@app.get('/api/snapshots/{host_id}',dependencies=[Depends(require)])
def snapshots(host_id:str):
    with conn() as c:
        rows=c.execute('SELECT id,at,payload FROM snapshots WHERE host_id=? ORDER BY at DESC LIMIT 25',(host_id,)).fetchall()
    return [{'id':r['id'],'at':r['at'],'metrics':json.loads(r['payload'])} for r in rows]

@app.get('/api/diagnostics/{host_id}',dependencies=[Depends(require)])
def diagnostics(host_id:str):
    with conn() as c:
        h=c.execute('SELECT last_json,last_seen FROM hosts WHERE id=?',(host_id,)).fetchone()
    if not h: raise HTTPException(404,'Host not found')
    m=json.loads(h['last_json']); findings=[]
    if time.time()-h['last_seen']>STALE_SECONDS: findings.append({'severity':'critical','title':'Telemetry offline','detail':'Agent heartbeat is stale. Verify network access and agent process.'})
    for k,label in [('cpu','CPU'),('memory','Memory'),('disk','Root disk')]:
        if m[k]>=90: findings.append({'severity':'critical','title':f'High {label}','detail':f'{label} at {m[k]:.1f}%. Inspect processes and recent workloads.'})
        elif m[k]>=75: findings.append({'severity':'warning','title':f'Elevated {label}','detail':f'{label} at {m[k]:.1f}%. Review trends before changes.'})
    for item in m.get('containers',[]):
        if item.get('state') not in ('running',): findings.append({'severity':'warning','title':'Container not running','detail':f'{item.get("name", "Container")} state: {item.get("state", "unknown")}'})
    return {'host_id':host_id,'findings':findings,'note':'Rule-based read-only diagnostics; not AI or a proof of root cause.'}

@app.get('/health')
def health(): return {'status':'ok'}
