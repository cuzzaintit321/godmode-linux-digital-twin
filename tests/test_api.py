import os, tempfile
from fastapi.testclient import TestClient

def test_report_and_events():
    with tempfile.TemporaryDirectory() as d:
        os.environ['GODMODE_DB']=d+'/test.sqlite'
        os.environ['GODMODE_TOKEN']='testtoken'
        from server.main import app
        client=TestClient(app)
        payload={'id':'test-linux','hostname':'test-linux','os':'Fedora','kernel':'7.2','cpu':15,'memory':25,'disk':30,'uptime':3600,'containers':[{'name':'web','state':'running'}]}
        assert client.get('/health').status_code==200
        assert client.get('/api/overview').status_code==401
        auth={'x-godmode-token':'testtoken'}
        assert client.post('/api/report',json=payload,headers=auth).status_code==200
        payload['cpu']=95
        payload['containers'][0]['state']='exited'
        assert client.post('/api/report',json=payload,headers=auth).status_code==200
        r=client.get('/api/overview',headers=auth).json()
        assert len(r['hosts'])==1
        assert len(r['events'])==3
        assert client.get('/api/history/test-linux',headers=auth).status_code==200
        assert client.get('/api/diagnostics/test-linux',headers=auth).json()['findings']
        assert client.post('/api/snapshots/test-linux',headers=auth).status_code==200
        assert len(client.get('/api/snapshots/test-linux',headers=auth).json())==1
