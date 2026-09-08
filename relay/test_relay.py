import asyncio
import importlib.util
import json
import sys
import httpx

spec=importlib.util.spec_from_file_location('relay_under_test',sys.argv[1])
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

async def main():
 async with m.lifespan(m.app):
  await m.app.state.http_client.aclose()
  publications=[]
  def publish(req):
   publications.append(req)
   return httpx.Response(200,json={'id':'test'})
  m.app.state.http_client=httpx.AsyncClient(transport=httpx.MockTransport(publish))
  async with httpx.AsyncClient(transport=httpx.ASGITransport(app=m.app),base_url='http://test') as c:
   headers={'X-Api-Key':m.API_KEY,'Content-Type':'text/plain'}
   assert (await c.post('/send?source=windows',content=b'x')).status_code==401
   assert m.API_KEY not in (await c.get('/setup')).text
   assert (await c.post('/copied?kind=text')).status_code == 401
   assert (await c.post('/copied?kind=image',headers=headers)).status_code == 200
   receipt=json.loads(publications[-1].content)
   assert 'click' not in receipt and 'actions' not in receipt
   assert 'clipboard' in receipt['message'] and not m.storage
   for content,kind in [(b'synthetic text','text/plain'),(b'\x89PNG\r\n\x1a\nsynthetic','image/png')]:
    before=len(publications)
    r=await c.post('/send?source=windows',content=content,headers=headers)
    assert r.status_code==200 and 'Server-Timing' in r.headers
    assert len(publications)==before+1
    p=json.loads(publications[-1].content)
    assert m.API_KEY not in json.dumps(p) and 'synthetic' not in p['message']
    assert 'ntfy.sh' not in str(publications[-1].url)
    token=r.json()['token']; assert len(token)>=43
    f=await c.get('/fetch/'+token)
    assert f.status_code==200 and f.content==content and f.headers['content-type'].startswith(kind)
    assert f.headers['cache-control']=='no-store'
    assert (await c.get('/fetch/'+token)).status_code==404
   m.MAX_PAYLOAD_SIZE=4
   assert (await c.post('/send?source=windows',content=b'12345',headers=headers)).status_code==413
   m.MAX_PAYLOAD_SIZE=1024
   m.MAX_STORED_ITEMS=0
   assert (await c.post('/send?source=windows',content=b'abc',headers=headers)).status_code==503
   m.MAX_STORED_ITEMS=256
   m.storage['expired']={'created_at':0,'data':b'abc','content_type':'text/plain'}
   assert (await c.get('/fetch/expired')).status_code==404
   await m.app.state.http_client.aclose()
   m.app.state.http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda req:httpx.Response(500)))
   assert (await c.post('/send?source=windows',content=b'abc',headers=headers)).status_code==502
   assert not m.storage
 print('PASS: auth, no exposed key/content, one publication, text/image fetch, single use, expiry, size/storage limits, failed-publish cleanup')
asyncio.run(main())
