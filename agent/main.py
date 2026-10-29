"""Read-only collector. No remote shell, escalation, or host changes."""
import argparse, os, platform, socket, time, subprocess, json, uuid
import psutil, httpx

def command(args, timeout=3):
    try:
        p=subprocess.run(args,capture_output=True,text=True,timeout=timeout,check=False)
        return p.stdout if p.returncode==0 else ''
    except (OSError,subprocess.TimeoutExpired): return ''

def gather():
    host=socket.gethostname()
    processes=[]
    for p in psutil.process_iter(['pid','name','username','cpu_percent','memory_percent','status']):
        try: processes.append({k:p.info.get(k) for k in ['pid','name','username','cpu_percent','memory_percent','status']})
        except (psutil.NoSuchProcess,psutil.AccessDenied): pass
    processes=sorted(processes,key=lambda x:x.get('memory_percent') or 0,reverse=True)[:15]
    services=[]
    raw=command(['systemctl','list-units','--type=service','--all','--no-pager','--no-legend','--plain'])
    for line in raw.splitlines()[:50]:
        parts=line.strip().split(None,4)
        if len(parts)>=4: services.append({'name':parts[0], 'load':parts[1], 'active':parts[2], 'state':parts[3]})
    containers=[]
    raw=command(['docker','ps','-a','--format','{{json .}}'])
    for line in raw.splitlines()[:70]:
        try:
            d=json.loads(line)
            containers.append({'id':d.get('ID'),'name':d.get('Names'), 'image':d.get('Image'), 'state':d.get('State','unknown'), 'status':d.get('Status'),'ports':d.get('Ports')})
        except json.JSONDecodeError: pass
    interfaces=[]
    for name, addrs in psutil.net_if_addrs().items():
        ips=[a.address for a in addrs if a.family in (socket.AF_INET,socket.AF_INET6)]
        interfaces.append({'name':name,'addresses':ips[:5]})
    disks=[]
    for part in psutil.disk_partitions(all=False):
        try:
            u=psutil.disk_usage(part.mountpoint)
            disks.append({'mount':part.mountpoint,'device':part.device,'fstype':part.fstype,'percent':u.percent,'total':u.total,'used':u.used})
        except (OSError,PermissionError): pass
    conns=[]
    try:
        for c in psutil.net_connections(kind='inet'):
            if c.status=='LISTEN' and c.laddr:
                conns.append({'local':f'{c.laddr.ip}:{c.laddr.port}','pid':c.pid,'status':'LISTEN'})
    except (OSError,psutil.AccessDenied): pass
    return {'id':os.getenv('GODMODE_HOST_ID',host), 'hostname':host, 'os':platform.platform(), 'kernel':platform.release(),
        'cpu':psutil.cpu_percent(interval=.2),'memory':psutil.virtual_memory().percent,'disk':psutil.disk_usage('/').percent,
        'uptime':max(0,time.time()-psutil.boot_time()),'processes':processes,'services':services,
        'containers':containers,'interfaces':interfaces[:40], 'connections':conns[:50], 'disks':disks[:30],
        'load':list(os.getloadavg()) if hasattr(os,'getloadavg') else []}

def main():
    ap=argparse.ArgumentParser(description='GODMODE read-only Linux telemetry agent')
    ap.add_argument('--server',default=os.getenv('GODMODE_SERVER','http://127.0.0.1:8383'))
    ap.add_argument('--interval',type=int,default=5)
    ap.add_argument('--once',action='store_true')
    a=ap.parse_args()
    if a.interval<2: ap.error('interval must be at least 2 seconds')
    token=os.getenv('GODMODE_TOKEN','')
    with httpx.Client(timeout=10) as client:
        while True:
            try:
                r=client.post(a.server.rstrip('/')+'/api/report',json=gather(),headers={'x-godmode-token':token})
                r.raise_for_status()
                print(time.strftime('%H:%M:%S'),'report delivered',flush=True)
            except (httpx.HTTPError, OSError) as e: print('Agent delivery error:',e,flush=True)
            if a.once: break
            time.sleep(a.interval)
if __name__=='__main__': main()
